#!/usr/bin/env python3
"""Recognize the pinned RTC candidate before stage 2 and request owned rescue.

The original supervisor/writer keeps ownership. This only extends Linux-side
identification/reboot; it starts no writer and never reboots another image.
"""
import json
from pathlib import Path
import re
import subprocess


def guard(context, before, boot=None):
    if not re.fullmatch('[0-9a-f-]{36}', before['boot_id']):
        raise ValueError('Unpinned old boot')
    if boot is not None and not re.fullmatch('[0-9a-f-]{36}', boot):
        raise ValueError('Unpinned Stage 1 boot')
    persistent = getattr(context, 'STORE_ROOT', None) == '/persist/nixos'
    hashes = (context.NOTES_SHA, context.BOOT_SHA, before['gpt_sha256'])
    if (any(not re.fullmatch('[0-9a-f]{64}', value) for value in hashes) or
            (not persistent and (not re.fullmatch('[0-9a-f]{64}', context.STORE_SHA) or
                                 not isinstance(context.STORE_SIZE, int) or context.STORE_SIZE <= 0))):
        raise ValueError('Unpinned Stage 1 image')
    name = 'mainline-nixos-'+str(context.STORE_SHA)+'.squashfs'
    required = (f'store-provision=required target=/mnt/gemian/nixos/{name} '
                f'temp=/mnt/gemian/nixos/{name}.provision.tmp '
                f'sha256={context.STORE_SHA} size={context.STORE_SIZE}')
    store_check = (f"tr ' ' '\\n' < /proc/cmdline | grep -Fx 'init={context.SYSTEM}/init' >/dev/null" if persistent else
                   f"test \"$(cat /run/store-provision.required)\" = '{required}'")
    return f'''set -eu
boot=$(cat /proc/sys/kernel/random/boot_id)
test "$boot" != {before['boot_id']}
'''+(f'test "$boot" = {boot}\n' if boot else '')+f'''
test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = {context.NOTES_SHA}
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = {context.BOOT_SHA}
test "$(head -c 32768 /dev/mmcblk0 | sha256sum | cut -d' ' -f1)" = {before['gpt_sha256']}
test ! -e /run/current-system
test ! -e /run/store-provision.ready
{store_check}
test -x /bin/busybox
printf 'boot_id=%s\\n' "$boot"
'''


def request(runner, ssh, directory, script, boot):
    (directory/'stage1-rescue-request.sh').write_text(script)
    timed_out = False; rc = None
    with (directory/'stage1-rescue-request.stdout').open('w') as stdout, \
            (directory/'stage1-rescue-request.stderr').open('w') as stderr:
        try:
            result = subprocess.run(ssh+[script], stdout=stdout, stderr=stderr, timeout=25)
            rc = result.returncode
        except subprocess.TimeoutExpired:
            # A reboot can leave the old SSH TCP session waiting. Preserve its
            # output before waiting for the independent supervisor's proof.
            timed_out = True
    raw = (directory/'stage1-rescue-request.stdout').read_text().splitlines()
    verified = (len(raw) == 2 and raw[0] == 'boot_id='+boot and
                raw[1] == 'stage1-rescue-request=verified p29=ro' and rc in (None, 0, 255))
    proof = dict(stage1_rescue_request_verified=verified, ssh_timed_out=timed_out,
                 returncode=rc, reset_proven=False, existing_supervisor_retained=True)
    runner.qualify.save(directory, 'stage1-rescue-request.json', proof)
    if not verified: raise RuntimeError('Stage 1 rescue request did not pass all identity/mount guards')
    return proof


def install(context, runner, directory):
    original_needs = runner.candidate_needs_rescue_reboot
    original_reboot = runner.reboot
    identified = None
    def needs(ssh, before, profile):
        nonlocal identified
        identified = None
        if original_needs(ssh, before, profile): return True
        if profile != context.PROFILE: return False
        try:
            raw = runner.persistence.run(ssh, guard(context, before), directory, 'stage1-rescue-identity').strip()
            if not re.fullmatch('boot_id=[0-9a-f-]{36}', raw): return False
            identified = (before, raw.removeprefix('boot_id='))
            return True
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return False
    def reboot(ssh, out, filename):
        if identified is None or filename != 'rescue-reboot-request.json':
            return original_reboot(ssh, out, filename)
        if Path(out) != directory: raise RuntimeError('Stage 1 rescue directory changed')
        units = json.loads((directory/'units.json').read_text())
        for key in ('owner','supervisor','network'):
            raw = runner.qualify.run(['systemctl','--user','show',units[key],'-p','ActiveState','-p','MainPID'])
            values = dict(row.split('=',1) for row in raw.splitlines())
            if values.get('ActiveState') != 'active' or not values.get('MainPID','').isdigit() or int(values['MainPID']) < 2:
                raise RuntimeError('Original Stage 1 rescue owner is not active')
        if (not (directory/'supervisor.state').read_text().startswith('supervisor_rollback_armed ') or
                not (directory/'supervisor-rollback.state').read_text().startswith('tool_started ')):
            raise RuntimeError('Original rescue writer is not waiting')
        before, boot = identified
        script = guard(context, before, boot)+'''
sync
mount -o remount,ro /mnt/gemian
opts=$(awk '$1 == "/dev/mmcblk0p29" && $2 == "/mnt/gemian" && $3 == "ext4" {print $4}' /proc/mounts)
case ",$opts," in *,ro,*) ;; *) exit 1;; esac
printf 'stage1-rescue-request=verified p29=ro\n'
/bin/busybox reboot -f
'''
        request(runner, ssh, directory, script, boot)
    runner.candidate_needs_rescue_reboot = needs
    runner.reboot = reboot
