#!/usr/bin/env python3
"""Host-only evidence and USB-ordering tests; never open a real USB device."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('backend', Path(__file__).with_name('p22-mtkclient-backend.py'))
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
spec = importlib.util.spec_from_file_location('qualification',
    Path(__file__).resolve().parents[1] / 'tools/qualify-uboot-recovery.py')
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)

GADGET = ('0525', 'a4a2', '6')
DA = ('0e8d', '2000', '7')
FIRST = ('0e8d', '2000', '8')
SECOND = ('0e8d', '2000', '9')


class BootWindowTests(unittest.TestCase):
    def window(self):
        result = backend.BootWindow()
        for index, state in enumerate((GADGET, None, DA)):
            result.observe(state, index)
        return result

    def test_ack_and_da_departure_do_not_arm_rescue(self):
        window = self.window()
        window.acknowledged = True
        window.observe(None, 3)
        self.assertTrue(window.da_departed)
        self.assertFalse(window.complete)
        window.observe(FIRST, 4)
        self.assertFalse(window.complete)
        window.observe(None, 5)
        self.assertTrue(window.complete)

    def test_fast_reset_cannot_be_confused_with_first_boot(self):
        window = self.window()
        window.acknowledged = True
        window.observe(FIRST, 4)
        self.assertFalse(window.complete)
        window.observe(SECOND, 5)
        self.assertTrue(window.complete)
        self.assertEqual(window.first_boot, FIRST)

    def test_unpublished_sysfs_attributes_do_not_prove_departure(self):
        window = self.window()
        window.acknowledged = True
        window.observe(FIRST, 4)
        window.observe(backend.UNKNOWN, 5)
        self.assertFalse(window.complete)
        window.observe(FIRST, 6)
        self.assertFalse(window.complete)

    def test_missing_first_boot_never_completes(self):
        window = self.window()
        window.acknowledged = True
        window.observe(None, 4)
        window.observe(GADGET, 5)
        self.assertFalse(window.complete)

    def test_reenumeration_before_ack_fails(self):
        window = self.window()
        with self.assertRaises(RuntimeError):
            window.observe(FIRST, 4)

    def test_brom_after_da_is_not_normal_boot(self):
        window = self.window()
        window.acknowledged = True
        with self.assertRaises(RuntimeError):
            window.observe(('0e8d', '0003', '8'), 4)

    def test_only_device_free_timeout_is_retryable(self):
        log = 'Waiting for PreLoader'
        self.assertTrue(backend.scan_missed(124, log, backend.BootWindow()))
        self.assertFalse(backend.scan_missed(1, log, backend.BootWindow()))
        self.assertFalse(backend.scan_missed(124, log, self.window()))
        for evidence in ('Detected', 'HW code:', 'DAXFlash'):
            self.assertFalse(backend.scan_missed(124, log + evidence, backend.BootWindow()))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(version=1, mtk=backend.MTK, stage_image='/run/private/boot.img',
                           candidate_state='/run/private/candidate.state',
                           rollback_state='/run/private/rollback.state',
                           candidate_sha256='a' * 64, rollback_sha256='b' * 64,
                           gpt_sha256='c' * 64, usb_port='3-2')

    def test_candidate_and_rescue_hashes_are_role_bound(self):
        for role, expected in (('candidate', 'a'), ('rollback', 'b')):
            self.assertEqual(backend.config_for_state(self.config, Path(self.config[role + '_state'])), expected * 64)
        with self.assertRaises(ValueError):
            backend.config_for_state(self.config, Path('/run/other/state'))

    def test_unqualified_tool_and_unknown_config_are_rejected(self):
        for key, value in (('mtk', '/usr/bin/mtk'), ('usb_port', '../3-2'),
                           ('rollback_sha256', ''), ('unexpected', 'yes'),
                           ('rollback_state', self.config['candidate_state'])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                backend.config_for_state(dict(self.config, **{key: value}), Path(self.config['candidate_state']))


class PhaseEvidenceTests(unittest.TestCase):
    def test_fresh_early_phase_proves_execution_but_not_test_branch(self):
        result = qualification.phase_evidence('0x00000000', '0x474d10e3', 'watchdog')
        self.assertTrue(result['uboot_execution_proven'])
        self.assertEqual(result['uboot_phase'], 'board_init')
        self.assertFalse(result['intended_test_branch_reached'])

    def test_stale_missing_and_unknown_phases_do_not_prove_execution(self):
        for before, after in ((None, '0x474d10e3'), ('0x474d10e3', '0x474d10e3'),
                              ('0x00000000', '0xdeadbeef'), ('0x00000000', None)):
            with self.subTest(before=before, after=after):
                self.assertFalse(qualification.phase_evidence(before, after, 'watchdog')['uboot_execution_proven'])

    def test_baseline_never_proves_uboot_execution(self):
        self.assertFalse(qualification.phase_evidence('0x00000000', '0x474d10e3', 'baseline')['uboot_execution_proven'])

    def test_intended_branch_is_profile_specific(self):
        for profile, phase in (('reset', '0x474d10ec'), ('watchdog', '0x474d10ed')):
            self.assertTrue(qualification.phase_evidence('0x00000000', phase, profile)['intended_test_branch_reached'])
        self.assertFalse(qualification.phase_evidence('0x00000000', '0x474d10ec', 'watchdog')['intended_test_branch_reached'])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.image = b'\x5a' * backend.SIZE
        self.sha = backend.digest(self.image)
        self.gpt = b'\x33' * 32768
        self.gptsha = backend.digest(self.gpt)
        (self.directory / 'boot-readback.img').write_bytes(self.image)
        (self.directory / 'gpt-primary.bin').write_bytes(self.gpt)
        (self.directory / 'boot-phase.bin').write_bytes(bytes.fromhex('ec104d47'))
        self.log = backend.WRITE_ACK + '\n' + backend.ACK + '\n'

    def verify(self, rc=0, log=None):
        backend.verify_result(rc, self.log if log is None else log,
                              self.directory, self.sha, self.gptsha)

    def test_complete_evidence_passes(self):
        self.verify()

    def test_identical_readback_is_not_write_proof(self):
        with self.assertRaises(RuntimeError):
            self.verify(log=backend.ACK)

    def test_write_without_reboot_ack_fails(self):
        with self.assertRaises(RuntimeError):
            self.verify(log=backend.WRITE_ACK)

    def test_nonzero_with_valid_bytes_still_fails(self):
        with self.assertRaises(RuntimeError):
            self.verify(rc=1)

    def test_missing_or_partial_phase_read_fails(self):
        path = self.directory / 'boot-phase.bin'
        path.write_bytes(b'abc')
        with self.assertRaises(RuntimeError):
            self.verify()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_short_read_or_different_gpt_fails(self):
        for name in ('boot-readback.img', 'gpt-primary.bin'):
            path = self.directory / name
            original = path.read_bytes()
            path.write_bytes(original[:-1])
            with self.assertRaises(RuntimeError):
                self.verify()
            path.write_bytes(original)
        (self.directory / 'gpt-primary.bin').write_bytes(b'\x34' * 32768)
        with self.assertRaises(RuntimeError):
            self.verify()

    def test_staging_rejects_partial_wrong_sha_and_symlink(self):
        path = self.directory / 'boot-readback.img'
        self.assertEqual(backend.checked_image(path, self.sha), self.image)
        with self.assertRaises(ValueError):
            backend.checked_image(path, 'f' * 64)
        link = self.directory / 'link'
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            backend.checked_image(link, self.sha)
        path.write_bytes(b'partial')
        with self.assertRaises(ValueError):
            backend.checked_image(path, self.sha)


if __name__ == '__main__':
    unittest.main()
