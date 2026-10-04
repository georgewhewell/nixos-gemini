#!/usr/bin/env python3
"""Require the distro manager's own EFI evidence, beyond the launch marker."""
import re
import subprocess

SHA='ed24e7e8b385f25f9df8812c899ecf581a6aa87368827b6a4a41fe4cb6f513cd'
PREFIX='chosen/gemini,uefi-manager-'
MARKERS=tuple(PREFIX+key for key in ('result','stage','status','sha256'))
VARIABLES=('LoaderInfo','LoaderEntrySelected','LoaderImageIdentifier','LoaderDevicePartUUID',
           'LoaderTimeMenuUSec','LoaderTimeExecUSec')
GUID='4a67b082-0a4c-41cf-b6c7-440b29bb8c4f'
# Matching EFI userspace closure: the default modprobe is BusyBox and /lib/modules is absent.
KMOD='/nix/store/cpdb15nd870rimjyqwbf3f9iarhh2k4f-kmod-aarch64-unknown-linux-gnu-30/bin/modprobe'
KERNEL='/nix/store/6463y1syk23clrh7qgl6mdmk1507m320-gemini-mainline-efi-kernel-7.1.3'


def verify_tree(tree):
    expected={'result':b'starting\0'.hex(),'stage':b'start-image\0'.hex(),'sha256':SHA}
    if any(tree.get(PREFIX+key)!=value for key,value in expected.items()) or PREFIX+'status' in tree:
        raise RuntimeError('Distro manager was not started or returned to the FIT fallback: '+
                           repr({key:tree.get(key) for key in MARKERS}))


def decode_variable(raw):
    try:
        data=bytes.fromhex(raw)
        if not 6<=len(data)<=4096 or len(data)%2 or int.from_bytes(data[:4],'little')!=6:
            raise ValueError('invalid length or variable attributes')
        value=data[4:].decode('utf-16-le')
        if not value.endswith('\0') or '\0' in value[:-1] or any(ord(c)<32 for c in value[:-1]):
            raise ValueError('invalid EFI string')
        return value[:-1]
    except (ValueError,UnicodeError) as error:
        raise RuntimeError('Invalid loader EFI variable: '+str(error)) from error


def verify_variables(rows,boot_id,entry='gemini-efi-trial.conf'):
    if rows.get('boot_id')!=boot_id or set(rows)!={'boot_id',*VARIABLES}:
        raise RuntimeError('Loader EFI variables are missing or from another boot')
    values={name:decode_variable(rows[name]) for name in VARIABLES}
    if not re.fullmatch(r'systemd-boot 261\.2(?:[ +().-][ -~]*)?',values['LoaderInfo']):
        raise RuntimeError('Unexpected distro manager: '+values['LoaderInfo'])
    if values['LoaderEntrySelected']!=entry:
        raise RuntimeError('The manager selected a different boot entry')
    # U-Boot's DevicePathToText prefixes every node with '/', including FilePath.
    image=values['LoaderImageIdentifier'].replace('\\','/').lower()
    if image not in ('/efi/systemd/systemd-bootaa64.efi','//efi/systemd/systemd-bootaa64.efi'):
        raise RuntimeError('The manager loaded from a different path')
    values['LoaderDevicePartUUID']=values['LoaderDevicePartUUID'].lower()
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',values['LoaderDevicePartUUID']):
        raise RuntimeError('The manager did not report a GPT boot volume')
    for name in ('LoaderTimeMenuUSec','LoaderTimeExecUSec'):
        if not re.fullmatch('[0-9]{1,18}',values[name]):
            raise RuntimeError('Malformed loader menu timing')
    elapsed=int(values['LoaderTimeExecUSec'])-int(values['LoaderTimeMenuUSec'])
    if not 7_000_000<=elapsed<=60_000_000:
        raise RuntimeError('The unattended eight-second menu was not observed in loader timing')
    return dict(values,menu_to_exec_usec=elapsed)


def evidence(ssh,boot_id,directory,qualify,tree,entry='gemini-efi-trial.conf',kernel=KERNEL):
    verify_tree(tree)
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-[A-Za-z0-9._+-]+',str(kernel)):
        raise ValueError('Loader evidence requires a pinned kernel path')
    command=f'''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
if ! awk '$2 == "/sys/firmware/efi/efivars" && $3 == "efivarfs" {{ found=1 }} END {{ exit !found }}' /proc/mounts; then
    printf 'loader-evidence: loading efivarfs\\n' >&2
    {KMOD} -d {kernel} efivarfs
    mkdir -p /sys/firmware/efi/efivars
    printf 'loader-evidence: mounting efivarfs read-only\\n' >&2
    mount -t efivarfs -o ro,nosuid,nodev,noexec efivarfs /sys/firmware/efi/efivars
fi
for name in {' '.join(VARIABLES)}; do
    file=/sys/firmware/efi/efivars/$name-{GUID}
    if ! test -f "$file"; then
        printf 'loader-evidence: missing %s\\n' "$name" >&2
        exit 1
    fi
    test "$(stat -c %s "$file")" -le 4096
    printf '%s=' "$name"
    od -An -v -tx1 "$file" | tr -d ' \\n'
    printf '\\n'
done
'''
    try:
        raw=qualify.run(ssh+[command])
    except subprocess.CalledProcessError as error:
        # Preserve partial reads and the failing stage before automatic rescue.
        (directory/'manager-variables.txt').write_text(error.stdout or '')
        (directory/'manager-variables-error.txt').write_text(error.stderr or '')
        raise RuntimeError('Cannot read loader EFI variables: '+
                           (error.stderr or f'exit {error.returncode}').strip()) from error
    (directory/'manager-variables.txt').write_text(raw)
    values=verify_variables(dict(row.split('=',1) for row in raw.splitlines()),boot_id,entry)
    uuid=values['LoaderDevicePartUUID']
    path=qualify.run(ssh+[f'readlink -f /dev/disk/by-partuuid/{uuid}']).strip()
    if path!='/dev/mmcblk0p29':
        raise RuntimeError('The manager boot volume does not resolve to p29: '+path)
    qualify.save(directory,'manager-evidence.json',dict(boot_id=boot_id,sha256=SHA,
                 boot_volume=path,efi_variables=values,physical_key_press_observed=False))
