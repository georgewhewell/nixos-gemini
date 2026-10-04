#!/usr/bin/env python3
"""Execute the production early-boot hook with isolated files and mocked mounts."""
import hashlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class Provisioning(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.run=self.base/'run';self.etc=self.base/'etc';self.target=self.base/'mnt/gemian';self.proc=self.base/'proc';self.sys=self.base/'sys/block'
        for p in (self.run,self.etc,self.target,self.proc,self.sys):p.mkdir(parents=True)
        self.files={'EFI/systemd/systemd-bootaa64.efi':b'manager','EFI/Gemini/abc/linux.efi':b'kernel',
                    'EFI/Gemini/abc/initrd.cpio.gz':b'initrd','loader/entries/gemini.conf':b'entry','loader/loader.conf':b'config'}
        self.archive=self.base/'archive.tar'
        with tarfile.open(self.archive,'w') as tf:
            for name,data in self.files.items():
                t=tarfile.TarInfo(name);t.size=len(data);tf.addfile(t,io.BytesIO(data))
        blob=self.archive.read_bytes();self.sha=hashlib.sha256(blob).hexdigest();self.size=len(blob)
        (self.etc/'gemini-efi-archive.meta').write_text(f'{self.sha} {self.size}\n')
        (self.etc/'gemini-efi-files.manifest').write_text(''.join(f'{hashlib.sha256(v).hexdigest()} {len(v)} {k}\n' for k,v in self.files.items()))
        (self.target/'nixos').mkdir();records=[]
        for name,data in (('accepted.squashfs',b'accepted'),('efi.squashfs',b'efi')):
            (self.target/'nixos'/name).write_bytes(data)
            records.append(f'{hashlib.sha256(data).hexdigest()} {len(data)} {name}\n')
        (self.etc/'gemini-efi-protected-stores.manifest').write_text(''.join(records))
        (self.run/'unattended-recovery.lease-deadline').write_text('format=gemini-unattended-recovery-lease-v1\nclock=monotonic-uptime-seconds\ndeadline=820\n')
        (self.proc/'uptime').write_text('100.00 80.00\n')
        (self.proc/'mounts').write_text(f'/dev/fakep29 {self.target} ext4 ro,norecovery 0 0\n')
        self.calls=self.base/'calls';self.calls.write_text('')
        self.hook=self.base/'hook.sh'
        source=(ROOT/'nix/gemini-efi-provision.sh').read_text().replace('/bin/gemini-efi-publish',str(ROOT/'nix/gemini-efi-publish.sh'))
        for a,b in (('/mnt/gemian',self.target),('/proc/mounts',self.proc/'mounts'),('/proc/uptime',self.proc/'uptime'),('/sys/block',self.sys),('/etc/',str(self.etc)+'/'),('/run/',str(self.run)+'/')):
            source=source.replace(a,str(b))
        self.hook.write_text(source)
        self.driver=self.base/'driver.sh'
        self.driver.write_text('''#!/bin/sh
log() { printf 'log:%s\n' "$*" >> "$CALLS"; }
fail() { printf 'fail:%s\n' "$*" >> "$CALLS"; exit 77; }
umount() { printf 'unmount\n' >> "$CALLS"; : > "$MOUNTS"; }
mount() {
 printf 'mount\n' >> "$CALLS"
 [ "$FAULT" != mount ] || return 1
 opts=rw
 [ "$FAULT" != journal ] || opts=rw,norecovery
 printf '/dev/fakep29 %s ext4 %s 0 0\n' "$TARGET" "$opts" > "$MOUNTS"
 [ "$FAULT" != changed_store ] || printf bad > "$TARGET/nixos/accepted.squashfs"
}
restore_store_readonly() {
 printf 'restore\n' >> "$CALLS"
 printf '/dev/fakep29 %s ext4 ro,norecovery 0 0\n' "$TARGET" > "$MOUNTS"
 [ "$FAULT" != restore ]
}
provision_abort() { restore_store_readonly; fail "$*"; }
df() { printf 'Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/fakep29 100000 0 100000 0%% %s\n' "$TARGET"; }
sleep() {
 [ "$FAULT" != timeout ] || return 0
 cp "$ARCHIVE" "$RUN/efi-boot-files.upload"
 printf 'efi-files=ready sha256=%s size=%s\n' "$SHA" "$SIZE" > "$RUN/efi-boot-files.ready"
}
watchdog_pid=$$
p29=/dev/fakep29
. "$HOOK"
''')
    def execute(self,fault=''):
        env=dict(os.environ,CALLS=str(self.calls),MOUNTS=str(self.proc/'mounts'),TARGET=str(self.target),FAULT=fault,
                 ARCHIVE=str(self.archive),RUN=str(self.run),SHA=self.sha,SIZE=str(self.size),HOOK=str(self.hook))
        return subprocess.run(['sh',str(self.driver)],env=env,capture_output=True,text=True,timeout=15)
    def test_success_restores_readonly_before_verified_and_retry_skips_writes(self):
        r=self.execute();self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('ro,norecovery',(self.proc/'mounts').read_text())
        self.assertEqual((self.run/'efi-boot-files.verified').read_text(),f'efi-files=verified sha256={self.sha} size={self.size}\n')
        for name,data in self.files.items():self.assertEqual((self.target/name).read_bytes(),data)
        self.assertLess(self.calls.read_text().index('restore'),self.calls.read_text().index('log:efi-files=verified'))
        self.calls.write_text('');self.assertEqual(self.execute().returncode,0);self.assertEqual(self.calls.read_text(),'')
    def test_bad_archive_is_rejected_before_writable_mount(self):
        blob=self.archive.read_bytes();self.archive.write_bytes(b'x'+blob[1:])
        self.assertEqual(self.execute().returncode,77);self.assertNotIn('mount\n',self.calls.read_text())
        self.assertFalse((self.target/'EFI').exists())
    def test_busy_loop_and_damaged_protected_store_prevent_upload(self):
        p=self.sys/'loop0/loop/backing_file';p.parent.mkdir(parents=True);p.write_text('/store\n')
        self.assertEqual(self.execute().returncode,77);self.assertFalse((self.run/'efi-boot-files.required').exists())
        p.unlink();(self.target/'nixos/accepted.squashfs').write_bytes(b'bad')
        self.assertEqual(self.execute().returncode,77);self.assertFalse((self.run/'efi-boot-files.required').exists())
    def test_short_lease_and_timeout_never_mount_writable(self):
        p=self.run/'unattended-recovery.lease-deadline';p.write_text(p.read_text().replace('deadline=820','deadline=110'))
        self.assertEqual(self.execute().returncode,77);self.assertNotIn('mount\n',self.calls.read_text())
        (self.run/'efi-boot-files.upload').unlink();(self.run/'efi-boot-files.ready').unlink()
        self.assertEqual(self.execute('timeout').returncode,77);self.assertNotIn('mount\n',self.calls.read_text())
    def test_mount_failure_restores_readonly(self):
        self.assertEqual(self.execute('mount').returncode,77);self.assertIn('restore',self.calls.read_text())
        self.assertFalse((self.run/'efi-boot-files.verified').exists())
    def test_journal_disabled_is_rejected_and_restored(self):
        self.assertEqual(self.execute('journal').returncode,77);self.assertIn('restore',self.calls.read_text())
        self.assertFalse((self.target/'EFI').exists());self.assertFalse((self.run/'efi-boot-files.verified').exists())
    def test_store_change_or_failed_restore_cannot_claim_success(self):
        self.assertEqual(self.execute('changed_store').returncode,77)
        self.assertIn('restore',self.calls.read_text());self.assertFalse((self.run/'efi-boot-files.verified').exists())
    def test_failed_readonly_restore_cannot_claim_success(self):
        self.assertEqual(self.execute('restore').returncode,77);self.assertFalse((self.run/'efi-boot-files.verified').exists())
    def test_owner_config_is_preserved(self):
        (self.target/'loader').mkdir();(self.target/'loader/loader.conf').write_bytes(b'owner')
        self.assertEqual(self.execute().returncode,77);self.assertIn('restore',self.calls.read_text())
        self.assertEqual((self.target/'loader/loader.conf').read_bytes(),b'owner');self.assertFalse((self.target/'EFI').exists())
if __name__=='__main__':unittest.main()
