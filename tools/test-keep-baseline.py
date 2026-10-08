#!/usr/bin/env python3
"""Check promotion of a qualified candidate to the accepted baseline."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('keep_recovery', ROOT / 'tools/qualify-uboot-recovery.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
SUPERVISOR = ROOT / 'research/p22-proof-supervisor.sh'


class Keep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.dir = Path(self.tmp.name) / 'promote-01'; self.dir.mkdir()
        self.image = Path(self.tmp.name) / 'boot-padded-p22.img'
        self.image.write_bytes(b'\x5a' * (16 * 1024 * 1024))
        self.sha = hashlib.sha256(self.image.read_bytes()).hexdigest()
        r.PROFILES = {'normal': (self.image, self.sha)}
        r.LINUX_PROFILES = r.LINUX_PROFILES + ('normal',)
        self.middle = dict(boot_id='11111111-2222-3333-4444-555555555555',
                           system='/nix/store/' + 'b' * 32 + '-nixos-system-gemini')

    def tearDown(self):
        self.tmp.cleanup()

    def keep(self, kept):
        def run(argv):
            command = argv[-1]
            if 'gemini-system' in command: return 'normal\n'
            if 'shrinker_enabled' in command: return 'Y\n'
            if argv[:2] == ['systemctl', '--user']: return ''
            raise AssertionError(argv)
        with mock.patch.object(r, 'wait_state') as wait, \
                mock.patch.object(r, 'candidate_snapshot', return_value=kept), \
                mock.patch.object(r, 'handoff_tree', return_value={r.HANDOFF_MARKER: b'efi\0'.hex()}), \
                mock.patch.object(r.qualify, 'run', side_effect=run):
            result = r.keep_candidate(self.dir, 'normal', {}, self.middle, ['ssh'], 'owner', 'net')
        wait.assert_called_once()
        return result

    def test_record_matches_supervisor_and_baseline_is_written(self):
        result = self.keep(dict(self.middle))
        self.assertTrue(result['promoted'])
        record = (self.dir / 'candidate-self-accepted').read_text()
        self.assertEqual(record, f'candidate_self_accepted sha256={self.sha}\n')
        # The supervisor compares $(cat record), which drops the final newline.
        self.assertIn('"candidate_self_accepted sha256=$CANDIDATE_SHA" ]', SUPERVISOR.read_text())
        baseline = json.loads((self.dir / 'promoted-baseline.json').read_text())
        self.assertEqual(baseline['boot_sha256'], self.sha)
        self.assertEqual(baseline['system'], self.middle['system'])
        self.assertEqual((baseline['store'], baseline['zswap_shrinker'], baseline['boot']),
                         ('normal', 'Y', 'uboot-efi'))
        self.assertEqual(baseline['previous'], r.BASELINE['name'])

    def test_reboot_during_stand_down_is_not_promoted(self):
        with self.assertRaisesRegex(RuntimeError, 'rebooted'):
            self.keep(dict(self.middle, boot_id='99999999-2222-3333-4444-555555555555'))
        self.assertFalse((self.dir / 'promoted-baseline.json').exists())

    def test_existing_record_is_never_overwritten(self):
        (self.dir / 'candidate-self-accepted').write_text('stale\n')
        with self.assertRaises(FileExistsError):
            self.keep(dict(self.middle))

    def test_baseline_tree_follows_boot_type(self):
        efi = {r.HANDOFF_MARKER: b'efi\0'.hex()}
        with mock.patch.dict(r.BASELINE, boot='direct'):
            r.verify_baseline_tree({})
            with self.assertRaisesRegex(RuntimeError, 'Direct-Linux'): r.verify_baseline_tree(efi)
        with mock.patch.dict(r.BASELINE, boot='uboot-efi'):
            r.verify_baseline_tree(efi)
            with self.assertRaisesRegex(RuntimeError, 'EFI handoff'): r.verify_baseline_tree({})

    def test_supervisor_self_accept_suite(self):
        subprocess.run(['sh', str(ROOT / 'research/p22-self-accept-supervisor.test.sh')],
                       check=True, capture_output=True, timeout=600)


if __name__ == '__main__':
    unittest.main()
