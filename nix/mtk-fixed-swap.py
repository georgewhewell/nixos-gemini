# SPDX-License-Identifier: GPL-3.0-or-later
"""Install or restore exactly the reviewed Gemini GPT and fixed-swap header."""
import json
import os
from pathlib import Path
import time

from mtkclient.Library import gemini_gpt_rewrite as g
from mtkclient.Library import gemini_data_backup as b

SWAP_PRIMARY_SHA = 'cd04227af4c88b18d106f2f5e22a99934043c320055464f953bcd4544802f989'
SWAP_PRIMARY_WRITE_SHA = '04787b98b6fd2c3dbc55185eebf2f7bbaa424d1e634035dd6aec29d4029c2d0b'
SWAP_BACKUP_SHA = '6b0f25fb0f4d70a48d55e16b5d886fadce8d8f069e7413c6782f29d7e30cc6e0'
SWAP_HEADER_SHA = '807f5f949455432666930598531247d0b6dc2bb23ba2ab3b18bc60f1f7382e7d'
OLD_HEADER_SHA = 'c65572c3c11869091c01d20812f1766304fe691cc6450e6dcff2ddc18ec4fc9e'
INPUTS = (
    ('primary-factory.bin', 32768, g.PRIMARY_SHA),
    ('backup-factory.bin', 33 * 512, g.BACKUP_SHA),
    ('primary-swap.bin', 34 * 512, SWAP_PRIMARY_WRITE_SHA),
    ('backup-swap.bin', 33 * 512, SWAP_BACKUP_SHA),
    ('header-factory.bin', 4096, OLD_HEADER_SHA),
    ('header-swap.bin', 4096, SWAP_HEADER_SHA),
)
OUTPUTS = ('swap-events.jsonl', 'swap-result.json', 'primary-before.bin', 'backup-before.bin',
           'header-before.bin', 'superblock-before.bin', 'primary-after.bin', 'backup-after.bin',
           'header-after.bin', 'superblock-after.bin')


def inputs(directory):
    values = {}
    for name, size, digest in INPUTS:
        with g.private_file(directory / name) as stream: raw = stream.read(size + 1)
        if len(raw) != size or g.sha(raw) != digest:
            raise ValueError('Unqualified transition input: ' + name)
        values[name] = raw
    full = values['primary-swap.bin'] + values['primary-factory.bin'][34 * 512:]
    if g.sha(full) != SWAP_PRIMARY_SHA:
        raise ValueError('Proposed primary GPT differs from its full captured extent')
    values['primary-swap.bin'] = full
    for name in OUTPUTS:
        with g.private_file(directory / name, True) as stream:
            if os.fstat(stream.fileno()).st_size: raise ValueError('Transition output already used: ' + name)
    return values


def classify(raw, factory, swap):
    if raw == factory: return 'factory'
    if raw == swap: return 'swap'
    # Restore may repair a torn transition, but may not overwrite changes to
    # any byte that this reviewed transition leaves untouched.
    if len(raw) == len(factory) == len(swap) and all(x == a for x, a, z in zip(raw, factory, swap) if a == z):
        return 'partial'
    raise RuntimeError('Bytes outside the reviewed transition have changed')


