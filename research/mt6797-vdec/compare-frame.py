#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare a raw decoder allocation against the verified pcm64 fixture.

The layout must be explicitly selected; matching it is a hardware qualification
result, not an assumption made by this tool. MM21's public layout is described at
https://docs.kernel.org/userspace-api/media/v4l/pixfmt-yuv-planar.html
"""
import argparse
import hashlib
import json
from pathlib import Path


def unpack(data, width, height, stride, chroma_offset, layout):
    if min(width, height, stride) <= 0 or stride < width or height % 2 or width % 2 or \
       chroma_offset < stride * height:
        raise ValueError('Invalid geometry or overlapping planes')
    if layout == 'mm21':
        padded_height = (height + 31) // 32 * 32
        if stride % 16 or chroma_offset < stride * padded_height:
            raise ValueError('MM21 requires complete 16x32 storage tiles')
        if len(data) < chroma_offset + stride * padded_height // 2:
            raise ValueError('Decoder allocation lacks complete MM21 storage tiles')

    result = bytearray()
    for component in (None, 0, 1):
        rows = height if component is None else height // 2
        plane = 0 if component is None else chroma_offset
        for row in range(rows):
            if layout == 'nv12':
                line = data[plane + row * stride:plane + row * stride + width]
                if len(line) != width:
                    raise ValueError('Decoder allocation is too short')
                result.extend(line if component is None else line[component::2])
                continue
            tile_height = 32 if component is None else 16
            line_base = plane + (row // tile_height) * stride * tile_height + \
                        (row % tile_height) * 16
            for x in range(0, width, 16):
                start = line_base + (x // 16) * 16 * tile_height
                line = data[start:start + min(16, width - x)]
                result.extend(line if component is None else line[component::2])
    if len(result) != width * height * 3 // 2:
        raise ValueError('Decoder allocation is too short')
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('allocation', type=Path)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--prefix', default='pcm64',
                        choices=('pcm64', 'grey64', 'pattern64', 'pcm64-p', 'pcm64-motion'))
    parser.add_argument('--layout', choices=('nv12', 'mm21'), required=True)
    parser.add_argument('--stride', type=int, required=True)
    parser.add_argument('--chroma-offset', type=int, required=True)
    args = parser.parse_args()
    metadata = json.loads((args.fixture / (args.prefix + '.json')).read_text())
    expected = (args.fixture / (args.prefix + '.yuv')).read_bytes()
    if not metadata['software_decode_verified'] or \
       hashlib.sha256(expected).hexdigest() != metadata['hashes'][args.prefix + '.yuv'] or \
       len(expected) != metadata['width'] * metadata['height'] * 3 // 2:
        raise ValueError('Fixture reference identity differs')
    actual = unpack(args.allocation.read_bytes(), metadata['width'], metadata['height'],
                    args.stride, args.chroma_offset, args.layout)
    if actual != expected:
        differences = sum(a != b for a, b in zip(actual, expected))
        first = next(i for i, (a, b) in enumerate(zip(actual, expected)) if a != b)
        raise SystemExit(f'FAIL: {differences}/{len(expected)} pixels differ; '
                         f'first byte {first}: actual={actual[first]}, expected={expected[first]}')
    print(f'PASS: all {len(expected)} decoded sample bytes match; '
          f'layout={args.layout}, stride={args.stride}, chroma_offset={args.chroma_offset}')


if __name__ == '__main__':
    main()
