#!/usr/bin/env python3
"""Check startup evidence, temporary policy ownership and recovery on failures."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('startup_profile', Path(__file__).with_name('test-boot.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s = m.startup
BOOT = '11111111-1111-1111-1111-111111111111'
NOW = int(datetime(2026, 10, 7, tzinfo=timezone.utc).timestamp())


def raw(values):
    return ''.join(f'{k}={v}\n' for k,v in values.items())


class Startup(unittest.TestCase):
    def good(self):
        return dict(boot_id=BOOT, rtc=NOW+180, system=NOW+180, uptime=181.3, hctosys=1)

    def kernel(self, epoch=NOW, seconds='1.300000'):
        iso = datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
        return f'[    {seconds}] mt6397-rtc mt6351-rtc: setting system clock to {iso} UTC ({epoch})\n'

    def check(self, values=None, kernel=None, **kwargs):
        args = dict(start=NOW+180, end=NOW+180.5, elapsed=.5); args.update(kwargs)
        return s.verify_startup(m.calendar, raw(values or self.good()), kernel or self.kernel(), BOOT,
            dict(retained_utc_verified=True, host_start=NOW-50), **args)

    def test_native_and_early_kernel_clock_agree(self):
        self.assertTrue(self.check()['rtc_startup_qualified'])

    def test_ntp_corrected_system_cannot_hide_wrong_rtc_or_hctosys(self):
        for change in (dict(rtc=NOW+2145916800), dict(hctosys=0), dict(boot_id='wrong'),
                       dict(uptime=300), dict(uptime='nan'), dict(system=NOW), dict(extra='yes')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.check(dict(self.good(), **change))
        for log in (self.kernel(NOW+2145916800), self.kernel()*2, self.kernel(NOW-200),
                    self.kernel(seconds='999.0'), self.kernel().replace('2026-10-07','2026-10-06')):
            with self.subTest(log=log), self.assertRaises(RuntimeError): self.check(kernel=log)
        for change in (dict(end=NOW+190), dict(elapsed=12), dict(start=float('nan'))):
            with self.assertRaises(RuntimeError): self.check(**change)

    def test_legacy_start_requires_current_firmware_utc(self):
        actual = datetime.fromtimestamp(NOW, timezone.utc)
        legacy = int(actual.replace(year=actual.year-68).timestamp())+4039286400
        values = dict(boot_id=BOOT, rtc=legacy, system=NOW)
        proof=s.verify_baseline(m.calendar, raw(values), BOOT, NOW, NOW+.5, .5)
        self.assertEqual(proof['firmware_decoded_utc'], NOW)
        for change in (dict(rtc=3155673600), dict(system=NOW+60), dict(boot_id='bad')):
            with self.assertRaises(RuntimeError):
                s.verify_baseline(m.calendar, raw(dict(values, **change)), BOOT, NOW, NOW+.5, .5)

    def test_runtime_condition_only_after_guards_and_real_skip_verified(self):
        r=m.base_configure(); script=s.policy_script(r, dict(boot_id=BOOT), 'a'*64)
        subprocess.run(['sh','-n'],input=script,text=True,check=True)
        self.assertLess(script.index(r.qualify.ACCEPTED_BOOT), script.index('mkdir '+s.DROP_DIR))
        self.assertLess(script.index('systemctl daemon-reload'),script.index('systemctl start save-hwclock.service'))
        self.assertIn('ConditionResult --value)" = no', script)
        self.assertGreater(script.rindex('ExecMainPID --value)" = 0'),script.index('systemctl start save-hwclock.service'))
        self.assertNotIn('hwclock ',script)
        self.assertNotIn('systemctl mask ',script)
        self.assertIn('trap cleanup_failed_setup EXIT',script)
        self.assertIn('ConditionPathExists=/run/gemini-rtc-startup-'+BOOT+'/allow-save',script)
        with self.assertRaises(ValueError): s.policy('shell; text')

    def test_only_implemented_diagnostics_are_available(self):
        for args in (dict(pm_test='devices'),dict(cycle=True)):
            with self.assertRaises(ValueError): m.configure(**args)

    def test_watchdog_runs_after_startup_and_clock_checks_without_alarm_sequence(self):
        for watchdog in (False,True):
            events=[]
            runner=SimpleNamespace(candidate_return=lambda *a:events.append('health') or {'boot_id':BOOT},
                backend=SimpleNamespace(MTK='old',MTK_RTC='rtc'),watchdog_expiry_requested=False)
            def wrap(label):
                def install(context,r,*args):
                    original=r.candidate_return
                    def check(*a):
                        state=original(*a);events.append(label);return state
                    r.candidate_return=check
                return install
            with mock.patch.object(m,'base_configure',return_value=runner) as base, \
                    mock.patch.object(s,'install_probe',side_effect=wrap('startup')), \
                    mock.patch.object(m.calendar,'install',side_effect=wrap('clock')), \
                    mock.patch.object(m.rtc,'install',side_effect=wrap('alarms')), \
                    mock.patch.object(m.p.watchdog_expiry,'trigger',side_effect=lambda *a:events.append('watchdog')):
                self.assertEqual(m.configure(watchdog=watchdog).candidate_return([],{},Path('/trial'),'profile'),{'boot_id':BOOT})
                base.assert_called_once_with()
            self.assertEqual(events,['health','startup','clock','watchdog' if watchdog else 'alarms'])
            self.assertEqual(runner.watchdog_expiry_requested,watchdog)

    def save(self, directory, name, value):
        (directory/name).write_text(json.dumps(value))

    def test_missing_startup_still_recovers_and_restores_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=SimpleNamespace(qualify=SimpleNamespace(save=self.save))
            self.save(root,'result.json',dict(result='passed',profile_qualified=True))
            with mock.patch.object(m,'calendar_finish',side_effect=RuntimeError('recovery audited')) as finish, \
                    mock.patch.object(s,'cleanup',return_value=dict(runtime_clock_policy_restored=True)) as cleanup:
                with self.assertRaisesRegex(RuntimeError,'recovery audited'): m.finish(runner,root,'before')
            self.assertIsInstance(finish.call_args.args[-1],FileNotFoundError)
            cleanup.assert_called_once()
            result=json.loads((root/'result.json').read_text())
            self.assertFalse(result['profile_qualified'])
            self.assertTrue(result['runtime_clock_policy_restored'])

    def test_policy_cleanup_failure_cannot_leave_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); runner=SimpleNamespace(qualify=SimpleNamespace(save=self.save))
            self.save(root,'result.json',dict(result='passed',profile_qualified=True))
            with mock.patch.object(s,'verify_final'), mock.patch.object(m,'calendar_finish'), \
                    mock.patch.object(s,'cleanup',side_effect=RuntimeError('policy remains')):
                with self.assertRaisesRegex(RuntimeError,'policy remains'): m.finish(runner,root,'before')
            self.assertFalse(json.loads((root/'result.json').read_text())['profile_qualified'])

    def test_probe_must_precede_explicit_clock_write_on_same_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'rtc-startup').mkdir(); (root/'rtc-calendar').mkdir()
            proof=self.check(); self.save(root/'rtc-startup','result.json',proof)
            clock=dict(boot_id=BOOT,host_start=NOW+181,host_end=NOW+185,before_rtc=NOW+181)
            self.save(root/'rtc-calendar','result.json',clock)
            self.assertEqual(s.verify_final(root),proof)
            for change in (dict(boot_id='wrong'),dict(host_start=NOW+170),dict(before_rtc=NOW+999)):
                self.save(root/'rtc-calendar','result.json',dict(clock,**change))
                with self.assertRaises(RuntimeError): s.verify_final(root)

    def test_actual_cleanup_shell_removes_only_owned_policy_on_original_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dropdir=root/'drop-in'; drop=dropdir/'50-gemini-rtc-startup.conf'
            bootfile=root/'boot'; bootfile.write_text(BOOT+'\n')
            current=dict(boot_id=BOOT)
            context=SimpleNamespace(f=SimpleNamespace(q=SimpleNamespace(SSH=[]),snapshot=lambda layout:current))
            def run(ssh, script, directory, name):
                translated=script.replace(s.DROP_DIR,str(dropdir)).replace('/proc/sys/kernel/random/boot_id',str(bootfile))
                translated=translated.replace('systemctl daemon-reload','true')
                return subprocess.check_output(['sh','-c',translated],text=True,stderr=subprocess.PIPE)
            runner=SimpleNamespace(LOCKS=root,qualify=SimpleNamespace(check_host_idle=lambda:None),
                                   persistence=SimpleNamespace(run=run))
            # Unit identity is checked separately; execute the real generated
            # ownership/removal shell against an isolated filesystem fixture.
            with mock.patch.object(s,'unit_guard',return_value=''):
                dropdir.mkdir(); drop.write_text(s.policy(BOOT))
                self.assertTrue(s.cleanup(context,runner,root,dict(boot_id=BOOT))['runtime_clock_policy_restored'])
                self.assertFalse(dropdir.exists())
                dropdir.mkdir(); drop.write_text('foreign policy\n')
                with self.assertRaises(subprocess.CalledProcessError): s.cleanup(context,runner,root,dict(boot_id=BOOT))
                self.assertEqual(drop.read_text(),'foreign policy\n')
                drop.write_text(s.policy(BOOT))
                current['boot_id']='22222222-2222-2222-2222-222222222222';bootfile.write_text(current['boot_id']+'\n')
                with self.assertRaises(subprocess.CalledProcessError): s.cleanup(context,runner,root,dict(boot_id=BOOT))
                self.assertEqual(drop.read_text(),s.policy(BOOT))


if __name__ == '__main__': unittest.main()
