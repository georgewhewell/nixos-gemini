#!/usr/bin/env python3
"""Check distinct initial/rescue admission and no-paging migration fences."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/file)
    out = importlib.util.module_from_spec(spec); spec.loader.exec_module(out)
    return out


m = module('migration', 'qualify-ram-only-recovery.py')
b = module('boot_migration', 'test-boot.py')
BOOT = '11111111-1111-1111-1111-111111111111'
STATE = dict(boot_id=BOOT, boot_sha256='a'*64, system='/nix/store/test-system')
RECORD = dict(system=STATE['system'], notes_sha256='b'*64, kernel_config_sha256='c'*64,
              command_line='init='+STATE['system']+'/init '+' '.join(m.builder.POLICY_ARGS))
STAT = '66 0 4720 841 0 0 0 0 0 612 841 0 0 0 0 0 0'


def raw(**changes):
    values = dict(boot_id=BOOT, cmdline=RECORD['command_line'], p34_stat=STAT, swap_rows='0', zswap='N', resume='0:0', p34_dev='259:2')
    values.update(changes)
    return ''.join(key+'='+value+'\n' for key, value in values.items())


class Migration(unittest.TestCase):
    def test_policy_rejects_swap_resume_and_all_mutating_block_io(self):
        self.assertFalse(m.verify_policy(raw(), STATE, RECORD)['active_swap'])
        for change in (dict(swap_rows='1'), dict(zswap='Y'), dict(resume='179:34'), dict(boot_id='other')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                m.verify_policy(raw(**change), STATE, RECORD)
        for index in (4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 16):
            values = STAT.split(); values[index] = '1'
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                m.verify_policy(raw(p34_stat=' '.join(values)), STATE, RECORD)
        for bad in (STAT+' 0', STAT.replace('841', '-1', 1)):
            with self.assertRaises(RuntimeError): m.verify_policy(raw(p34_stat=bad), STATE, RECORD)
        self.assertEqual(m.verify_policy(raw(resume='259:2'), STATE, RECORD, False)['resume'], '259:2')
        with self.assertRaises(RuntimeError): m.verify_policy(raw(resume='259:3'), STATE, RECORD, False)

    def test_boot_policy_requires_every_literal_mask_and_no_conflicts(self):
        for argument in RECORD['command_line'].split():
            for bad in (RECORD['command_line'].replace(argument, ''), RECORD['command_line']+' '+argument):
                with self.subTest(argument=argument), self.assertRaises(RuntimeError):
                    m.verify_policy(raw(cmdline=bad), STATE, RECORD)
        for extra in ('resume=/dev/mmcblk0p34', 'zswap.enabled=1', 'systemd.gpt_auto=1', 'systemd.mask=other.swap'):
            with self.assertRaises(RuntimeError):
                m.verify_policy(raw(cmdline=RECORD['command_line']+' '+extra), STATE, RECORD)
        # A volatile mask is admissible only on the original boot, never as
        # successful migration evidence.
        self.assertFalse(m.verify_policy(raw(cmdline='old'), STATE, RECORD, False)['masks_from_boot'])
        with self.assertRaises(RuntimeError): m.verify_policy(raw(cmdline='old'), STATE, RECORD)

    def test_script_uses_early_masks_without_policy_writes(self):
        script = m.policy_script(STATE, RECORD)
        self.assertEqual(subprocess.run(['sh', '-n'], input=script, text=True).returncode, 0)
        self.assertIn('/run/systemd/generator.early', script)
        for unit in m.builder.MASK_UNITS: self.assertIn(unit, script)
        for command in ('swapoff ', 'swapon ', 'systemctl mask', 'systemctl daemon-reload', 'echo N >'):
            self.assertNotIn(command, script)
        self.assertIn('test ! -e /sys/firmware/efi', script)
        volatile = m.policy_script(STATE, RECORD, False)
        self.assertIn('/run/systemd/system', volatile)
        self.assertNotIn('swap.target', volatile)

    def test_durable_worker_keeps_explicit_migration_and_forbids_keep_or_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)/'bundle'; bundle.mkdir()
            ordinary, migration = mock.Mock(), mock.Mock()
            argv = ['test-boot.py', '--out', tmp+'/trial', '--bundle', str(bundle),
                    '--migrate-ram-only', '--observe-seconds', '90', '--execute']
            with mock.patch.object(sys, 'argv', argv), \
                    mock.patch.object(b.p.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                b.p.main(ordinary, migration)
            ordinary.assert_not_called(); migration.assert_called_once_with(bundle)
            child = run.call_args.args[0]
            self.assertIn('--worker', child); self.assertIn('--migrate-ram-only', child)
            self.assertEqual(child[child.index('--observe-seconds')+1], '90')
            for option in ('--keep', '--watchdog-expiry', '--usb-cycle', '--pm-test'):
                with mock.patch.object(sys, 'argv', argv+[option]+(['freezer'] if option == '--pm-test' else [])), \
                        mock.patch.object(sys, 'stderr'), mock.patch.object(b.p, 'configure') as configure:
                    with self.assertRaises(SystemExit): b.p.main(ordinary, migration)
                    configure.assert_not_called()

    def test_staging_uses_new_image_twice_and_retains_original_identity(self):
        r = b.configure()
        original = dict(r.qualify.BASELINE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); trial = root/'trial'; trial.mkdir()
            locks = root/'locks'; locks.mkdir()
            (locks/'download-only-strix-4.xml').write_text('<fixture/>')
            image = root/'new.img'; image.write_bytes(b'\x01'*(16*1024*1024))
            sha = m.digest(image)
            r.RESCUE_BASELINE = dict(original, image=str(image), boot_sha256=sha)
            r.PROFILES = {'migration': (image, sha)}
            with mock.patch.object(r, 'LOCKS', locks):
                staged = r.stage(trial, 'migration', dict(gpt_sha256='c'*64))
            self.assertEqual(staged['candidate_sha256'], sha)
            self.assertEqual(staged['rollback_sha256'], sha)
            self.assertEqual(m.digest(trial/'boot.img'), sha)
            self.assertEqual(m.digest(trial/'rescue.img'), sha)
            self.assertEqual(r.qualify.BASELINE, original)
            self.assertEqual(r.BASELINE, original)
            self.assertEqual(r.backend.config_for_state(staged, trial/'candidate.state'), sha)
            self.assertEqual(r.backend.config_for_state(staged, trial/'supervisor-rollback.state'), sha)

    def test_rescue_expectation_changes_only_after_verified_owned_readback(self):
        r = b.configure()
        original = dict(r.qualify.BASELINE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = b'\x02'*(16*1024*1024); sha = hashlib.sha256(image).hexdigest()
            for name in ('boot.img', 'rescue.img'): (root/name).write_bytes(image)
            gpt = b'\x03'*32768; gpt_sha = hashlib.sha256(gpt).hexdigest()
            before = dict(boot_sha256=original['boot_sha256'], system=original['system'], boot_id=BOOT, gpt_sha256=gpt_sha)
            r.RESCUE_BASELINE = dict(original, boot_sha256=sha)
            config = dict(candidate_sha256=sha, rollback_sha256=sha, gpt_sha256=gpt_sha)
            (root/'backend.json').write_text(json.dumps(config))
            attempt = root/'supervisor-rollback.state-mtk-fixture'; attempt.mkdir()
            (attempt/'boot-readback.img').write_bytes(image)
            (attempt/'gpt-primary.bin').write_bytes(gpt)
            evidence = dict(attempt=str(attempt), backend='mtkclient', returncode=0,
                            expected_sha256=sha, first_boot_window_departed=True)
            evidence_path = root/'supervisor-rollback.state.mtk.json'; evidence_path.write_text(json.dumps(evidence))
            with mock.patch.object(r.qualify, 'adopt_baseline') as adopt:
                with self.assertRaises(RuntimeError): r.expect_verified_rescue(root, before)
                adopt.assert_not_called()
                (root/'supervisor.state').write_text(r.SUCCESS+'fixture')
                for field, value in (('returncode', 1), ('expected_sha256', original['boot_sha256']),
                                     ('first_boot_window_departed', False), ('attempt', str(root))):
                    evidence_path.write_text(json.dumps(dict(evidence, **{field: value})))
                    with self.assertRaises(RuntimeError): r.expect_verified_rescue(root, before)
                    adopt.assert_not_called()
                evidence_path.write_text(json.dumps(evidence))
                (attempt/'boot-readback.img').write_bytes(b'bad')
                with self.assertRaises(ValueError): r.expect_verified_rescue(root, before)
                adopt.assert_not_called()
                (attempt/'boot-readback.img').write_bytes(image)
                expected = r.expect_verified_rescue(root, before)
                adopt.assert_called_once_with(r.RESCUE_BASELINE)
                self.assertEqual(expected, dict(before, boot_sha256=sha))
                self.assertEqual(before['boot_sha256'], original['boot_sha256'])
                self.assertEqual(r.BASELINE, original)

    def test_trial_arms_new_rescue_sha_while_admitting_old_boot(self):
        r = b.configure()
        before = dict(boot_id=BOOT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix in ('pid', 'pgid', 'sid'): (root/('candidate.'+suffix)).write_text('12345')
            with mock.patch.object(r, 'stage', return_value={'rollback_sha256': 'f'*64}), \
                    mock.patch.object(r, 'snapshot', return_value=before) as snapshot, \
                    mock.patch.object(r, 'wait_state'), mock.patch.object(r, 'unit') as unit, \
                    mock.patch.object(r, 'reboot', side_effect=RuntimeError('stop before hardware')):
                with self.assertRaisesRegex(RuntimeError, 'stop before hardware'):
                    r.trial(root, b.p.PROFILE, before, [])
                snapshot.assert_called_once_with([])
                supervisor = next(call.args[2] for call in unit.call_args_list if 'supervisor' in call.args[0])
                self.assertEqual(supervisor[4], root/'rescue.img')
                self.assertEqual(supervisor[5], 'f'*64)
                self.assertNotEqual(supervisor[5], r.qualify.ACCEPTED_BOOT)

    def test_incomplete_platform_proof_cannot_publish_baseline(self):
        passed = dict(result='passed', **{flag: True for flag in m.QUALIFICATION_FLAGS})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for flag in m.QUALIFICATION_FLAGS:
                (root/'result.json').write_text(json.dumps(dict(passed, **{flag: False})))
                with self.subTest(flag=flag), self.assertRaises(RuntimeError):
                    m.qualified_baseline(None, None, root, RECORD, {}, {})
                self.assertFalse((root/'qualified-ram-only-baseline.json').exists())

    def test_completed_rescue_cannot_be_rebooted_as_an_identical_candidate(self):
        r = b.configure()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'supervisor-rollback.state').write_text('flash_rc=0 fixture')
            with mock.patch.object(r, 'candidate_needs_rescue_reboot', return_value=True) as needs, \
                    mock.patch.object(r, 'reboot') as reboot:
                self.assertFalse(r.request_linux_rescue([], {}, root, b.p.PROFILE))
                needs.assert_not_called(); reboot.assert_not_called()

    def test_unqualified_none_baseline_is_rejected_without_remote_calls(self):
        runner = SimpleNamespace(qualify=SimpleNamespace(BASELINE={'paging_policy': 'none'}), persistence=mock.Mock())
        with self.assertRaises(RuntimeError): m.accepted_policy(None, runner, STATE, Path('/unused'))
        runner.persistence.run.assert_not_called()

    def test_host_artifact_reproduces_and_wrong_build_record_is_rejected(self):
        proof = json.loads(m.HOST_PROOF.read_text())
        record = m.validate_bundle(Path(proof['package']))
        self.assertEqual(record['image_sha256'], proof['build']['image_sha256'])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp)/'proof.json'
            bad.write_text(json.dumps(dict(proof, build=dict(proof['build'], image_sha256='0'*64))))
            with mock.patch.object(m, 'HOST_PROOF', bad), self.assertRaises(RuntimeError):
                m.validate_bundle(Path(proof['package']))


if __name__ == '__main__': unittest.main()
