#!/usr/bin/env python3
"""Decode the accepted Gemini DT's fixed ramoops layout from a DA RAM read."""
import argparse
import json
from pathlib import Path
import struct

BASE = 0x44410000
SIZE = 0xe0000
RECORD_SIZE = 0x1000
CONSOLE_OFFSET = 0xaf000
CONSOLE_SIZE = 0x10000
SIGNATURE = 0x43474244


def ring(blob, offset, extent):
    if offset < 0 or extent < 12 or offset + extent > len(blob):
        raise ValueError('Ramoops extent is outside captured bytes')
    sig, start, size = struct.unpack_from('<III', blob, offset)
    if sig != SIGNATURE or size > extent - 12 or start > size:
        raise ValueError(f'Invalid ramoops ring at {BASE + offset:#x}')
    data = blob[offset+12:offset+12+size]
    return data[start:] + data[:start]


def decode(source, output):
    blob = source.read_bytes()
    if len(blob) != SIZE:
        raise ValueError('Expected the full 896 KiB Gemini ramoops region')
    output.mkdir(exist_ok=False)
    result = dict(source=str(source), base=hex(BASE), size=SIZE, valid=[], invalid=[])
    regions = [('console', CONSOLE_OFFSET, CONSOLE_SIZE)]
    regions += [(f'record-{i:03}', i * RECORD_SIZE, RECORD_SIZE)
                for i in range(CONSOLE_OFFSET // RECORD_SIZE)]
    for name, offset, size in regions:
        try:
            data = ring(blob, offset, size)
            result['valid'].append(dict(name=name, bytes=len(data)))
            if data:
                (output / (name + '.txt')).write_bytes(data)
        except ValueError as error:
            result['invalid'].append(str(error))
    (output / 'manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path); p.add_argument('output', type=Path)
    a=p.parse_args(); result=decode(a.source,a.output)
    print(f"Decoded {len(result['valid'])} valid rings; {len(result['invalid'])} invalid")
