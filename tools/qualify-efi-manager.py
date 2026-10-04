#!/usr/bin/env python3
"""Require the distro manager's own EFI evidence, beyond the launch marker."""
import re

SHA='ed24e7e8b385f25f9df8812c899ecf581a6aa87368827b6a4a41fe4cb6f513cd'
PREFIX='chosen/gemini,uefi-manager-'
MARKERS=tuple(PREFIX+key for key in ('result','stage','status','sha256'))
VARIABLES=('LoaderInfo','LoaderEntrySelected','LoaderImageIdentifier','LoaderDevicePartUUID',
           'LoaderTimeMenuUSec','LoaderTimeExecUSec')
GUID='4a67b082-0a4c-41cf-b6c7-440b29bb8c4f'


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


def verify_variables(rows,boot_id):
    if rows.get('boot_id')!=boot_id or set(rows)!={'boot_id',*VARIABLES}:
        raise RuntimeError('Loader EFI variables are missing or from another boot')
    values={name:decode_variable(rows[name]) for name in VARIABLES}
    if not re.fullmatch(r'systemd-boot 261\.2(?:[ +().-][ -~]*)?',values['LoaderInfo']):
        raise RuntimeError('Unexpected distro manager: '+values['LoaderInfo'])
    if values['LoaderEntrySelected']!='gemini-efi-trial.conf':
        raise RuntimeError('The manager selected a different boot entry')
    if values['LoaderImageIdentifier'].replace('\\','/').lower()!='/efi/systemd/systemd-bootaa64.efi':
        raise RuntimeError('The manager loaded from a different path')
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',values['LoaderDevicePartUUID']):
        raise RuntimeError('The manager did not report a GPT boot volume')
    for name in ('LoaderTimeMenuUSec','LoaderTimeExecUSec'):
        if not re.fullmatch('[0-9]{1,18}',values[name]):
            raise RuntimeError('Malformed loader menu timing')
    elapsed=int(values['LoaderTimeExecUSec'])-int(values['LoaderTimeMenuUSec'])
    if not 7_000_000<=elapsed<=60_000_000:
        raise RuntimeError('The unattended eight-second menu was not observed in loader timing')
    return dict(values,menu_to_exec_usec=elapsed)


def evidence(ssh,boot_id,directory,qualify,tree):
    verify_tree(tree)
    command=f'''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
if ! awk '$2 == "/sys/firmware/efi/efivars" && $3 == "efivarfs" {{ found=1 }} END {{ exit !found }}' /proc/mounts; then
    modprobe efivarfs
    mkdir -p /sys/firmware/efi/efivars
    mount -t efivarfs -o ro,nosuid,nodev,noexec efivarfs /sys/firmware/efi/efivars
fi
for name in {' '.join(VARIABLES)}; do
    file=/sys/firmware/efi/efivars/$name-{GUID}
    test -f "$file" && test "$(stat -c %s "$file")" -le 4096
    printf '%s=' "$name"
    od -An -v -tx1 "$file" | tr -d ' \\n'
    printf '\\n'
done
'''
    raw=qualify.run(ssh+[command])
    (directory/'manager-variables.txt').write_text(raw)
    values=verify_variables(dict(row.split('=',1) for row in raw.splitlines()),boot_id)
    uuid=values['LoaderDevicePartUUID']
    path=qualify.run(ssh+[f'readlink -f /dev/disk/by-partuuid/{uuid}']).strip()
    if path!='/dev/mmcblk0p29':
        raise RuntimeError('The manager boot volume does not resolve to p29: '+path)
    qualify.save(directory,'manager-evidence.json',dict(boot_id=boot_id,sha256=SHA,
                 boot_volume=path,efi_variables=values,physical_key_press_observed=False))
