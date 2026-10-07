#!/usr/bin/env python3
"""Reject wrong storage/kernel identities and runtime-supplied default policy."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('power_swap', Path(__file__).with_name('qualify-power-swap.py'))
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


class Profile(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = p.configure()

    def before(self):
        return dict(p.STORAGE, boot_id='11111111-1111-1111-1111-111111111111',
                    boot_sha256=self.r.qualify.ACCEPTED_BOOT, system=self.r.qualify.ACCEPTED_SYSTEM, healthy='yes')

    def test_profile_uses_pinned_bundle_and_exact_swap_geometry(self):
        self.assertEqual(set(self.r.PROFILES), {p.PROFILE})
        self.assertEqual(self.r.PROFILES[p.PROFILE][1], p.BOOT_SHA)
        self.assertEqual(self.r.candidate_system(self.before(), p.PROFILE), p.SYSTEM)
        self.assertEqual(self.r.store_profile_for(p.PROFILE).sha, p.STORE_SHA)
        self.assertFalse(self.r.store_profile_for(p.PROFILE).require_efi)
        self.assertIn('= 22249472', self.r.qualify.SNAPSHOT)
        self.assertIn('= 10485760', self.r.qualify.SNAPSHOT)
        self.assertNotIn('= 32737247', self.r.qualify.SNAPSHOT)
        self.r.verify_handoff_tree({'memory/reg':'same'}, {'memory/reg':'same'}, p.PROFILE)

    def test_old_runner_and_snapshot_are_not_mutated(self):
        old = p.f.q.module('unchanged_recovery', p.ROOT/'tools/qualify-uboot-recovery.py')
        self.assertNotIn(p.PROFILE, old.PROFILES)
        self.assertIn('= 32737247', old.qualify.SNAPSHOT)
        self.assertNotEqual(old.power_kernel.SYSTEM, p.SYSTEM)
        self.assertIn('= 32737247', p.f.q.r.qualify.SNAPSHOT)

    def test_factory_or_changed_protected_layout_rejected_before_admission(self):
        p.storage_identity(self.before())
        for key in p.STORAGE:
            bad = dict(self.before(), **{key:'0'*64})
            with self.subTest(key=key), self.assertRaises(RuntimeError): p.storage_identity(bad)
        with self.assertRaises(RuntimeError): p.storage_identity(dict(self.before(), gpt_sha256=p.f.GEOMETRY['factory'][0]))

    def test_candidate_and_recovery_return_both_check_extra_storage_hashes(self):
        before = self.before(); after = dict(before, boot_id='22222222-2222-2222-2222-222222222222')
        self.r.qualify.verify_return(before, after)
        for key in p.STORAGE:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.r.qualify.verify_return(before, dict(after, **{key:'0'*64}))
        with self.assertRaises(RuntimeError): self.r.qualify.verify_return(before, before)

    def good_power(self):
        return dict(boot_id=self.before()['boot_id'], system=p.SYSTEM, notes_sha256=p.NOTES_SHA,
            config_sha256=p.hashlib.sha256((p.KERNEL/'kernel.config').read_bytes()).hexdigest(),
            pm_test='[none] core processors platform devices freezer', mem_sleep='[s2idle]',
            disk='[shutdown] reboot suspend test_resume', hibernation='false',
            suspend_then_hibernate='false', zswap='Y', shrinker='Y')

    def test_old_kernel_wrong_default_and_sleep_policy_rejected(self):
        state = self.good_power()
        def verify(value, suffix=''):
            return p.verify_power_state(''.join(f'{k}={v}\n' for k,v in value.items())+suffix,state['boot_id'])
        verify(state)
        for key, value in dict(system=self.r.qualify.ACCEPTED_SYSTEM, notes_sha256='0'*64,
                              config_sha256='0'*64, shrinker='N', hibernation='true', zswap='N').items():
            with self.subTest(key=key), self.assertRaises(RuntimeError): verify(dict(state, **{key:value}))
        with self.assertRaises(RuntimeError): verify(state, 'shrinker=Y\n')
        with self.assertRaises(RuntimeError): verify({k:v for k,v in state.items() if k!='notes_sha256'})


class PagingMode(unittest.TestCase):
    def test_kernel_default_mode_never_installs_or_runs_policy_writers(self):
        q = p.paging
        for runtime in (False, True):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); (directory/'probe').write_bytes(b'probe-fixture')
                service = dict(q.LIMITS, ActiveState='active', SubState='exited', MainPID='0',
                    RemainAfterExit='yes', Result='success', ExecMainCode='1', ExecMainStatus='0')
                payload = dict(bytes=134217728, swapped_kib=131080, read_sectors=200000,
                               written_sectors=262184, pattern_verified=True)
                def read(ssh, command, out, name, **kwargs):
                    if name=='target-service': return ''.join(f'{k}={v}\n' for k,v in service.items())
                    if name=='probe-output': return json.dumps(payload)
                    if name=='memory-policy-during': return 'Y\n'
                    if name=='memory-policy-restored': return 'N\n' if runtime else 'Y\n'
                    return ''
                with mock.patch.object(q.subprocess, 'run', side_effect=[subprocess.CompletedProcess([],0,b'',b''),
                      subprocess.CompletedProcess([],0,'','')]), mock.patch.object(q.f.q.r.persistence, 'run', side_effect=read):
                    self.assertEqual(q.run_probe(directory, {'boot_id':'known'}, 'gemini-swap-io-1-2', runtime_policy=runtime), payload)
                command = (directory/'probe.sh').read_text(); transfer = (directory/'transfer.sh').read_text()
                self.assertEqual('ExecStartPre=' in command, runtime)
                self.assertEqual('ExecStopPost=' in command, runtime)
                self.assertEqual('> /sys/module/zswap/parameters/shrinker_enabled' in transfer, runtime)
                if not runtime: self.assertIn('shrinker_enabled)" = Y', command)


class Cleanup(unittest.TestCase):
    inactive = 'ActiveState=inactive\nMainPID=0\n'
    active = 'ActiveState=active\nMainPID=123\n'

    def runner(self, responses):
        return SimpleNamespace(qualify=SimpleNamespace(run=mock.Mock(side_effect=responses)))

    def test_collected_unit_needs_no_second_stop(self):
        r = self.runner([self.inactive]); p.stop_owned_unit(r, 'owned-unit')
        self.assertEqual(r.qualify.run.call_count, 1)

    def test_active_unit_must_be_stopped_and_observed_terminal(self):
        r = self.runner([self.active, '', self.inactive]); p.stop_owned_unit(r, 'owned-unit')
        self.assertEqual(r.qualify.run.call_args_list[1].args[0], ['systemctl', '--user', 'stop', 'owned-unit'])
        r = self.runner([self.active, '', self.active])
        with self.assertRaises(RuntimeError): p.stop_owned_unit(r, 'owned-unit')

    def test_concurrent_collection_is_accepted_only_with_terminal_proof(self):
        error = subprocess.CalledProcessError(5, ['systemctl', 'stop'])
        r = self.runner([self.active, error, self.inactive]); p.stop_owned_unit(r, 'owned-unit')
        r = self.runner([self.active, error, self.active])
        with self.assertRaises(subprocess.CalledProcessError): p.stop_owned_unit(r, 'owned-unit')

    def test_other_errors_and_unknown_states_remain_errors(self):
        r = self.runner([self.active, subprocess.CalledProcessError(1, ['systemctl', 'stop'])])
        with self.assertRaises(subprocess.CalledProcessError): p.stop_owned_unit(r, 'owned-unit')
        for raw in ('', 'ActiveState=unknown\nMainPID=0\n', 'ActiveState=inactive\nMainPID=abc\n'):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                p.stop_owned_unit(self.runner([raw]), 'owned-unit')


class Retention(unittest.TestCase):
    def test_prior_builds_survive_later_trials_and_invalid_shell_paths_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); old = root/'power-swap-01'; old.mkdir()
            token = 'a'*32
            proof = dict(ordinary_daemon_build_qualified=True, token=token,
                output='/nix/store/'+'b'*32+'-gemini-daemon-'+token,
                output_link='/home/gemini/.gemini-daemon-build-'+token+'/result', proof_sha256='c'*64)
            path = old/'nix-candidate.json'; path.write_text(json.dumps(proof))
            self.assertEqual(p.prior_outputs(root), {'power-swap-01':proof})
            self.assertEqual(p.prior_outputs(root, old), {})
            rtc=root/'power-rtc-01';rtc.mkdir();(rtc/'nix-candidate.json').write_text(json.dumps(proof))
            self.assertEqual(p.prior_outputs(root), {'power-rtc-01':proof,'power-swap-01':proof})
            self.assertEqual(p.prior_outputs(root, rtc), {'power-swap-01':proof})
            calendar=root/'power-rtc-calendar-01';calendar.mkdir();(calendar/'nix-candidate.json').write_text(json.dumps(proof))
            self.assertEqual(p.prior_outputs(root), {'power-rtc-01':proof,'power-swap-01':proof,'power-rtc-calendar-01':proof})
            self.assertEqual(p.prior_outputs(root, calendar), {'power-rtc-01':proof,'power-swap-01':proof})
            startup=root/'power-rtc-startup-01';startup.mkdir();(startup/'nix-candidate.json').write_text(json.dumps(proof))
            self.assertEqual(p.prior_outputs(root)['power-rtc-startup-01'], proof)
            path.write_text(json.dumps(dict(proof, output=proof['output']+'; unreviewed-command')))
            with self.assertRaises(RuntimeError): p.prior_outputs(root)


if __name__ == '__main__': unittest.main()
