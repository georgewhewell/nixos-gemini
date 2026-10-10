#!/usr/bin/env python3
"""Build a host-only, no-swap rescue derivative of a recorded direct-boot bundle.

The old kernel, DTB and NixOS closure remain byte-identical. Only the Android
command line and the initramfs init script change. This does not flash, reboot,
or qualify the result. It is a temporary migration fallback, not a normal
development system or a substitute for qualifying the current zram system.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

PAGE = 2048
SIZE = 16 * 1024 * 1024
PARTUUID = '5e0f3a1c-9b2d-4c8e-a7f6-2d1b0c9e8a71'
SWAP_UNIT = r'dev-disk-by\x2dpartuuid-5e0f3a1c\x2d9b2d\x2d4c8e\x2da7f6\x2d2d1b0c9e8a71.swap'
MASK_UNITS = ['dev-mmcblk0p34.swap', SWAP_UNIT, 'swap.target']
POLICY_ARGS = ['zswap.enabled=0', 'noresume', 'systemd.gpt_auto=0'] + [
    'systemd.mask='+unit for unit in MASK_UNITS]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def align(n, size):
    return (n+size-1)//size*size


def parse_archive(raw):
    """Parse newc without extracting files or following archive symlinks."""
    entries, names, pos = [], set(), 0
    while pos+110 <= len(raw):
        header = raw[pos:pos+110]
        if header[:6] != b'070701' or not re.fullmatch(b'[0-9a-fA-F]{104}', header[6:]):
            raise ValueError('Invalid newc header')
        size, namesize = int(header[54:62], 16), int(header[94:102], 16)
        end = pos+110+namesize
        if namesize < 1 or end > len(raw) or raw[end-1] != 0:
            raise ValueError('Invalid newc name')
        name = raw[pos+110:end-1].decode('ascii')
        normalized = name.removeprefix('./')
        if not normalized or name.startswith('/') or '..' in name.split('/') or normalized in names:
            raise ValueError('Unsafe or duplicate archive name')
        names.add(normalized)
        start = align(end, 4)
        following = align(start+size, 4)
        if following > len(raw):
            raise ValueError('Truncated newc body')
        entries.append((name, header, raw[start:start+size]))
        pos = following
        if name == 'TRAILER!!!':
            if size or raw[pos:].strip(b'\0'):
                raise ValueError('Invalid archive trailer')
            return entries
    raise ValueError('Missing archive trailer')


def serialize_archive(entries):
    raw = bytearray()
    for name, header, data in entries:
        name = name.encode('ascii')+b'\0'
        header = bytearray(header)
        if len(data) != int(header[54:62], 16):
            header[54:62] = f'{len(data):08X}'.encode()
        raw.extend(header)
        raw.extend(name)
        raw.extend(b'\0'*(align(len(raw), 4)-len(raw)))
        raw.extend(data)
        raw.extend(b'\0'*(align(len(raw), 4)-len(raw)))
    raw.extend(b'\0'*(align(len(raw), 512)-len(raw)))
    return bytes(raw)


def remove_resume(init):
    pattern = r'^hibernate_resume\(\) \{\n.*?^\}\n'
    matches = list(re.finditer(pattern, init, re.M | re.S))
    if len(matches) != 1 or '/sys/power/resume' not in matches[0][0]:
        raise ValueError('Expected exactly one old hibernation-resume function')
    if init.count('\nhibernate_resume\n') != 1:
        raise ValueError('Expected exactly one early resume call')
    init = init[:matches[0].start()]+init[matches[0].end():]
    # Check the boot policy before mounting eMMC or entering old stage two.
    guard = '''
# This rescue image must never activate physical swap or resume a disk image.
test "$(cat /sys/module/zswap/parameters/enabled)" = N || fail "rescue-zswap-enabled"
awk 'NR > 1 { bad=1 } END { exit bad }' /proc/swaps || fail "rescue-active-swap"
log "paging-policy=none recovery=ram-only"
'''
    init = init.replace('\nhibernate_resume\n', guard)
    if any(word in init for word in ['/sys/power/resume', 'hibernate_resume', 'swapon', 'mkswap']):
        raise ValueError('Unexpected remaining early paging or resume operation')
    return init


def patch_initramfs(compressed):
    decoder = zlib.decompressobj(31)
    raw = decoder.decompress(compressed, 32*1024*1024+1)
    if len(raw) > 32*1024*1024 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Invalid or unexpectedly large source initramfs')
    entries = parse_archive(raw)
    output, changed = [], []
    for name, header, data in entries:
        if name.removeprefix('./') == 'init':
            if int(header[14:22], 16) & 0o170000 != 0o100000 or int(header[38:46], 16) != 1:
                raise ValueError('Init must be a standalone regular file')
            new = remove_resume(data.decode())
            changed.append({'name':name, 'before_sha256':sha(data), 'after_sha256':sha(new.encode())})
            data = new.encode()
        output.append((name, header, data))
    if len(changed) != 1:
        raise ValueError('Expected exactly one init file')
    patched = gzip.compress(serialize_archive(output), compresslevel=9, mtime=0)
    actual = parse_archive(gzip.decompress(patched))
    if len(actual) != len(entries):
        raise ValueError('Archive entry count changed')
    for before, after in zip(entries, actual):
        if before[0] != after[0]:
            raise ValueError('Archive names or ordering changed')
        if before[0].removeprefix('./') != 'init' and before != after:
            raise ValueError('Unexpected non-init archive change')
    return patched, changed, len(entries)


def unpack_image(raw):
    if len(raw) != SIZE or raw[:8] != b'ANDROID!':
        raise ValueError('Source must be a full Android p22 image')
    values = struct.unpack_from('<10I', raw, 8)
    ksize, kaddr, rsize, raddr, second, saddr, tags, page, dt_size, version = values
    if (kaddr, raddr, second, saddr, tags, page, dt_size, version) != (
            0x40200000, 0x45000000, 0, 0x40f00000, 0x44000000, PAGE, 0, 0):
        raise ValueError('Unexpected Android load contract')
    rstart = align(PAGE+ksize, PAGE)
    if not ksize or not rsize or rstart+rsize > SIZE:
        raise ValueError('Invalid payload size')
    if raw[PAGE+ksize:rstart].strip(b'\0') or raw[rstart+rsize:].strip(b'\0'):
        raise ValueError('Unexpected payload or padding')
    kernel, ramdisk = raw[PAGE:PAGE+ksize], raw[rstart:rstart+rsize]
    if raw[576:596] != image_id(kernel, ramdisk):
        raise ValueError('Invalid Android image ID')
    cmd = raw[64:576]
    if b'\0' not in cmd or raw[608:1632].strip(b'\0'):
        raise ValueError('LK must receive a terminated first-field command line')
    return raw[:PAGE], kernel, ramdisk, cmd.split(b'\0', 1)[0].decode('ascii')


def image_id(kernel, ramdisk):
    digest = hashlib.sha1()
    for data in (kernel, ramdisk, b''):
        digest.update(data)
        digest.update(struct.pack('<I', len(data)))
    return digest.digest()


def repack_image(header, kernel, ramdisk, cmdline):
    cmd = cmdline.encode('ascii')
    if len(cmd) >= 512 or b'\0' in cmd:
        raise ValueError('Recovery policy exceeds LK command-line field')
    header = bytearray(header)
    struct.pack_into('<I', header, 16, len(ramdisk))
    header[64:576] = cmd.ljust(512, b'\0')
    header[576:596] = image_id(kernel, ramdisk)
    header[608:1632] = bytes(1024)
    raw = header+kernel
    raw.extend(bytes(align(len(raw), PAGE)-len(raw)))
    raw.extend(ramdisk)
    if len(raw) > SIZE:
        raise ValueError('Recovery payload exceeds p22')
    raw.extend(bytes(SIZE-len(raw)))
    return bytes(raw)


def build(bundle, out):
    bundle = bundle.resolve(strict=True)
    system = (bundle/'system').resolve(strict=True)
    kernel = (bundle/'kernel').resolve(strict=True)
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-nixos-system-gemini-[A-Za-z0-9.+_-]+', str(system)):
        raise ValueError('Unexpected system identity')
    if (system/'kernel').resolve().parent != kernel:
        raise ValueError('Bundle kernel differs from its system')
    rows = [line.split() for line in (system/'etc/fstab').read_text().splitlines()
            if line.strip() and not line.startswith('#')]
    swaps = [line for line in rows if len(line) > 2 and line[2] == 'swap']
    if len(swaps) != 1 or swaps[0][0] != '/dev/disk/by-partuuid/'+PARTUUID:
        raise ValueError('Source physical swap declaration is not the expected unique p34')
    sleep = (system/'etc/systemd/sleep.conf').read_text()
    if 'AllowHibernation=false\n' not in sleep or 'AllowSuspendThenHibernate=false\n' not in sleep:
        raise ValueError('Source sleep policy permits disk hibernation')
    config = (kernel/'kernel.config').read_text()
    if any(line not in config.splitlines() for line in (
            'CONFIG_CMDLINE_EXTEND=y', '# CONFIG_ZRAM is not set', 'CONFIG_ZSWAP=y')):
        raise ValueError('Expected the historical no-zram kernel with an extended command line')
    builtin = re.search(r'^CONFIG_CMDLINE="(.*)"$', config, re.M)
    if not builtin or any(word.startswith(('zswap.', 'resume=', 'systemd.mask=', 'systemd.gpt_auto='))
                          for word in builtin[1].split()):
        raise ValueError('Built-in kernel command line conflicts with the rescue policy')
    original = (bundle/'boot-padded-p22.img').read_bytes()
    header, payload, ramdisk, cmdline = unpack_image(original)
    expected = 'bootopt=64S3,32N2,64N2 init='+str(system)+'/init '+(system/'kernel-params').read_text().strip()
    if cmdline != expected or ramdisk != (system/'initrd').read_bytes():
        raise ValueError('Direct image does not contain the selected system and initramfs')
    decoder = zlib.decompressobj(31)
    expanded = decoder.decompress(payload)+decoder.flush()
    dtb = (system/'gemini.dtb').read_bytes()
    if (not decoder.eof or expanded != (kernel/'Image').read_bytes() or
            decoder.unused_data != dtb or (bundle/'gemini-usb11-host.dtb').read_bytes() != dtb):
        raise ValueError('Direct kernel or appended DTB differs from its system')
    ramdisk, changed, count = patch_initramfs(ramdisk)
    cmdline += ' '+' '.join(POLICY_ARGS)
    image = repack_image(header, payload, ramdisk, cmdline)
    _, checked_kernel, checked_ramdisk, checked_cmd = unpack_image(image)
    if (checked_kernel, checked_ramdisk, checked_cmd) != (payload, ramdisk, cmdline):
        raise ValueError('Repacked image did not round-trip')
    out.mkdir(exist_ok=False)
    (out/'kernel').symlink_to(kernel)
    (out/'system').symlink_to(system)
    (out/'gemini-usb11-host.dtb').symlink_to((system/'gemini.dtb').resolve())
    (out/'initramfs.cpio.gz').write_bytes(ramdisk)
    (out/'boot-padded-p22.img').write_bytes(image)
    (out/'MANIFEST').write_text(f'target=Gemini p22 direct Linux RAM-only migration rescue\n'
        f'store=persistent\nstore-root=/persist/nixos\nkernel={kernel.name}\nsystem={system}\n'
        'paging-policy=none\nrecovery-migration-only=true\n')
    result = dict(result='host-built-not-booted', hardware_tested=False, paging_policy='none',
        boot='direct', source_bundle=str(bundle), source_image_sha256=sha(original),
        system=str(system), kernel=str(kernel), kernel_payload_unchanged=True,
        kernel_config_sha256=sha((kernel/'kernel.config').read_bytes()),
        image_sha256=sha(image), initramfs_sha256=sha(ramdisk), archive_entries=count,
        changed_archive_entries=changed, command_line=cmdline,
        command_line_bytes=len(cmdline.encode()), mask_units=MASK_UNITS,
        systemd_generator_qualification_required=True, accepted_baseline_changed=False)
    (out/'build-result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.bundle, args.out)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
