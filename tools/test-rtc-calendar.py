#!/usr/bin/env python3
"""Calendar clock, reboot-decoder, recovery and worker identity regression tests."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('calendar_profile', Path(__file__).with_name('test-boot.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c = m.calendar
BOOT = '11111111-1111-1111-1111-111111111111'
NOW = int(datetime(2026, 10, 7, tzinfo=timezone.utc).timestamp())


class Calendar(unittest.TestCase):
    def good(self):
        values = dict(boot_id=BOOT, before_rtc=1262304000, before_system=NOW,
            after_rtc=NOW, after_system=NOW, tick_rtc=NOW+2, tick_system=NOW+2,
            before_uptime=100, tick_uptime=102.1, alarm_disabled='yes')
        service = dict(c.LIMITS, ActiveState='active', SubState='exited', MainPID='0',
            Result='success', ExecMainCode='1', ExecMainStatus='0')
        return values, service

    def check(self, values, service, **kwargs):
        options = dict(host_start=NOW, host_end=NOW+4, elapsed=4); options.update(kwargs)
        return c.verify(''.join(f'{k}={v}\n' for k,v in values.items()), service, BOOT, **options)

    def test_correct_utc_write_read_tick(self):
        proof = self.check(*self.good())
        self.assertTrue(proof['rtc_utc_write_read_qualified'])
        self.assertFalse(proof['kernel_periodic_rtc_updates'])

    def test_stale_wrong_or_non_ticking_rtc_rejected(self):
        values, service = self.good()
        for change in (dict(after_rtc=1262304000), dict(tick_rtc=NOW), dict(after_system=NOW+100),
                       dict(boot_id='wrong'), dict(alarm_disabled='no'), dict(tick_uptime=101)):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.check(dict(values, **change), service)
        for change in (dict(elapsed=30), dict(host_end=NOW+40), dict(elapsed=float('nan'))):
            with self.subTest(change=change), self.assertRaises(RuntimeError): self.check(values, service, **change)

    def test_failed_or_unbounded_service_rejected(self):
        values, service = self.good()
        for k,v in dict(Result='exit-code', ExecMainStatus='1', MainPID='123', RuntimeMaxUSec='infinity').items():
            with self.subTest(k=k), self.assertRaises(RuntimeError): self.check(values, dict(service, **{k:v}))

    def test_legacy_decoder_uses_calendar_years_after_core_rotation(self):
        for year, month, day in ((2010,1,1),(2026,10,7),(2028,2,29),(2000,2,29),(2038,1,19),(2095,12,31)):
            actual = datetime(year, month, day, 12, 34, 56, tzinfo=timezone.utc)
            old = actual.replace(year=year-68)
            encoded = int(old.timestamp())
            if old < datetime(1968,1,2,tzinfo=timezone.utc): encoded += 4039286400
            with self.subTest(year=year): self.assertEqual(c.decode_m69(encoded), int(actual.timestamp()))
        self.assertEqual(c.decode_m69(int(datetime(2069,12,31,tzinfo=timezone.utc).timestamp())),1262304000)
        with self.assertRaises(ValueError): c.decode_m69(0-10000000000)

    def save(self, directory, name, value):
        (directory/name).write_text(json.dumps(value))

    def test_missing_calendar_proof_still_completes_recovery_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=SimpleNamespace(qualify=SimpleNamespace(save=self.save))
            self.save(root, 'result.json', dict(result='passed', profile_qualified=True))
            with mock.patch.object(m, 'alarm_finish', side_effect=RuntimeError('failed after recovery')) as finish:
                with self.assertRaisesRegex(RuntimeError, 'failed after recovery'): m.calendar_finish(runner, root, 'before')
            self.assertIsInstance(finish.call_args.args[-1], FileNotFoundError)
            result=json.loads((root/'result.json').read_text())
            self.assertFalse(result['profile_qualified'])
            self.assertFalse(result['rtc_reboot_persistence_qualified'])

    def test_reboot_failure_cannot_leave_profile_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=SimpleNamespace(qualify=SimpleNamespace(save=self.save))
            self.save(root, 'result.json', dict(result='passed', profile_qualified=True))
            with mock.patch.object(c, 'verify_candidate', return_value={}), mock.patch.object(m, 'alarm_finish'), \
                    mock.patch.object(m.cache, 'verify_final', return_value={}), \
                    mock.patch.object(c, 'recovered', side_effect=RuntimeError('RTC reset')):
                with self.assertRaisesRegex(RuntimeError, 'RTC reset'): m.calendar_finish(runner, root, 'before')
            result=json.loads((root/'result.json').read_text())
            self.assertEqual(result['result'], 'failed')
            self.assertTrue(result['rtc_utc_write_read_qualified'])
            self.assertFalse(result['rtc_reboot_persistence_qualified'])


if __name__ == '__main__': unittest.main()
