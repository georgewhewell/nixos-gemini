#!/usr/bin/env python3
"""Exercise real trigger guards with fake signals and independent reset proof."""
import hashlib
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
w = p.watchdog_expiry
BOOT = '11111111-1111-1111-1111-111111111111'


class ShellGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('proc/sys/kernel/random','proc/541/fd','run/expiry','sys/kernel','sys/class/watchdog/watchdog0'):
            (self.root/name).mkdir(parents=True, exist_ok=True)
        self.write('proc/sys/kernel/random/boot_id', BOOT)
        self.write('proc/541/stat', '541 (busybox watchdog) S '+'0 '*18+'1000 0\n')
        self.write('proc/uptime', '200.00 300.00\n')
        (self.root/'proc/541/fd/3').symlink_to('/dev/watchdog')
        (self.root/'run/current-system').symlink_to(p.SYSTEM)
        self.write('run/unattended-recovery.watchdog-owner', '541\n')
        self.write('run/unattended-recovery.lease-deadline', 'deadline=720\n')
        self.write('sys/kernel/notes', 'kernel-notes')
        for field,value in dict(identity='mtk-wdt',state='active',timeout='31',nowayout='1').items():
            self.write('sys/class/watchdog/watchdog0/'+field, value)
        self.scripts = w.target_scripts(BOOT,p.SYSTEM,hashlib.sha256(b'kernel-notes').hexdigest(),
            '541','1000','/run/gemini-watchdog-expiry-1-2',
            dict(proc=str(self.root/'proc'),run=str(self.root/'run'),sys=str(self.root/'sys'),remote=str(self.root/'run/expiry')))

    def write(self, path, text): (self.root/path).write_text(text)

    def run_script(self, index=0, extra=''):
        # Shell functions prevent every real signal, delay and reboot. The
        # production guard/control-flow code itself is unmodified.
        prefix = '''
systemctl() {
 case "$*" in
  'show gemini-watchdog-takeover.service -p MainPID --value') echo 541;;
  'show gemini-watchdog-takeover.service -p Restart --value') echo no;;
  'is-active gemini-watchdog-takeover.service') echo active;;
  reboot) echo reboot >> "$remote/events";;
  *) return 90;;
 esac
}
kill() {
 printf '%s %s\n' "$1" "$2" >> "$remote/events"
 case "$1" in
  -STOP) sed -i 's/) S /) T /' "$proc/$owner/stat";;
  -CONT) sed -i 's/) T /) S /' "$proc/$owner/stat";;
  *) return 91;;
 esac
}
sleep() { printf 'sleep %s\n' "$1" >> "$remote/events"; }
sync() { :; }
'''
        return subprocess.run(['sh','-c',prefix+extra+self.scripts[index]],capture_output=True,text=True,timeout=5)

    def events(self):
        path=self.root/'run/expiry/events'
        return path.read_text().splitlines() if path.exists() else []

    def test_failed_expiry_resumes_exact_owner_before_software_reboot(self):
        result=self.run_script(); self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.events(),['-STOP 541','sleep 55','-CONT 541','reboot'])
        raw=(self.root/'run/expiry/stopped').read_text()
        self.assertEqual(w.verify_stopped(raw,BOOT,'541','1000')['owner_state'],'T')

    def test_wrong_boot_kernel_owner_starttime_fd_timeout_or_lease_never_signals(self):
        cases = dict(
            boot=('proc/sys/kernel/random/boot_id','2'*36),
            kernel=('sys/kernel/notes','different kernel'),
            owner=('run/unattended-recovery.watchdog-owner','542'),
            reused_pid=('proc/541/stat','541 (busybox watchdog) S '+'0 '*18+'1001 0\n'),
            timeout=('sys/class/watchdog/watchdog0/timeout','30'),
            lease=('run/unattended-recovery.lease-deadline','deadline=250\n'))
        for name,(path,value) in cases.items():
            original=(self.root/path).read_text()
            with self.subTest(name=name):
                self.write(path,value); result=self.run_script()
                self.assertNotEqual(result.returncode,0); self.assertEqual(self.events(),[])
            self.write(path,original)
        (self.root/'proc/541/fd/3').unlink()
        result=self.run_script(); self.assertNotEqual(result.returncode,0); self.assertEqual(self.events(),[])

    def test_identity_rechecked_after_sync_before_any_signal(self):
        result=self.run_script(extra='sync() { printf changed > "$run/unattended-recovery.watchdog-owner"; }\n')
        self.assertNotEqual(result.returncode,0); self.assertEqual(self.events(),[])

    def test_stop_post_is_noop_before_arming_and_rejects_reused_pid(self):
        self.assertEqual(self.run_script(1).returncode,0); self.assertEqual(self.events(),[])
        (self.root/'run/expiry/armed').touch()
        self.write('proc/541/stat','541 (busybox watchdog) T '+'0 '*18+'1001 0\n')
        self.assertNotEqual(self.run_script(1).returncode,0); self.assertEqual(self.events(),[])
        self.write('proc/541/stat','541 (busybox watchdog) T '+'0 '*18+'1000 0\n')
        self.assertEqual(self.run_script(1).returncode,0); self.assertEqual(self.events(),['-CONT 541'])


