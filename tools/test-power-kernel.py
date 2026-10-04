#!/usr/bin/env python3
"""Reject old-kernel evidence and unsafe power-policy/owner state."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('qualify-uboot-recovery.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
p = r.power_kernel


class PowerKernel(unittest.TestCase):
    def good(self):
        return dict(boot_id='11111111-1111-1111-1111-111111111111', system=p.SYSTEM,
                    notes_sha256='a' * 64, watchdog_identity='mtk-wdt',
                    watchdog_state='active', watchdog_timeout='31', watchdog_nowayout='1',
                    watchdog_owned='yes', owner_unit='active', owner_restart='no',
                    owner_pid='42', owner_starttime='2345',
                    pm_test='[none] core processors platform devices freezer',
                    mem_sleep='[s2idle]', disk='[shutdown] reboot suspend test_resume',
                    hibernation='false', suspend_then_hibernate='false', swap_count='0')

    def verify(self, state, suffix=''):
        return p.verify_state(''.join(f'{k}={v}\n' for k,v in state.items()) + suffix,
                              self.good()['boot_id'], 'a' * 64)

    def test_old_kernel_and_changed_policy_or_owner_are_rejected(self):
        self.verify(self.good())
        for field, bad in dict(system=r.persistent_nix.SYSTEM, notes_sha256='b' * 64,
                               boot_id='22222222-2222-2222-2222-222222222222',
                               watchdog_state='inactive', watchdog_timeout='15',
                               watchdog_nowayout='0', watchdog_owned='no', owner_pid='1',
                               owner_starttime='0', owner_unit='inactive', owner_restart='always',
                               hibernation='true', suspend_then_hibernate='true', swap_count='1',
                               pm_test='none [core] processors platform devices freezer').items():
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.verify(dict(self.good(), **{field: bad}))
        missing=self.good();del missing['watchdog_owned']
        for state, suffix in ((missing,''),(self.good(),'watchdog_owned=yes\n'),(self.good(),'invalid\n')):
            with self.assertRaises(RuntimeError): self.verify(state, suffix)

    def test_power_profile_uses_its_own_kernel_system_and_preserves_efi_files(self):
        profile='power-kernel'
        self.assertEqual(r.PROFILES[profile][1],p.BOOT_SHA)
        self.assertEqual(r.candidate_system({'system':'old'},profile),p.SYSTEM)
        self.assertEqual(r.store_profile_for(profile).system,p.SYSTEM)
        self.assertFalse(r.store_profile_for(profile).require_efi)
        self.assertEqual(r.files_profile_for(profile),r.entry_dt.files_profile(r.efi_files))
        before={'memory/reg':'same'}
        r.verify_handoff_tree(before,before,profile)
        with self.assertRaises(RuntimeError):
            r.verify_handoff_tree(before,dict(before,**{r.HANDOFF_MARKER:b'efi\0'.hex()}),profile)
        self.assertFalse(r.phase_evidence('0x474d10e0','0x474d10ee',profile)['uboot_execution_proven'])

    def test_same_config_does_not_identify_different_kernel_code(self):
        self.assertEqual((p.KERNEL/'kernel.config').read_bytes(),
                         (r.persistent_nix.KERNEL/'kernel.config').read_bytes())
        self.assertNotEqual(p.notes_sha(),p.notes_sha(r.persistent_nix.KERNEL))
        self.assertRegex(p.notes_sha(),r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
