#!/usr/bin/env python3
"""Exercise additive publication, rejection before writes and interrupted retries."""
import hashlib
import os
import shlex
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'nix/gemini-efi-publish.sh'
class Publication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.dest=self.base/'target';self.source=self.base/'source'
        self.dest.mkdir();self.source.mkdir();self.manifest=self.base/'files.manifest'
        self.files={'EFI/systemd/systemd-bootaa64.efi':b'manager','EFI/Gemini/abc/linux.efi':b'kernel',
                    'EFI/Gemini/abc/initrd.cpio.gz':b'initrd','loader/entries/gemini.conf':b'entry',
                    'loader/loader.conf':b'config'}
        self.real_cat=shlex.quote(shutil.which('cat'))
        self.manifest.write_text(''.join(f'{hashlib.sha256(v).hexdigest()} {len(v)} {k}\n' for k,v in self.files.items()))
        for name,data in self.files.items():
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        (self.dest/'nixos').mkdir();(self.dest/'nixos/store.squashfs').write_bytes(b'protected store')
    def run_script(self,mode='install',env=None,previous=None):
        args=['sh',str(SCRIPT),mode,str(self.dest),str(self.source),str(self.manifest)]
        if previous is not None:args.append(previous)
        return subprocess.run(args,
                              capture_output=True,text=True,env=env).returncode
    def old_default(self):
        p=self.dest/'loader/loader.conf';p.parent.mkdir();p.write_bytes(b'old default')
        old_entry=self.dest/'loader/entries/old.conf';old_entry.parent.mkdir();old_entry.write_bytes(b'old entry')
        return hashlib.sha256(p.read_bytes()).hexdigest()
    def snapshot(self):
        return {str(p.relative_to(self.dest)):('symlink',os.readlink(p)) if p.is_symlink() else
                ('directory',) if p.is_dir() else ('file',p.read_bytes()) for p in self.dest.rglob('*')}
    def test_publish_verify_and_idempotent_retry_preserve_store(self):
        before=self.snapshot();self.assertNotEqual(self.run_script('verify'),0);self.assertEqual(before,self.snapshot())
        self.assertEqual(self.run_script(),0);self.assertEqual(self.run_script('verify'),0)
        inodes={name:(self.dest/name).stat().st_ino for name in self.files}
        self.assertEqual(self.run_script(),0);self.assertEqual(inodes,{n:(self.dest/n).stat().st_ino for n in self.files})
        self.assertEqual((self.dest/'nixos/store.squashfs').read_bytes(),b'protected store')
    def test_conflict_is_rejected_before_any_new_file(self):
        name='loader/loader.conf';p=self.dest/name;p.parent.mkdir();p.write_bytes(b'owner config')
        before=self.snapshot();self.assertNotEqual(self.run_script(),0);self.assertEqual(before,self.snapshot())
    def test_source_corruption_is_rejected_before_publication(self):
        (self.source/'loader/loader.conf').write_bytes(b'corrupt')
        before=self.snapshot();self.assertNotEqual(self.run_script(),0);self.assertEqual(before,self.snapshot())
    def test_all_symlink_positions_are_rejected(self):
        outside=self.base/'outside';outside.mkdir()
        for base in (self.source,self.dest):
            for name in ('EFI','EFI/Gemini','EFI/Gemini/abc','EFI/Gemini/abc/linux.efi'):
                p=base/name;p.parent.mkdir(parents=True,exist_ok=True)
                saved=p.with_name(p.name+'.saved')
                if p.exists():p.rename(saved)
                p.symlink_to(outside);before=self.snapshot()
                self.assertNotEqual(self.run_script(),0);self.assertEqual(before,self.snapshot())
                p.unlink()
                if saved.exists():saved.rename(p)
        self.assertEqual(list(outside.iterdir()),[])
    def test_copy_failure_removes_owned_temp_and_can_resume(self):
        bindir=self.base/'bin';bindir.mkdir();cat=bindir/'cat'
        cat.write_text('#!/bin/sh\ncase "$1" in */initrd.cpio.gz) printf partial; exit 1;; esac\nexec '+self.real_cat+' "$@"\n')
        cat.chmod(0o755);env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'])
        self.assertNotEqual(self.run_script(env=env),0)
        self.assertEqual((self.dest/'EFI/Gemini/abc/linux.efi').read_bytes(),b'kernel')
        self.assertFalse((self.dest/'EFI/Gemini/abc/initrd.cpio.gz').exists())
        self.assertFalse((self.dest/'loader').exists());self.assertFalse(list(self.dest.rglob('*.gemini-upload.tmp')))
        self.assertEqual(self.run_script(),0);self.assertEqual(self.run_script('verify'),0)
    def test_existing_temp_is_preserved(self):
        p=self.dest/'EFI/systemd/systemd-bootaa64.efi.gemini-upload.tmp';p.parent.mkdir(parents=True);p.write_bytes(b'owner temp')
        self.assertNotEqual(self.run_script(),0);self.assertEqual(p.read_bytes(),b'owner temp')
        self.assertFalse((self.dest/'EFI/systemd/systemd-bootaa64.efi').exists())
    def test_invalid_manifest_paths_and_missing_record(self):
        good=self.manifest.read_text()
        for bad in ('../escape','/absolute','EFI/../../escape','EFI//escape','EFI/./escape','EFI/escape;bad'):
            self.manifest.write_text(good.replace('EFI/systemd/systemd-bootaa64.efi',bad))
            before=self.snapshot();self.assertNotEqual(self.run_script(),0);self.assertEqual(before,self.snapshot())
        self.manifest.write_text('\n'.join(good.splitlines()[:-1])+'\n')
        self.assertNotEqual(self.run_script(),0)
    def test_activate_keeps_old_entry_and_checked_default_backup(self):
        sha=self.old_default();backup=self.dest/('loader/loader.conf.gemini-backup-'+sha)
        self.assertEqual(self.run_script('activate',previous=sha),0)
        self.assertEqual((self.dest/'loader/loader.conf').read_bytes(),b'config')
        self.assertEqual(backup.read_bytes(),b'old default')
        self.assertEqual((self.dest/'loader/entries/old.conf').read_bytes(),b'old entry')
        self.assertEqual(self.run_script('activate',previous=sha),0)
        self.assertEqual(self.run_script('verify'),0)
    def test_activation_refuses_wrong_pin_or_foreign_backup_before_writes(self):
        sha=self.old_default();before=self.snapshot()
        self.assertNotEqual(self.run_script('activate',previous='0'*64),0)
        self.assertEqual(before,self.snapshot())
        backup=self.dest/('loader/loader.conf.gemini-backup-'+sha);backup.write_bytes(b'owner data')
        before=self.snapshot();self.assertNotEqual(self.run_script('activate',previous=sha),0)
        self.assertEqual(before,self.snapshot())
    def test_failed_config_rename_keeps_old_default_and_retry_finishes(self):
        sha=self.old_default();bindir=self.base/'bin';bindir.mkdir();mv=bindir/'mv'
        mv.write_text('#!/bin/sh\nexit 1\n');mv.chmod(0o755)
        env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'])
        self.assertNotEqual(self.run_script('activate',env=env,previous=sha),0)
        self.assertEqual((self.dest/'loader/loader.conf').read_bytes(),b'old default')
        self.assertTrue((self.dest/'loader/entries/gemini.conf').is_file())
        self.assertFalse(list(self.dest.rglob('*.gemini-upload.tmp')))
        self.assertEqual(self.run_script('activate',previous=sha),0)
    def test_activation_rechecks_default_after_payload_copy(self):
        sha=self.old_default();bindir=self.base/'bin';bindir.mkdir();cat=bindir/'cat'
        cat.write_text('#!/bin/sh\ncase "$1" in */initrd.cpio.gz) printf "owner edit" > "$GEMINI_TEST_DEFAULT";; esac\nexec '+self.real_cat+' "$@"\n')
        cat.chmod(0o755);env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],GEMINI_TEST_DEFAULT=str(self.dest/'loader/loader.conf'))
        self.assertNotEqual(self.run_script('activate',env=env,previous=sha),0)
        self.assertEqual((self.dest/'loader/loader.conf').read_bytes(),b'owner edit')
    def test_activation_requires_last_config_and_unique_records(self):
        sha=self.old_default();rows=self.manifest.read_text().splitlines();before=self.snapshot()
        for bad in ([rows[-1]]+rows[:-1],rows[:-1]+[rows[0]]):
            self.manifest.write_text('\n'.join(bad)+'\n')
            self.assertNotEqual(self.run_script('activate',previous=sha),0)
            self.assertEqual(before,self.snapshot())
if __name__=='__main__':unittest.main()