class Evidence(unittest.TestCase):
    def test_timing_rejects_early_late_fallback_and_invalid_clocks(self):
        self.assertEqual(w.verify_elapsed(100,101,130),30)
        for times in ((100,101,110),(100,101,155),(100,109,130),(100,99,130),(100,101,float('nan'))):
            with self.subTest(times=times), self.assertRaises(RuntimeError): w.verify_elapsed(*times)

    def test_missing_duplicate_or_wrong_stopped_identity_rejected(self):
        good=f'boot_id={BOOT}\nowner_pid=541\nowner_starttime=1000\nowner_state=T\nstopped_uptime=200.00\n'
        w.verify_stopped(good,BOOT,'541','1000')
        for raw in (good.replace('=T','=S'), good.replace('=541','=542'), good+'owner_state=T\n',good.replace('stopped_uptime=200.00\n','')):
            with self.subTest(raw=raw),self.assertRaises(RuntimeError): w.verify_stopped(raw,BOOT,'541','1000')

    def test_independent_backend_reset_and_no_software_reboot_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); attempt=root/'attempt'; attempt.mkdir()
            trigger=dict(boot_id=BOOT,host_started=100,host_acknowledged=101,owner_state='T',
                         signal='SIGSTOP',fallback_seconds=55,software_reboot_requested=False)
            observed=dict(host_reset=130,expiry_observed=True,software_reboot_requested=False)
            writer=dict(attempt=str(attempt),returncode=0,first_boot_window_departed=True,
                        expected_sha256=p.f.q.r.qualify.ACCEPTED_BOOT)
            def save(name,value): (root/name).write_text(json.dumps(value))
            save('watchdog-trigger.json',trigger);save('watchdog-observation.json',observed)
            save('candidate-linux.json',dict(boot_id=BOOT,system=p.SYSTEM))
            save('supervisor-rollback.state.mtk.json',writer)
            save('attempt/usb-events.json',[dict(monotonic=130.1,usb=['0e8d','2000','123'])])
            self.assertTrue(w.verify_final(p,root)['watchdog_expiry_qualified'])
            save('attempt/usb-events.json',[dict(monotonic=155,usb=['0e8d','2000','123'])])
            with self.assertRaises(RuntimeError): w.verify_final(p,root)
            save('attempt/usb-events.json',[dict(monotonic=133,usb=['0e8d','2000','123'])])
            with self.assertRaises(RuntimeError): w.verify_final(p,root)
            save('attempt/usb-events.json',[dict(monotonic=130.1,usb=['0e8d','2000','123'])])
            save('rescue-reboot-request.json',dict(returncode=0))
            with self.assertRaises(RuntimeError): w.verify_final(p,root)

    def test_trigger_only_follows_complete_candidate_checks(self):
        for failure in (False,True):
            r=SimpleNamespace(candidate_return=mock.Mock(return_value={'boot_id':BOOT},side_effect=RuntimeError('health') if failure else None))
            with mock.patch.object(w,'trigger') as trigger:
                w.install(p,r)
                if failure:
                    with self.assertRaises(RuntimeError): r.candidate_return('ssh','before','directory','profile')
                    trigger.assert_not_called()
                else:
                    self.assertEqual(r.candidate_return('ssh','before','directory','profile'),{'boot_id':BOOT})
                    trigger.assert_called_once_with(p,r,'ssh','directory',{'boot_id':BOOT})


if __name__ == '__main__': unittest.main()
