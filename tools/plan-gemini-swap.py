#!/usr/bin/env python3
"""Prepare exact GPT byte ranges for fixed swap, without opening any device.

Inputs are captured primary (first 32 KiB) and backup (last 33 sectors) GPT
bytes plus the observed ext4 extent. Outputs are a reviewable host-only plan;
this tool has no flash, SSH, mount, formatting or reboot operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib

SECTOR = 512
SECTORS = 122142720
PRIMARY_SHA = '6addff62cc67f5b5fac9bd87194b6643f4029262251c51c1e43e1b5b64cb887d'
DATA_UUID = '5d978ad4-a987-4b3f-bef6-f73ad7c2d986'
DATA_START = 89372672
OLD_DATA_SIZE = 32737247
DATA_SIZE = 22249472
SWAP_START = 111622144
SWAP_SIZE = 10485760
SWAP_GUID = '5e0f3a1c-9b2d-4c8e-a7f6-2d1b0c9e8a71'
SWAP_TYPE = '0657fd6d-a4ab-43c4-84e5-0933c84b4f4f'
ENTRY_SIZE = 128
ENTRIES = 128
TABLE_SIZE = ENTRY_SIZE * ENTRIES


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def header(raw, backup=False):
    expected_size = 33 * SECTOR if backup else 32768
    if len(raw) != expected_size:
        raise ValueError('Incomplete GPT capture')
    off = 32 * SECTOR if backup else SECTOR
    h = raw[off:off + SECTOR]
    signature, revision, size, crc, reserved = struct.unpack_from('<8sIIII', h)
    if (signature, revision, size, reserved) != (b'EFI PART', 0x10000, 92, 0):
        raise ValueError('Unexpected GPT header format')
    checked = bytearray(h[:size]);checked[16:20] = bytes(4)
    if zlib.crc32(checked) != crc:
        raise ValueError('GPT header CRC mismatch')
    current, alternate, first, last = struct.unpack_from('<QQQQ', h, 24)
    table_lba, count, entry_size, table_crc = struct.unpack_from('<QIII', h, 72)
    if (current, alternate, first, last, table_lba, count, entry_size) != (
            SECTORS - 1 if backup else 1, 1 if backup else SECTORS - 1,
            34, SECTORS - 34, SECTORS - 33 if backup else 2, ENTRIES, ENTRY_SIZE):
        raise ValueError('Unexpected GPT bounds or table geometry')
    start = 0 if backup else 2 * SECTOR
    table = raw[start:start + TABLE_SIZE]
    if zlib.crc32(table) != table_crc:
        raise ValueError('GPT table CRC mismatch')
    return h, table


def geometry(entry):
    first, last = struct.unpack_from('<QQ', entry, 32)
    name = entry[56:128].decode('utf-16-le').rstrip('\0')
    return name, first, last - first + 1


def verify_pair(primary, backup):
    ph, pt = header(primary)
    bh, bt = header(backup, True)
    if ph[56:72] != bh[56:72] or pt != bt:
        raise ValueError('Primary and backup GPT disagree')
    return pt


def rewrite(raw, table, backup=False):
    data = bytearray(raw)
    start = 0 if backup else 2 * SECTOR
    off = 32 * SECTOR if backup else SECTOR
    data[start:start + TABLE_SIZE] = table
    struct.pack_into('<I', data, off + 88, zlib.crc32(table))
    struct.pack_into('<I', data, off + 16, 0)
    struct.pack_into('<I', data, off + 16, zlib.crc32(data[off:off + 92]))
    return bytes(data)


def plan(primary, backup, extent):
    if sha(primary) != PRIMARY_SHA:
        raise ValueError('Primary GPT is not the captured factory baseline')
    table = verify_pair(primary, backup)
    entries = [table[i:i + ENTRY_SIZE] for i in range(0, TABLE_SIZE, ENTRY_SIZE)]
    if any(entry[:16] == bytes(16) for entry in entries[:33]) or any(any(entry) for entry in entries[33:]):
        raise ValueError('Expected exactly the 33 factory partitions')
    for number, expected in {
        22: ('boot', 362496, 32768), 29: ('linux', 6586368, 82720768),
        30: ('boot2', 89307136, 32768), 31: ('boot3', 89339904, 32768),
        32: ('userdata', DATA_START, OLD_DATA_SIZE), 33: ('flashinfo', 122109919, 32768),
    }.items():
        if geometry(entries[number - 1]) != expected:
            raise ValueError(f'Unexpected p{number} geometry')
    if set(extent) != {'uuid', 'block_count', 'block_size'} or extent['uuid'] != DATA_UUID:
        raise ValueError('Unidentified persistent data filesystem')
    blocks, block_size = extent['block_count'], extent['block_size']
    if type(blocks) is not int or type(block_size) is not int or blocks < 1 or block_size != 4096:
        raise ValueError('Invalid observed ext4 extent')
    if blocks * block_size > DATA_SIZE * SECTOR:
        raise ValueError('Persistent filesystem would exceed the proposed p32')
    data = bytearray(entries[31])
    struct.pack_into('<Q', data, 40, DATA_START + DATA_SIZE - 1)
    swap = bytearray(ENTRY_SIZE)
    swap[:16] = uuid.UUID(SWAP_TYPE).bytes_le
    swap[16:32] = uuid.UUID(SWAP_GUID).bytes_le
    struct.pack_into('<QQQ', swap, 32, SWAP_START, SWAP_START + SWAP_SIZE - 1, 0)
    swap[56:64] = 'swap'.encode('utf-16-le')
    updated = entries.copy();updated[31] = bytes(data);updated[33] = bytes(swap)
    new_table = b''.join(updated)
    new_primary, new_backup = rewrite(primary, new_table), rewrite(backup, new_table, True)
    assert verify_pair(new_primary, new_backup) == new_table
    assert all(updated[i] == entries[i] for i in range(ENTRIES) if i not in (31, 33))
    # Primary writes stop at its table; backup writes start after flashinfo.
    # Never include partition data just to round a GPT write to 32 KiB.
    primary_write = new_primary[:34 * SECTOR]
    manifest = dict(schema='gemini-fixed-swap-plan-v1', device_writes_performed=False,
        primary_before_sha256=sha(primary), backup_before_sha256=sha(backup),
        primary_after_sha256=sha(new_primary), backup_after_sha256=sha(new_backup),
        data_filesystem=extent, data_start=DATA_START, data_sectors=DATA_SIZE,
        swap_start=SWAP_START, swap_sectors=SWAP_SIZE, swap_partuuid=SWAP_GUID,
        changed_partitions=[32, 34], flashinfo_unchanged=True,
        writes=[dict(file='primary-gpt.bin', offset=0, size=len(primary_write), sha256=sha(primary_write)),
                dict(file='backup-gpt.bin', offset=(SECTORS - 33) * SECTOR,
                     size=len(new_backup), sha256=sha(new_backup))],
        rollback=[dict(file='primary-gpt-before.bin', offset=0, size=34 * SECTOR,
                       sha256=sha(primary[:34 * SECTOR])),
                  dict(file='backup-gpt-before.bin', offset=(SECTORS - 33) * SECTOR,
                       size=len(backup), sha256=sha(backup))],
        required_before_execution=['Fresh matching device and offline filesystem/backup checks',
            'Qualified GPT writer with independent readback and rollback',
            'Recovery guards for both old and proposed GPT layouts'])
    return manifest, primary_write, new_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--extent', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    old_primary, old_backup = args.primary.read_bytes(), args.backup.read_bytes()
    manifest, primary, backup = plan(old_primary, old_backup, json.loads(args.extent.read_text()))
    args.out.mkdir(mode=0o700)
    (args.out/'primary-gpt-before.bin').write_bytes(old_primary[:34 * SECTOR])
    (args.out/'backup-gpt-before.bin').write_bytes(old_backup)
    (args.out/'primary-gpt.bin').write_bytes(primary)
    (args.out/'backup-gpt.bin').write_bytes(backup)
    (args.out/'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Host-only fixed-swap plan: {args.out}; no device access')


if __name__ == '__main__':
    main()
