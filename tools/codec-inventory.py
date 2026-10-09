#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Query V4L2 codec interfaces without allocating buffers or starting a stream.

Run on the board: python3 codec-inventory.py [/dev/videoN ...]
The JSON is an interface inventory, not evidence of successful acceleration.
Only Linux's public QUERYCAP, ENUM_FMT and QUERYCTRL ioctls are used.
"""
import argparse
import errno
import fcntl
import glob
import json
import os
import struct
import sys


CAP = struct.Struct("<16s32s32s6I")
FMT = struct.Struct("<III32sII3I")
CTRL = struct.Struct("<II32siiiiI2I")
NEXT_CTRL = 0x80000000 | 0x40000000


def request(direction, number, size):
    return (direction << 30) | (size << 16) | (ord("V") << 8) | number


def query(fd, opcode, data):
    while True:
        try:
            fcntl.ioctl(fd, opcode, data, True)
            return
        except InterruptedError:
            continue


def cstring(raw):
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def formats(fd, kind):
    result = []
    for index in range(4096):
        data = bytearray(FMT.pack(index, kind, 0, b"", 0, 0, 0, 0, 0))
        try:
            query(fd, request(3, 2, FMT.size), data)
        except OSError as error:
            if error.errno == errno.EINVAL:
                return result
            raise
        fields = FMT.unpack(data)
        result.append({"fourcc": struct.pack("<I", fields[4]).decode("ascii", errors="replace"),
                       "description": cstring(fields[3]), "flags": fields[2]})
    raise RuntimeError("format enumeration did not terminate")


def controls(fd):
    result = []
    previous = 0
    for _ in range(4096):
        data = bytearray(CTRL.pack(previous | NEXT_CTRL, 0, b"", 0, 0, 0, 0, 0, 0, 0))
        try:
            query(fd, request(3, 36, CTRL.size), data)
        except OSError as error:
            if error.errno == errno.EINVAL:
                return result
            raise
        fields = CTRL.unpack(data)
        if fields[0] <= previous:
            raise RuntimeError("control enumeration did not advance")
        previous = fields[0]
        result.append({"id": previous, "name": cstring(fields[2]),
                       "type": fields[1], "flags": fields[7]})
    raise RuntimeError("control enumeration did not terminate")


def inspect(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        data = bytearray(CAP.size)
        query(fd, request(2, 0, CAP.size), data)
        fields = CAP.unpack(data)
        caps = fields[5] if fields[4] & 0x80000000 else fields[4]
        # Device capabilities, rather than the parent device's union of caps,
        # determine which queue types this particular node supports.
        queues = {}
        if caps & 0x00004000:  # V4L2_CAP_VIDEO_M2M_MPLANE
            queues = {"capture_mplane": formats(fd, 9), "output_mplane": formats(fd, 10)}
        elif caps & 0x00008000:  # V4L2_CAP_VIDEO_M2M
            queues = {"capture": formats(fd, 1), "output": formats(fd, 2)}
        return {"path": path, "driver": cstring(fields[0]), "card": cstring(fields[1]),
                "bus": cstring(fields[2]), "version": fields[3], "capabilities": caps,
                "queues": queues, "controls": controls(fd)}
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("devices", nargs="*")
    args = parser.parse_args()
    report = {"schema": 1, "query_only": True, "streaming_tested": False,
              "requests_capability": "not queried (requires a buffer ioctl)", "devices": []}
    failed = False
    for path in args.devices or sorted(glob.glob("/dev/video[0-9]*")):
        try:
            report["devices"].append(inspect(path))
        except (OSError, RuntimeError) as error:
            report["devices"].append({"path": path, "error": str(error)})
            failed = True
    print(json.dumps(report, indent=2))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
