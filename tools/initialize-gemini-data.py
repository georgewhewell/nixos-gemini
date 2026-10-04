#!/usr/bin/env python3
"""Initialize the empty, existing Gemini data filesystem without changing GPT.

Default is read-only admission and a private backup of the current temporary
home. --execute publishes the Stage 1 layout, preserving that home. No format,
resize, swap setup or reboot is performed here. Qualify persistence on reboot
with the supervised baseline runner afterward.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('recovery',ROOT/'tools/qualify-uboot-recovery.py')
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
q=recovery.qualify
SSH=['ssh','-F','/dev/null','-i','/home/grw/.ssh/gemini-stage1-ed25519',
     '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=5',
     '-o','ControlPath=none','-o','StrictHostKeyChecking=yes',
     '-o','HostKeyAlias=192.168.23.70','root@10.15.19.82']
FS_UUID='5d978ad4-a987-4b3f-bef6-f73ad7c2d986'
MOUNT='/run/gemini-data-initialize'


def verify_filesystem(raw):
    fields=dict((k.strip(),v.strip()) for line in raw.splitlines() if ':' in line
                for k,v in [line.split(':',1)])
    expected={'Filesystem volume name':'gemini-data','Filesystem UUID':FS_UUID,
              'Filesystem state':'clean','Block count':'2781184','Block size':'4096'}
    if any(fields.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Existing data filesystem differs from the inspected empty filesystem')
    return expected


def guards(before):
    return f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(before['boot_id'])}
test "$(readlink /run/current-system)" = {shlex.quote(q.ACCEPTED_SYSTEM)}
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = {q.ACCEPTED_BOOT}
test "$(head -c 32768 /dev/mmcblk0 | sha256sum | cut -d' ' -f1)" = {recovery.MMC_GPT_SHA}
test "$(cat /sys/class/block/mmcblk0p32/start)" = 89372672
test "$(cat /sys/class/block/mmcblk0p32/size)" = 32737247
test ! -e /sys/class/block/mmcblk0p34
grep -qx 'PARTNAME=userdata' /sys/class/block/mmcblk0p32/uevent
case "$(readlink -f /sys/class/block/mmcblk0/device)" in */11230000.mmc/*) ;; *) exit 1 ;; esac
test "$(dumpe2fs -h /dev/mmcblk0p32 2>/dev/null | sed -n 's/^Filesystem UUID: *//p')" = {FS_UUID}
awk '$1 == "/dev/mmcblk0p32" {{ found=1 }} END {{ exit found }}' /proc/mounts /proc/swaps
test ! -e {MOUNT} && test ! -L {MOUNT}
mkdir -m 0700 {MOUNT}
trap 'umount {MOUNT} 2>/dev/null || true; rmdir {MOUNT} 2>/dev/null || true' EXIT
trap 'exit 1' HUP INT TERM
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();os.umask(0o077)
    directory=args.out.resolve();directory.mkdir(mode=0o700)
    helper=(ROOT/'tools/gemini-data-layout.sh').read_text()
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock','.p22-flash-writer.lock'):
            fd=locks.enter_context((recovery.LOCKS/name).open('a'))
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        q.check_host_idle()
        before=recovery.snapshot(SSH)
        q.save(directory,'before.json',before)
        raw=q.run(SSH+['dumpe2fs -h /dev/mmcblk0p32'])
        (directory/'filesystem-before.txt').write_text(raw)
        q.save(directory,'filesystem.json',verify_filesystem(raw))
        inspect=guards(before)+f'''
mount -t ext4 -o ro,noload,nosuid,nodev,noexec /dev/mmcblk0p32 {MOUNT}
for path in {MOUNT}/* {MOUNT}/.[!.]* {MOUNT}/..?*; do
    test -e "$path" || test -L "$path" || continue
    test "${{path##*/}}" = lost+found && test -d "$path" && test ! -L "$path" || exit 1
done
printf 'filesystem=empty mount=read-only\\n'
'''
        (directory/'admission.txt').write_text(q.run(SSH+[inspect]))
        with (directory/'home-before.tar').open('wb') as backup:
            subprocess.run(SSH+['tar -C /home -cf - .'],stdout=backup,check=True,timeout=30)
        backup=directory/'home-before.tar'
        q.save(directory,'plan.json',dict(execute=args.execute,filesystem_uuid=FS_UUID,
            helper_sha256=hashlib.sha256(helper.encode()).hexdigest(),
            home_backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
            partition_table_changes=False,format=False,resize=False))
        if not args.execute:
            print(f'PASS: empty existing filesystem admitted; no layout change. Evidence: {directory}')
            return
        if recovery.snapshot(SSH)!=before:
            raise RuntimeError('Device identity changed before layout publication')
        command=guards(before)+f'''
mount -t ext4 -o rw,nosuid,nodev,noatime /dev/mmcblk0p32 {MOUNT}
sh -s -- {MOUNT} /home <<'GEMINI_DATA_LAYOUT'
{helper}
GEMINI_DATA_LAYOUT
test "$(stat -c %u:%g:%a {MOUNT}/nix/upper)" = 0:30000:1775
umount {MOUNT}
'''
        (directory/'initialize.sh').write_text(command)
        (directory/'initialize.log').write_text(q.run(SSH+[command]))
        after=recovery.snapshot(SSH)
        q.save(directory,'after.json',after)
        if after!=before:
            raise RuntimeError('Boot or protected partition identity changed during initialization')
        (directory/'filesystem-after.txt').write_text(q.run(SSH+['dumpe2fs -h /dev/mmcblk0p32']))
        q.save(directory,'result.json',dict(status='initialized-not-rebooted',boot_id=after['boot_id']))
        print(f'PASS: home preserved and data layout initialized; reboot qualification required. Evidence: {directory}')


if __name__=='__main__':main()
