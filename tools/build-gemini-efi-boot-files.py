#!/usr/bin/env python3
"""Build immutable systemd-boot trial files and their checked publication archive."""
import gzip, hashlib, io, json, struct, sys, tarfile
from pathlib import Path
out, bootloader, linux, kernel = map(Path, sys.argv[1:5])
assert sys.argv[5:] in ([], ['--versioned-entry'])
versioned = bool(sys.argv[5:])
image = gzip.decompress((linux/'kernel/Image.gz').read_bytes())
initrd = (linux/'initramfs.cpio.gz').read_bytes()
manager = (bootloader/'lib/systemd/boot/efi/systemd-bootaa64.efi').read_bytes()
for name, data in [('Linux', image), ('systemd-boot', manager)]:
    assert data[:2] == b'MZ', name
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe+4] == b'PE\0\0', name
    assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64, name
    assert struct.unpack_from('<H', data, pe+24)[0] == 0x20b, name
    assert struct.unpack_from('<H', data, pe+24+68)[0] == 10, name
# This first manager trial retains the hardware-qualified kernel command
# line and CPU provenance. General NixOS generation updates remain separate.
config = (kernel/'kernel.config').read_text()
assert 'CONFIG_CMDLINE_FORCE=y\n' in config
payload = hashlib.sha256(image + initrd).hexdigest()
directory = 'EFI/Gemini/' + payload
entry = 'gemini-' + payload + '.conf' if versioned else 'gemini-efi-trial.conf'
title = 'NixOS Gemini' if versioned else 'NixOS Gemini (EFI trial)'
files = {
    'EFI/systemd/systemd-bootaa64.efi': manager,
    directory + '/linux.efi': image,
    directory + '/initrd.cpio.gz': initrd,
    'loader/loader.conf': ("default " + entry + "\ntimeout 8\nconsole-mode keep\n"
                           "editor no\nauto-entries no\nauto-firmware no\nrandom-seed-mode off\n").encode(),
    'loader/entries/' + entry: ("title " + title + "\n"
        "sort-key gemini\nversion 7.1.3\nlinux /" + directory + "/linux.efi\n"
        "initrd /" + directory + "/initrd.cpio.gz\n").encode(),
}
tree = out/'tree'
for name, data in files.items():
    path = tree/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
manifest = {'status': 'host-prepared-not-published-or-booted',
            'bootloader': str(bootloader), 'linux_payload': str(linux),
            'kernel': str(kernel), 'payload_identity': payload,
            'entry': entry, 'menu_timeout_seconds': 8,
            'requires': ['LK-derived FDT in EFI configuration table',
                         'native EFI Block I/O and Simple File System',
                         'image device handle bound to the containing filesystem'],
            'files': {name: {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
                      for name, data in files.items()}}
# Publish payloads first and menu configuration last.
order = [name for name in files if not name.startswith('loader/')] + [
    'loader/entries/' + entry, 'loader/loader.conf']
(out/'files.manifest').write_text(''.join(
    f"{hashlib.sha256(files[name]).hexdigest()} {len(files[name])} {name}\n" for name in order))
with tarfile.open(out/'boot-files.tar', 'w', format=tarfile.USTAR_FORMAT) as archive:
    for name in order:
        entry=tarfile.TarInfo(name)
        entry.size=len(files[name]); entry.mode=0o644; entry.mtime=1788493603
        archive.addfile(entry, io.BytesIO(files[name]))
archive=(out/'boot-files.tar').read_bytes()
manifest['archive']={'size':len(archive), 'sha256':hashlib.sha256(archive).hexdigest()}
(out/'archive.meta').write_text(f"{manifest['archive']['sha256']} {len(archive)}\n")
(out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print('PASS: AArch64 systemd-boot and Linux PE images; content-addressed payload and bounded menu entry prepared')
