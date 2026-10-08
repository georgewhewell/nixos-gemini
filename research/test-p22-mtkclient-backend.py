#!/usr/bin/env python3
"""Host-only evidence and USB-ordering tests; never open a real USB device."""
import os
import importlib.util
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

# These fixtures model trials from the direct-boot M69 baseline.
os.environ['GEMINI_ACCEPTED_BASELINE'] = str(Path(__file__).resolve().parents[1]/'research/baselines/m69.json')
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


class SnapshotTests(unittest.TestCase):
    def test_disappearing_sysfs_attributes_are_incomplete_until_directory_gone(self):
        for error in (errno.ENOENT, errno.ENODEV):
            for exists in (True, False):
                with self.subTest(error=error, exists=exists), \
                        patch.object(Path, 'read_text', side_effect=OSError(error, 'USB disconnected')), \
                        patch.object(Path, 'exists', return_value=exists):
                    self.assertEqual(backend.usb_snapshot('3-2'), backend.UNKNOWN if exists else None)

    def test_unrelated_io_and_permission_errors_remain_fatal(self):
        for error in (errno.EIO, errno.EACCES):
            with patch.object(Path, 'read_text', side_effect=OSError(error, 'fault')), self.assertRaises(OSError):
                backend.usb_snapshot('3-2')

    def test_reenumeration_during_snapshot_does_not_prove_a_new_device(self):
        with patch.object(Path, 'read_text', side_effect=['7','0e8d','2000','8']):
            self.assertEqual(backend.usb_snapshot('3-2'), backend.UNKNOWN)
        with patch.object(Path, 'read_text', side_effect=['7','0e8d','2000','7']):
            self.assertEqual(backend.usb_snapshot('3-2'), DA)


