#!/usr/bin/env python3
"""EFI Linux evidence and unique-file provisioning for the p22 trial runner.

No independent writer or reboot path. The caller owns the bounded rescue lane.
All SSH uses the existing pinned Gemini host key, including Stage 1.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import time

ACCEPTED_STORE_SHA = '1ef4d81260718cbb66ff10745f6460552a37ffb31d27565392bba301acd8f527'
ACCEPTED_STORE = f'mainline-nixos-{ACCEPTED_STORE_SHA}.squashfs'
BUNDLE = Path(__file__).resolve().parents[2] / 'handoff/uboot-efi-provenance-fix-1'
# Pinned matching kernel/module/userspace bundle for this hardware trial.
SYSTEM = '/nix/store/1rkszq4jimhspriv141ffx1mzpki2ffa-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
STORE_SHA = '2475e3d85aecd02091b5bfe070bc2963ba8a64981e29ac71258c712c8b3fadd0'
STORE_SIZE = 426971136


def payload():
    if not re.fullmatch('[0-9a-f]{64}', STORE_SHA) or STORE_SIZE <= 0:
        raise RuntimeError('EFI Linux profile has no pinned store')
    name = f'mainline-nixos-{STORE_SHA}.squashfs'
    source = BUNDLE / name
    if source.stat().st_size != STORE_SIZE:
        raise RuntimeError('EFI store size differs from the pinned bundle')
    with source.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != STORE_SHA:
            raise RuntimeError('EFI store hash differs from the pinned bundle')
    manifest = (BUNDLE / 'MANIFEST').read_text().splitlines()
    if f'system={SYSTEM}' not in manifest or f'store-file={name}' not in manifest:
        raise RuntimeError('EFI userspace identity differs from the pinned bundle')
    return source, name


def upload_command(name, before, boot_sha):
    # Inputs below are pinned paths/hashes or captured hexadecimal identities.
    if name != f'mainline-nixos-{STORE_SHA}.squashfs' or not re.fullmatch('[0-9a-f]{64}', STORE_SHA):
        raise ValueError('Unpinned EFI store name')
    if not all(re.fullmatch('[0-9a-f]{64}', v) for v in (boot_sha, before['gpt_sha256'])):
        raise ValueError('Invalid image identity')
    if not re.fullmatch('[0-9a-f-]{36}', before['boot_id']):
        raise ValueError('Invalid boot identity')
    target = '/mnt/gemian/nixos/' + name
    tmp = target + '.provision.tmp'
    required = f'store-provision=required target={target} temp={tmp} sha256={STORE_SHA} size={STORE_SIZE}'
    return f'''set -eu
umask 077
test "$(cat /proc/sys/kernel/random/boot_id)" != '{before['boot_id']}'
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = '{boot_sha}'
test "$(head -c 32768 /dev/mmcblk0 | sha256sum | cut -d' ' -f1)" = '{before['gpt_sha256']}'
test "$(cat /sys/firmware/efi/fw_platform_size)" = 64
test "$(tr -d '\\000' < /sys/firmware/devicetree/base/chosen/gemini,uboot-handoff)" = efi
test "$(cat /run/store-provision.required)" = '{required}'
test ! -L /mnt/gemian/nixos
opts=$(awk '$1 == "/dev/mmcblk0p29" && $2 == "/mnt/gemian" && $3 == "ext4" {{print $4}}' /proc/mounts)
case ",$opts," in *,rw,*) ;; *) exit 1 ;; esac
case ",$opts," in *,noload,*|*,norecovery,*) exit 1 ;; esac
available=$(df -Pk /mnt/gemian/nixos | awk '$1 == "/dev/mmcblk0p29" && $6 == "/mnt/gemian" {{print $4}}')
test "$available" -ge {(STORE_SIZE + 1023)//1024 + 1024}
test ! -e '{target}' && test ! -L '{target}'
test ! -e '{tmp}' && test ! -L '{tmp}'
test -f '/mnt/gemian/nixos/{ACCEPTED_STORE}'
test ! -L '/mnt/gemian/nixos/{ACCEPTED_STORE}'
test "$(sha256sum '/mnt/gemian/nixos/{ACCEPTED_STORE}' | cut -d' ' -f1)" = '{ACCEPTED_STORE_SHA}'
# Exclusive creation, hash validation, then an atomic link that cannot overwrite.
(set -C; cat > '{tmp}')
test "$(stat -c %s '{tmp}')" = '{STORE_SIZE}'
test "$(stat -c %h '{tmp}')" = 1
test "$(sha256sum '{tmp}' | cut -d' ' -f1)" = '{STORE_SHA}'
ln '{tmp}' '{target}'
test "$(stat -c %i '{tmp}')" = "$(stat -c %i '{target}')"
rm -- '{tmp}'
sync
test "$(sha256sum '{target}' | cut -d' ' -f1)" = '{STORE_SHA}'
test "$(sha256sum '/mnt/gemian/nixos/{ACCEPTED_STORE}' | cut -d' ' -f1)" = '{ACCEPTED_STORE_SHA}'
printf '%s\\n' 'store-provision=ready sha256={STORE_SHA} size={STORE_SIZE}' > /run/store-provision.ready
printf '%s\\n' 'EFI store installed and accepted store retained'
'''


def provision(ssh, before, boot_sha, directory, qualify, rescued):
    source, name = payload()
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        if rescued():
            raise RuntimeError('Automatic rescue ran before EFI Stage 1 provisioning')
        try:
            state = qualify.run(ssh + [
                'if test -s /run/store-provision.required; then cat /run/store-provision.required; '
                'elif test -L /run/current-system; then readlink /run/current-system; fi']).strip()
        except subprocess.SubprocessError:
            time.sleep(3)
            continue
        if state == SYSTEM:
            return  # A previous checked trial already installed this unique file.
        if not state.startswith('store-provision=required '):
            time.sleep(3)
            continue
        command = upload_command(name, before, boot_sha)
        (directory / 'store-upload.sh').write_text(command)
        print('EFI Stage 1 is reachable with the known host key; provisioning matching userspace', flush=True)
        with source.open('rb') as f, (directory / 'store-upload.log').open('w') as log:
            subprocess.run(ssh + [command], stdin=f, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=300)
        return
    raise RuntimeError('EFI Stage 1 did not expose provisioning within 150s')


def verify_evidence(log, properties, platform_size, tree):
    for message in ('verified the pre-finalization runtime identity binding',
                    'mt6797-a53-a72-a41-v7 ready'):
        if 'arm64-late-cpu-profile: ' + message not in log:
            raise RuntimeError('EFI kernel did not verify its late-CPU runtime binding: ' + message)
    if platform_size.strip() != '64' or not re.search(r'efi: EFI v[0-9.]+ by Das U-Boot', log):
        raise RuntimeError('Linux did not initialize the U-Boot EFI system table')
    if not re.search(r'efi:.*\bINITRD=0x[0-9a-f]+', log):
        raise RuntimeError('Linux lacks the EFI stub initrd configuration table')
    widths = {'linux,uefi-system-table': 8, 'linux,uefi-mmap-start': 8,
              'linux,uefi-mmap-size': 4, 'linux,uefi-mmap-desc-size': 4,
              'linux,uefi-mmap-desc-ver': 4}
    values = {}
    for key, width in widths.items():
        raw = bytes.fromhex(properties.get(key, ''))
        if len(raw) != width:
            raise RuntimeError('Missing or malformed EFI handoff property: ' + key)
        values[key] = int.from_bytes(raw, 'big')
    if values['linux,uefi-mmap-desc-size'] < 40 or values['linux,uefi-mmap-desc-ver'] != 1:
        raise RuntimeError('Unexpected EFI descriptor format')
    if (not values['linux,uefi-mmap-size'] or
            values['linux,uefi-mmap-size'] % values['linux,uefi-mmap-desc-size']):
        raise RuntimeError('EFI memory map size is invalid')
    for key in ('linux,uefi-system-table', 'linux,uefi-mmap-start'):
        if not 0x40001000 <= values[key] < 0x43fff000:
            raise RuntimeError('EFI handoff table is outside the firmware bank')
    descriptors = []
    for match in re.finditer(r'efi:\s+0x([0-9a-f]+)-0x([0-9a-f]+)\s+\[([^\]]+)\]', log):
        start, end = int(match[1], 16), int(match[2], 16) + 1
        descriptors.append((start, end, match[3].strip()))
    if not descriptors:
        raise RuntimeError('Missing EFI debug memory map')
    # All physical RAM must be represented; reservations stay distinguishable.
    ordered = sorted(descriptors)
    cursor = 0x40000000
    for start, end, kind in ordered:
        if start != cursor or end <= start or end > 0x140000000:
            raise RuntimeError('EFI memory map is overlapping, incomplete or outside RAM')
        cursor = end
    if cursor != 0x140000000:
        raise RuntimeError('EFI memory map omits upper RAM')
    if len(descriptors) != values['linux,uefi-mmap-size'] // values['linux,uefi-mmap-desc-size']:
        raise RuntimeError('EFI debug map differs from the stub descriptor count')
    for start, end, kind in ordered:
        if start >= 0x43fff000 and kind.split('|')[0].strip() not in ('Boot Data', 'Reserved'):
            raise RuntimeError('EFI made unmapped high RAM available to its allocator')
    for key, value in tree.items():
        if not key.startswith('reserved-memory/') or not key.endswith('/reg'):
            continue
        raw = bytes.fromhex(value)
        if not raw or len(raw) % 16:
            raise RuntimeError('Malformed static LK reservation')
        parent = key.rsplit('/', 1)[0]
        status = tree.get(parent + '/status')
        if status and bytes.fromhex(status) not in (b'okay\0', b'ok\0'):
            continue
        expected = 'Reserved' if parent + '/no-map' in tree else 'Boot Data'
        for offset in range(0, len(raw), 16):
            start = int.from_bytes(raw[offset:offset+8], 'big')
            end = start + int.from_bytes(raw[offset+8:offset+16], 'big')
            covered = sum(min(end, hi) - max(start, lo) for lo, hi, kind in ordered
                          if lo < end and hi > start and kind.split('|')[0].strip() == expected)
            if covered != end - start:
                raise RuntimeError('EFI lost an LK reservation: ' + parent)
    return dict(platform_size=64, handoff=values, memory_map=ordered, late_cpu_identity_verified=True,
                exit_boot_services_proven=True)


def evidence(ssh, directory, qualify, tree):
    log = qualify.run(ssh + ['dmesg'])
    (directory / 'candidate-dmesg.txt').write_text(log)
    command = '''set -eu
test ! -e /sys/firmware/devicetree/base/chosen/linux,initrd-start
test ! -e /sys/firmware/devicetree/base/chosen/linux,initrd-end
for name in linux,uefi-system-table linux,uefi-mmap-start linux,uefi-mmap-size linux,uefi-mmap-desc-size linux,uefi-mmap-desc-ver; do
 printf '%s=' "$name"
 od -An -v -tx1 "/sys/firmware/devicetree/base/chosen/$name" | tr -d ' \\n'
 printf '\\n'
done'''
    props = dict(line.split('=', 1) for line in qualify.run(ssh + [command]).splitlines())
    result = verify_evidence(log, props, qualify.run(ssh + ['cat /sys/firmware/efi/fw_platform_size']), tree)
    qualify.save(directory, 'candidate-efi.json', result)
    # Capture the complete tree without printing private modem properties.
    with (directory / 'candidate-fdt.dtb').open('wb') as out:
        subprocess.run(ssh + ['cat /sys/firmware/fdt'], stdout=out, check=True, timeout=25)
