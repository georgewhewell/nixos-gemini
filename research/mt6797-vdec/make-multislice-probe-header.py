#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pack verified original slice fixtures into the private diagnostic's header."""
import argparse
import hashlib
import json
from pathlib import Path


def load_partition(root, partition):
    folder = root / ('multislice-pcm-' + partition)
    metadata = json.loads((folder / 'fixture.json').read_text())
    if (metadata['partition'] != partition or not metadata['software_decode_verified'] or
            (metadata['width'], metadata['height'], metadata['frames']) != (64, 64, 2)):
        raise ValueError('Fixture metadata does not describe the original 64x64 pair')
    blobs = {}
    for name, digest in metadata['hashes'].items():
        data = (folder / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Fixture identity differs: ' + str(folder / name))
        blobs[name] = data
    frames = []
    for frame in range(2):
        slices = [entry for entry in metadata['slices'] if entry['frame'] == frame]
        next_mb = 0
        for entry in slices:
            if (entry['first_mb'] != next_mb or entry['count'] < 1 or
                    entry['last_mb'] != next_mb + entry['count'] - 1):
                raise ValueError('Slice partition is not complete and ordered')
            next_mb += entry['count']
        if next_mb != 16:
            raise ValueError('Slice partition does not cover the picture')
        frames.append([blobs[entry['nal']] for entry in slices])
    reference = blobs['reference.yuv']
    if len(reference) != 12288 or reference[:6144] != reference[6144:]:
        raise ValueError('Expected identical original I_PCM/P_Skip pictures')
    return frames, reference


def c_arrays(arrays):
    lines = []
    for name, data in arrays.items():
        lines.append('static const u8 ' + name + '[] = {')
        for offset in range(0, len(data), 12):
            lines.append('\t' + ', '.join(f'0x{x:02x}' for x in data[offset:offset + 12]) + ',')
        lines.append('};')
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True,
                        help='Directory containing multislice-pcm-one/two/four/sixteen/uneven')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    partitions = {}
    expected = None
    for partition in ('one', 'two', 'four', 'sixteen', 'uneven'):
        frames, reference = load_partition(args.fixtures, partition)
        if expected is not None and reference != expected:
            raise ValueError('Partitions describe different pictures')
        expected = reference
        partitions[partition] = frames
    first, last = partitions['two'][0]
    arrays = {
        'multislice_first_nal': first,
        'multislice_last_nal': last,
        'multislice_packet': b'\x00\x00\x00\x01'.join((first, last)),
        'multislice_full_nal': partitions['one'][0][0],
    }
    lines = ['/* SPDX-License-Identifier: GPL-2.0-only */',
             '/* Original fixture bytes from make-multislice-pcm-fixture.py;',
             ' * software decoded and mathematically checked before any hardware use. */']
    lines.extend(c_arrays(arrays))
    lines.append('')
    extra = {}
    for partition in ('two', 'four', 'sixteen', 'uneven', 'one'):
        name = 'full' if partition == 'one' else partition
        for frame in range(2):
            if frame == 0 and partition in ('one', 'two'):
                continue
            key = 'multislice_' + name + ('_p' if frame else '')
            key += '_nal' if partition == 'one' else '_packet'
            extra[key] = b'\x00\x00\x00\x01'.join(partitions[partition][frame])
    lines.extend(c_arrays(extra))
    args.out.write_text('\n'.join(lines) + '\n')
    print('Packed original fixtures:', hashlib.sha256(args.out.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
