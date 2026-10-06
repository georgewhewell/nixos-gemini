#!/usr/bin/env python3
"""Exercise diagnostic guards, cleanup and evidence without suspending a host."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('watchdog_tests',Path(__file__).with_name('test-linux-watchdog.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
p=fixture.p; m=p.pm_stages; BOOT=fixture.BOOT


class Target(unittest.TestCase):
    def setUp(self):
        f=fixture.ShellGuards();f.setUp();self.addCleanup(f.doCleanups)
        self.root=f.root;self.write=f.write
        for name in ('sys/power/suspend_stats','sys/module/suspend/parameters'):
            (self.root/name).mkdir(parents=True)
        for name,value in dict(pm_test=m.NONE,state='freeze mem disk',mem_sleep='[s2idle]').items():
            self.write('sys/power/'+name,value+'\n')
        self.write('sys/module/suspend/parameters/pm_test_delay','5\n')
        for name in ('success',)+m.FAILURES: self.write('sys/power/suspend_stats/'+name,'0\n')
        self.paths=dict(proc=str(self.root/'proc'),run=str(self.root/'run'),sys=str(self.root/'sys'),
                        remote=str(self.root/'run/expiry'),kmsg=str(self.root/'kmsg'))
        self.token='gemini-pm-freezer-1-2'
        self.stage='freezer'
        self.action,self.cleanup=m.scripts('freezer',BOOT,p.SYSTEM,hashlib.sha256(b'kernel-notes').hexdigest(),
                                          '541','1000','/run/'+self.token,self.paths)
        self.prefix='''
systemctl() {
 case "$*" in
  'show gemini-watchdog-takeover.service -p MainPID --value') echo 541;;
  'show gemini-watchdog-takeover.service -p Restart --value') echo no;;
  'is-active gemini-watchdog-takeover.service') echo active;;
  *) return 90;;
 esac
}
kill() { return 99; }
sync() { :; }
printf() {
 case "$1" in
  '<6>GEMINI_PM_TEST '*) command printf "$@" >> "$remote/kernel";;
  none) command printf '[none] core processors platform devices freezer\\n'; return;;
  freeze)
   test "${reject_freeze:-no}" = no || return 5
   echo requested >> "$remote/requests"
   command printf '205.00 300.00\\n' > "$proc/uptime"
   command printf '1\\n' > "$sys/power/suspend_stats/success"
   command printf 'PM: suspend entry (s2idle)\\nPM: suspend debug: Waiting for 5 second(s).\\nPM: suspend exit\\n' >> "$remote/kernel"
   ;;
 esac
 if test "$1" = '%s' && test "$2" = "$stage"; then
  case "$stage" in
   freezer) command printf 'none core processors platform devices [freezer]\\n';;
   devices) command printf 'none core processors platform [devices] freezer\\n';;
  esac
  return
 fi
 command printf "$@"
}
'''

    def run_script(self,script=None,extra=''):
        return subprocess.run(['sh','-c',self.prefix+extra+(script or self.action)],capture_output=True,text=True,timeout=5)

    def check(self,result,service=None,diagnostics=None):
        service=service or dict(m.LIMITS,ActiveState='active',SubState='exited',MainPID='0',Result='success',ExecMainCode='1',ExecMainStatus='0')
        return m.verify(result.stdout,service,self.stage,BOOT,'541','1000',
                        diagnostics if diagnostics is not None else (self.root/'run/expiry/kernel').read_text(),self.token)

    def test_success_requires_actual_stage_counters_dwell_cleanup_and_kernel_markers(self):
        result=self.run_script();self.assertEqual(result.returncode,0,result.stderr)
        proof=self.check(result);self.assertEqual(proof['elapsed_seconds'],5)
        self.assertTrue(proof['pm_test_restored']);self.assertFalse(proof['full_suspend_requested'])
        self.assertFalse((self.root/'run/gemini-pm-test.lock').exists())
        self.assertFalse((self.root/'run/expiry/armed').exists())

    def test_wrong_kernel_owner_existing_test_or_lease_never_requests_suspend(self):
        for path,value in (
            ('sys/kernel/notes','wrong'),('run/unattended-recovery.watchdog-owner','542'),
            ('sys/power/pm_test','none [core]'),('sys/module/suspend/parameters/pm_test_delay','30'),
            ('run/unattended-recovery.lease-deadline','deadline=201')):
            original=(self.root/path).read_text()
            with self.subTest(path=path):
                self.write(path,value);self.assertNotEqual(self.run_script().returncode,0)
                self.assertFalse((self.root/'run/expiry/requests').exists())
            self.write(path,original)

    def test_device_stage_selects_and_restores_its_own_setting(self):
        self.stage='devices';self.token='gemini-pm-devices-1-2'
        self.action,self.cleanup=m.scripts(self.stage,BOOT,p.SYSTEM,hashlib.sha256(b'kernel-notes').hexdigest(),
                                          '541','1000','/run/'+self.token,self.paths)
        result=self.run_script();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.check(result)['stage'],'devices')

    def test_request_failure_restores_none_and_releases_only_owned_lock(self):
        result=self.run_script(extra='reject_freeze=yes\n')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.root/'sys/power/pm_test').read_text().strip(),m.NONE)
        self.assertFalse((self.root/'run/gemini-pm-test.lock').exists())
        with self.assertRaises(RuntimeError):self.check(result)

    def test_cleanup_will_not_touch_another_boot_or_lock_owner(self):
        lock=self.root/'run/gemini-pm-test.lock';lock.mkdir()
        (lock/'owner').write_text('foreign')
        (self.root/'run/expiry/armed').touch()
        self.write('sys/power/pm_test','none core processors platform devices [freezer]\n')
        self.assertNotEqual(self.run_script(self.cleanup).returncode,0)
        self.assertEqual((lock/'owner').read_text(),'foreign')
        (lock/'owner').write_text(self.token)
        self.write('proc/sys/kernel/random/boot_id','2'*36)
        self.assertNotEqual(self.run_script(self.cleanup).returncode,0)
        self.assertIn('[freezer]',(self.root/'sys/power/pm_test').read_text())

    def test_false_success_early_return_errors_or_unbounded_service_are_rejected(self):
        result=self.run_script();self.assertEqual(result.returncode,0)
        for before,after in (('after_success=1','after_success=0'),('after_fail=0','after_fail=1'),
                             ('uptime_after=205.00','uptime_after=201.00'),('restored=[none]','restored=none')):
            bad=SimpleNamespace(stdout=result.stdout.replace(before,after))
            with self.subTest(after=after),self.assertRaises(RuntimeError):self.check(bad)
        diagnostics=(self.root/'run/expiry/kernel').read_text()
        for text in (diagnostics+'\nBUG: broken\n',diagnostics.replace('Waiting for 5','Waiting for 0'),
                     diagnostics.replace(' end',' missing')):
            with self.subTest(text=text),self.assertRaises(RuntimeError):self.check(result,diagnostics=text)
        with self.assertRaises(RuntimeError):self.check(result,service={'RuntimeMaxUSec':'infinity'})


class Integration(unittest.TestCase):
    def test_only_stages_before_noirq_are_accepted(self):
        for stage in ('platform','processors','core','none','disk'):
            with self.subTest(stage=stage),self.assertRaises(ValueError):p.configure(pm_test=stage)
        with self.assertRaises(ValueError):p.configure(watchdog=True,pm_test='freezer')

    def test_devices_only_follows_freezer_and_health_failure_stops_sequence(self):
        for fail in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'units.json').write_text(json.dumps({'supervisor':'owned'}))
                state={'boot_id':BOOT}
                r=SimpleNamespace(candidate_return=mock.Mock(return_value=state),wait_state=mock.Mock(),
                    candidate_snapshot=mock.Mock(return_value={'boot_id':'wrong'} if fail else state),
                    qualify=SimpleNamespace(save=mock.Mock()))
                with mock.patch.object(p.f,'owner_alive',return_value=True),mock.patch.object(m,'run_stage',return_value={}) as run:
                    m.install(p,r,'devices')
                    if fail:
                        with self.assertRaises(RuntimeError):r.candidate_return('ssh','before',root,'profile')
                        self.assertEqual([c.args[-1] for c in run.call_args_list],['freezer'])
                    else:
                        r.candidate_return('ssh','before',root,'profile')
                        self.assertEqual([c.args[-1] for c in run.call_args_list],['freezer','devices'])

    def test_final_proof_rejects_missing_device_stage_or_gpu_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'candidate-linux.json').write_text(json.dumps({'boot_id':BOOT}))
            stages=[dict(stage=s,boot_id=BOOT,diagnostic_stage_qualified=True,fresh_gpu_render_qualified=True) for s in m.STAGES]
            proof=dict(boot_id=BOOT,pm_diagnostics_qualified=True,stages=stages)
            dest=root/'pm-stages.json';dest.write_text(json.dumps(proof))
            self.assertTrue(m.verify_final(root,'devices')['pm_diagnostics_qualified'])
            stages[1]['fresh_gpu_render_qualified']=False;dest.write_text(json.dumps(proof))
            with self.assertRaises(RuntimeError):m.verify_final(root,'devices')
            stages.pop();dest.write_text(json.dumps(proof))
            with self.assertRaises(RuntimeError):m.verify_final(root,'devices')


if __name__=='__main__':unittest.main()
