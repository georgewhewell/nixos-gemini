#!/usr/bin/env python3
"""Reject FIT fallback, stale identity and malformed loader EFI evidence."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import unittest
from unittest.mock import Mock

spec=importlib.util.spec_from_file_location('manager',Path(__file__).with_name('qualify-efi-manager.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def encoded(value,attrs=6):
    return (attrs.to_bytes(4,'little')+(value+'\0').encode('utf-16-le')).hex()

class Manager(unittest.TestCase):
    def setUp(self):
        self.boot='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        self.tree={m.PREFIX+'result':b'starting\0'.hex(),m.PREFIX+'stage':b'start-image\0'.hex(),m.PREFIX+'sha256':m.SHA}
        self.values=dict(LoaderInfo='systemd-boot 261.2',LoaderEntrySelected='gemini-efi-trial.conf',
                         LoaderImageIdentifier='\\EFI\\systemd\\systemd-bootaa64.efi',
                         LoaderDevicePartUUID='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                         LoaderTimeMenuUSec='20000000',LoaderTimeExecUSec='29000000')
        self.rows={'boot_id':self.boot,**{k:encoded(v) for k,v in self.values.items()}}
    def test_only_nonreturning_verified_manager_marker_passes(self):
        m.verify_tree(self.tree)
        for key,value in (('result',b'returned\0'.hex()),('result',b'failed\0'.hex()),
                          ('stage',b'file-hash\0'.hex()),('sha256','0'*64),('status','0000000000000000')):
            with self.assertRaises(RuntimeError):m.verify_tree(dict(self.tree,**{m.PREFIX+key:value}))
        for key in self.tree:
            missing=dict(self.tree);del missing[key]
            with self.assertRaises(RuntimeError):m.verify_tree(missing)
    def test_loader_identity_entry_volume_path_and_timeout(self):
        self.assertEqual(m.verify_variables(self.rows,self.boot)['menu_to_exec_usec'],9_000_000)
        uboot=dict(self.rows,LoaderImageIdentifier=encoded('/\\EFI\\systemd\\systemd-bootaa64.efi'))
        self.assertEqual(m.verify_variables(uboot,self.boot)['menu_to_exec_usec'],9_000_000)
        uppercase=dict(uboot,LoaderDevicePartUUID=encoded(self.values['LoaderDevicePartUUID'].upper()))
        self.assertEqual(m.verify_variables(uppercase,self.boot)['LoaderDevicePartUUID'],self.values['LoaderDevicePartUUID'])
        for key,value in (('LoaderInfo','grub'),('LoaderEntrySelected','other.conf'),
                          ('LoaderImageIdentifier','\\EFI\\other.efi'),('LoaderImageIdentifier','///EFI/systemd/systemd-bootaa64.efi'),
                          ('LoaderDevicePartUUID','$(false)'),
                          ('LoaderTimeMenuUSec','30000000'),('LoaderTimeExecUSec','22000000'),
                          ('LoaderTimeExecUSec','999999999'),('LoaderTimeExecUSec','-1')):
            with self.assertRaises(RuntimeError):m.verify_variables(dict(self.rows,**{key:encoded(value)}),self.boot)
        for key in self.rows:
            missing=dict(self.rows);del missing[key]
            with self.assertRaises(RuntimeError):m.verify_variables(missing,self.boot)
        with self.assertRaises(RuntimeError):m.verify_variables(self.rows,'other-boot')
    def test_variable_binary_format_and_attributes(self):
        for raw in ('','xx',encoded('ok',attrs=7),encoded('ok')[:-4],encoded('x\0y'),encoded('x\ny'),
                    '0600000000d80000',encoded('x'*3000)):
            with self.assertRaises(RuntimeError):m.decode_variable(raw)
    def test_evidence_requires_actual_p29_and_preserves_no_keypress_claim(self):
        raw='\n'.join(k+'='+v for k,v in self.rows.items())
        with tempfile.TemporaryDirectory() as d:
            q=SimpleNamespace(run=Mock(side_effect=[raw,'/dev/mmcblk0p29\n']),save=Mock())
            m.evidence([],self.boot,Path(d),q,self.tree)
            self.assertFalse(q.save.call_args.args[2]['physical_key_press_observed'])
            self.assertIn('mount -t efivarfs -o ro,',q.run.call_args_list[0].args[0][0])
            self.assertIn(m.KMOD+' -d '+m.KERNEL+' efivarfs',q.run.call_args_list[0].args[0][0])
            for wrong in ('/dev/mmcblk0p30',''):
                q.run=Mock(side_effect=[raw,wrong]);q.save.reset_mock()
                with self.assertRaises(RuntimeError):m.evidence([],self.boot,Path(d),q,self.tree)
                q.save.assert_not_called()
    def test_failed_read_retains_partial_evidence_before_rescue(self):
        with tempfile.TemporaryDirectory() as d:
            partial='boot_id='+self.boot+'\nLoaderInfo='+self.rows['LoaderInfo']+'\n'
            error='loader-evidence: missing LoaderEntrySelected\n'
            q=SimpleNamespace(run=Mock(side_effect=subprocess.CalledProcessError(
                1,['ssh'],output=partial,stderr=error)),save=Mock())
            with self.assertRaisesRegex(RuntimeError,'missing LoaderEntrySelected'):
                m.evidence([],self.boot,Path(d),q,self.tree)
            self.assertEqual((Path(d)/'manager-variables.txt').read_text(),partial)
            self.assertEqual((Path(d)/'manager-variables-error.txt').read_text(),error)
            q.save.assert_not_called()

if __name__=='__main__':unittest.main()
