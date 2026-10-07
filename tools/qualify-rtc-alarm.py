#!/usr/bin/env python3
"""Check RTC alarm delivery/cancellation while awake on accepted M69.

Default is read-only. No sleep, clock-setting, USB disconnection or flash
operation is performed. The ten-second alarm uses the RTC's own clock.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('power_swap', ROOT/'tools/qualify-power-swap.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
r = p.f.q.r
NONE = '[none] core processors platform devices freezer'
LIMITS = dict(RuntimeMaxUSec='30s', TimeoutStopUSec='3s', KillMode='control-group', RemainAfterExit='yes')


def scripts(boot, system, notes, pid, stamp, unit, mode):
    if (mode not in ('delivery', 'cancel') or not re.fullmatch('[0-9a-f-]{36}', boot) or
            not re.fullmatch('/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+', system) or
            not re.fullmatch('[0-9a-f]{64}', notes) or
            any(not str(v).isdecimal() or int(v)<2 for v in (pid, stamp)) or
            not re.fullmatch('gemini-rtc-alarm-[0-9]+-[0-9]+', unit)):
        raise ValueError('Unpinned RTC diagnostic')
    common = '#!/bin/sh\nset -eu\n' + '\n'.join(f'{k}={shlex.quote(str(v))}' for k,v in
        dict(boot=boot, system=system, notes=notes, owner=pid, stamp=stamp, token=unit, mode=mode).items()) + '''
remote=/run/$token
rtc=/sys/class/rtc/rtc0
same_boot() {
 test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot" &&
 test "$(readlink /run/current-system)" = "$system" &&
 test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = "$notes"
}
same_owner() {
 same_boot &&
 test "$(cat /run/unattended-recovery.watchdog-owner)" = "$owner" &&
 test "$(systemctl show gemini-watchdog-takeover.service -p MainPID --value)" = "$owner" &&
 test "$(sed 's/.*) //' /proc/$owner/stat | awk '{print $20}')" = "$stamp" &&
 test "$(cat /sys/class/watchdog/watchdog0/state)" = active
}
irq_count() {
 awk '$NF == "mt6397-rtc" {n++; s=0; for(i=2;i<=NF && $i ~ /^[0-9]+$/;i++) s+=$i; print s} END {if(n!=1)exit 1}' /proc/interrupts
}
snapshot() {
 printf '%s_irq=' "$1"; irq_count
 printf '%s_rtc=' "$1"; cat "$rtc/since_epoch"
 printf '%s_uptime=' "$1"; cut -d' ' -f1 /proc/uptime
 printf '%s_success=' "$1"; cat /sys/power/suspend_stats/success
 printf '%s_fail=' "$1"; cat /sys/power/suspend_stats/fail
}
cleanup() {
 test -f "$remote/armed" || return 0
 same_boot || return 1
 test "$(cat /run/gemini-rtc-alarm.lock/owner)" = "$token" || return 1
 current=$(cat "$rtc/wakealarm")
 if test -n "$current"; then
  test "$current" = "$(cat "$remote/alarm")" || return 1
  printf 0 > "$rtc/wakealarm"
 fi
 test -z "$(cat "$rtc/wakealarm")"
 # This proves the software queue is clear, not hardware cancellation.
 # The independent interrupt count after the deadline tests that separately.
 rm /run/gemini-rtc-alarm.lock/owner
 rmdir /run/gemini-rtc-alarm.lock
 rm "$remote/armed"
}
'''
    action = common + '''
same_owner
test "$(cat "$rtc/name")" = 'mt6397-rtc mt6351-rtc'
test "$(cat "$rtc/device/power/wakeup")" = enabled
test -z "$(cat "$rtc/wakealarm")"
test "$(cat /sys/power/pm_test)" = '[none] core processors platform devices freezer'
test "$(cat /sys/class/udc/11271000.usb/state)" = configured
test ! -d /run/gemini-pm-test.lock
test ! -d /run/gemini-usb-cycle.lock
mkdir /run/gemini-rtc-alarm.lock
printf '%s' "$token" > /run/gemini-rtc-alarm.lock/owner
touch "$remote/armed"
trap cleanup EXIT
printf 'boot_id=%s\nmode=%s\n' "$boot" "$mode"
snapshot before
now=$(cat "$rtc/since_epoch")
case "$now" in ''|*[!0-9]*) exit 1;; esac
alarm=$((now + 10))
printf '%s' "$alarm" > "$remote/alarm"
printf '%s' "$alarm" > "$rtc/wakealarm"
test "$(cat "$rtc/wakealarm")" = "$alarm"
printf 'alarm=%s\n' "$alarm"
if test "$mode" = cancel; then
 sleep 2
 printf 'cancel_rtc='; cat "$rtc/since_epoch"
 test "$(cat "$rtc/wakealarm")" = "$alarm"
 printf 0 > "$rtc/wakealarm"
 test -z "$(cat "$rtc/wakealarm")"
 sleep 11
else
 sleep 13
fi
same_owner
snapshot after
test -z "$(cat "$rtc/wakealarm")"
test "$(cat /sys/power/pm_test)" = '[none] core processors platform devices freezer'
cleanup
trap - EXIT
printf 'software_alarm_disabled=yes\n'
'''
    return action, common+'cleanup\n'


def verify(raw, service, boot, mode):
    rows=raw.splitlines(); values=dict(row.split('=',1) for row in rows)
    keys={'boot_id','mode','alarm','software_alarm_disabled'}|{
        prefix+'_'+field for prefix in ('before','after') for field in ('irq','rtc','uptime','success','fail')}
    if mode=='cancel': keys.add('cancel_rtc')
    if (len(rows)!=len(values) or set(values)!=keys or values['boot_id']!=boot or
            values['mode']!=mode or values['software_alarm_disabled']!='yes'):
        raise RuntimeError('RTC identity or completion evidence differs')
    for key in keys-{'boot_id','mode','software_alarm_disabled','before_uptime','after_uptime'}:
        if not values[key].isdigit(): raise RuntimeError('Invalid RTC counter/time')
    elapsed=float(values['after_uptime'])-float(values['before_uptime'])
    alarm=int(values['alarm'])
    if (not 12<=elapsed<=20 or not 10<=alarm-int(values['before_rtc'])<=11 or
            not 2<=int(values['after_rtc'])-alarm<=10 or
            any(values['before_'+k]!=values['after_'+k] for k in ('success','fail')) or
            (mode=='cancel' and not 5<=alarm-int(values['cancel_rtc'])<=9)):
        raise RuntimeError('RTC test timing or no-suspend evidence differs')
    expected=dict(LIMITS, ActiveState='active',SubState='exited',MainPID='0',Result='success',ExecMainCode='1',ExecMainStatus='0')
    if service!=expected: raise RuntimeError('RTC service failed or was not bounded')
    delta=int(values['after_irq'])-int(values['before_irq'])
    return dict(mode=mode,boot_id=boot,elapsed_seconds=round(elapsed,3),irq_delta=delta,
        alarm_delivery_qualified=(mode=='delivery' and delta==1),
        alarm_cancellation_qualified=(mode=='cancel' and delta==0),
        software_alarm_disabled=True,sleep_requested=False,wake_from_suspend_qualified=False,
        result='passed' if delta==(1 if mode=='delivery' else 0) else 'failed')


def run_test(r, ssh, out, before, owner, identity, mode):
    unit='gemini-rtc-alarm-'+str(int(time.time()))+'-'+str(os.getpid());remote='/run/'+unit
    action,cleanup=scripts(before['boot_id'],before['system'],identity['notes'],owner['owner_pid'],identity['stamp'],unit,mode)
    for name,body in (('action',action),('cleanup',cleanup)):
        (out/(name+'.sh')).write_text(body)
        subprocess.run(['sh','-n',str(out/(name+'.sh'))],check=True)
    source=Path(__file__).read_bytes();(out/'executed-source.py').write_bytes(source)
    r.qualify.save(out,'plan.json',dict(mode=mode,execute=True,unit=unit,limits=LIMITS,
        source_sha256=hashlib.sha256(source).hexdigest(),kernel_notes_sha256=identity['notes'],sleep_requested=False))
    transfer=f'set -eu\ntest "$(cat /proc/sys/kernel/random/boot_id)" = {before["boot_id"]}\numask 077\nmkdir {remote}\n'
    for name,body in (('action',action),('cleanup',cleanup)):
        transfer+=f"cat > {remote}/{name} <<'SCRIPT'\n{body}\nSCRIPT\nchmod 0500 {remote}/{name}\n"
    r.persistence.run(ssh,transfer,out,'stage')
    launch=f'''set -eu
systemd-run --quiet --unit={unit} --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=30 --property=TimeoutStopSec=3 --property=KillMode=control-group \\
 --property=RemainAfterExit=yes --property=ExecStopPost={remote}/cleanup \\
 --property=StandardOutput=file:{remote}/stdout --property=StandardError=file:{remote}/stderr {remote}/action
'''
    r.persistence.run(ssh,launch,out,'launch')
    try:
        time.sleep(15)
        raw=r.persistence.run(ssh,f'cat {remote}/stdout; cat {remote}/stderr >&2',out,'output')
        fields=tuple(LIMITS)+('ActiveState','SubState','MainPID','Result','ExecMainCode','ExecMainStatus')
        service=r.persistence.run(ssh,f'systemctl show {unit} '+''.join(' -p '+k for k in fields),out,'service')
        proof=verify(raw,dict(row.split('=',1) for row in service.splitlines()),before['boot_id'],mode)
    finally:
        r.persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {before['boot_id']}
systemctl stop {unit}
test "$(systemctl show {unit} -p MainPID --value)" = 0
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
test ! -d /run/gemini-rtc-alarm.lock
''',out,'stop')
    if Path(__file__).read_bytes()!=source: raise RuntimeError('Executed RTC source changed')
    return proof


def install(context, runner):
    original=runner.candidate_return
    def candidate_return(ssh,before,directory,profile):
        state=original(ssh,before,directory,profile)
        results=[]
        for label,mode in (('delivery-before','delivery'),('cancel','cancel'),('delivery-after','delivery')):
            out=directory/('rtc-'+label);out.mkdir(mode=0o700)
            owner=context.paging.watchdog(out,state,'watchdog-before')
            stamp=runner.persistence.run(ssh,
                f"sed 's/.*) //' /proc/{int(owner['owner_pid'])}/stat | awk '{{print $20}}'",out,'owner-starttime').strip()
            result=run_test(runner,ssh,out,state,owner,dict(notes=context.NOTES_SHA,stamp=stamp),mode)
            if (runner.candidate_snapshot(ssh,before,profile)!=state or
                    context.paging.watchdog(out,state,'watchdog-after')!=owner):
                raise RuntimeError('Candidate health or watchdog changed across RTC diagnostic')
            result.update(same_boot_health=True,watchdog_owner_unchanged=True)
            runner.qualify.save(out,'result.json',result)
            if result['result']!='passed': raise RuntimeError('RTC alarm '+label+' failed its interrupt-count check')
            results.append(result)
            print('RTC alarm diagnostic passed: '+label,flush=True)
        runner.qualify.save(directory,'rtc-stages.json',dict(boot_id=state['boot_id'],stages=results,
            rtc_alarm_diagnostics_qualified=True,sleep_requested=False,wake_from_suspend_qualified=False))
        return state
    runner.candidate_return=candidate_return


def verify_final(directory):
    proof=json.loads((directory/'rtc-stages.json').read_text())
    candidate=json.loads((directory/'candidate-linux.json').read_text())
    if (proof.get('boot_id')!=candidate['boot_id'] or proof.get('rtc_alarm_diagnostics_qualified') is not True or
            [s.get('mode') for s in proof.get('stages',[])]!=['delivery','cancel','delivery']):
        raise RuntimeError('Missing complete RTC alarm sequence')
    for stage,delta in zip(proof['stages'],(1,0,1)):
        if (stage.get('boot_id')!=candidate['boot_id'] or stage.get('result')!='passed' or stage.get('irq_delta')!=delta or
                any(stage.get(k) is not True for k in ('same_boot_health','watchdog_owner_unchanged','software_alarm_disabled')) or
                stage.get('sleep_requested') is not False):
            raise RuntimeError('Incomplete RTC alarm and post-stage health evidence')
    return dict(rtc_alarm_diagnostics_qualified=True,rtc_alarm_delivery_qualified=True,
        rtc_alarm_cancellation_qualified=True,sleep_requested=False,wake_from_suspend_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=('delivery','cancel'),required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();out=args.out.resolve();os.umask(0o077)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock','.p22-flash-writer.lock'):
            handle=locks.enter_context((r.LOCKS/name).open('a'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        r.qualify.check_host_idle();before=p.f.snapshot('swap');out.mkdir(mode=0o700)
        r.qualify.save(out,'before.json',before)
        owner=p.paging.watchdog(out,before,'watchdog-before')
        baseline=r.persistence.run(p.f.q.SSH,'''set -eu
printf 'notes='; sha256sum /sys/kernel/notes | cut -d' ' -f1
owner=$(cat /run/unattended-recovery.watchdog-owner)
printf 'stamp='; sed 's/.*) //' /proc/$owner/stat | awk '{print $20}'
test "$(cat /sys/class/rtc/rtc0/name)" = 'mt6397-rtc mt6351-rtc'
test "$(cat /sys/class/rtc/rtc0/device/power/wakeup)" = enabled
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
cat /proc/driver/rtc >&2
''',out,'baseline')
        identity=dict(line.split('=',1) for line in baseline.splitlines())
        if not args.execute:
            r.qualify.save(out,'preflight.json',dict(mode=args.mode,execute=False,kernel_notes_sha256=identity['notes']))
            print('RTC preflight passed; no alarm or clock writes');return
        proof=run_test(r,p.f.q.SSH,out,before,owner,identity,args.mode)
        after=p.f.snapshot('swap');after_owner=p.paging.watchdog(out,after,'watchdog-after')
        if after!=before or after_owner!=owner: raise RuntimeError('Device or watchdog changed during RTC trial')
        r.qualify.check_host_idle()
        proof.update(same_boot_health=True,watchdog_owner_unchanged=True,no_writer=True)
        r.qualify.save(out,'result.json',proof)
        print(json.dumps(proof,indent=2))
        if proof['result']!='passed': raise SystemExit(1)


if __name__=='__main__':main()
