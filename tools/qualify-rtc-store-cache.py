#!/usr/bin/env python3
"""Reclaim only the previous opt-in RTC userspace cache after host archival.

The existing supervised provisioner owns all target writes. Never remount an
active read-only/noload filesystem: pruning is inserted into its already
validated Stage 1 rw/journalled upload transaction, before the capacity guard.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

SHA = '4bfae12544e2d4d885a1a11552ebc27ab0e24d945498d4a44317f497a3316ae5'
SIZE = 427040768
NAME = 'mainline-nixos-'+SHA+'.squashfs'
SOURCE = Path('/nix/store/7bh3lx2npyddffbyn41bcgrzaambv0qi-gemini-mainline-nixos-bundle')/NAME


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def unused(root):
    # Preflight has independently verified the retained EFI tree. Check every
    # installed Gemini initrd and loader entry as well as active loop devices.
    return f'''
for backing in /sys/class/block/loop*/loop/backing_file; do
 test -f "$backing" || continue
 if grep -qF '{NAME}' "$backing"; then exit 1; fi
done
for initrd in {root}/EFI/Gemini/*/initrd.cpio.gz; do
 test -f "$initrd" && test ! -L "$initrd"
 gzip -t "$initrd"
 if gzip -dc "$initrd" | grep -aqF '{SHA}'; then exit 1; fi
done
for entry in {root}/loader/entries/*.conf; do
 test -f "$entry" && test ! -L "$entry"
 if grep -qF '{SHA}' "$entry"; then exit 1; fi
done
'''


def prepare(context, runner, directory, before):
    target = '/gemian/nixos/mainline-nixos-'+context.STORE_SHA+'.squashfs'
    raw = runner.persistence.run(context.f.q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {before['boot_id']}
opts=$(awk '$1 == "/dev/mmcblk0p29" && $2 == "/gemian" && $3 == "ext4" {{print $4}}' /proc/mounts)
case ",$opts," in *,ro,*) ;; *) exit 1;; esac
test ! -L /gemian/nixos
test ! -L {target}
printf 'available_kib='; df -Pk /gemian/nixos | awk '$1 == "/dev/mmcblk0p29" && $6 == "/gemian" {{print $4}}'
if test -e {target}; then
 test -f {target}
 test "$(stat -c %s {target})" = {context.STORE_SIZE}
 test "$(sha256sum {target} | cut -d' ' -f1)" = {context.STORE_SHA}
 echo installed=yes
else echo installed=no; fi
''', directory, 'store-capacity')
    rows = raw.splitlines()
    values = dict(row.split('=',1) for row in rows)
    if len(rows) != 2 or set(values) != {'available_kib','installed'} or values['installed'] not in ('yes','no'):
        raise RuntimeError('Incomplete store capacity evidence')
    required = (context.STORE_SIZE+1023)//1024+1024
    available = int(values['available_kib'])
    prune = values['installed'] == 'no' and available < required
    proof = dict(available_kib=available, required_kib=required,
                 candidate_already_installed=values['installed']=='yes', prune_previous_rtc_cache=prune)
    if prune:
        if context.STORE_SHA == SHA or SHA == runner.efi_linux.ACCEPTED_STORE_SHA:
            raise RuntimeError('Cannot prune the candidate or accepted store')
        if available + SIZE//1024 < required:
            raise RuntimeError('Archiving the prior RTC cache cannot provide enough capacity')
        old = '/gemian/nixos/'+NAME
        runner.persistence.run(context.f.q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {before['boot_id']}
test -f {old} && test ! -L {old}
test "$(stat -c %s {old})" = {SIZE}
test "$(stat -c %h {old})" = 1
test "$(sha256sum {old} | cut -d' ' -f1)" = {SHA}
{unused('/gemian')}
''', directory, 'previous-rtc-cache')
        archive = directory/NAME
        with SOURCE.open('rb') as src, archive.open('xb') as dst:
            shutil.copyfileobj(src, dst, 1024*1024)
            dst.flush(); os.fsync(dst.fileno())
        archive.chmod(0o400)
        if archive.stat().st_size != SIZE or digest(archive) != SHA:
            raise RuntimeError('Host RTC cache archive did not verify')
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        proof.update(archived_sha256=SHA, archived_size=SIZE, archive=str(archive),
                     source=str(SOURCE), installed_efi_and_active_loops_unreferenced=True)
    runner.qualify.save(directory, 'store-capacity.json', proof)


def install(context, runner, directory):
    original = runner.efi_linux.upload_command
    def upload(name, before, boot_sha, profile=None):
        command = original(name, before, boot_sha, profile)
        proof = json.loads((directory/'store-capacity.json').read_text())
        if not proof['prune_previous_rtc_cache']: return command
        archive = directory/NAME
        if (proof.get('archive') != str(archive) or archive.stat().st_size != SIZE or digest(archive) != SHA or
                profile is None or profile.sha != context.STORE_SHA or boot_sha != context.BOOT_SHA):
            raise RuntimeError('RTC cache archive or upload profile changed')
        target = '/mnt/gemian/nixos/'+NAME
        anchor = 'available=$(df -Pk /mnt/gemian/nixos '
        if command.count(anchor) != 1: raise RuntimeError('Store capacity guard moved')
        prune = f'''# Previous opt-in RTC image was verified and archived on the host.
test -f {target} && test ! -L {target}
test "$(stat -c %s {target})" = {SIZE}
test "$(stat -c %h {target})" = 1
test "$(sha256sum {target} | cut -d' ' -f1)" = {SHA}
{unused('/mnt/gemian')}
rm -- {target}
sync
printf 'rtc-cache-pruned={SHA}\\n'
'''
        return command.replace(anchor, prune+anchor)
    runner.efi_linux.upload_command = upload


def verify_final(runner, directory):
    proof = json.loads((directory/'store-capacity.json').read_text())
    if not proof['prune_previous_rtc_cache']:
        return dict(previous_rtc_cache_pruned=False)
    archive = directory/NAME
    lines = (directory/'store-upload.log').read_text().splitlines()
    if (archive.stat().st_size != SIZE or digest(archive) != SHA or
            lines.count('rtc-cache-pruned='+SHA) != 1):
        raise RuntimeError('Previous RTC cache archival/prune evidence differs')
    return dict(previous_rtc_cache_pruned=True, previous_rtc_cache_host_archive_verified=True,
                previous_rtc_cache_archive=str(archive), previous_rtc_cache_sha256=SHA)
