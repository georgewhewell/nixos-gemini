#!/usr/bin/env python3
"""Generation promotion must not revive historical flash-backed paging."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('update_system', Path(__file__).with_name('update-system.py'))
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)

SYSTEM = '/nix/store/' + '0' * 32 + '-nixos-system-gemini-test'


class PromotionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trial = Path(self.temp.name) / 'trial'
        self.trial.mkdir()
        self.result = dict(result='passed', profile_qualified=True,
                           paging_policy='zram', ram_only_paging_qualified=True)
        self.evidence = dict(system=SYSTEM, paging_policy='zram',
                             ram_only_paging_qualified=True,
                             default_policy_paging_qualified=True,
                             runtime_policy_writes=False,
                             swap=dict(device='/dev/zram0', flash_swap_active=False, writeback=False),
                             paging=dict(flash_swap_written_sectors=0))
        self.write()

    def write(self, audit=True):
        for name, value in [('result.json', self.result),
                            ('power-swap-evidence.json', self.evidence),
                            ('final-idle-check.json', dict(no_writer=audit))]:
            (self.trial / name).write_text(json.dumps(value))

    def test_qualified_ram_trial_selects_exact_system(self):
        self.assertEqual(update.trial_system(self.trial), SYSTEM)

    def test_historical_passing_disk_trial_is_rejected(self):
        self.result.pop('paging_policy')
        self.result.pop('ram_only_paging_qualified')
        self.evidence = dict(system=SYSTEM, default_policy_paging_qualified=True,
                             runtime_policy_writes=False)
        self.write()
        with self.assertRaisesRegex(RuntimeError, 'RAM-only'):
            update.trial_system(self.trial)

    def test_flash_or_writeback_cannot_be_promoted(self):
        for changes in [dict(device='/dev/mmcblk0p34'),
                        dict(flash_swap_active=True), dict(writeback=True)]:
            with self.subTest(changes=changes):
                self.evidence['swap'] = dict(device='/dev/zram0', flash_swap_active=False, writeback=False)
                self.evidence['swap'].update(changes)
                self.write()
                with self.assertRaisesRegex(RuntimeError, 'RAM-only'):
                    update.trial_system(self.trial)

    def test_written_flash_or_ambiguous_zero_is_rejected(self):
        for sectors in [1, False, '0', None]:
            with self.subTest(sectors=sectors):
                self.evidence['paging']['flash_swap_written_sectors'] = sectors
                self.write()
                with self.assertRaisesRegex(RuntimeError, 'RAM-only'):
                    update.trial_system(self.trial)

    def test_runtime_policy_change_is_not_boot_qualification(self):
        self.evidence['runtime_policy_writes'] = True
        self.write()
        with self.assertRaisesRegex(RuntimeError, 'RAM-only'):
            update.trial_system(self.trial)

    def test_final_audit_requires_boolean_true(self):
        for audit in [False, 'false', 1]:
            with self.subTest(audit=audit):
                self.write(audit=audit)
                with self.assertRaisesRegex(RuntimeError, 'final audit'):
                    update.trial_system(self.trial)

    def test_flash_backed_baseline_blocks_execute_before_remote_io(self):
        root = Path(self.temp.name) / 'repo'
        (root / 'research').mkdir(parents=True)
        (root / 'research/accepted-baseline.json').write_text(json.dumps(
            dict(boot='uboot-efi', system=SYSTEM, zswap_shrinker='Y')))
        with patch.object(update, 'ROOT', root), \
             patch.object(sys, 'argv', ['update-system', '--trial', str(self.trial), '--execute']), \
             patch.object(update, 'run') as remote, \
             patch.object(update.subprocess, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'RAM-only recovery baseline'):
                update.main()
            remote.assert_not_called()
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
