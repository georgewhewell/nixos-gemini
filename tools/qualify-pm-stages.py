#!/usr/bin/env python3
"""Bounded freezer/device diagnostics before the watchdog's noirq stop."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import time
from types import SimpleNamespace

STAGES = ('freezer', 'devices', 's2idle')
# Stages that suspend the USB gadget and so run detached behind the USB guard.
DETACHED = ('devices', 's2idle')
FAILURES = ('fail','failed_freeze','failed_prepare','failed_suspend','failed_suspend_late',
            'failed_suspend_noirq','failed_resume','failed_resume_early','failed_resume_noirq')
NONE = '[none] core processors platform devices freezer'
LIMITS = dict(RuntimeMaxUSec='40s', TimeoutStopUSec='3s', KillMode='control-group', RemainAfterExit='yes')


def qualified_trial(p, flag):
    """Newest supervised trial of exactly this system and kernel with `flag` qualified."""
    candidates = sorted((p.ROOT.parent/'handoff').glob('*/result.json'), key=lambda x: x.stat().st_mtime, reverse=True)
    for path in candidates:
        prior = path.parent
        try:
            result = json.loads(path.read_text())
            candidate = json.loads((prior/'candidate-linux.json').read_text())
            power = json.loads((prior/'power-swap-evidence.json').read_text())
            plan = json.loads((prior/'plan.json').read_text())
        except (OSError, ValueError):
            continue
        if (result.get('result') != 'passed' or any(result.get(k) is not True for k in
                ('profile_qualified', flag, 'fixed_swap_preserved', 'no_writer')) or
                candidate.get('system') != p.SYSTEM or candidate.get('boot_sha256') != p.BOOT_SHA or
                power.get('notes_sha256') != p.NOTES_SHA):
            continue
        for name, sha in plan['all_executed_sources_sha256'].items():
            if hashlib.sha256((prior/'executed-sources'/Path(name).name).read_bytes()).hexdigest() != sha:
                raise RuntimeError('Prior trial source archive changed: '+str(prior))
        return prior
    return None


def prerequisites(p):
    prior = qualified_trial(p, 'watchdog_expiry_qualified')
    if prior is None:
        raise RuntimeError('Selected kernel lacks qualified Linux watchdog recovery')
    return dict(watchdog_trial=str(prior),
                watchdog_result_sha256=hashlib.sha256((prior/'result.json').read_bytes()).hexdigest())


def scripts(stage, boot, system, notes, pid, stamp, remote, paths=None):
    if (stage not in STAGES or not re.fullmatch('[0-9a-f-]{36}',boot) or
            not re.fullmatch('/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+',system) or
            not re.fullmatch('[0-9a-f]{64}',notes) or
            any(not str(v).isdecimal() or int(v)<2 for v in (pid,stamp)) or
            not re.fullmatch('/run/gemini-pm-(freezer|devices|s2idle)-[0-9]+-[0-9]+',remote)):
        raise ValueError('Invalid PM stage or candidate identity')
    paths = paths or dict(proc='/proc',run='/run',sys='/sys',remote=remote,kmsg='/dev/kmsg')
    common = '#!/bin/sh\nset -eu\n'+'\n'.join(f'{k}={shlex.quote(str(v))}' for k,v in dict(paths,
        boot=boot,system=system,notes=notes,owner=pid,stamp=stamp,stage=stage,token=Path(remote).name).items())+'''
same_boot() {
 test "$(cat "$proc/sys/kernel/random/boot_id")" = "$boot" &&
 test "$(readlink "$run/current-system")" = "$system" &&
 test "$(sha256sum "$sys/kernel/notes" | cut -d' ' -f1)" = "$notes"
}
same_owner() {
 same_boot &&
 test "$(cat "$run/unattended-recovery.watchdog-owner")" = "$owner" &&
 test "$(systemctl show gemini-watchdog-takeover.service -p MainPID --value)" = "$owner" &&
 test "$(sed 's/.*) //' "$proc/$owner/stat" | awk '{print $20}')" = "$stamp"
}
cleanup() {
 test -f "$remote/armed" || return 0
 same_boot || return 1
 test "$(cat "$run/gemini-pm-test.lock/owner")" = "$token"
 current=$(cat "$sys/power/pm_test")
 case "$current" in
  *"[$stage]"*) printf none > "$sys/power/pm_test";;
  *'[none]'*) :;;
  *) return 1;;
 esac
 grep -Fq '[none]' "$sys/power/pm_test"
 if test "$stage" = s2idle; then printf 0 > "$sys/class/rtc/rtc0/wakealarm"; fi
 rm "$run/gemini-pm-test.lock/owner"
 rmdir "$run/gemini-pm-test.lock"
 rm "$remote/armed"
}
'''
    cleanup = common+'cleanup\n'
    action = common+'''
same_owner
test "$(systemctl is-active gemini-watchdog-takeover.service)" = active
test "$(systemctl show gemini-watchdog-takeover.service -p Restart --value)" = no
for pair in identity:mtk-wdt state:active timeout:31 nowayout:1; do
 field=${pair%:*}; value=${pair#*:}
 test "$(cat "$sys/class/watchdog/watchdog0/$field")" = "$value"
done
owned=no
for fd in "$proc/$owner/fd/"*; do
 case "$(readlink "$fd" || true)" in /dev/watchdog|/dev/watchdog0) owned=yes;; esac
done
test "$owned" = yes
test "$(cat "$sys/power/pm_test")" = '[none] core processors platform devices freezer'
test "$(cat "$sys/module/suspend/parameters/pm_test_delay")" = 5
test "$(cat "$sys/power/mem_sleep")" = '[s2idle]'
grep -qw freeze "$sys/power/state"
test ! -e "$run/unattended-recovery.lease-expired"
deadline=$(sed -n 's/^deadline=//p' "$run/unattended-recovery.lease-deadline")
uptime=$(awk '{sub(/\\..*/,"",$1); print $1}' "$proc/uptime")
case "$deadline:$uptime" in *[!0-9:]*|:*|*:) exit 1;; esac
test "$deadline" -gt "$((uptime + 120))"
sync
same_owner
mkdir "$run/gemini-pm-test.lock"
printf '%s' "$token" > "$run/gemini-pm-test.lock/owner"
touch "$remote/armed"
trap cleanup EXIT
printf 'boot_id=%s\nstage=%s\nowner_pid=%s\nowner_starttime=%s\n' "$boot" "$stage" "$owner" "$stamp"
printf 'uptime_before='; cut -d' ' -f1 "$proc/uptime"
''' + '\n'.join(f'printf "before_{field}="; cat "$sys/power/suspend_stats/{field}"' for field in ('success',)+FAILURES)+'''
printf '<6>GEMINI_PM_TEST %s begin\n' "$token" > "$kmsg"
if test "$stage" = s2idle; then
 # A real s2idle sleep, woken by the RTC alarm well inside the watchdog's
 # 31 s budget (mtk_wdt.suspend_keep_running keeps it counting).
 test "$(cat "$sys/module/mtk_wdt/parameters/suspend_keep_running")" = Y
 test -z "$(cat "$sys/class/rtc/rtc0/wakealarm")"
 printf '+10' > "$sys/class/rtc/rtc0/wakealarm"
else
 printf '%s' "$stage" > "$sys/power/pm_test"
 grep -Fq "[$stage]" "$sys/power/pm_test"
fi
printf freeze > "$sys/power/state"
printf 'uptime_after='; cut -d' ' -f1 "$proc/uptime"
''' + '\n'.join(f'printf "after_{field}="; cat "$sys/power/suspend_stats/{field}"' for field in ('success',)+FAILURES)+'''
same_owner
test "$(cat "$sys/class/watchdog/watchdog0/state")" = active
cleanup
trap - EXIT
printf 'restored='; cat "$sys/power/pm_test"
printf '<6>GEMINI_PM_TEST %s end\n' "$token" > "$kmsg"
'''
    return action, cleanup


def verify(raw, service, stage, boot, pid, stamp, diagnostics, token, limits=None):
    rows=raw.splitlines(); values=dict(row.split('=',1) for row in rows)
    expected=dict(boot_id=boot,stage=stage,owner_pid=pid,owner_starttime=stamp,restored=NONE)
    keys=set(expected)|{'uptime_before','uptime_after'}|{prefix+'_'+name for prefix in ('before','after') for name in ('success',)+FAILURES}
    if len(rows)!=len(values) or set(values)!=keys or any(values[k]!=v for k,v in expected.items()):
        raise RuntimeError('PM stage identity, ownership or policy restoration differs')
    if any(not re.fullmatch('[0-9]+\\.[0-9]+',values[k]) for k in ('uptime_before','uptime_after')):
        raise RuntimeError('Invalid PM stage clock evidence')
    elapsed=float(values['uptime_after'])-float(values['uptime_before'])
    # CLOCK_BOOTTIME-based uptime includes the sleep itself.
    if not (8<=elapsed<=25 if stage=='s2idle' else 4.5<=elapsed<=20):
        raise RuntimeError('PM stage dwell outside its bound')
    for prefix in ('before','after'):
        for name in ('success',)+FAILURES:
            if not values[prefix+'_'+name].isdigit(): raise RuntimeError('Invalid PM counter')
    if (int(values['after_success'])!=int(values['before_success'])+1 or
            any(values['before_'+name]!=values['after_'+name] for name in FAILURES)):
        raise RuntimeError('PM diagnostic did not complete without suspend/resume failures')
    required=dict(limits or LIMITS,ActiveState='active',SubState='exited',MainPID='0',Result='success',ExecMainCode='1',ExecMainStatus='0')
    if any(service.get(k)!=v for k,v in required.items()): raise RuntimeError('PM service failed or is not bounded')
    begin='GEMINI_PM_TEST '+token+' begin'; end='GEMINI_PM_TEST '+token+' end'
    if diagnostics.count(begin)!=1 or diagnostics.count(end)!=1 or diagnostics.index(begin)>=diagnostics.index(end):
        raise RuntimeError('Missing bounded kernel diagnostic markers')
    scoped=diagnostics.split(begin,1)[1]
    if (scoped.count('suspend debug: Waiting for 5 second(s).')!=(0 if stage=='s2idle' else 1) or
            'PM: suspend entry (s2idle)' not in scoped or 'PM: suspend exit' not in scoped or
            re.search(r'\bBUG:|\bOops:|Kernel panic|I/O error|Call trace:|failed to (?:suspend|resume)',scoped,re.I)):
        raise RuntimeError('Kernel diagnostics do not establish clean PM test execution')
    return dict(stage=stage,boot_id=boot,owner_pid=pid,owner_starttime=stamp,
        elapsed_seconds=round(elapsed,3),success_delta=1,failures_delta=0,pm_test_restored=True,
        full_suspend_requested=stage=='s2idle',diagnostic_stage_qualified=True)


def run_stage(p,r,ssh,directory,state,stage):
    if stage in DETACHED:
        return run_detached_stage(p,r,ssh,directory,state,stage)
    out=directory/('pm-'+stage); out.mkdir(mode=0o700)
    owner=p.paging.watchdog(out,state,'watchdog-before'); pid=owner['owner_pid']
    stamp=r.persistence.run(ssh,f"sed 's/.*) //' /proc/{int(pid)}/stat | awk '{{print $20}}'",out,'owner-starttime').strip()
    unit='gemini-pm-'+stage+'-'+str(int(time.time()))+'-'+str(os.getpid()); remote='/run/'+unit
    action,cleanup=scripts(stage,state['boot_id'],p.SYSTEM,p.NOTES_SHA,pid,stamp,remote)
    command=f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
umask 077
mkdir {remote}
cat > {remote}/test <<'ACTION'
{action}
ACTION
cat > {remote}/cleanup <<'CLEANUP'
{cleanup}
CLEANUP
chmod 0500 {remote}/test {remote}/cleanup
systemd-run --quiet --unit={unit} --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=40 --property=TimeoutStopSec=3 --property=KillMode=control-group \\
 --property=RemainAfterExit=yes --property=ExecStopPost={remote}/cleanup \\
 --property=StandardOutput=file:{remote}/stdout --property=StandardError=file:{remote}/stderr {remote}/test
'''
    r.persistence.run(ssh,command,out,'launch',timeout=25)
    print('Running bounded PM diagnostic: '+stage,flush=True)
    deadline=time.monotonic()+50
    while time.monotonic()<deadline:
        raw=r.persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
systemctl show {unit} -p ActiveState -p SubState -p MainPID -p Result -p ExecMainCode -p ExecMainStatus \\
 -p RuntimeMaxUSec -p TimeoutStopUSec -p KillMode -p RemainAfterExit
''',out,'service',timeout=20)
        service=dict(row.split('=',1) for row in raw.splitlines())
        if service.get('SubState') in ('exited','dead','failed'): break
        time.sleep(0.5)
    else: raise RuntimeError('PM target service did not terminate; independent rescue remains armed')
    r.qualify.save(out,'service.json',service)
    raw=r.persistence.run(ssh,f'cat {remote}/stdout',out,'output')
    r.persistence.run(ssh,f'cat {remote}/stderr',out,'errors')
    diagnostics=r.persistence.run(ssh,'dmesg',out,'kernel')
    result=verify(raw,service,stage,state['boot_id'],pid,stamp,diagnostics,unit)
    r.persistence.run(ssh,f'''set -eu
systemctl stop {unit}
test "$(cat /sys/power/pm_test)" = '{NONE}'
test ! -d /run/gemini-pm-test.lock
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
''',out,'stop')
    after=p.paging.watchdog(out,state,'watchdog-after')
    if after!=owner: raise RuntimeError('Watchdog ownership changed across PM stage')
    render(r,ssh,out,state['boot_id'])
    result['fresh_gpu_render_qualified']=True
    r.qualify.save(out,'result.json',result)
    print('PM diagnostic passed with watchdog ownership and fresh GPU render: '+stage,flush=True)
    return result


def render(r,ssh,out,boot):
    rendered=r.persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}
gpu=/sys/bus/platform/devices/13040000.gpu
test "$(basename "$(readlink -f "$gpu/driver")")" = panfrost
set -- "$gpu"/drm/renderD*
test "$#" -eq 1
timeout -s TERM -k 3 20 /etc/gemini/gpu-render /dev/dri/$(basename "$1")
''',out,'gpu-after',timeout=30)
    if 'GPU_RENDER_PASS backend=panfrost draws=2 pixels=8192' not in rendered.splitlines():
        raise RuntimeError('Fresh GPU rendering after PM stage did not verify')


def run_detached_stage(p,r,ssh,directory,state,stage='devices'):
    out=directory/('pm-'+stage); out.mkdir(mode=0o700)
    proof=p.usb_cycle.run(p,r,ssh,directory,state,pm=SimpleNamespace(scripts=scripts,verify=verify),stage=stage)
    result=dict(proof['pm_diagnostic'],usb_disconnected=True,usb_guard_qualified=True)
    r.persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(cat /sys/power/pm_test)" = '{NONE}'
test ! -d /run/gemini-pm-test.lock
test ! -d /run/gemini-usb-cycle.lock
''',out,'cleanup-verified')
    render(r,ssh,out,state['boot_id'])
    result['fresh_gpu_render_qualified']=True
    r.qualify.save(out,'result.json',result)
    print('Detached PM stage passed with fresh GPU render: '+stage,flush=True)
    return result


def install(p,r,last_stage):
    if last_stage not in STAGES: raise ValueError('Unsupported PM diagnostic stage')
    original=r.candidate_return
    def candidate_return(ssh,before,directory,profile):
        state=original(ssh,before,directory,profile)
        units=json.loads((directory/'units.json').read_text())
        if not p.f.owner_alive(units['supervisor']): raise RuntimeError('PM test lacks active recovery supervisor')
        r.wait_state(directory/'supervisor-rollback.state','tool_started ',30,terminal=False)
        results=[]
        for stage in STAGES[:STAGES.index(last_stage)+1]:
            results.append(run_stage(p,r,ssh,directory,state,stage))
            if r.candidate_snapshot(ssh,before,profile)!=state:
                raise RuntimeError('Candidate health or protected storage changed across PM stage')
        r.qualify.save(directory,'pm-stages.json',dict(boot_id=state['boot_id'],stages=results,
            pm_diagnostics_qualified=True,full_suspend_requested=last_stage=='s2idle',hibernation_io_qualified=False))
        return state
    r.candidate_return=candidate_return


def verify_final(directory,last_stage):
    proof=json.loads((directory/'pm-stages.json').read_text())
    candidate=json.loads((directory/'candidate-linux.json').read_text())
    if (proof.get('boot_id')!=candidate['boot_id'] or proof.get('pm_diagnostics_qualified') is not True or
            [s['stage'] for s in proof['stages']]!=list(STAGES[:STAGES.index(last_stage)+1]) or
            any(s.get('diagnostic_stage_qualified') is not True or s.get('fresh_gpu_render_qualified') is not True
                or s.get('boot_id')!=candidate['boot_id'] for s in proof['stages'])):
        raise RuntimeError('Missing complete PM stage and post-stage health evidence')
    for stage in [s for s in DETACHED if s in STAGES[:STAGES.index(last_stage)+1]]:
        usb=json.loads((directory/('usb-pm-'+stage)/'result.json').read_text())
        staged=[x for x in proof['stages'] if x['stage']==stage][0]
        if (any(staged.get(k) is not True for k in ('usb_disconnected','usb_guard_qualified')) or
                usb.get('boot_id')!=candidate['boot_id'] or usb.get('sleep_requested') is not True or
                any(usb.get(k) is not True for k in ('usb_cycle_qualified','independent_sleep_inhibitor',
                    'original_usb_inhibitor_restored','watchdog_owner_unchanged','post_cycle_health')) or
                usb.get('fallback_reboot_requested') is not False):
            raise RuntimeError('Missing qualified USB detachment/restoration around device PM')
    return dict(pm_diagnostics_qualified=True,pm_test_stages=[s['stage'] for s in proof['stages']],
                sleep_requested=True,full_suspend_requested=last_stage=='s2idle',
                s2idle_resume_qualified=last_stage=='s2idle',hibernation_io_qualified=False)
