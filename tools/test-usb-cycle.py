#!/usr/bin/env python3
"""Run real USB guard shell with fake sysfs, networking and reboot calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

spec = importlib.util.spec_from_file_location('watchdog_tests', Path(__file__).with_name('test-linux-watchdog.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
p = fixture.p; m = p.usb_cycle; BOOT = fixture.BOOT
UNIT = 'gemini-usb-cycle-1-2'


class Target(unittest.TestCase):
    def setUp(self):
        f = fixture.ShellGuards(); f.setUp(); self.addCleanup(f.doCleanups)
        self.root = f.root; self.write = f.write
        for name in ('sys/power/suspend_stats', 'sys/class/udc/11271000.usb', 'proc/777'):
            (self.root/name).mkdir(parents=True)
        for name,value in {'pm_test':m.NONE, 'suspend_stats/success':'0', 'suspend_stats/fail':'0'}.items():
            self.write('sys/power/'+name, value+'\n')
        self.write('sys/class/udc/11271000.usb/state', 'configured\n')
        self.write('sys/class/udc/11271000.usb/soft_connect', '')
        self.write('proc/777/stat', '777 (systemd-inhibit) S '+'0 '*18+'2000 0\n')
        self.write('run/expiry/ready', BOOT+'\n')
        self.write('run/expiry/inhibitor-verified', '777 2000\n')
        self.scripts = m.scripts(BOOT, p.SYSTEM, hashlib.sha256(b'kernel-notes').hexdigest(),
            '541', '1000', '/run/'+UNIT,
            dict(proc=str(self.root/'proc'),run=str(self.root/'run'),sys=str(self.root/'sys'),remote=str(self.root/'run/expiry')))
        self.prefix = '''
systemctl() {
 case "$*" in
  'show gemini-watchdog-takeover.service -p MainPID --value') echo 541;;
  'show gemini-watchdog-takeover.service -p Restart --value') echo no;;
  'is-active gemini-watchdog-takeover.service') echo active;;
  "is-active $token-guard"|"is-active $token-fallback") echo active;;
  "show $token-guard -p MainPID --value") echo 777;;
  '--no-block reboot') echo reboot >> "$remote/events";;
  *) return 90;;
 esac
}
sync() { :; }
timeout() { shift 5; "$@"; }
kill() { echo "signal $*" >> "$remote/events"; }
ip() { echo "ip $*" >> "$remote/events"; }
busctl() {
 test "$broken_bus" = no || return 5
 command printf '{"type":"a(ssssuu)","data":[[["sleep","gemini-usb-cycle-1-2","Gemini USB diagnostic recovery guard","block",0,777]]]}\\n'
}
sleep() {
 case "$1" in
  5) command printf '205.00 300.00\\n' > "$proc/uptime";;
 esac
}
printf() {
 case "$1" in
  disconnect) echo disconnect >> "$remote/events"; echo 'not attached' > "$udc/state";;
  connect) echo connect >> "$remote/events"; echo configured > "$udc/state";;
 esac
 command printf "$@"
}
broken_bus=no
'''

    def run_script(self, name='action', extra=''):
        return subprocess.run(['sh','-c',self.prefix+extra+self.scripts[name]],
                              capture_output=True,text=True,timeout=5)

    def events(self):
        file = self.root/'run/expiry/events'
        return file.read_text().splitlines() if file.exists() else []

    def test_cycle_disconnects_reconnects_restores_network_and_keeps_guard(self):
        result = self.run_script()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.events(),['disconnect','connect','ip address replace 10.15.19.82/24 dev usb0','ip link set usb0 up'])
        self.assertTrue((self.root/'run/expiry/armed').exists())
        self.assertTrue((self.root/'run/expiry/finished').exists())
        self.assertFalse((self.root/'run/expiry/acknowledged').exists())
        m.inhibitor((self.root/'run/expiry/inhibitors-during.json').read_text(),UNIT,'777')

    def test_preconditions_reject_wrong_identity_owner_guard_lease_or_pm_selection(self):
        for file,value in (
            ('proc/sys/kernel/random/boot_id','2'*36),('sys/kernel/notes','other'),
            ('run/unattended-recovery.watchdog-owner','542'),
            ('proc/777/stat','777 (systemd-inhibit) S '+'0 '*18+'2001 0\n'),
            ('run/unattended-recovery.lease-deadline','deadline=300'),
            ('run/unattended-recovery.lease-deadline','deadline=1200'),
            ('sys/power/pm_test','none [devices]'),
            ('sys/class/udc/11271000.usb/state','not attached')):
            original=(self.root/file).read_text()
            with self.subTest(file=file,value=value):
                self.write(file,value)
                self.assertNotEqual(self.run_script().returncode,0)
                self.assertEqual(self.events(),[])
                self.assertFalse((self.root/'run/expiry/armed').exists())
            self.write(file,original)

    def test_host_completion_check_with_every_program_staged(self):
        remote=self.root/'run/expiry'
        for name,body in self.scripts.items():(remote/name).write_text(body)
        result=self.run_script()
        self.assertEqual(result.returncode,0,result.stderr)
        (remote/'stdout').write_text(result.stdout)
        (remote/'stderr').write_text(result.stderr)
        command=m.returned_command(BOOT,str(remote),str(self.root/'proc'))
        returned=subprocess.run(['sh','-c',command],capture_output=True,text=True,timeout=5)
        self.assertEqual(returned.returncode,0,returned.stderr)
        self.assertEqual(returned.stdout,result.stdout)
        (remote/'fallback').write_text('fallback=reboot\n')
        rejected=subprocess.run(['sh','-c',command],capture_output=True,text=True,timeout=5)
        self.assertEqual(rejected.returncode,4)
        self.assertEqual(rejected.stdout,result.stdout)

    def test_failure_after_disconnect_still_reconnects_but_never_acknowledges(self):
        result=self.run_script(extra='broken_bus=yes\n')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.events()[:2],['disconnect','connect'])
        self.assertFalse((self.root/'run/expiry/finished').exists())
        self.assertFalse((self.root/'run/expiry/acknowledged').exists())
        self.assertEqual(self.run_script('rescue').returncode,0)
        self.assertEqual(self.events()[-2:],['reboot','signal -STOP 541'])

    def test_cleanup_only_operates_on_owned_lock_same_boot_and_is_idempotent(self):
        lock=self.root/'run/gemini-usb-cycle.lock';lock.mkdir()
        (lock/'owner').write_text('foreign')
        (self.root/'run/expiry/armed').touch()
        self.assertNotEqual(self.run_script('cleanup').returncode,0)
        self.assertEqual(self.events(),[])
        (lock/'owner').write_text(UNIT)
        self.write('proc/sys/kernel/random/boot_id','2'*36)
        self.assertNotEqual(self.run_script('cleanup').returncode,0)
        self.assertEqual(self.events(),[])
        self.write('proc/sys/kernel/random/boot_id',BOOT)
        self.assertEqual(self.run_script('cleanup').returncode,0)
        old=self.events()
        self.assertEqual(self.run_script('cleanup').returncode,0)
        self.assertEqual(self.events(),old)

    def test_recovery_reboots_only_armed_unacknowledged_same_candidate(self):
        self.assertEqual(self.run_script('rescue').returncode,0)
        self.assertEqual(self.events(),[])
        (self.root/'run/expiry/armed').touch()
        self.write('proc/sys/kernel/random/boot_id','2'*36)
        self.assertNotEqual(self.run_script('rescue').returncode,0)
        self.assertEqual(self.events(),[])
        self.write('proc/sys/kernel/random/boot_id',BOOT)
        (self.root/'run/expiry/acknowledged').touch()
        self.assertEqual(self.run_script('rescue').returncode,0)
        self.assertEqual(self.events(),[])
        (self.root/'run/expiry/acknowledged').unlink()
        self.assertEqual(self.run_script('rescue').returncode,0)
        self.assertEqual(self.events(),['reboot','signal -STOP 541'])

    def test_fallback_never_signals_reused_watchdog_pid(self):
        (self.root/'run/expiry/armed').touch()
        self.write('proc/541/stat','541 (watchdog) S '+'0 '*18+'1001 0\n')
        self.assertNotEqual(self.run_script('rescue').returncode,0)
        self.assertEqual(self.events(),['reboot'])

    def test_evidence_requires_actual_usb_outage_new_enumeration_and_no_sleep(self):
        result=self.run_script()
        self.assertEqual(result.returncode,0,result.stderr)
        initial=['1d6b','0104','23']
        events=[dict(monotonic=100,usb=initial),dict(monotonic=103,usb=None),
                dict(monotonic=108.2,usb=['1d6b','0104','24'])]
        self.assertEqual(m.verify(result.stdout,BOOT,'541','1000',events,initial)['host_offline_seconds'],5.2)
        for bad in (events[:1],events[:2],
                    [events[0],events[1],dict(monotonic=108,usb=initial)],
                    [events[0],events[1],dict(monotonic=108,usb=['0e8d','2000','24'])],
                    [events[0],events[1],dict(monotonic=104,usb=['1d6b','0104','24'])]):
            with self.subTest(events=bad),self.assertRaises(RuntimeError):
                m.verify(result.stdout,BOOT,'541','1000',bad,initial)
        with self.assertRaises(RuntimeError):
            m.verify(result.stdout.replace('after_success=0','after_success=1'),BOOT,'541','1000',events,initial)


class Host(unittest.TestCase):
    def test_logind_proof_requires_exact_block_owner_and_reason(self):
        row=['sleep',UNIT,m.WHY,'block',0,777]
        obj=dict(type='a(ssssuu)',data=[[row]])
        self.assertEqual(m.inhibitor(json.dumps(obj),UNIT,'777'),row)
        for i,value in ((0,'shutdown'),(1,'other'),(2,'unrelated'),(3,'delay'),(4,1000),(5,778)):
            bad=copy.deepcopy(obj);bad['data'][0][0][i]=value
            with self.subTest(i=i),self.assertRaises(RuntimeError):m.inhibitor(json.dumps(bad),UNIT,'777')

    def test_cycle_follows_normal_candidate_checks_and_modes_are_exclusive(self):
        order=[]
        r=SimpleNamespace(candidate_return=lambda *a: order.append('normal') or {'boot_id':BOOT})
        with mock.patch.object(m,'run',side_effect=lambda *a:order.append('cycle')):
            m.install(p,r);r.candidate_return('ssh','before','directory','profile')
        self.assertEqual(order,['normal','cycle'])
        for kw in (dict(watchdog=True,cycle=True),dict(pm_test='devices',cycle=True)):
            with self.subTest(kw=kw),self.assertRaises(ValueError):p.configure(**kw)


if __name__=='__main__':unittest.main()
