#!/usr/bin/env python3
"""Check bundle selection, durable worker routing and recovery on failed checks."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('rtc_profile',Path(__file__).with_name('test-boot.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Profile(unittest.TestCase):
    def test_manifest_selects_bundle_and_rejects_changed_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); data=b'compressed store fixture'
            sha=hashlib.sha256(data).hexdigest(); name='mainline-nixos-'+sha+'.squashfs'
            (root/name).write_bytes(data)
            (root/'kernel').symlink_to(m.p.KERNEL)
            (root/'boot-padded-p22.img').write_bytes(b'boot fixture')
            manifest=(f'store-file={name}\nstore-sha256={sha}\nstore-size={len(data)}\n'
                      f'kernel={m.p.KERNEL.name}\nsystem=/nix/store/'+ 'a'*32+'-system\n')
            (root/'MANIFEST').write_text(manifest)
            names=('BUNDLE','KERNEL','SYSTEM','STORE_SHA','STORE_SIZE','BOOT_SHA','NOTES_SHA')
            original={key:getattr(m.p,key) for key in names}
            try:
                with mock.patch.object(m.p.f.q.r.power_kernel,'notes_sha',return_value='b'*64):
                    m.artifacts(root)
                    self.assertEqual(m.p.BUNDLE,root)
                    self.assertEqual(m.p.STORE_SHA,sha)
                    self.assertEqual(m.p.store_profile(m.p.f.q.r.efi_linux).bundle,root)
                    (root/name).write_bytes(b'X'*len(data))
                    with self.assertRaisesRegex(ValueError,'content'): m.artifacts(root)
                    (root/name).write_bytes(data)
                    (root/'MANIFEST').write_text(manifest+'store-size=1\n')
                    with self.assertRaisesRegex(ValueError,'Duplicate'): m.artifacts(root)
            finally:
                for key,value in original.items(): setattr(m.p,key,value)

    def test_durable_worker_receives_resolved_bundle_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); bundle=root/'bundle'; bundle.mkdir()
            cache=root/'cache'; cache.touch(); alias=root/'result'; alias.symlink_to(bundle)
            argv=['test-boot.py','--execute','--out',tmp+'/trial','--bundle',str(alias),
                  '--reclaim-cache',str(cache),'--watchdog-expiry']
            setup=mock.Mock()
            with mock.patch.object(sys,'argv',argv),mock.patch.object(m.p.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                m.p.main(setup)
            setup.assert_called_once_with(bundle,cache,None)
            command=run.call_args.args[0]
            self.assertIn(str(m.p.ENTRYPOINT),command)
            self.assertIn('--worker',command)
            self.assertEqual(command[command.index('--bundle')+1],str(bundle))
            self.assertEqual(command[command.index('--reclaim-cache')+1],str(cache))
            self.assertIn('--watchdog-expiry',command)
            self.assertTrue(any(v.startswith('--unit=boot-test-') for v in command))

    def test_durable_worker_receives_efi_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=root/'bundle';bundle.mkdir();efi=root/'efi';efi.mkdir()
            setup=mock.Mock()
            with mock.patch.object(sys,'argv',['test-boot.py','--execute','--out',tmp+'/trial',
                    '--bundle',str(bundle),'--install-efi',str(efi)]), \
                    mock.patch.object(m.p.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                m.p.main(setup)
            setup.assert_called_once_with(bundle,None,efi)
            command=run.call_args.args[0]
            self.assertEqual(command[command.index('--install-efi')+1],str(efi))

    def test_pm_requires_new_kernel_prerequisites(self):
        for args in (dict(pm_test='devices'),dict(pm_test='freezer'),dict(cycle=True)):
            with self.subTest(args=args),self.assertRaises(ValueError):m.configure(**args)

    def test_missing_rtc_proof_still_runs_existing_recovery_and_retention_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r=SimpleNamespace(watchdog_expiry_requested=False,qualify=SimpleNamespace(save=mock.Mock()))
            with mock.patch.object(m,'base_finish',side_effect=RuntimeError('failed profile')) as finish:
                with self.assertRaisesRegex(RuntimeError,'failed profile'):m.alarm_finish(r,root,'before')
            self.assertIsInstance(finish.call_args.args[-1],FileNotFoundError)
            saved=r.qualify.save.call_args.args[-1]
            self.assertFalse(saved['rtc_alarm_diagnostics_qualified'])


if __name__=='__main__':unittest.main()
