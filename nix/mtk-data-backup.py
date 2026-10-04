# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture the identified, offline Gemini ext4 filesystem without DA writes."""
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import uuid

from mtkclient.Library import gemini_gpt_rewrite as g

DATA_OFFSET = 89372672 * 512
DATA_SIZE = 22249472 * 512
DATA_UUID = '5d978ad4-a987-4b3f-bef6-f73ad7c2d986'
SWAP_OFFSET = 111622144 * 512
CHUNK = 16 * 1024 * 1024
OUTPUTS = ('data.ext4', 'backup-events.jsonl', 'backup-result.json',
           'primary-before.bin', 'backup-before.bin',
           'primary-after.bin', 'backup-after.bin', 'swap-header-before.bin')


def extent(raw):
    if len(raw) != 1024 or struct.unpack_from('<H', raw, 56)[0] != 0xef53:
        raise ValueError('Missing ext4 superblock')
    blocks, = struct.unpack_from('<I', raw, 4)
    log_size, = struct.unpack_from('<I', raw, 24)
    state, = struct.unpack_from('<H', raw, 58)
    incompat, = struct.unpack_from('<I', raw, 96)
    if incompat & 0x80:
        blocks |= struct.unpack_from('<I', raw, 0x150)[0] << 32
    if log_size != 2 or str(uuid.UUID(bytes=raw[104:120])) != DATA_UUID:
        raise ValueError('Unidentified persistent ext4 filesystem')
    if blocks * 4096 != DATA_SIZE:
        raise ValueError('Persistent filesystem extent differs from the fixed-swap plan')
    if state != 1:
        raise ValueError('Offline ext4 filesystem has unexpected state: ' + str(state))
    # The store overlay can leave the journal recovery flag set at shutdown.
    # Preserve those offline bytes; only a separate host copy may replay it.
    recovery = bool(incompat & 4)
    return dict(uuid=DATA_UUID, block_count=blocks, block_size=4096,
                size=DATA_SIZE, clean=not recovery, needs_recovery=recovery)


def capture(mtk, directory):
    directory = Path(directory)
    for name in OUTPUTS:
        with g.private_file(directory / name, True) as stream:
            if os.fstat(stream.fileno()).st_size:
                raise ValueError('Backup output already used: ' + name)
    if (mtk.config.hwcode != 0x279 or mtk.config.pagesize != 512 or
            mtk.daloader.daconfig.storage.flashsize != g.FLASH_SIZE):
        raise ValueError('DA identity is not the qualified MT6797 Gemini eMMC')
    loader = mtk.daloader
    result = dict(schema='gemini-offline-data-backup-v1', capture_complete=False,
                  original_layout_verified=False, reboot_acknowledged=False,
                  device_writes_performed=False)
    events = []

    def save(name, raw):
        with g.private_file(directory / name, True) as stream:
            stream.write(raw); stream.truncate(); stream.flush(); os.fsync(stream.fileno())

    def event(kind, **fields):
        events.append(dict(event=kind, monotonic=time.monotonic(), **fields))
        save('backup-events.jsonl', ''.join(json.dumps(row) + '\n' for row in events).encode())

    def read(offset, size):
        raw = loader.readflash(addr=offset, length=size, filename='', parttype='user', display=False)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) != size:
            raise RuntimeError('Incomplete DA read at byte offset ' + str(offset))
        return bytes(raw)

    def guards(suffix, expected=None):
        for name, offset, size, digest in (
                ('primary', 0, 32768, g.PRIMARY_SHA),
                ('backup', g.BACKUP_OFFSET, 33 * 512, g.BACKUP_SHA)):
            raw = read(offset, size)
            if g.sha(raw) != digest:
                raise RuntimeError('Changed factory GPT: ' + name)
            save(name + '-' + suffix + '.bin', raw)
            event('gpt-verified', name=name, phase=suffix, offset=offset, size=size, sha256=digest)
        protected = {}
        for name, offset, size, digest in g.PROTECTED:
            actual = g.sha(read(offset, size))
            wanted = expected[name] if expected else digest
            if wanted is not None and actual != wanted:
                raise RuntimeError('Changed protected partition: ' + name)
            protected[name] = actual
            event('protected-verified', name=name, phase=suffix, offset=offset, size=size, sha256=actual)
        return protected

    admitted = False
    try:
        result['protected_before'] = guards('before')
        admitted = True
        superblock = read(DATA_OFFSET + 1024, 1024)
        result['filesystem'] = extent(superblock)
        event('filesystem-admitted', **result['filesystem'], superblock_sha256=g.sha(superblock))
        tail = read(SWAP_OFFSET, 4096)
        save('swap-header-before.bin', tail)
        result['swap_header_sha256'] = g.sha(tail)
        digest = hashlib.sha256()
        with g.private_file(directory / 'data.ext4', True) as stream:
            for relative in range(0, DATA_SIZE, CHUNK):
                size = min(CHUNK, DATA_SIZE - relative)
                raw = read(DATA_OFFSET + relative, size)
                if relative == 0 and raw[1024:2048] != superblock:
                    raise RuntimeError('Filesystem changed after offline admission')
                stream.write(raw); digest.update(raw)
                event('chunk-captured', offset=relative, size=size, sha256=g.sha(raw))
                if relative == 0 or (relative + size) // (256 * 1024 * 1024) != relative // (256 * 1024 * 1024):
                    print('Offline data captured: ' + str(relative + size) + '/' + str(DATA_SIZE), flush=True)
            stream.flush(); os.fsync(stream.fileno())
            if os.fstat(stream.fileno()).st_size != DATA_SIZE:
                raise RuntimeError('Host backup size differs from filesystem extent')
        if read(DATA_OFFSET + 1024, 1024) != superblock or read(SWAP_OFFSET, 4096) != tail:
            raise RuntimeError('Filesystem or proposed swap header changed during offline capture')
        result.update(capture_complete=True, data_sha256=digest.hexdigest(), data_size=DATA_SIZE)
        event('capture-complete', size=DATA_SIZE, sha256=digest.hexdigest())
    except Exception as error:
        result['capture_error'] = str(error)
        event('capture-failed', error=str(error))
    # An incomplete host copy never requires a device write. Still try to
    # return the known original Linux after rereading GPT and protected data.
    if admitted:
        try:
            result['protected_after'] = guards('after', result['protected_before'])
            result['original_layout_verified'] = True
            result['reboot_acknowledged'] = loader.shutdown(bootmode=1) is True
        except Exception as error:
            result['recovery_error'] = str(error)
        event('reboot', acknowledged=result['reboot_acknowledged'])
        if result['reboot_acknowledged']:
            print('Download agent acknowledged reboot request', flush=True)
    result['events'] = events
    result['qualified'] = all(result[k] for k in ('capture_complete', 'original_layout_verified', 'reboot_acknowledged'))
    save('backup-result.json', (json.dumps(result, indent=2) + '\n').encode())
    return result['qualified']
