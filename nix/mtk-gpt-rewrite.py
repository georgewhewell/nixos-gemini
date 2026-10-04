# SPDX-License-Identifier: GPL-3.0-or-later
"""Gemini factory-GPT rewrite qualification inside one connected DA session.

Only these exact existing GPT bytes can be written. The future p34 layout is
intentionally not admitted by this first hardware qualification command.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import time

SECTORS = 122142720
FLASH_SIZE = SECTORS * 512
BACKUP_OFFSET = (SECTORS - 33) * 512
PRIMARY_SHA = '6addff62cc67f5b5fac9bd87194b6643f4029262251c51c1e43e1b5b64cb887d'
PRIMARY_WRITE_SHA = '7ebdff9bf10fbe5d626671a010c4f9b27c65f04e4cff06610bd5f39c23ad4037'
BACKUP_SHA = '0b1b304506f1a156ca1ee43028c0885466933dd933a6f9da4f557ab34b72b2b5'
PROTECTED = (
    ('boot', 362496 * 512, 16777216, '913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3'),
    ('boot2', 89307136 * 512, 16777216, '122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159'),
    ('boot3', 89339904 * 512, 16777216, '1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513'),
    ('flashinfo', 122109919 * 512, 16777216, None),
)
OUTPUTS = ('gpt-events.jsonl', 'gpt-result.json', 'primary-before.bin',
           'backup-before.bin', 'primary-after.bin', 'backup-after.bin')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def private_file(path, write=False):
    flags = os.O_NOFOLLOW | (os.O_WRONLY if write else os.O_RDONLY)
    fd = os.open(path, flags)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError('GPT files must be private regular files')
    return os.fdopen(fd, 'r+b' if write else 'rb')


def load_inputs(directory):
    data = []
    for name, size, digest in (('primary-gpt-before.bin', 34 * 512, PRIMARY_WRITE_SHA),
                               ('backup-gpt-before.bin', 33 * 512, BACKUP_SHA)):
        with private_file(directory / name) as stream:
            raw = stream.read(size + 1)
        if len(raw) != size or sha(raw) != digest:
            raise ValueError('Unqualified GPT input: ' + name)
        data.append(raw)
    # The host pre-creates empty output files, retaining ownership across sudo.
    for name in OUTPUTS:
        with private_file(directory / name, True) as stream:
            if os.fstat(stream.fileno()).st_size:
                raise ValueError('GPT evidence output already used: ' + name)
    return tuple(data)


def rewrite_factory(mtk, directory):
    directory = Path(directory)
    primary, backup = load_inputs(directory)
    if (mtk.config.hwcode != 0x279 or mtk.config.pagesize != 512 or
            mtk.daloader.daconfig.storage.flashsize != FLASH_SIZE):
        raise ValueError('DA identity is not the qualified MT6797 Gemini eMMC')
    loader = mtk.daloader
    events = []
    result = dict(schema='gemini-factory-gpt-rewrite-v1', operation_qualified=False,
                  original_layout_verified=False, reboot_acknowledged=False,
                  write_attempted=False, rollback_attempted=False)

    def save(name, raw):
        with private_file(directory / name, True) as stream:
            stream.write(raw); stream.truncate(); stream.flush(); os.fsync(stream.fileno())

    def event(kind, **fields):
        record = dict(event=kind, monotonic=time.monotonic(), **fields)
        events.append(record)
        save('gpt-events.jsonl', ''.join(json.dumps(e) + '\n' for e in events).encode())

    def read(name, offset, size, digest=None, output=None):
        raw = loader.readflash(addr=offset, length=size, filename='', parttype='user', display=False)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) != size:
            raise RuntimeError('Incomplete DA read: ' + name)
        raw = bytes(raw)
        actual = sha(raw)
        if digest is not None and actual != digest:
            raise RuntimeError('DA hash mismatch: ' + name)
        if output: save(output, raw)
        event('read-verified', name=name, offset=offset, size=size, sha256=actual)
        return actual

    def read_layout(suffix):
        read('primary-' + suffix, 0, 32768, PRIMARY_SHA, 'primary-' + suffix + '.bin')
        read('backup-' + suffix, BACKUP_OFFSET, len(backup), BACKUP_SHA, 'backup-' + suffix + '.bin')

    def protected(expected=None):
        observed = {}
        for name, offset, size, digest in PROTECTED:
            observed[name] = read(name, offset, size, expected[name] if expected else digest)
        return observed

    def write(name, offset, raw):
        event('write-intent', name=name, offset=offset, size=len(raw), sha256=sha(raw))
        if loader.writeflash(addr=offset, length=len(raw), wdata=raw,
                             filename='', parttype='user', display=False) is not True:
            raise RuntimeError('DA did not acknowledge GPT write: ' + name)
        event('write-acknowledged', name=name, offset=offset, size=len(raw), sha256=sha(raw))
        read(name + '-readback', offset, len(raw), sha(raw))

    admitted = False
    try:
        read_layout('before')
        before = protected()
        admitted = True
        result['protected_before'] = before
        event('admitted', primary_sha256=PRIMARY_SHA, backup_sha256=BACKUP_SHA)
        result['write_attempted'] = True
        # Preserve the primary until the backup write has independently passed.
        write('backup', BACKUP_OFFSET, backup)
        write('primary', 0, primary)
        read_layout('after')
        result['protected_after'] = protected(before)
        result['original_layout_verified'] = True
        result['operation_qualified'] = True
    except Exception as error:
        result['error'] = str(error)
        event('operation-failed', error=str(error))
        if admitted:
            result['rollback_attempted'] = True
            try:
                # A failed acknowledgement may still mean a partial write.
                # Try both original copies in the same DA session before reset.
                rollback_errors = []
                for name, offset, raw in (('backup-rollback', BACKUP_OFFSET, backup),
                                           ('primary-rollback', 0, primary)):
                    try: write(name, offset, raw)
                    except Exception as rollback_error: rollback_errors.append(str(rollback_error))
                read_layout('after')
                result['protected_after'] = protected(before)
                result['original_layout_verified'] = True
                result['rollback_errors'] = rollback_errors
                event('original-layout-restored')
            except Exception as rollback_error:
                result['rollback_error'] = str(rollback_error)
                event('rollback-unverified', error=str(rollback_error))
    # Never reset an unidentified device or one with unverified GPT/protected data.
    if result['original_layout_verified']:
        try:
            result['reboot_acknowledged'] = loader.shutdown(bootmode=1) is True
        except Exception as error:
            result['reboot_error'] = str(error)
        event('reboot', acknowledged=result['reboot_acknowledged'])
        if result['reboot_acknowledged']:
            print('Download agent acknowledged reboot request', flush=True)
    result['operation_qualified'] &= result['reboot_acknowledged']
    result['events'] = events
    save('gpt-result.json', (json.dumps(result, indent=2) + '\n').encode())
    print('Gemini factory GPT rewrite: ' + ('verified' if result['operation_qualified'] else 'not qualified'), flush=True)
    return result['operation_qualified']
