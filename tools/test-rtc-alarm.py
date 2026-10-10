#!/usr/bin/env python3
"""Reject false RTC cancellation, stale timing and incomplete rearm evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('rtc_alarm',Path(__file__).with_name('qualify-rtc-alarm.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BOOT='11111111-1111-1111-1111-111111111111'


class Evidence(unittest.TestCase):
    def test_actual_counter_keeps_parked_cpu_events(self):
        action, _ = m.scripts(BOOT, '/nix/store/'+'a'*32+'-system', 'b'*64,
                              123, 456, 'gemini-rtc-alarm-123-456', 'cancel')
        body = action.split('irq_count() {', 1)[1].split('\n}\n', 1)[0]
        body = 'irq_count() {'+body+'\n}\nirq_count\n'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'irq/77').mkdir(parents=True)
            proc = root/'interrupts'; counts = root/'irq/77/per_cpu_count'
            actions = root/'irq/77/actions'; actions.write_text('mt6397-rtc\n')
            body = body.replace('/proc/interrupts', str(proc)).replace('/sys/kernel/irq', str(root/'irq'))
            def run():
                return subprocess.check_output(['sh', '-e', '-c', body], text=True,
                                               stderr=subprocess.PIPE).strip()
            proc.write_text(' CPU0 CPU9\n77: 1 1 mt6351 mt6397-rtc\n')
            counts.write_text('1,1,0,0,0,0,0,0,0,0\n')
            self.assertEqual(run(), '2')
            proc.write_text(' CPU0\n77: 1 mt6351 mt6397-rtc\n')
            self.assertEqual(run(), '2')
            counts.write_text('1,2,0,0,0,0,0,0,0,0\n')
            self.assertEqual(run(), '3')
            for malformed in ('1,corrupt\n', '1\n2\n', ''):
                counts.write_text(malformed)
                with self.assertRaises(subprocess.CalledProcessError): run()
            counts.write_text('1,2\n'); actions.write_text('foreign\n')
            with self.assertRaises(subprocess.CalledProcessError): run()
            actions.write_text('mt6397-rtc\n')
            proc.write_text('77: 1 mt6397-rtc\n78: 1 mt6397-rtc\n')
            with self.assertRaises(subprocess.CalledProcessError): run()

    def raw(self,mode,delta):
        fields=dict(boot_id=BOOT,mode=mode,alarm='1010',software_alarm_disabled='yes',
            before_irq='4',after_irq=str(4+delta),before_rtc='1000',after_rtc='1013',
            before_uptime='200.0',after_uptime='213.0',before_success='0',after_success='0',before_fail='0',after_fail='0')
        if mode=='cancel':fields['cancel_rtc']='1002'
        return ''.join(k+'='+v+'\n' for k,v in fields.items())

    def service(self):
        return dict(m.LIMITS,ActiveState='active',SubState='exited',MainPID='0',Result='success',ExecMainCode='1',ExecMainStatus='0')

    def test_delivery_and_cancellation_require_different_hardware_interrupt_results(self):
        for mode,good in (('delivery',1),('cancel',0)):
            self.assertEqual(m.verify(self.raw(mode,good),self.service(),BOOT,mode)['result'],'passed')
            # A cancelled software timer can still leave the PMIC alarm armed.
            self.assertEqual(m.verify(self.raw(mode,1-good),self.service(),BOOT,mode)['result'],'failed')

    def test_alarm_must_be_cancelled_before_deadline_and_observed_past_it(self):
        raw=self.raw('cancel',0)
        for old,new in (('cancel_rtc=1002','cancel_rtc=1010'),('after_rtc=1013','after_rtc=1009'),
                        ('after_uptime=213.0','after_uptime=201.0'),('alarm=1010','alarm=1020')):
            with self.subTest(new=new),self.assertRaises(RuntimeError):
                m.verify(raw.replace(old,new),self.service(),BOOT,'cancel')

    def test_other_boot_sleep_or_failed_service_cannot_pass(self):
        raw=self.raw('delivery',1)
        for old,new in (('boot_id='+BOOT,'boot_id='+'2'*36),('after_success=0','after_success=1'),
                        ('after_fail=0','after_fail=1'),('software_alarm_disabled=yes','software_alarm_disabled=no')):
            with self.subTest(new=new),self.assertRaises(RuntimeError):
                m.verify(raw.replace(old,new),self.service(),BOOT,'delivery')
        with self.assertRaises(RuntimeError):m.verify(raw+'mode=delivery\n',self.service(),BOOT,'delivery')
        with self.assertRaises(RuntimeError):m.verify(raw,dict(self.service(),RuntimeMaxUSec='infinity'),BOOT,'delivery')

    def test_final_proof_requires_successful_rearm_after_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'candidate-linux.json').write_text(json.dumps(dict(boot_id=BOOT)))
            stages=[]
            for mode,delta in (('delivery',1),('cancel',0),('delivery',1)):
                stages.append(dict(m.verify(self.raw(mode,delta),self.service(),BOOT,mode),
                    same_boot_health=True,watchdog_owner_unchanged=True))
            proof=dict(boot_id=BOOT,stages=stages,rtc_alarm_diagnostics_qualified=True)
            dest=root/'rtc-stages.json';dest.write_text(json.dumps(proof))
            self.assertTrue(m.verify_final(root)['rtc_alarm_cancellation_qualified'])
            stages[-1]['watchdog_owner_unchanged']=False;dest.write_text(json.dumps(proof))
            with self.assertRaises(RuntimeError):m.verify_final(root)
            stages.pop();dest.write_text(json.dumps(proof))
            with self.assertRaises(RuntimeError):m.verify_final(root)

    def test_failed_stage_or_health_stops_later_alarm_requests(self):
        for fail in ('none','stage','health'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);state=dict(boot_id=BOOT,system='/nix/store/'+'a'*32+'-system')
                owner=dict(owner_pid='541')
                r=SimpleNamespace(candidate_return=mock.Mock(return_value=state),qualify=SimpleNamespace(save=mock.Mock()),
                    persistence=SimpleNamespace(run=mock.Mock(return_value='1000')),
                    candidate_snapshot=mock.Mock(return_value={} if fail=='health' else state))
                p=SimpleNamespace(paging=SimpleNamespace(watchdog=mock.Mock(return_value=owner)),NOTES_SHA='b'*64)
                def result(*args):return dict(result='failed' if fail=='stage' else 'passed')
                with mock.patch.object(m,'run_test',side_effect=result) as run:
                    m.install(p,r)
                    if fail=='none':
                        r.candidate_return('ssh','before',root,'profile')
                        self.assertEqual([c.args[-1] for c in run.call_args_list],['delivery','cancel','delivery'])
                    else:
                        with self.assertRaises(RuntimeError):r.candidate_return('ssh','before',root,'profile')
                        self.assertEqual(run.call_count,1)


if __name__=='__main__':unittest.main()