def transition(mtk, directory, restore=False):
    directory = Path(directory); images = inputs(directory)
    if (mtk.config.hwcode != 0x279 or mtk.config.pagesize != 512 or
            mtk.daloader.daconfig.storage.flashsize != g.FLASH_SIZE):
        raise ValueError('Unqualified Gemini DA identity')
    loader = mtk.daloader; events = []
    target = 'factory' if restore else 'swap'
    result = dict(schema='gemini-fixed-swap-v1', target=target, operation_qualified=False,
                  write_attempted=False, rollback_attempted=False, final_layout=None,
                  reboot_acknowledged=False)
    offsets = {'primary': 0, 'backup': g.BACKUP_OFFSET, 'header': b.SWAP_OFFSET}

    def save(name, raw):
        with g.private_file(directory / name, True) as stream:
            stream.write(raw); stream.truncate(); stream.flush(); os.fsync(stream.fileno())

    def event(kind, **fields):
        events.append(dict(event=kind, monotonic=time.monotonic(), **fields))
        save('swap-events.jsonl', ''.join(json.dumps(row) + '\n' for row in events).encode())

    def read(name, offset, size, digest=None, output=None):
        raw = loader.readflash(addr=offset, length=size, filename='', parttype='user', display=False)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) != size:
            raise RuntimeError('Incomplete transition read: ' + name)
        raw = bytes(raw); actual = g.sha(raw)
        if digest is not None and actual != digest: raise RuntimeError('Transition read mismatch: ' + name)
        if output: save(output, raw)
        event('read-verified', name=name, offset=offset, size=size, sha256=actual)
        return raw

    def state(phase, layout=None):
        observed = {}
        for name, offset in offsets.items():
            factory = images[name + '-factory.bin']; swap = images[name + '-swap.bin']
            expected = g.sha(images[name + '-' + layout + '.bin']) if layout else None
            raw = read(name + '-' + phase, offset, len(factory), expected, name + '-' + phase + '.bin')
            observed[name] = classify(raw, factory, swap)
        return observed

    def protected(expected=None):
        return {name: g.sha(read(name, offset, size, expected[name] if expected else digest))
                for name, offset, size, digest in g.PROTECTED}

    def write(name, layout):
        result['final_layout'] = None
        raw = images[name + '-' + layout + '.bin']
        if name == 'primary': raw = raw[:34 * 512]
        detail = dict(name=name, layout=layout, offset=offsets[name], size=len(raw), sha256=g.sha(raw))
        event('write-intent', **detail)
        if loader.writeflash(addr=offsets[name], length=len(raw), filename='',
                             parttype='user', wdata=raw, display=False) is not True:
            raise RuntimeError('Unacknowledged transition write: ' + name)
        event('write-acknowledged', **detail)
        read(name + '-readback', offsets[name], len(raw), g.sha(raw))

    def final(layout):
        state('after', layout)
        read('superblock-after', b.DATA_OFFSET + 1024, 1024, g.sha(superblock), 'superblock-after.bin')
        result['protected_after'] = protected(before)
        result['final_layout'] = layout
        event('layout-verified', layout=layout)

    admitted = False
    try:
        observed = state('before')
        before = protected(); result['protected_before'] = before
        superblock = read('superblock-before', b.DATA_OFFSET + 1024, 1024, output='superblock-before.bin')
        result['filesystem'] = b.extent(superblock)
        if b.DATA_OFFSET + result['filesystem']['size'] != b.SWAP_OFFSET:
            raise RuntimeError('Filesystem is not contained before the swap boundary')
        if not restore and any(value != 'factory' for value in observed.values()):
            raise RuntimeError('Installation requires the exact original GPT and swap-start bytes')
        result['initial_state'] = observed; admitted = True
        event('admitted', target=target, initial_state=observed, filesystem=result['filesystem'])
        result['write_attempted'] = True
        # Publish a valid normal swap header before exposing p34 to early resume.
        order = ('backup', 'primary', 'header') if restore else ('header', 'backup', 'primary')
        for name in order: write(name, target)
        final(target); result['operation_qualified'] = True
    except Exception as error:
        result['error'] = str(error); event('operation-failed', error=str(error))
        if admitted:
            result['rollback_attempted'] = True
            errors = []
            for name in ('backup', 'primary', 'header'):
                try: write(name, 'factory')
                except Exception as caught: errors.append(str(caught))
            try:
                final('factory'); result['rollback_errors'] = errors
            except Exception as caught:
                result['rollback_error'] = str(caught); event('rollback-unverified', error=str(caught))
        elif 'before' in locals() and 'superblock' in locals() and all(value == 'factory' for value in observed.values()):
            # A refused filesystem extent need not strand an unchanged,
            # identified original system in the download agent.
            try: final('factory')
            except Exception as caught: result['recovery_error'] = str(caught)
    if result['final_layout']:
        try: result['reboot_acknowledged'] = loader.shutdown(bootmode=1) is True
        except Exception as caught: result['reboot_error'] = str(caught)
        event('reboot', acknowledged=result['reboot_acknowledged'])
        if result['reboot_acknowledged']:
            print('Download agent acknowledged reboot request', flush=True)
    result['operation_qualified'] &= result['reboot_acknowledged']
    result['events'] = events
    save('swap-result.json', (json.dumps(result, indent=2) + '\n').encode())
    return result['operation_qualified']