class RescueFlowTests(unittest.TestCase):
    def test_failed_writer_still_rescues_only_an_identified_linux_candidate(self):
        class ObservingSupervisor(Exception): pass
        for verified in (False, True):
            for identified in (False, True):
                with self.subTest(verified=verified, identified=identified), tempfile.TemporaryDirectory() as tmp:
                    directory=Path(tmp); before={'boot_id':'old'}
                    for suffix in ('pid','pgid','sid'): (directory/('candidate.'+suffix)).write_text('1234')
                    (directory/'candidate.state').write_text('flash_rc='+('0' if verified else '2')+' timestamp')
                    def wait(path,prefix,*args,**kwargs):
                        if prefix==qualification.SUCCESS: raise ObservingSupervisor()
                        if prefix=='flash_rc=0 ' and not verified: raise RuntimeError('observer race')
                        return prefix
                    with patch.object(qualification,'unit'), patch.object(qualification,'stage'), \
                            patch.object(qualification.time,'monotonic',side_effect=[0,151]), \
                            patch.object(qualification,'snapshot',return_value=before), \
                            patch.object(qualification,'wait_state',side_effect=wait), \
                            patch.object(qualification,'candidate_return',side_effect=RuntimeError('userspace unavailable')), \
                            patch.object(qualification,'candidate_needs_rescue_reboot',return_value=identified) as needs, \
                            patch.object(qualification,'reboot') as reboot:
                        with self.assertRaises(ObservingSupervisor): qualification.trial(directory,'handoff',before,[])
                    needs.assert_called_once_with([],before,'handoff')
                    self.assertEqual([call.args[2] for call in reboot.call_args_list],
                        ['candidate-reboot-request.json']+(['rescue-reboot-request.json'] if identified else []))

    def test_waits_for_identified_candidate_and_stops_when_rescue_already_won(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(qualification,'candidate_needs_rescue_reboot',side_effect=[False,True]) as needs, \
                    patch.object(qualification.time,'monotonic',side_effect=[0,1]), \
                    patch.object(qualification.time,'sleep'),patch.object(qualification,'wait_state') as wait, \
                    patch.object(qualification,'reboot') as reboot:
                self.assertTrue(qualification.request_linux_rescue([],{},root,'handoff',150))
            self.assertEqual(needs.call_count,2)
            wait.assert_called_once_with(root/'supervisor-rollback.state','tool_started ',30,terminal=False)
            reboot.assert_called_once_with([],root,'rescue-reboot-request.json')
            (root/'supervisor.state').write_text(qualification.SUCCESS+'timestamp')
            with patch.object(qualification,'candidate_needs_rescue_reboot') as needs,patch.object(qualification,'reboot') as reboot:
                self.assertFalse(qualification.request_linux_rescue([],{},root,'handoff',150))
            needs.assert_not_called();reboot.assert_not_called()


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

    def test_explicit_rtc_tool_changes_only_reboot_preservation(self):
        config=dict(self.config,mtk=backend.MTK_RTC)
        self.assertEqual(backend.config_for_state(config,Path(config['candidate_state'])),'a'*64)
        self.assertEqual(backend.command_sequence(backend.MTK),backend.COMMANDS)
        self.assertEqual(backend.command_sequence(backend.MTK_RTC),backend.COMMANDS+' --preserve-rtc')
        with self.assertRaises(ValueError):backend.command_sequence('/usr/bin/mtk')

    def test_idle_scan_leaves_transfer_time_inside_existing_outer_timeout(self):
        command = backend.client_command(backend.MTK_RTC)
        self.assertIn('180s',command)
        self.assertEqual(command[command.index('--connect-timeout')+1], '120')
        self.assertLess(command.index('--connect-timeout'),command.index('multi'))
        self.assertEqual(backend.CLIENT_TIMEOUT-backend.CONNECT_TIMEOUT,60)
        self.assertEqual(command[-1], backend.COMMANDS+' --preserve-rtc')
        self.assertNotIn('--connect-timeout',backend.client_command(backend.MTK))

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

    def test_recovery_timing_must_agree_with_the_intended_branch(self):
        good = {'intended_test_branch_reached': True}
        early = {'intended_test_branch_reached': False}
        self.assertTrue(qualification.profile_qualified('reset', good, 13, False))
        self.assertFalse(qualification.profile_qualified('reset', good, 44, False))
        self.assertTrue(qualification.profile_qualified('watchdog', good, 44, False))
        for elapsed in (9, 30.9, 61, 180):
            self.assertFalse(qualification.profile_qualified('watchdog', good, elapsed, False))
        self.assertFalse(qualification.profile_qualified('watchdog', early, 44, False))
        self.assertFalse(qualification.profile_qualified('watchdog', good, 44, True))


class HandoffEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.before = {'memory@40000000/reg': '00000000400000000000000100000000',
                       'chosen/ccci,modem_info_v2': '00' * 48, 'memtotal_kib': '3784500'}
        for index in (5, 6, 7):
            self.before[f'reserved-memory/mblock-{index}-ccci/reg'] = '00000000880000000000000000600000'
        self.range_key = 'reserved-memory/reserve-memory-dram_r0_dummy_read/alloc-ranges'
        self.before[self.range_key] = '00000000452590000000000038d57000'
        self.after = dict(self.before, **{qualification.HANDOFF_MARKER: b'fit\0'.hex()})

    def test_phandle_renumbering_preserves_live_reservations(self):
        a = 'reserved-memory/mblock-5-ccci/phandle'
        b = 'reserved-memory/mblock-6-ccci/phandle'
        before = dict(self.before, **{a:'00000001', b:'00000002'})
        after = dict(self.after, **{a:'00000031', b:'00000032'})
        qualification.verify_handoff_tree(before, after, 'handoff')
        for change in ({b:'00000031'}, {a:'00000000'}, {a:'ffffffff'}, {a:'1234'},
                       {'reserved-memory/mblock-5-ccci/reg':'00000000'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                qualification.verify_handoff_tree(before, dict(after, **change), 'handoff')
        for key in (a, b):
            with self.subTest(missing=key), self.assertRaises(RuntimeError):
                qualification.verify_handoff_tree(before, {k:v for k,v in after.items() if k != key}, 'handoff')

    def test_full_memory_modem_reservations_and_markers(self):
        qualification.verify_handoff_tree(self.before, self.after, 'handoff')
        efi = dict(self.after, **{qualification.EFI_MARKER: b'passed\0'.hex()})
        qualification.verify_handoff_tree(self.before, efi, 'efi-smoke')
        for after, profile in ((self.before, 'handoff'), (self.after, 'efi-smoke'), (efi, 'handoff')):
            with self.assertRaises(RuntimeError):
                qualification.verify_handoff_tree(self.before, after, profile)
        with self.assertRaises(RuntimeError):
            qualification.verify_handoff_tree(self.after, self.after, 'handoff')
        for key in self.before:
            if key in ('memtotal_kib', self.range_key):
                continue
            altered = dict(self.after, **{key: '00'})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                qualification.verify_handoff_tree(self.before, altered, 'handoff')

    def test_lk_ramdisk_allocation_window_may_shift_but_must_remain_in_ram(self):
        for start, end, valid in ((0x45900000, 0x7dfb0000, True),
                                  (0x3ffff000, 0x7dfb0000, False),
                                  (0x45900000, 0x80000000, False),
                                  (0x45900000, 0x45900000, False)):
            after = dict(self.after)
            after[self.range_key] = (start.to_bytes(8, 'big') + (end-start).to_bytes(8, 'big')).hex()
            if valid:
                qualification.verify_handoff_tree(self.before, after, 'handoff')
            else:
                with self.assertRaises(RuntimeError):
                    qualification.verify_handoff_tree(self.before, after, 'handoff')

    def test_snapshot_requires_full_memory_and_modem_data(self):
        for key, value in ((None, None), ('memtotal_kib', '96000'),
                           ('memory@40000000/reg', '00000000400000000000000006000000'),
                           ('chosen/ccci,modem_info_v2', '00'),
                           ('reserved-memory/mblock-7-ccci/reg', '')):
            tree = dict(self.before)
            if key:
                tree[key] = value
            output = '\n'.join(f'{k}={v}' for k, v in tree.items())
            with patch.object(qualification.qualify, 'run', return_value=output):
                if key:
                    with self.assertRaises(RuntimeError):
                        qualification.handoff_tree([])
                else:
                    self.assertEqual(qualification.handoff_tree([]), tree)

    def test_candidate_requires_exact_carrier_new_boot_and_unchanged_baseline(self):
        before = dict(boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                      system=qualification.qualify.ACCEPTED_SYSTEM, healthy='yes',
                      boot_sha256=qualification.qualify.ACCEPTED_BOOT, gpt_sha256='b'*64)
        after = dict(before, boot_id='cccccccc-cccc-cccc-cccc-cccccccccccc',
                     boot_sha256=qualification.PROFILES['handoff'][1])
        hashes = qualification.P30_SHA + ' p30\n' + qualification.P31_SHA + ' p31\n'
        for change in ({}, {'boot_id': before['boot_id']}, {'boot_sha256': before['boot_sha256']},
                       {'gpt_sha256': 'd'*64}, {'system': 'other'}, {'healthy': 'no'}):
            observed = dict(after, **change)
            output = '\n'.join(f'{k}={v}' for k, v in observed.items())
            with patch.object(qualification.qualify, 'run', side_effect=[output, hashes]):
                if change:
                    with self.assertRaises(RuntimeError):
                        qualification.candidate_snapshot([], before, 'handoff')
                else:
                    self.assertEqual(qualification.candidate_snapshot([], before, 'handoff'),
                                     dict(after, p30_sha256=qualification.P30_SHA,
                                          p31_sha256=qualification.P31_SHA))

    def test_rescue_reboot_requires_the_identified_candidate(self):
        before = dict(boot_id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                      system=qualification.qualify.ACCEPTED_SYSTEM, gpt_sha256='b'*64)
        rows = ['cccccccc-cccc-cccc-cccc-cccccccccccc', before['system'],
                qualification.PROFILES['handoff'][1] + '  /dev/mmcblk0p22', 'b'*64 + '  -']
        with patch.object(qualification.qualify, 'run', return_value='\n'.join(rows)):
            self.assertTrue(qualification.candidate_needs_rescue_reboot([], before, 'handoff'))
        for index, value in ((0, before['boot_id']), (0, 'malformed'), (1, '/other/system'),
                             (2, qualification.qualify.ACCEPTED_BOOT + ' p22'), (2, ''),
                             (3, 'c'*64 + ' -')):
            altered = rows.copy()
            altered[index] = value
            with patch.object(qualification.qualify, 'run', return_value='\n'.join(altered)):
                self.assertFalse(qualification.candidate_needs_rescue_reboot([], before, 'handoff'))


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
        (self.directory / 'ramoops.bin').write_bytes(bytes(0xe0000))
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
        for name in ('boot-readback.img', 'gpt-primary.bin', 'ramoops.bin'):
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
