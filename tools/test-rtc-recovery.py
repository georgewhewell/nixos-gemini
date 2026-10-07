#!/usr/bin/env python3
"""Test cache archival/admission and pinned pre-userspace rescue handling."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name('qualify-'+name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c=module('rtc-store-cache');s=module('rtc-stage1-rescue');e=module('efi-linux')
OLD='11111111-1111-1111-1111-111111111111';BOOT='22222222-2222-2222-2222-222222222222'
BEFORE=dict(boot_id=OLD,gpt_sha256='c'*64)
CTX=SimpleNamespace(STORE_SHA='a'*64,STORE_SIZE=2048,NOTES_SHA='d'*64,BOOT_SHA='b'*64,PROFILE='calendar',f=SimpleNamespace(q=SimpleNamespace(SSH=['ssh'])))


def save(directory,name,value): (directory/name).write_text(json.dumps(value))


class Cache(unittest.TestCase):
    def runner(self, raw):
        return SimpleNamespace(persistence=SimpleNamespace(run=mock.Mock(side_effect=[raw,''])),
            qualify=SimpleNamespace(save=save),efi_linux=SimpleNamespace(ACCEPTED_STORE_SHA=e.ACCEPTED_STORE_SHA,upload_command=e.upload_command))

    def test_enough_space_or_installed_image_does_not_prune(self):
        for values in ('available_kib=9000\ninstalled=no\n','available_kib=0\ninstalled=yes\n'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);r=self.runner(values);c.prepare(CTX,r,root,BEFORE)
                proof=json.loads((root/'store-capacity.json').read_text())
                self.assertFalse(proof['prune_previous_rtc_cache']);self.assertEqual(r.persistence.run.call_count,1)

    def test_insufficient_capacity_fails_before_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(c,'SIZE',1024),self.assertRaisesRegex(RuntimeError,'enough capacity'):
                c.prepare(CTX,self.runner('available_kib=0\ninstalled=no\n'),Path(tmp),BEFORE)

    def test_archive_verified_before_prune_and_guards_precede_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';data=b'x'*4096;source.write_bytes(data)
            sha=hashlib.sha256(data).hexdigest();name='mainline-nixos-'+sha+'.squashfs'
            with mock.patch.multiple(c,SOURCE=source,SIZE=len(data),SHA=sha,NAME=name):
                r=self.runner('available_kib=1023\ninstalled=no\n');c.prepare(CTX,r,root,BEFORE)
                archive=root/name
                self.assertEqual(archive.read_bytes(),data);self.assertEqual(archive.stat().st_mode&0o777,0o400)
                c.install(CTX,r,root)
                profile=e.StoreProfile(root,'/nix/store/'+'z'*32+'-system',CTX.STORE_SHA,CTX.STORE_SIZE,False)
                cmd=r.efi_linux.upload_command('mainline-nixos-'+CTX.STORE_SHA+'.squashfs',BEFORE,CTX.BOOT_SHA,profile)
                prune=cmd.index('rm -- /mnt/gemian/nixos/'+name)
                self.assertLess(cmd.index('store-provision.required'),prune)
                self.assertLess(cmd.index('*,noload,*|*,norecovery,*'),prune)
                self.assertLess(cmd.index('gzip -t'),prune)
                self.assertLess(prune,cmd.index('available=$(df'))
                self.assertNotIn('remount',cmd)
                subprocess.run(['sh','-n'],input=cmd,text=True,check=True)
                (root/'store-upload.log').write_text('rtc-cache-pruned='+sha+'\n')
                self.assertTrue(c.verify_final(r,root)['previous_rtc_cache_host_archive_verified'])
                (root/'store-upload.log').write_text('')
                with self.assertRaises(RuntimeError): c.verify_final(r,root)
                archive.chmod(0o600);archive.write_bytes(b'y'*4096)
                with self.assertRaisesRegex(RuntimeError,'archive or upload profile changed'):
                    r.efi_linux.upload_command('mainline-nixos-'+CTX.STORE_SHA+'.squashfs',BEFORE,CTX.BOOT_SHA,profile)

    def test_duplicate_capacity_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(RuntimeError):
            c.prepare(CTX,self.runner('available_kib=9000\navailable_kib=0\ninstalled=no\n'),Path(tmp),BEFORE)


class Rescue(unittest.TestCase):
    def test_guard_requires_matching_image_and_actual_stage1(self):
        cmd=s.guard(CTX,BEFORE,BOOT)
        for value in (BOOT,CTX.NOTES_SHA,CTX.BOOT_SHA,BEFORE['gpt_sha256'],CTX.STORE_SHA):self.assertIn(value,cmd)
        self.assertIn('test ! -e /run/current-system',cmd)
        self.assertIn('test ! -e /run/store-provision.ready',cmd)
        self.assertIn('test -x /bin/busybox',cmd)
        subprocess.run(['sh','-n'],input=cmd,text=True,check=True)
        with self.assertRaises(ValueError):s.guard(CTX,dict(BEFORE,gpt_sha256='; bad'),BOOT)

    def test_stage2_rescue_is_unchanged_and_wrong_stage1_rejected(self):
        for stage2,raw,expected in ((True,'',True),(False,'boot_id='+BOOT,True),(False,'unexpected',False)):
            with tempfile.TemporaryDirectory() as tmp:
                r=SimpleNamespace(candidate_needs_rescue_reboot=mock.Mock(return_value=stage2),reboot=mock.Mock(),
                    persistence=SimpleNamespace(run=mock.Mock(return_value=raw)))
                old=r.reboot;s.install(CTX,r,Path(tmp))
                self.assertEqual(r.candidate_needs_rescue_reboot(['ssh'],BEFORE,'calendar'),expected)
                r.reboot(['ssh'],Path(tmp),'candidate-reboot-request.json');old.assert_called_once()

    def test_ssh_timeout_preserves_marker_but_does_not_prove_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r=SimpleNamespace(qualify=SimpleNamespace(save=save))
            def reboot(*args,**kwargs):
                kwargs['stdout'].write('boot_id='+BOOT+'\nstage1-rescue-request=verified p29=ro\n')
                kwargs['stdout'].flush()
                raise subprocess.TimeoutExpired(['ssh'],25)
            with mock.patch.object(s.subprocess,'run',side_effect=reboot):
                proof=s.request(r,['ssh'],root,'guarded-script',BOOT)
            self.assertTrue(proof['stage1_rescue_request_verified']);self.assertTrue(proof['ssh_timed_out'])
            self.assertFalse(proof['reset_proven'])

    def test_missing_or_wrong_boot_marker_is_not_accepted(self):
        for text in ('','boot_id='+OLD+'\nstage1-rescue-request=verified p29=ro\n'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);r=SimpleNamespace(qualify=SimpleNamespace(save=save))
                def fail(*args,**kwargs):kwargs['stdout'].write(text);return SimpleNamespace(returncode=255)
                with mock.patch.object(s.subprocess,'run',side_effect=fail),self.assertRaises(RuntimeError):
                    s.request(r,['ssh'],root,'guarded-script',BOOT)


if __name__=='__main__':unittest.main()
