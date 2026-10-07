#!/usr/bin/env python3
"""Qualify USB detach/reconnect with separate sleep and recovery guards."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

BUS = 'busctl --json=short call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager ListInhibitors'
NONE = '[none] core processors platform devices freezer'
WHY = 'Gemini USB diagnostic recovery guard'
LIMITS = dict(RuntimeMaxUSec='30s', TimeoutStopUSec='3s', KillMode='control-group', RemainAfterExit='yes')


def prerequisites(p):
    prior = p.ROOT.parent/'handoff/power-swap-05'
    result = json.loads((prior/'result.json').read_text())
    candidate = json.loads((prior/'candidate-linux.json').read_text())
    power = json.loads((prior/'power-swap-evidence.json').read_text())
    if (result.get('result') != 'passed' or any(result.get(k) is not True for k in
            ('profile_qualified', 'usb_cycle_qualified', 'fixed_swap_preserved', 'no_writer')) or
            candidate.get('system') != p.SYSTEM or candidate.get('boot_sha256') != p.BOOT_SHA or
            power.get('notes_sha256') != p.NOTES_SHA):
        raise RuntimeError('Selected kernel lacks qualified guarded USB recovery')
    verify_final(prior)
    plan = json.loads((prior/'plan.json').read_text())
    for name, sha in plan['all_executed_sources_sha256'].items():
        if hashlib.sha256((prior/'executed-sources'/Path(name).name).read_bytes()).hexdigest() != sha:
            raise RuntimeError('Prior USB source archive changed')
    return dict(usb_cycle_trial=str(prior), result_sha256=hashlib.sha256((prior/'result.json').read_bytes()).hexdigest())


def scripts(boot, system, notes, pid, stamp, remote, paths=None, diagnostic=None):
    if (diagnostic not in (None, 'devices') or not re.fullmatch('[0-9a-f-]{36}', boot) or
            not re.fullmatch('/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+', system) or
            not re.fullmatch('[0-9a-f]{64}', notes) or
            any(not str(v).isdecimal() or int(v) < 2 for v in (pid, stamp)) or
            not re.fullmatch('/run/gemini-usb-cycle-[0-9]+-[0-9]+', remote)):
        raise ValueError('Unpinned USB cycle identity')
    paths = paths or dict(proc='/proc', run='/run', sys='/sys', remote=remote)
    common = '#!/bin/sh\nset -eu\n' + '\n'.join(
        f'{k}={shlex.quote(str(v))}' for k, v in dict(paths, boot=boot, system=system,
        notes=notes, owner=pid, stamp=stamp, token=Path(remote).name,
        diagnostic=diagnostic or 'none').items()) + '''
udc="$sys/class/udc/11271000.usb"
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
guard_alive() {
 read guard_pid guard_stamp < "$remote/inhibitor-verified"
 test "$(systemctl is-active "$token-guard")" = active &&
 test "$(systemctl show "$token-guard" -p MainPID --value)" = "$guard_pid" &&
 test "$(sed 's/.*) //' "$proc/$guard_pid/stat" | awk '{print $20}')" = "$guard_stamp"
}
reconnect() {
 test -f "$remote/armed" || return 0
 same_boot || return 1
 test "$(cat "$run/gemini-usb-cycle.lock/owner")" = "$token" || return 1
 cleanup_rc=0
 if test "$diagnostic" = devices; then
  "$remote/pm-cleanup" || cleanup_rc=$?
 fi
 if test ! -f "$remote/reconnected"; then
  printf connect > "$udc/soft_connect"
  ip address replace 10.15.19.82/24 dev usb0
  ip link set usb0 up
  touch "$remote/reconnected"
 fi
 return "$cleanup_rc"
}
'''
    hold = common + '''
same_owner
printf '%s\n' "$boot" > "$remote/ready"
# Separate systemd-inhibit service survives action timeout and cleanup.
# Its lifetime exceeds the independent reboot/watchdog fallback below. The
# ordinary boot lease may already have been accepted, so it is not sufficient.
exec sleep 900
'''
    rescue = common + '''
test -f "$remote/armed" || exit 0
test ! -f "$remote/acknowledged" || exit 0
same_boot
printf 'fallback=reboot\n' > "$remote/fallback"
# Never wait on the USB driver here: it may be why reconnection failed.
timeout -s TERM -k 1 3 systemctl --no-block reboot || true
sleep 2
# If software reboot did not take us down, stop the exact keepalive process.
# Check files/fds directly so an unresponsive system manager cannot block it.
same_boot
test "$(cat "$run/unattended-recovery.watchdog-owner")" = "$owner"
test "$(sed 's/.*) //' "$proc/$owner/stat" | awk '{print $20}')" = "$stamp"
owned=no
for fd in "$proc/$owner/fd/"*; do
 case "$(readlink "$fd" || true)" in /dev/watchdog|/dev/watchdog0) owned=yes;; esac
done
test "$owned" = yes
test "$(cat "$sys/class/watchdog/watchdog0/state")" = active
kill -STOP "$owner"
printf 'fallback=watchdog\n' > "$remote/fallback-watchdog"
'''
    deadline = common + 'sleep 120\nexec "$remote/rescue"\n'
    cleanup = common + 'reconnect\n'
    action = common + '''
# Let the launching SSH command return before disconnecting it.
sleep 3
same_owner
guard_alive
test "$(systemctl is-active "$token-fallback")" = active
test "$(cat "$remote/ready")" = "$boot"
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
test "$(cat "$udc/state")" = configured
test -w "$udc/soft_connect"
test "$(cat "$sys/power/pm_test")" = '[none] core processors platform devices freezer'
test ! -d "$run/gemini-pm-test.lock"
test ! -e "$run/unattended-recovery.lease-expired"
deadline=$(sed -n 's/^deadline=//p' "$run/unattended-recovery.lease-deadline")
uptime=$(awk '{sub(/\\..*/,"",$1); print $1}' "$proc/uptime")
case "$deadline:$uptime" in *[!0-9:]*|:*|*:) exit 1;; esac
test "$deadline" -gt "$((uptime + 240))"
test "$deadline" -le "$((uptime + 720))"
sync
same_owner
guard_alive
mkdir "$run/gemini-usb-cycle.lock"
printf '%s' "$token" > "$run/gemini-usb-cycle.lock/owner"
touch "$remote/armed"
trap reconnect EXIT
printf 'boot_id=%s\nowner_pid=%s\nowner_starttime=%s\n' "$boot" "$owner" "$stamp"
printf 'before_success='; cat "$sys/power/suspend_stats/success"
printf 'before_fail='; cat "$sys/power/suspend_stats/fail"
printf 'uptime_before='; cut -d' ' -f1 "$proc/uptime"
printf disconnect > "$udc/soft_connect"
''' + BUS + ''' > "$remote/inhibitors-during.json"
guard_alive
if test "$diagnostic" = devices; then
 pm_status=0
 "$remote/pm-test" > "$remote/pm-stdout" 2> "$remote/pm-stderr" || pm_status=$?
 printf '%s\n' "$pm_status" > "$remote/pm-status"
else
 sleep 5
fi
reconnect
attempt=0
while test "$(cat "$udc/state")" != configured; do
 attempt=$((attempt + 1)); test "$attempt" -lt 50
 sleep 0.1
done
same_owner
guard_alive
printf 'uptime_after='; cut -d' ' -f1 "$proc/uptime"
printf 'after_success='; cat "$sys/power/suspend_stats/success"
printf 'after_fail='; cat "$sys/power/suspend_stats/fail"
printf 'pm_test='; cat "$sys/power/pm_test"
printf 'udc_state='; cat "$udc/state"
touch "$remote/finished"
'''
    return dict(hold=hold, rescue=rescue, deadline=deadline, cleanup=cleanup, action=action)


def returned_command(boot, remote, proc='/proc', diagnostic=None):
    # Capture action output even when its completion predicate fails. Losing
    # these files on automatic recovery would hide the target's actual error.
    if diagnostic not in (None, 'devices'): raise ValueError('Unsupported detached diagnostic')
    capture = ''
    if diagnostic:
        capture = f'''for part in pm-stdout pm-stderr pm-status; do
 if test -f {shlex.quote(remote)}/"$part"; then
  printf '\\n%s\\n' "$part" >&2
  cat {shlex.quote(remote)}/"$part" >&2
 fi
done
if test ! -f {shlex.quote(remote)}/finished; then dmesg >&2; fi
'''
    return f'''set -eu
test "$(cat {shlex.quote(proc)}/sys/kernel/random/boot_id)" = {shlex.quote(boot)}
cat {shlex.quote(remote)}/stdout
cat {shlex.quote(remote)}/stderr >&2
''' + capture + f'''test ! -f {shlex.quote(remote)}/fallback || exit 4
test -f {shlex.quote(remote)}/finished || exit 3
'''


def inhibitor(raw, who, pid, why=WHY):
    obj = json.loads(raw)
    if obj.get('type') != 'a(ssssuu)' or len(obj.get('data', [])) != 1:
        raise RuntimeError('Unexpected logind inhibitor evidence')
    wanted = ['sleep', who, why, 'block', 0, int(pid)]
    if obj['data'][0].count(wanted) != 1:
        raise RuntimeError('Exact sleep inhibitor owner not observed')
    return wanted


def verify(raw, boot, pid, stamp, events, initial, diagnostic=None):
    if diagnostic not in (None, 'devices'): raise ValueError('Unsupported detached diagnostic')
    rows = raw.splitlines(); values = dict(row.split('=', 1) for row in rows)
    expected = dict(boot_id=boot, owner_pid=pid, owner_starttime=stamp, pm_test=NONE, udc_state='configured')
    keys = set(expected) | {'uptime_before', 'uptime_after', 'before_success', 'after_success', 'before_fail', 'after_fail'}
    if len(rows) != len(values) or set(values) != keys or any(values[k] != v for k,v in expected.items()):
        raise RuntimeError('USB cycle identity or restored state differs')
    for k in ('uptime_before', 'uptime_after'):
        if not re.fullmatch('[0-9]+\\.[0-9]+', values[k]): raise RuntimeError('Invalid target clock')
    for name in ('success', 'fail'):
        delta = 1 if diagnostic == 'devices' and name == 'success' else 0
        if (not values['before_'+name].isdigit() or not values['after_'+name].isdigit() or
                int(values['after_'+name]) != int(values['before_'+name]) + delta):
            raise RuntimeError('Unexpected suspend request during USB cycle')
    elapsed = float(values['uptime_after']) - float(values['uptime_before'])
    if not 4.5 <= elapsed <= 20: raise RuntimeError('Invalid USB disconnect dwell')
    if len(events) != 3 or events[0]['usb'] != list(initial) or events[1]['usb'] is not None:
        raise RuntimeError('Missing independent host USB departure')
    returned = events[2]['usb']
    if not returned or returned[:2] != list(initial[:2]) or returned[2] == initial[2]:
        raise RuntimeError('USB did not re-enumerate as the same gadget')
    offline = events[2]['monotonic'] - events[1]['monotonic']
    if not 4 <= offline <= 20 or events[1]['monotonic'] <= events[0]['monotonic']:
        raise RuntimeError('Invalid independent USB outage timing')
    return dict(boot_id=boot, target_elapsed_seconds=round(elapsed, 3),
                host_offline_seconds=round(offline, 3), sleep_requested=diagnostic is not None)


def run(p, r, ssh, directory, state, pm=None):
    diagnostic = 'devices' if pm is not None else None
    out = directory/('usb-pm-devices' if diagnostic else 'usb-cycle'); out.mkdir(mode=0o700)
    units = json.loads((directory/'units.json').read_text())
    if not p.f.owner_alive(units['supervisor']): raise RuntimeError('USB cycle lacks independent rescue')
    r.wait_state(directory/'supervisor-rollback.state', 'tool_started ', 30, terminal=False)
    backend = p.f.q.module('cycle_usb', p.ROOT/'research/p22-mtkclient-backend.py')
    port = json.loads((directory/'backend.json').read_text())['usb_port']
    initial = backend.usb_snapshot(port)
    if not initial or initial == backend.UNKNOWN or initial[0] == '0e8d':
        raise RuntimeError('Candidate gadget missing')
    owner = p.paging.watchdog(out, state, 'watchdog-before'); pid = owner['owner_pid']
    stamp = r.persistence.run(ssh, f"sed 's/.*) //' /proc/{int(pid)}/stat | awk '{{print $20}}'", out, 'owner-starttime').strip()
    unit = 'gemini-usb-cycle-'+str(int(time.time()))+'-'+str(os.getpid()); remote = '/run/'+unit
    source = scripts(state['boot_id'], p.SYSTEM, p.NOTES_SHA, pid, stamp, remote, diagnostic=diagnostic)
    transfer = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
umask 077
mkdir {remote}
'''
    if diagnostic:
        pm_unit = unit.replace('usb-cycle', 'pm-devices')
        pm_remote = '/run/'+pm_unit
        source['pm-test'], source['pm-cleanup'] = pm.scripts(
            'devices', state['boot_id'], p.SYSTEM, p.NOTES_SHA, pid, stamp, pm_remote)
        transfer += f'mkdir {pm_remote}\n'
    for name, body in source.items():
        transfer += f"cat > {remote}/{name} <<'SCRIPT'\n{body}\nSCRIPT\nchmod 0500 {remote}/{name}\n"
    r.persistence.run(ssh, transfer, out, 'stage')
    r.persistence.run(ssh, f'''set -eu
systemd-run --quiet --unit={unit}-guard --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=900 --property=TimeoutStopSec=3 --property=KillMode=control-group \\
 systemd-inhibit --what=sleep --mode=block --who={unit} --why='{WHY}' {remote}/hold
attempt=0
while test ! -f {remote}/ready; do attempt=$((attempt + 1)); test "$attempt" -lt 50; sleep 0.1; done
systemctl show {unit}-guard -p MainPID --value
''', out, 'guard-start', timeout=20)
    guard_pid = (out/'guard-start.stdout').read_text().strip()
    if not guard_pid.isdecimal() or int(guard_pid) < 2: raise RuntimeError('Invalid guard process')
    raw = r.persistence.run(ssh, BUS, out, 'inhibitors-before')
    inhibitor(raw, unit, guard_pid)
    r.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(systemctl show {unit}-guard -p MainPID --value)" = {guard_pid}
guard_stamp=$(sed 's/.*) //' /proc/{guard_pid}/stat | awk '{{print $20}}')
printf '%s %s\n' {guard_pid} "$guard_stamp" > {remote}/inhibitor-verified
systemd-run --quiet --unit={unit}-fallback --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=140 --property=TimeoutStopSec=10 --property=KillMode=control-group \\
 --property=ExecStopPost={remote}/rescue {remote}/deadline
test "$(systemctl is-active {unit}-fallback)" = active
systemd-run --quiet --unit={unit}-action --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=30 --property=TimeoutStopSec=3 --property=KillMode=control-group \\
 --property=RemainAfterExit=yes --property=ExecStopPost={remote}/cleanup \\
 --property=StandardOutput=file:{remote}/stdout --property=StandardError=file:{remote}/stderr {remote}/action
''', out, 'launch', timeout=20)
    print('USB cycle armed with independent sleep inhibitor and 120-second recovery fallback', flush=True)
    events = [dict(monotonic=time.monotonic(), usb=list(initial))]
    until = time.monotonic()+35
    while time.monotonic() < until:
        usb = backend.usb_snapshot(port)
        if usb != backend.UNKNOWN:
            value = list(usb) if usb else None
            if value != events[-1]['usb']:
                events.append(dict(monotonic=time.monotonic(), usb=value))
            if len(events) >= 3: break
        time.sleep(0.05)
    r.qualify.save(out, 'host-usb-events.json', events)
    until = time.monotonic()+25
    while True:
        try:
            raw = r.persistence.run(ssh, returned_command(state['boot_id'], remote, diagnostic=diagnostic), out, 'returned', timeout=7)
            break
        except (OSError, subprocess.SubprocessError) as error:
            if isinstance(error, subprocess.CalledProcessError) and error.returncode == 4:
                raise RuntimeError('Target requested USB recovery fallback') from error
            if time.monotonic() >= until:
                raise RuntimeError('USB completion not verified; last SSH result: '+str(error)) from error
            time.sleep(0.5)
    # Collect the PM attempt before verifying the surrounding USB cycle, so
    # a real device-callback failure survives automatic rescue too.
    if diagnostic:
        pm_raw = r.persistence.run(ssh, f'cat {remote}/pm-stdout', out, 'pm-output')
        r.persistence.run(ssh, f'cat {remote}/pm-stderr', out, 'pm-errors')
        pm_status = r.persistence.run(ssh, f'cat {remote}/pm-status', out, 'pm-status').strip()
        diagnostics = r.persistence.run(ssh, 'dmesg', out, 'pm-kernel')
    service = r.persistence.run(ssh, f'systemctl show {unit}-action -p ActiveState -p SubState -p Result -p MainPID -p ExecMainCode -p ExecMainStatus -p RuntimeMaxUSec -p TimeoutStopUSec -p KillMode -p RemainAfterExit', out, 'action-state')
    service = dict(row.split('=', 1) for row in service.splitlines())
    r.qualify.save(out, 'action-state.json', service)
    if service != dict(LIMITS, ActiveState='active', SubState='exited', Result='success', MainPID='0', ExecMainCode='1', ExecMainStatus='0'):
        raise RuntimeError('USB action did not finish successfully within its bounds')
    if diagnostic:
        if pm_status != '0': raise RuntimeError('Detached device PM script failed; captured PM output and kernel diagnostics')
        pm_result = pm.verify(pm_raw, service, 'devices', state['boot_id'], pid, stamp, diagnostics, pm_unit, limits=LIMITS)
    proof = verify(raw, state['boot_id'], pid, stamp, events, initial, diagnostic=diagnostic)
    during = r.persistence.run(ssh, f'cat {remote}/inhibitors-during.json', out, 'inhibitors-during')
    inhibitor(during, unit, guard_pid)
    if p.paging.watchdog(out, state, 'watchdog-after') != owner:
        raise RuntimeError('Watchdog ownership changed during USB cycle')
    if r.candidate_snapshot(ssh, json.loads((directory/'before.json').read_text()), p.PROFILE) != state:
        raise RuntimeError('Candidate health or storage changed across USB cycle')
    # Hand the sleep block back only after logind confirms the normal cable
    # inhibitor. USB configured alone does not prove that policy handoff.
    policy_pid = r.persistence.run(ssh, 'systemctl show gemini-sleep-inhibit.service -p MainPID --value', out, 'policy-pid').strip()
    after = r.persistence.run(ssh, BUS, out, 'inhibitors-after')
    inhibitor(after, unit, guard_pid)
    inhibitor(after, 'gemini-sleep-inhibit', policy_pid, 'USB host attached to the recovery gadget')
    r.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(cat /sys/class/udc/11271000.usb/state)" = configured
test ! -f {remote}/fallback
test "$(cat /run/gemini-usb-cycle.lock/owner)" = {unit}
touch {remote}/acknowledged
systemctl stop {unit}-action {unit}-fallback
systemctl stop {unit}-guard
for suffix in action fallback guard; do
 test "$(systemctl show {unit}-$suffix -p MainPID --value)" = 0
done
rm /run/gemini-usb-cycle.lock/owner
rmdir /run/gemini-usb-cycle.lock
''', out, 'acknowledge', timeout=20)
    proof.update(usb_cycle_qualified=True, independent_sleep_inhibitor=True,
                 original_usb_inhibitor_restored=True, watchdog_owner_unchanged=True,
                 post_cycle_health=True, fallback_reboot_requested=False)
    if diagnostic: proof['pm_diagnostic'] = pm_result
    r.qualify.save(out, 'result.json', proof)
    print('USB disconnected, re-enumerated and returned to full candidate health on the same boot', flush=True)
    return proof


def install(p, r):
    original = r.candidate_return
    def candidate_return(ssh, before, directory, profile):
        state = original(ssh, before, directory, profile)
        run(p, r, ssh, directory, state)
        return state
    r.candidate_return = candidate_return


def verify_final(directory):
    proof = json.loads((directory/'usb-cycle/result.json').read_text())
    candidate = json.loads((directory/'candidate-linux.json').read_text())
    if (proof.get('boot_id') != candidate['boot_id'] or
            any(proof.get(k) is not True for k in ('usb_cycle_qualified', 'independent_sleep_inhibitor',
                'original_usb_inhibitor_restored', 'watchdog_owner_unchanged', 'post_cycle_health')) or
            proof.get('fallback_reboot_requested') is not False or proof.get('sleep_requested') is not False):
        raise RuntimeError('Incomplete USB cycle and inhibitor restoration proof')
    return dict(usb_cycle_qualified=True, sleep_requested=False)
