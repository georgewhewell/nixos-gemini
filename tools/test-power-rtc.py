#!/usr/bin/env python3
"""Check RTC candidate isolation, durable worker routing and failed-proof audit."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('rtc_profile',Path(__file__).with_name('qualify-power-rtc.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Profile(unittest.TestCase):
    def test_rtc_pins_are_isolated_from_qualified_power_swap(self):
        old=m.p.f.q.module('old_power_swap',m.ROOT/'tools/qualify-power-swap.py')
        rtc=m.p.configure();base=old.configure()
        self.assertEqual(set(rtc.PROFILES),{'power-rtc'})
        self.assertEqual(set(base.PROFILES),{'power-swap'})
        self.assertNotEqual(m.p.NOTES_SHA,old.NOTES_SHA)
        self.assertNotEqual(m.p.SYSTEM,old.SYSTEM)
        self.assertEqual((m.p.KERNEL/'kernel.config').read_bytes(),(old.KERNEL/'kernel.config').read_bytes())
        self.assertEqual(m.p.ENTRYPOINT,Path(m.__file__).resolve())
        self.assertEqual(old.ENTRYPOINT,m.ROOT/'tools/qualify-power-swap.py')
        self.assertEqual(set(m.p.EXTRA_EXECUTED_SOURCES),{'tools/qualify-power-rtc.py','tools/qualify-rtc-alarm.py'})

    def test_durable_worker_reenters_the_rtc_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv=['qualify-power-rtc.py','--execute','--out',tmp+'/trial']
            with mock.patch.object(sys,'argv',argv),mock.patch.object(m.p.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                m.p.main()
            command=run.call_args.args[0]
            self.assertIn(str(m.p.ENTRYPOINT),command)
            self.assertIn('--worker',command)
            self.assertTrue(any(v.startswith('--unit=power-rtc-') for v in command))

    def test_pm_requires_new_kernel_prerequisites(self):
        for args in (dict(pm_test='devices'),dict(pm_test='freezer'),dict(cycle=True)):
            with self.subTest(args=args),self.assertRaises(ValueError):m.configure(**args)

    def test_missing_rtc_proof_still_runs_existing_recovery_and_retention_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r=SimpleNamespace(watchdog_expiry_requested=False,qualify=SimpleNamespace(save=mock.Mock()))
            with mock.patch.object(m,'base_finish',side_effect=RuntimeError('failed profile')) as finish:
                with self.assertRaisesRegex(RuntimeError,'failed profile'):m.finish(r,root,'before')
            self.assertIsInstance(finish.call_args.args[-1],FileNotFoundError)
            saved=r.qualify.save.call_args.args[-1]
            self.assertFalse(saved['rtc_alarm_diagnostics_qualified'])


if __name__=='__main__':unittest.main()
