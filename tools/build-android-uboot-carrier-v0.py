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
# LK's mt6797 build enables CFG_DTB_EARLY_LOADER_SUPPORT (platform/mt6797/
# rules.mk:34).  Early in platform_init, bldr_load_dtb() (app/mt_boot/
# mt_boot.c:686) computes, for a 64-bit kernel:
#     offset = page_sz + kernel_sz - DTB_MAX_SIZE      /* u32 arithmetic */
# with DTB_MAX_SIZE = 512 KiB (app/mt_boot/mt_boot.h:36), then reads a
# 512 KiB window ending at the kernel blob's end and scans it backwards for
# the appended DTB, which it copies to tags_addr.  When kernel_sz + page_sz
# < 512 KiB the subtraction underflows, the partition read at ~4 GiB fails,
# no DTB ever reaches tags_addr, and boot_linux_fdt() later dies in
# "Can't find device tree" while(1) (mt_boot.c:1023) without executing one
# payload instruction.  Because CFG_DTB_EARLY_LOADER_SUPPORT also compiles
# out the late DTB copy (mt_boot.c:972), the only fix on the image side is
# to make the kernel blob at least 512 KiB.  We additionally keep kernel_sz
# a multiple of page_sz so ROUNDUP(offset, page_sz) == offset and LK's scan
# window ends exactly at the DTB's last byte, touching no ramdisk bytes.
LK_DTB_MAX_SIZE = 512 * 1024
# Load where the project's Linux images provably load.  0x40080000 is LK's own
# native kernel address and satisfies LK's 512 KiB alignment check, but a
# U-Boot built for it never executed: the board cycled every 28 s, identical to
# the baseline, and a bounded watchdog hold in board_late_init did not shift
# that cadence by a single second over fourteen intervals.  Every accepted
# NixOS p22 image on this device uses 0x40200000, so match the one address that
# is known good on this hardware rather than the one that merely looks legal.
# U-Boot is CONFIG_POSITION_INDEPENDENT, so running from here needs no relink.
KERNEL_ADDR = 0x40200000
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


def build(uboot: bytes, ramdisk: bytes, dtb: bytes, cmdline: str = CMDLINE) -> tuple[bytes, bytes]:
    encoded_cmdline = cmdline.encode('ascii')
    # Gemini's LK ignores extra_cmdline and reads past a full first field
    # into the image ID. Keep a NUL terminator inside the first 512 bytes.
    if len(encoded_cmdline) >= 512 or b'\0' in encoded_cmdline or CMDLINE not in cmdline.split():
        raise ValueError('Invalid Android boot command line')
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

    if len(dtb) > LK_DTB_MAX_SIZE:
        raise ValueError("carrier DTB exceeds LK early-loader window")

    compressed = gzip.compress(uboot, compresslevel=9, mtime=0)
    if gzip.decompress(compressed) != uboot:
        raise ValueError("internal deterministic gzip round-trip failed")
    # Zero padding sits between the gzip stream and the DTB: LK's raw-inflate
    # (zunzip, Z_FINISH) stops at the deflate stream end and never reads it,
    # and both of LK's backward FDT-magic scans still find the DTB first
    # because it remains the tail of the blob.
    kernel_len = max(
        LK_DTB_MAX_SIZE, align(len(compressed) + len(dtb), PAGE_SIZE)
    )
    padding = kernel_len - len(compressed) - len(dtb)
    kernel = compressed + b"\0" * padding + dtb
    assert len(kernel) == kernel_len and kernel_len % PAGE_SIZE == 0
    # Re-run LK's early-loader window arithmetic against the finished blob.
    early_offset = PAGE_SIZE + len(kernel) - LK_DTB_MAX_SIZE
    if early_offset < 0 or early_offset % PAGE_SIZE != 0:
        raise ValueError("early-loader window is misaligned or underflows")
    window = (bytes(PAGE_SIZE) + kernel)[early_offset:early_offset + LK_DTB_MAX_SIZE]
    found = window.rfind(FDT_MAGIC)
    if found != LK_DTB_MAX_SIZE - len(dtb):
        raise ValueError(
            f"early-loader backward scan would find 0x{found:x}, "
            f"expected 0x{LK_DTB_MAX_SIZE - len(dtb):x}"
        )
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
    header[64:576] = encoded_cmdline[:512].ljust(512, b"\0")
    header[608:1632] = encoded_cmdline[512:].ljust(1024, b"\0")
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
    parser.add_argument("--cmdline", default=CMDLINE)
    args = parser.parse_args()

    if args.output.exists():
        print(f"error: refusing to overwrite {args.output}", file=sys.stderr)
        return 2
    try:
        uboot = read(args.uboot)
        ramdisk = read(args.ramdisk)
        dtb = read(args.dtb)
        image, compressed = build(uboot, ramdisk, dtb, args.cmdline)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(image)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"output={args.output}")
    print(f"uboot_size={len(uboot)}")
    print(f"uboot_gzip_size={len(compressed)}")
    print(f"carrier_dtb_size={len(dtb)}")
    kernel_sz = struct.unpack_from("<I", image, 8)[0]
    print(f"kernel_field_size=0x{kernel_sz:x}")
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
