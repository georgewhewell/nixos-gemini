#!/usr/bin/env python3
"""Exercise additive layout publication and failure isolation on real files."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).with_name('gemini-data-layout.sh')

class Layout(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.root=self.base/'root';self.root.mkdir()
        (self.root/'lost+found').mkdir()
        self.home=self.base/'home';self.home.mkdir()
        (self.home/'gemini').mkdir(mode=0o700)
        (self.home/'gemini/private.txt').write_text('preserved\n')
        (self.home/'gemini/link').symlink_to('private.txt')
        self.bin=self.base/'bin';self.bin.mkdir()
        # Root ownership cannot be applied by an unprivileged host test.
        self.stub('chown','test "$1" = 0:30000\ntest "${2##*/}" = upper\n')
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'])
    def stub(self,name,body):
        p=self.bin/name;p.write_text('#!/bin/sh\nset -eu\n'+body);p.chmod(0o755)
    def run_script(self,success=True):
        p=subprocess.run(['sh',str(SCRIPT),str(self.root),str(self.home)],env=self.env,
                         text=True,capture_output=True,timeout=20)
        self.assertEqual(p.returncode==0,success,p.stdout+p.stderr)
        return p
    def test_home_copy_permissions_and_idempotence(self):
        self.run_script()
        self.assertEqual((self.root/'home/gemini/private.txt').read_text(),'preserved\n')
        self.assertTrue((self.root/'home/gemini/link').is_symlink())
        self.assertEqual((self.root/'home/gemini').stat().st_mode&0o777,0o700)
        self.assertEqual((self.root/'nix/upper').stat().st_mode&0o7777,0o1775)
        (self.root/'home/gemini/private.txt').write_text('new persistent data\n')
        self.assertIn('already-initialized',self.run_script().stdout)
        self.assertEqual((self.root/'home/gemini/private.txt').read_text(),'new persistent data\n')
    def test_foreign_data_refused_before_copy(self):
        (self.root/'keep').write_text('original')
        self.run_script(False)
        self.assertEqual((self.root/'keep').read_text(),'original')
        self.assertFalse((self.root/'.gemini-layout-stage').exists())
    def test_symlink_layout_and_dangling_entries_refused(self):
        for name in ('home','nix','.gemini-layout-stage','unrelated'):
            with self.subTest(name=name):
                p=self.root/name;p.symlink_to(self.base/'absent')
                self.run_script(False);self.assertTrue(p.is_symlink());p.unlink()
    def test_partial_copy_never_activates(self):
        self.stub('cp','mkdir "$3"\nprintf partial > "$3/partial"\nexit 1\n')
        self.run_script(False)
        self.assertFalse((self.root/'home').exists())
        self.assertFalse((self.root/'nix').exists())
        self.assertEqual((self.home/'gemini/private.txt').read_text(),'preserved\n')
        self.run_script(False) # A retry must not overwrite the partial staging area.
    def test_failed_ownership_never_activates(self):
        self.stub('chown','exit 1\n')
        self.run_script(False)
        self.assertFalse((self.root/'home').exists())
        self.assertFalse((self.root/'nix').exists())
    def test_final_publish_failure_keeps_home_gate_closed(self):
        mv=subprocess.check_output(['sh','-c','command -v mv'],text=True).strip()
        self.stub('mv',f'case "$1" in */home) exit 1 ;; esac\nexec {mv} "$@"\n')
        self.run_script(False)
        self.assertFalse((self.root/'home').exists())
        self.assertTrue((self.root/'nix/upper').is_dir())
        self.run_script(False)

if __name__=='__main__':unittest.main()
