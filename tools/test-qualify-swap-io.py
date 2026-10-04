#!/usr/bin/env python3
"""Reject weak paging evidence and unbounded/failed target services."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('paging', Path(__file__).with_name('qualify-swap-io.py'))
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.paging = dict(bytes=134217728, swapped_kib=131072, read_sectors=262144,
                           written_sectors=262144, pattern_verified=True)
        self.service = dict(q.LIMITS, ActiveState='active', SubState='exited', MainPID='0',
                            Result='success', ExecMainCode='1', ExecMainStatus='0', RemainAfterExit='yes')

    def verify(self, status=0):
        return q.verify_probe(json.dumps(self.paging), self.service, status)

    def test_complete_data_and_enforced_limits_pass(self):
        self.assertEqual(self.verify(), self.paging)

    def test_compressed_ram_alone_or_one_direction_of_disk_io_does_not_pass(self):
        for key in ('swapped_kib', 'read_sectors', 'written_sectors'):
            old = self.paging[key]; self.paging[key] = 0
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.verify()
            self.paging[key] = old

    def test_pattern_corruption_wrong_extent_and_impossible_swap_do_not_pass(self):
        for key, value in (('pattern_verified', False), ('pattern_verified', 1), ('bytes', 4096), ('swapped_kib', 262145)):
            old = self.paging[key]; self.paging[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.verify()
            self.paging[key] = old

    def test_process_swap_may_include_stack_and_allocator_pages(self):
        self.paging['swapped_kib'] = 131080
        self.verify()

    def test_larger_memory_allowance_missing_deadline_or_wrong_kill_mode_fail(self):
        for key in q.LIMITS:
            old = self.service.pop(key)
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.verify()
            self.service[key] = old
        self.service['MemoryMax'] = '268435456'
        with self.assertRaises(RuntimeError): self.verify()

    def test_live_failed_or_unidentified_target_does_not_pass(self):
        for key, value in (('SubState', 'running'), ('MainPID', '12'), ('Result', 'timeout'), ('ExecMainCode', '2'), ('ExecMainStatus', '1')):
            old = self.service[key]; self.service[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.verify()
            self.service[key] = old
        with self.assertRaises(RuntimeError): self.verify(255)


class RuntimePolicy(unittest.TestCase):
    def test_enable_and_stop_post_restore_original_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); parameter = directory/'parameter with space'
            parameter.write_text('N\n')
            enable, restore = q.policy_scripts(directory, parameter)
            subprocess.run(['sh', '-c', enable], check=True)
            self.assertEqual(parameter.read_text(), 'Y')
            subprocess.run(['sh', '-c', restore], check=True)
            self.assertEqual(parameter.read_text(), 'N')
            self.assertEqual((directory/'policy-restored').read_text(), 'restored=N\n')

    def test_refused_start_does_not_revert_someone_elses_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); parameter = directory/'parameter'
            parameter.write_text('Y')
            enable, restore = q.policy_scripts(directory, parameter)
            self.assertNotEqual(subprocess.run(['sh', '-c', enable]).returncode, 0)
            subprocess.run(['sh', '-c', restore], check=True)
            self.assertEqual(parameter.read_text(), 'Y')
            self.assertFalse((directory/'policy-armed').exists())


class Recovery(unittest.TestCase):
    def test_commit_requires_paging_and_policy_cleanup_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = dict(result='passed', factory_restore_qualified=True, swap_active=True,
                reboot_persistence_qualified=True, paging_io_qualified=True,
                swap_io_under_pressure_qualified=True, original_zswap_policy_restored=True)
            for key in result:
                (root/'commit.json').write_text(json.dumps({k:v for k,v in result.items() if k != key}))
                self.assertFalse(q.committed(root))
            (root/'commit.json').write_text(json.dumps(result))
            self.assertTrue(q.committed(root))

    def test_dead_worker_preserves_verified_swap_or_uses_factory_recovery(self):
        for healthy in (True, False):
            with self.subTest(healthy=healthy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); trial = root/'trial'; trial.mkdir(); locks = root/'locks'; locks.mkdir()
                (trial/'emergency-restore').mkdir()
                before = dict(boot_id='original', flashinfo_sha256='a'*64, layout='swap')
                after = dict(before, boot_id='recovered', layout='factory')
                (trial/'before.json').write_text(json.dumps(before))
                (trial/'units.json').write_text(json.dumps(dict(worker='swap-io-1-2')))
                with mock.patch.object(q.f, 'owner_alive', return_value=False), \
                     mock.patch.object(q.f.q.r, 'LOCKS', locks), \
                     mock.patch.object(q.f, 'snapshot', side_effect=[before, before] if healthy else RuntimeError('unhealthy')), \
                     mock.patch.object(q, 'cleanup_target') as cleanup, \
                     mock.patch.object(q.f, 'swap_evidence'), \
                     mock.patch.object(q.f, 'retained', return_value={'proof':'retained'}), \
                     mock.patch.object(q.f, 'run_da', return_value=(0, SimpleNamespace(), None)) as writer, \
                     mock.patch.object(q.f, 'healthy_return', return_value=after), \
                     mock.patch.object(q.f, 'verify_da') as verify, \
                     mock.patch.object(q.f.q.r.qualify, 'check_host_idle'):
                    q.rescue(trial)
                result = json.loads((trial/'rescue-result.json').read_text())
                self.assertEqual(result['result'], 'preserved' if healthy else 'restored')
                self.assertEqual(cleanup.call_count, 1 if healthy else 0)
                self.assertEqual(writer.call_count, 0 if healthy else 1)
                self.assertEqual(verify.call_count, 0 if healthy else 1)


if __name__ == '__main__': unittest.main()
