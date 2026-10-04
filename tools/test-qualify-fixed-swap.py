#!/usr/bin/env python3
"""Verify transition evidence, explicit layout guards and rescue commit rules."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('qualification',Path(__file__).with_name('qualify-fixed-swap.py'))
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
fixture=q.q.module('swap_fixture',q.ROOT/'nix/test-mtk-fixed-swap.py')


class Evidence(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.Transition('test_install_header_before_publishing_gpt_and_preserve_data_superblock')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.directory=self.fixture.directory
        ok,self.result=self.fixture.run_transition();self.assertTrue(ok)
        self.before=dict(flashinfo_sha256=self.result['protected_before']['flashinfo'])
        self.window=SimpleNamespace(complete=True,acknowledged=True)

    def save(self):
        (self.directory/'swap-result.json').write_text(json.dumps(self.result))
        (self.directory/'swap-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in self.result['events']))

    def verify(self,rc=0):return q.verify_da(self.directory,self.before,'swap',rc,self.window)

    def test_real_transaction_passes_full_independent_chronology(self):
        self.verify();self.assertEqual(len(self.result['events']),28)

    def test_false_flags_missing_usb_and_failure_exit_are_rejected(self):
        for key in ('operation_qualified','write_attempted','reboot_acknowledged'):
            old=self.result[key];self.result[key]=False;self.save()
            with self.assertRaises(RuntimeError):self.verify()
            self.result[key]=old;self.save()
        with self.assertRaises(RuntimeError):self.verify(1)
        self.window.complete=False
        with self.assertRaises(RuntimeError):self.verify()

    def test_missing_readback_reordered_writes_and_wrong_bounds_fail(self):
        original=copy.deepcopy(self.result)
        for change in ('missing','reordered','offset','layout'):
            self.result=copy.deepcopy(original);events=self.result['events']
            if change=='missing':events.pop(11)
            elif change=='reordered':events[9:15]=events[12:15]+events[9:12]
            elif change=='offset':events[9]['offset']+=512
            else:events[9]['layout']='factory'
            self.save()
            with self.subTest(change=change),self.assertRaises(RuntimeError):self.verify()

    def test_changed_host_readbacks_cannot_hide_behind_success_json(self):
        for name in ('primary-after.bin','header-after.bin','superblock-after.bin'):
            path=self.directory/name;raw=path.read_bytes();path.write_bytes(b'!'+raw[1:])
            with self.subTest(name=name),self.assertRaises(RuntimeError):self.verify()
            path.write_bytes(raw)

    def test_changed_protected_data_or_admission_is_rejected(self):
        original=copy.deepcopy(self.result)
        for change in ('protected','admission','journal'):
            self.result=copy.deepcopy(original)
            if change=='protected':self.result['protected_after']['flashinfo']='0'*64
            if change=='admission':self.result['events'][8]['target']='factory'
            self.save()
            if change=='journal':(self.directory/'swap-events.jsonl').write_text('')
            with self.assertRaises(RuntimeError):self.verify()


class Guards(unittest.TestCase):
    def test_factory_and_swap_guards_are_explicit_and_unknown_layout_fails(self):
        self.assertIn('= 32737247',q.script('factory'));self.assertIn('test ! -e /sys/class/block/mmcblk0p34',q.script('factory'))
        swap=q.script('swap');self.assertIn('= 22249472',swap);self.assertIn('= 10485760',swap)
        self.assertIn(q.PARTUUID,swap);self.assertNotIn('= 32737247',swap)
        self.assertNotIn("grep -qx 'unattended_recovery=healthy'",q.script('factory',False))
        self.assertIn('healthy=unchecked',q.script('factory',False))
        with self.assertRaises(ValueError):q.script('unknown')

    def test_service_status_errors_are_not_owner_death(self):
        for state,alive in (('active',True),('activating',True),('deactivating',True),('inactive',False),('failed',False)):
            with mock.patch.object(q.q.r.qualify,'run',return_value=state):self.assertEqual(q.owner_alive('unit'),alive)
        with mock.patch.object(q.q.r.qualify,'run',return_value='unrecognized'),self.assertRaises(RuntimeError):q.owner_alive('unit')

    def test_only_a_complete_commit_disarms_independent_rescue(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.assertFalse(q.committed(directory))
            result=dict(result='passed',factory_restore_qualified=True,swap_active=True,reboot_persistence_qualified=True)
            for key in result:
                (directory/'commit.json').write_text(json.dumps({k:v for k,v in result.items() if k!=key}))
                self.assertFalse(q.committed(directory))
            (directory/'commit.json').write_text(json.dumps(result));self.assertTrue(q.committed(directory))
            (directory/'commit.json').write_text('{');self.assertFalse(q.committed(directory))

    def test_swap_check_requires_exact_active_partition_and_page_size(self):
        state=dict(boot_id='11111111-1111-1111-1111-111111111111')
        valid=f'blkid=/dev/mmcblk0p34: LABEL="gemini-swap" UUID="{q.SWAP_UUID}" TYPE="swap"\npage_kib=4\nFilename Type Size Used Priority\n/dev/mmcblk0p34 partition 5242876 0 -2\n'
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(q.q.r.persistence,'run',return_value=valid):
            self.assertTrue(q.swap_evidence(Path(tmp),state)['active'])
        for wrong in (valid.replace('5242876','5242880'),valid.replace('page_kib=4','page_kib=16'),valid.replace('mmcblk0p34','mmcblk0p32'),valid.replace(q.SWAP_UUID,'foreign'),valid+'extra\n'):
            with tempfile.TemporaryDirectory() as tmp,mock.patch.object(q.q.r.persistence,'run',return_value=wrong),self.assertRaises(RuntimeError):q.swap_evidence(Path(tmp),state)

    def test_rescue_after_owner_death_restores_once_or_verifies_existing_factory(self):
        for factory_present in (False,True):
            with self.subTest(factory_present=factory_present),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);directory=root/'trial';directory.mkdir();(directory/'emergency-restore').mkdir()
                locks=root/'locks';locks.mkdir()
                (directory/'units.json').write_text(json.dumps(dict(worker='dead-owner')))
                before=dict(boot_id='original',flashinfo_sha256='a'*64)
                after=dict(before,boot_id='recovered',layout='factory')
                (directory/'before.json').write_text(json.dumps(before))
                with mock.patch.object(q,'owner_alive',return_value=False),mock.patch.object(q.q.r,'LOCKS',locks), \
                     mock.patch.object(q,'snapshot',side_effect=[after,after] if factory_present else RuntimeError('swap layout')), \
                     mock.patch.object(q,'run_da',return_value=(0,SimpleNamespace(),None)) as writer, \
                     mock.patch.object(q,'healthy_return',return_value=after),mock.patch.object(q,'verify_da') as verify, \
                     mock.patch.object(q,'retained',return_value={'proof':'retained'}),mock.patch.object(q.q.r.qualify,'check_host_idle'):
                    q.rescue(directory)
                result=json.loads((directory/'rescue-result.json').read_text())
                self.assertEqual(result['result'],'restored');self.assertEqual(result['healthy_boot'],'recovered')
                self.assertEqual(writer.call_count,0 if factory_present else 1)
                self.assertEqual(verify.call_count,0 if factory_present else 1)
                if not factory_present:self.assertIs(writer.call_args.kwargs['restore'],True)


if __name__=='__main__':unittest.main()
