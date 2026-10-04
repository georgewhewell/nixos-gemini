#!/usr/bin/env python3
"""Prepare a native mkswap header on a new host file; never access a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import uuid

BIN = Path('/nix/store/zwv3i1aawb8zmxj029x7lyd0an5q4nj6-util-linux-2.42.2-bin/bin')
PAGE_SIZE = 4096
SIZE = 5 * 1024**3
OFFSET = 111622144 * 512
UUID = '85ae0e4c-91cb-4b97-a960-fc6780f42361'
LABEL = 'gemini-swap'


def validate(raw):
    # Linux include/linux/swap.h: union swap_header. Check against an
    # independently generated util-linux image, including unused bytes.
    expected = bytearray(PAGE_SIZE)
    struct.pack_into('<III', expected, 1024, 1, SIZE // PAGE_SIZE - 1, 0)
    expected[1036:1052] = uuid.UUID(UUID).bytes
    expected[1052:1052 + len(LABEL)] = LABEL.encode()
    expected[-10:] = b'SWAPSPACE2'
    if raw != bytes(expected):
        raise ValueError('Swap header version, bounds, identity or reserved bytes differ')
    return dict(uuid=UUID, label=LABEL, page_size=PAGE_SIZE,
                partition_bytes=SIZE, usable_bytes=SIZE-PAGE_SIZE,
                header_sha256=hashlib.sha256(raw).hexdigest())


def prepare(directory):
    directory = Path(directory); directory.mkdir(mode=0o700)
    source = directory / 'swap-template.img'
    with source.open('xb') as stream: stream.truncate(SIZE)
    source.chmod(0o600)
    command = [str(BIN / 'mkswap'), '--endianness=little', '--pagesize', str(PAGE_SIZE),
               '--uuid', UUID, '--label', LABEL, str(source)]
    with (directory / 'mkswap.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=30)
    with source.open('rb') as stream: raw = stream.read(PAGE_SIZE)
    proof = validate(raw)
    output = subprocess.run([str(BIN / 'blkid'), '-p', '-o', 'export', str(source)],
                            capture_output=True, text=True, check=True, timeout=20).stdout
    observed = dict(row.split('=', 1) for row in output.splitlines())
    if any(observed.get(k) != v for k, v in {'UUID': UUID, 'LABEL': LABEL, 'TYPE': 'swap', 'VERSION': '1'}.items()):
        raise RuntimeError('Native blkid disagrees with swap header identity')
    with (directory / 'swap-header.bin').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    (directory / 'swap-header.bin').chmod(0o400)
    proof.update(schema='gemini-fixed-swap-header-v1', write_offset=OFFSET, write_size=PAGE_SIZE,
                 mkswap_command=command, blkid=observed, device_writes_performed=False,
                 swap_activation_qualified=False)
    (directory / 'manifest.json').write_text(json.dumps(proof, indent=2) + '\n')
    # Only the inspected first page is needed by the future transaction.
    source.unlink()
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    proof = prepare(args.out.resolve())
    print('Prepared host-only swap header: ' + proof['header_sha256'])


if __name__ == '__main__': main()
