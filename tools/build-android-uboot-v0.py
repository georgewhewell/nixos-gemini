#!/usr/bin/env python3
"""Wrap a raw U-Boot binary for the Gemini PDA's retained Android 8 LK."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import pathlib
import struct
import sys


ANDROID_MAGIC = b"ANDROID!"
FDT_MAGIC = b"\xd0\x0d\xfe\xed"
PAGE_SIZE = 2048
PARTITION_SIZE = 16 * 1024 * 1024
LK_DECOMPRESS_LIMIT = 28 * 1024 * 1024
KERNEL_ADDR = 0x40080000
RAMDISK_ADDR = 0x45000000
SECOND_ADDR = 0x40F00000
TAGS_ADDR = 0x44000000
CMDLINE = "bootopt=64S3,32N2,64N2"


def align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def read(path: pathlib.Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def canonical_v0_id(kernel: bytes, ramdisk: bytes) -> bytes:
    digest = hashlib.sha1()
    for payload in (kernel, ramdisk, b""):
        digest.update(payload)
        digest.update(struct.pack("<I", len(payload)))
    return digest.digest()


def build(uboot: bytes, ramdisk: bytes, dtb: bytes) -> tuple[bytes, bytes]:
    if not uboot:
        raise ValueError("U-Boot binary is empty")
    if len(uboot) > LK_DECOMPRESS_LIMIT:
        raise ValueError(
            f"U-Boot exceeds LK's 28 MiB decompression window: {len(uboot)}"
        )
    if len(dtb) < 8 or not dtb.startswith(FDT_MAGIC):
        raise ValueError("carrier DTB has no flattened-device-tree magic")
    dtb_size = struct.unpack_from(">I", dtb, 4)[0]
    if dtb_size != len(dtb):
        raise ValueError(
            f"carrier DTB totalsize is {dtb_size}, but file size is {len(dtb)}"
        )

    compressed = gzip.compress(uboot, compresslevel=9, mtime=0)
    if gzip.decompress(compressed) != uboot:
        raise ValueError("internal deterministic gzip round-trip failed")
    kernel = compressed + dtb
    digest = canonical_v0_id(kernel, ramdisk)

    header = bytearray(PAGE_SIZE)
    values = (
        len(kernel),
        KERNEL_ADDR,
        len(ramdisk),
        RAMDISK_ADDR,
        0,
        SECOND_ADDR,
        TAGS_ADDR,
        PAGE_SIZE,
        0,
        0,
    )
    struct.pack_into("<8s10I", header, 0, ANDROID_MAGIC, *values)
    header[48:64] = b"gemini-uboot\0\0\0\0"
    header[64:576] = CMDLINE.encode("ascii").ljust(512, b"\0")
    header[576:596] = digest

    image = bytearray(header)
    for payload in (kernel, ramdisk):
        image.extend(payload)
        image.extend(b"\0" * (align(len(image), PAGE_SIZE) - len(image)))
    if len(image) > PARTITION_SIZE:
        raise ValueError(
            f"boot image exceeds the 16 MiB p22 partition: {len(image)}"
        )
    return bytes(image), compressed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uboot", type=pathlib.Path, required=True)
    parser.add_argument("--ramdisk", type=pathlib.Path, required=True)
    parser.add_argument("--dtb", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        print(f"error: refusing to overwrite {args.output}", file=sys.stderr)
        return 2
    try:
        uboot = read(args.uboot)
        ramdisk = read(args.ramdisk)
        dtb = read(args.dtb)
        image, compressed = build(uboot, ramdisk, dtb)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(image)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"output={args.output}")
    print(f"uboot_size={len(uboot)}")
    print(f"uboot_gzip_size={len(compressed)}")
    print(f"carrier_dtb_size={len(dtb)}")
    print(f"ramdisk_size={len(ramdisk)}")
    print(f"kernel_addr=0x{KERNEL_ADDR:x}")
    print(f"ramdisk_addr=0x{RAMDISK_ADDR:x}")
    print(f"tags_addr=0x{TAGS_ADDR:x}")
    print(f"raw_size={len(image)}")
    print(f"raw_sha256={hashlib.sha256(image).hexdigest()}")
    print("hardware_write=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
