#!/usr/bin/env python3
"""Bind the A72 admission profile to the exact composed kernel and DTB.

The arm64 late-CPU profile accepts only a static /chosen record.  This helper
creates that record after the final diagnostic overlay has been composed: the
DTB is not an input to vmlinux, so the kernel build ID and embedded IKCONFIG
can be measured without a dependency cycle.
"""

import argparse
import hashlib
import re
import struct
import subprocess
from pathlib import Path


DOMAIN = b"gemini-a41-runtime-binding-v1\0"
PROFILE_ID = b"mt6797-a53-a72-a41-v7\0"
NODE = "/chosen/gemini-late-cpu-provenance"
CONFIG_INPUTS = bytes.fromhex(
    "5968c24f1904c0559dea25480c41fbc7db49e822dc3600d1bdd7632330853f40"
)


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def kernel_config_blob(vmlinux: Path) -> bytes:
    symbols = command("nm", "-n", str(vmlinux))
    addresses = {
        fields[2]: int(fields[0], 16)
        for line in symbols.splitlines()
        if len((fields := line.split())) >= 3
        and fields[2] in {"kernel_config_data", "kernel_config_data_end"}
    }
    if set(addresses) != {"kernel_config_data", "kernel_config_data_end"}:
        raise ValueError("kernel config symbols are missing")

    sections = command("readelf", "-SW", str(vmlinux))
    match = re.search(
        r"^\s*\[\s*\d+\]\s+\.rodata\s+\S+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)",
        sections,
        re.MULTILINE,
    )
    if not match:
        raise ValueError("vmlinux has no readable .rodata section")
    rodata_address, rodata_offset = (int(value, 16) for value in match.groups())
    begin = rodata_offset + addresses["kernel_config_data"] - rodata_address
    end = rodata_offset + addresses["kernel_config_data_end"] - rodata_address
    data = vmlinux.read_bytes()[begin:end]
    if not data:
        raise ValueError("embedded IKCONFIG is empty")
    return data


def digest(tag: bytes, length: int, payload: bytes) -> bytes:
    return hashlib.sha256(DOMAIN + tag + length.to_bytes(length, "big") + payload).digest()


def blob64(tag: bytes, payload: bytes) -> bytes:
    return digest(tag, 8, payload)


def blob32(tag: bytes, payload: bytes) -> bytes:
    return digest(tag, 4, payload)


def fdtput_bytes(fdtput: str, dtb: Path, name: str, value: bytes) -> None:
    subprocess.run(
        [fdtput, "-t", "bx", str(dtb), NODE, name, *[f"{byte:02x}" for byte in value]],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--vmlinux", type=Path, required=True)
    parser.add_argument("--kernel-config", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--cmdline", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--fdtput", required=True)
    args = parser.parse_args()

    raw_config = kernel_config_blob(args.vmlinux)
    generated = subprocess.check_output(["gzip", "-n", "-9", "-c", str(args.kernel_config)])
    if raw_config != generated:
        raise ValueError("embedded IKCONFIG does not match gzip -n -9 kernel.config")

    notes = command("readelf", "-n", str(args.vmlinux))
    build_id_match = re.search(r"Build ID:\s*([0-9a-fA-F]{40})", notes)
    if not build_id_match:
        raise ValueError("vmlinux does not contain the required 20-byte GNU build ID")
    build_id = bytes.fromhex(build_id_match.group(1))

    values = {
        "expected-ikconfig-identity": blob64(b"ikconfig\0", raw_config),
        "expected-gnu-build-id-identity": blob32(b"gnu-build-id\0", build_id),
        "expected-cmdline-identity": blob64(b"cmdline\0", args.cmdline.encode()),
        "upstream-source-sha256": hashlib.sha256(args.source_revision.encode()).digest(),
        "patch-series-sha256": hashlib.sha256(args.vmlinux.read_bytes()).digest(),
        "config-inputs-sha256": CONFIG_INPUTS,
        "resolved-config-sha256": hashlib.sha256(args.kernel_config.read_bytes()).digest(),
        "package-image-sha256": hashlib.sha256(args.image.read_bytes()).digest(),
        "build-provenance-sha256": hashlib.sha256(
            args.source_revision.encode() + raw_config + build_id + args.cmdline.encode()
        ).digest(),
    }
    record = (
        DOMAIN
        + b"record\0"
        + struct.pack(">I", 1)
        + struct.pack(">H", len(PROFILE_ID) - 1)
        + PROFILE_ID[:-1]
        + struct.pack(">I", 2)
        + struct.pack(">II", 8, 9)
        + struct.pack(">I", 2)
        + struct.pack(">QQ", 0x200, 0x201)
        + b"".join(values[name] for name in (
            "expected-ikconfig-identity",
            "expected-gnu-build-id-identity",
            "expected-cmdline-identity",
            "upstream-source-sha256",
            "patch-series-sha256",
            "config-inputs-sha256",
            "resolved-config-sha256",
            "package-image-sha256",
            "build-provenance-sha256",
        ))
    )
    values["record-identity"] = hashlib.sha256(record).digest()

    subprocess.run([args.fdtput, "-c", str(args.dtb), NODE], check=True)
    subprocess.run([args.fdtput, "-t", "s", str(args.dtb), NODE, "name", "gemini-late-cpu-provenance"], check=True)
    subprocess.run([args.fdtput, "-t", "s", str(args.dtb), NODE, "compatible", "planet,gemini-a72-runtime-binding-v1"], check=True)
    subprocess.run([args.fdtput, "-t", "i", str(args.dtb), NODE, "schema-version", "1"], check=True)
    subprocess.run([args.fdtput, "-t", "s", str(args.dtb), NODE, "profile-id", PROFILE_ID[:-1].decode()], check=True)
    subprocess.run([args.fdtput, "-t", "i", str(args.dtb), NODE, "target-cpus", "8", "9"], check=True)
    fdtput_bytes(args.fdtput, args.dtb, "target-mpidrs", struct.pack(">QQ", 0x200, 0x201))
    for name, value in values.items():
        fdtput_bytes(args.fdtput, args.dtb, name, value)

    properties = command(args.fdtput.replace("fdtput", "fdtget"), "-p", str(args.dtb), NODE).splitlines()
    expected = {
        "name", "compatible", "schema-version", "profile-id", "target-cpus", "target-mpidrs",
        *values.keys(),
    }
    if set(properties) != expected or len(properties) != len(expected):
        raise ValueError(f"unexpected provenance properties: {properties}")
    print("a72-provenance-record=" + values["record-identity"].hex())


if __name__ == "__main__":
    main()
