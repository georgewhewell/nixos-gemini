#!/usr/bin/env python3
"""Reject false daemon/sandbox evidence and crossed boot/store profiles."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('recovery',Path(__file__).with_name('qualify-uboot-recovery.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
n=r.persistent_nix

class PersistentNix(unittest.TestCase):
    def test_native_and_legacy_cpu_admission_use_the_correct_evidence(self):
        boot = '8ab215b1-2e33-4b19-9168-2ff5b0574d84'
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as tmp:
                kernel = Path(tmp)
                (kernel/'kernel.config').write_text('CONFIG_ARM64_LATE_CPU_RUNTIME_IDENTITY=y\n' if legacy else '')
                persistence = SimpleNamespace(run=mock.Mock(side_effect=RuntimeError('stop after admission')))
                with mock.patch.object(n, 'old_persistence'), self.assertRaisesRegex(RuntimeError, 'stop after admission'):
                    n.evidence([], boot, kernel, None, persistence, kernel=kernel)
                script = persistence.run.call_args.args[1]
                label = persistence.run.call_args.args[3]
                if legacy:
                    self.assertEqual(label, 'nix-candidate-state')
                    self.assertIn('test "$(cat /sys/devices/system/cpu/cpu8/online)" = 1', script)
                    self.assertIn('test "$(cat /sys/devices/system/cpu/cpu9/online)" = 1', script)
                    self.assertIn('verified the pre-finalization runtime identity binding', script)
                else:
                    self.assertEqual(label, 'nix-native-cpus')
                    self.assertEqual(script, n.native_cpu_script(boot))
                    self.assertIn('a72_startup=pass', script)

    def test_complete_build_and_retention_do_not_repeat_cpu_admission(self):
        token = 'a'*32
        boot = '8ab215b1-2e33-4b19-9168-2ff5b0574d84'
        output = '/nix/store/'+'b'*32+'-gemini-daemon-'+token
        proof = f'token={token}\nuid=1000\nnet=net:[200]\noutside_home=absent\n'
        digest = hashlib.sha256(proof.encode()).hexdigest()
        retained = f'proof_sha256={digest}\nnix_hash=sha256:test\nderiver={output}.drv\n'
        state = 'daemon_pid=23\nhost_net=net:[100]\ndaemon_net=net:[100]\nclient_uid=1000\nstore_root=/persist/nixos\n'
        replies = {'nix-native-cpus':'', 'nix-candidate-state':state,
                   'nix-unprivileged-build':output, 'nix-builder-proof':proof,
                   'nix-build-before':retained, 'nix-build-after':retained}
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Path(tmp); (kernel/'kernel.config').write_text('')
            persistence = SimpleNamespace(NIX='/nix/bin', BUSYBOX='/busybox',
                run=mock.Mock(side_effect=lambda ssh, script, directory, name: replies[name]))
            qualify = SimpleNamespace(save=mock.Mock())
            with mock.patch.object(n, 'old_persistence'), mock.patch.object(n.uuid, 'uuid4', return_value=SimpleNamespace(hex=token)):
                result = n.evidence([], boot, kernel, qualify, persistence, kernel=kernel)
            self.assertTrue(result['ordinary_daemon_build_qualified'])
            self.assertEqual([c.args[3] for c in persistence.run.call_args_list],
                             ['nix-native-cpus', 'nix-candidate-state', 'nix-unprivileged-build', 'nix-builder-proof', 'nix-build-before'])
            persistence.run.reset_mock()
            n.verify_retained([], 'recovery-boot', kernel, qualify, persistence, result)
            persistence.run.assert_called_once()
            script = persistence.run.call_args.args[1]
            self.assertIn("--store 'local?root=/persist/nixos'", script)
            self.assertNotIn('gemini-a72-preflight', script)
            replies['nix-build-after'] = retained.replace(digest, '0'*64)
            with self.assertRaisesRegex(RuntimeError, 'output changed'):
                n.verify_retained([], 'recovery-boot', kernel, qualify, persistence, result)

    def test_namespace_identity_and_nonroot_builder(self):
        proof=dict(token='a'*32,uid='1000',net='net:[200]',outside_home='absent')
        n.verify_builder(proof,'a'*32,'net:[100]','net:[100]')
        for key,bad in (('token','b'*32),('uid','0'),('uid','unknown'),('net','net:[100]'),
                        ('net','missing'),('outside_home','visible')):
            with self.subTest(key=key,bad=bad),self.assertRaises(RuntimeError):
                n.verify_builder(dict(proof,**{key:bad}),'a'*32,'net:[100]','net:[100]')
        with self.assertRaises(RuntimeError):n.verify_builder(proof,'a'*32,'net:[100]','net:[200]')
    def test_direct_candidate_cannot_claim_uboot(self):
        tree={'memory/reg':'same','reserved-memory/ccci/reg':'same'}
        r.verify_handoff_tree(tree,tree,'persistent-nix')
        with self.assertRaises(RuntimeError):
            r.verify_handoff_tree(tree,dict(tree,**{r.HANDOFF_MARKER:b'efi\0'.hex()}),'persistent-nix')
        with self.assertRaises(RuntimeError):
            r.verify_handoff_tree(tree,dict(tree,**{'memory/reg':'changed'}),'persistent-nix')
        self.assertFalse(r.phase_evidence('0x474d10e0','0x474d10ee','persistent-nix')['uboot_execution_proven'])
        self.assertEqual(r.candidate_system({'system':'accepted'},'persistent-nix'),n.SYSTEM)
        self.assertEqual(r.rescue_identity({'system':'accepted','boot_id':'old'}, {'boot_id':'new'})['system'],'accepted')
    def test_profile_hash_size_and_system_all_required(self):
        e=r.efi_linux
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=b'pinned test store';sha=hashlib.sha256(raw).hexdigest()
            name='mainline-nixos-'+sha+'.squashfs';path=root/name;path.write_bytes(raw)
            manifest=root/'MANIFEST';manifest.write_text(f'system={n.SYSTEM}\nstore-file={name}\n')
            p=e.StoreProfile(root,n.SYSTEM,sha,len(raw),False)
            self.assertEqual(e.payload(p),(path,name))
            with self.assertRaises(RuntimeError):e.payload(p._replace(size=len(raw)+1))
            path.write_bytes(b'x'*len(raw))
            with self.assertRaises(RuntimeError):e.payload(p)
            path.write_bytes(raw);manifest.write_text(f'system={e.SYSTEM}\nstore-file={name}\n')
            with self.assertRaises(RuntimeError):e.payload(p)
            with self.assertRaises(RuntimeError):e.payload(p._replace(system='$(false)'))
    def test_direct_and_efi_upload_admission_remain_separate(self):
        e=r.efi_linux;before=dict(boot_id='a'*8+'-'+ 'a'*4+'-'+ 'a'*4+'-'+ 'a'*4+'-'+ 'a'*12,gpt_sha256='b'*64)
        p=n.store_profile(e);name='mainline-nixos-'+p.sha+'.squashfs'
        direct=e.upload_command(name,before,n.BOOT_SHA,p)
        self.assertIn('test ! -e /sys/firmware/efi',direct)
        self.assertIn('test ! -e /sys/firmware/devicetree/base/chosen/gemini,uboot-handoff',direct)
        self.assertIn('(set -C; cat > ',direct)
        check=f'test "$(sha256sum \'/mnt/gemian/nixos/{e.ACCEPTED_STORE}\' | cut -d\' \' -f1)" = \'{e.ACCEPTED_STORE_SHA}\''
        self.assertLess(direct.index(check),direct.index('(set -C; cat > '))
        self.assertGreater(direct.rindex(check),direct.index("ln '"))
        efi=e.upload_command('mainline-nixos-'+e.STORE_SHA+'.squashfs',before,'c'*64)
        self.assertIn('fw_platform_size)',efi)
        self.assertNotIn('test ! -e /sys/firmware/efi',efi)
        with self.assertRaises(ValueError):e.upload_command(name,before,n.BOOT_SHA)
        with self.assertRaises(ValueError):e.upload_command(name,dict(before,boot_id='$(false)'),n.BOOT_SHA,p)

if __name__=='__main__':unittest.main()
