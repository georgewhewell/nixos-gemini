#!/usr/bin/env python3
"""Controlled Linux keepalive loss within the existing power/swap trial.

The owner retains its watchdog descriptor while SIGSTOP prevents writes.
An independent target service resumes it and reboots after 55 seconds if
expiry fails. Only a reset before that fallback may qualify as expiry.
"""
import json
import math
import os
from pathlib import Path
import re
import shlex
import time

FALLBACK_SECONDS = 55
OBSERVE_SECONDS = 45


def target_scripts(boot_id, system, notes, pid, starttime, remote, paths=None):
    if (not re.fullmatch('[0-9a-f-]{36}', boot_id) or
            not re.fullmatch('/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+', system) or
            not re.fullmatch('[0-9a-f]{64}', notes) or
            any(not str(n).isdecimal() or int(n) < 2 for n in (pid, starttime)) or
            not re.fullmatch('/run/gemini-watchdog-expiry-[0-9]+-[0-9]+', remote)):
        raise ValueError('Unpinned watchdog trigger identity')
    # Alternate paths are used only by host tests of the actual shell guards.
    paths = paths or dict(proc='/proc', run='/run', sys='/sys', remote=remote)
    common = '''#!/bin/sh
set -eu
''' + '\n'.join(f'{k}={shlex.quote(str(v))}' for k,v in dict(paths,
        boot=boot_id, system=system, notes=notes, owner=pid, stamp=starttime).items()) + '''
same_boot() {
 test "$(cat "$proc/sys/kernel/random/boot_id")" = "$boot" &&
 test "$(readlink "$run/current-system")" = "$system" &&
 test "$(sha256sum "$sys/kernel/notes" | cut -d' ' -f1)" = "$notes"
}
same_owner() {
 same_boot &&
 test "$(cat "$run/unattended-recovery.watchdog-owner")" = "$owner" &&
 test "$(systemctl show gemini-watchdog-takeover.service -p MainPID --value)" = "$owner" &&
 test "$(sed 's/.*) //' "$proc/$owner/stat" | awk '{ print $20 }')" = "$stamp"
}
resume_owner() {
 test -f "$remote/armed" || return 0
 same_owner || return 1
 kill -CONT "$owner"
 printf 'resumed\n' > "$remote/resumed"
}
'''
    resume = common + 'resume_owner\n'
    trigger = common + '''
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
test ! -e "$run/unattended-recovery.lease-expired"
deadline=$(sed -n 's/^deadline=//p' "$run/unattended-recovery.lease-deadline")
uptime=$(awk '{ sub(/\\..*/, "", $1); print $1 }' "$proc/uptime")
case "$deadline:$uptime" in *[!0-9:]*|:*|*:) exit 1;; esac
test "$deadline" -gt "$((uptime + 120))"
sync
same_owner
# Publish cleanup eligibility before sending STOP, so an interrupted start
# can always resume this exact owner through ExecStopPost.
touch "$remote/armed"
kill -STOP "$owner"
attempt=0
while test "$(sed 's/.*) //' "$proc/$owner/stat" | awk '{ print $1 }')" != T; do
 attempt=$((attempt + 1)); test "$attempt" -lt 10
 sleep 0.1
done
{
 printf 'boot_id=%s\nowner_pid=%s\nowner_starttime=%s\nowner_state=T\n' "$boot" "$owner" "$stamp"
 printf 'stopped_uptime='; cut -d' ' -f1 "$proc/uptime"
} > "$remote/stopped.new"
mv "$remote/stopped.new" "$remote/stopped"
''' + f'sleep {FALLBACK_SECONDS}\n' + '''
resume_owner
printf 'fallback=reboot\n' > "$remote/fallback"
sync
systemctl reboot
'''
    return trigger, resume


def verify_stopped(raw, boot_id, pid, stamp):
    rows = raw.splitlines(); state = dict(row.split('=', 1) for row in rows)
    expected = dict(boot_id=boot_id, owner_pid=pid, owner_starttime=stamp, owner_state='T')
    if (len(rows) != len(state) or set(state) != set(expected) | {'stopped_uptime'} or
            any(state.get(k) != v for k,v in expected.items()) or
            not re.fullmatch('[0-9]+\\.[0-9]+', state.get('stopped_uptime', ''))):
        raise RuntimeError('The identified watchdog owner was not observed stopped')
    return state


def verify_elapsed(started, acknowledged, reset):
    if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (started,acknowledged,reset)) or
            not 0 <= acknowledged-started <= 8 or
            not 20 <= reset-started <= OBSERVE_SECONDS or reset <= acknowledged):
        raise RuntimeError('Reset timing does not establish expiry before software fallback')
    return round(reset-started, 3)


def trigger(p, r, ssh, directory, state):
    units = json.loads((directory/'units.json').read_text())
    if not p.f.owner_alive(units['supervisor']):
        raise RuntimeError('Independent recovery supervisor is not active')
    r.wait_state(directory/'supervisor-rollback.state', 'tool_started ', 30, terminal=False)
    backend = p.f.q.module('expiry_usb', p.ROOT/'research/p22-mtkclient-backend.py')
    port = json.loads((directory/'backend.json').read_text())['usb_port']
    initial = backend.usb_snapshot(port)
    if not initial or initial == backend.UNKNOWN or initial[0] == '0e8d':
        raise RuntimeError('Candidate USB gadget is not independently present')
    owner = p.paging.watchdog(directory, state, 'expiry-watchdog')
    pid = owner['owner_pid']
    raw = r.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(state['boot_id'])}
sed 's/.*) //' /proc/{int(pid)}/stat | awk '{{ print $20 }}'
''', directory, 'expiry-owner-starttime')
    stamp = raw.strip()
    unit = 'gemini-watchdog-expiry-'+str(int(time.time()))+'-'+str(os.getpid())
    remote = '/run/'+unit
    action, resume = target_scripts(state['boot_id'], p.SYSTEM, p.NOTES_SHA, pid, stamp, remote)
    transfer = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
umask 077
mkdir {remote}
cat > {remote}/trigger <<'TRIGGER'
{action}
TRIGGER
cat > {remote}/resume <<'RESUME'
{resume}
RESUME
chmod 0500 {remote}/trigger {remote}/resume
'''
    r.persistence.run(ssh, transfer, directory, 'expiry-stage')
    start = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
systemd-run --quiet --unit={unit} --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=75 --property=TimeoutStopSec=3 --property=KillMode=control-group \\
 --property=ExecStopPost={remote}/resume {remote}/trigger
attempt=0
while test ! -f {remote}/stopped; do
 attempt=$((attempt + 1)); test "$attempt" -lt 50
 sleep 0.1
done
test ! -e {remote}/fallback
test ! -e {remote}/resumed
cat {remote}/stopped
'''
    started = time.monotonic()
    raw = r.persistence.run(ssh, start, directory, 'expiry-start')
    acknowledged = time.monotonic()
    stopped = verify_stopped(raw, state['boot_id'], pid, stamp)
    proof = dict(**stopped, host_started=started, host_acknowledged=acknowledged,
        fallback_seconds=FALLBACK_SECONDS, observation_seconds=OBSERVE_SECONDS,
        signal='SIGSTOP', unit=unit, initial_usb=initial, software_reboot_requested=False)
    r.qualify.save(directory, 'watchdog-trigger.json', proof)
    print('Identified Linux watchdog owner stopped; observing hardware reset', flush=True)
    events = []
    while time.monotonic()-started < OBSERVE_SECONDS:
        usb = backend.usb_snapshot(port); now = time.monotonic()
        if usb != backend.UNKNOWN and (not events or events[-1]['usb'] != usb):
            events.append(dict(monotonic=now, usb=usb))
        if usb and usb[0] == '0e8d' and usb[1] == '2000':
            elapsed = verify_elapsed(started, acknowledged, now)
            r.qualify.save(directory, 'watchdog-observation.json', dict(
                host_reset=now, seconds_from_trigger=elapsed, events=events,
                expiry_observed=True, software_reboot_requested=False))
            print(f'Watchdog reset observed after {elapsed}s; rescue writer owns recovery', flush=True)
            return
        time.sleep(0.05)
    r.qualify.save(directory, 'watchdog-observation.json', dict(events=events, expiry_observed=False))
    raise RuntimeError('Timely hardware watchdog reset not observed; bounded fallback/recovery remains armed')


def install(p, r):
    original = r.candidate_return

    def candidate_return(ssh, before, directory, profile):
        state = original(ssh, before, directory, profile)
        trigger(p, r, ssh, directory, state)
        return state

    r.candidate_return = candidate_return


def verify_final(p, directory):
    trigger = json.loads((directory/'watchdog-trigger.json').read_text())
    observed = json.loads((directory/'watchdog-observation.json').read_text())
    if ((directory/'rescue-reboot-request.json').exists() or
            trigger.get('software_reboot_requested') is not False or
            observed.get('software_reboot_requested') is not False or
            observed.get('expiry_observed') is not True or
            trigger.get('signal') != 'SIGSTOP' or trigger.get('owner_state') != 'T' or
            trigger.get('fallback_seconds') != FALLBACK_SECONDS):
        raise RuntimeError('Software reboot or incomplete watchdog trigger cannot qualify expiry')
    candidate = json.loads((directory/'candidate-linux.json').read_text())
    if trigger['boot_id'] != candidate['boot_id'] or candidate['system'] != p.SYSTEM:
        raise RuntimeError('Watchdog evidence belongs to a different candidate')
    verify_elapsed(trigger['host_started'], trigger['host_acknowledged'], observed['host_reset'])
    writer = json.loads((directory/'supervisor-rollback.state.mtk.json').read_text())
    if (writer.get('returncode') != 0 or writer.get('first_boot_window_departed') is not True or
            writer.get('expected_sha256') != p.f.q.r.qualify.ACCEPTED_BOOT):
        raise RuntimeError('Expiry lacks complete independent recovery evidence')
    events = json.loads((Path(writer['attempt'])/'usb-events.json').read_text())
    reset = next(e['monotonic'] for e in events if e['usb'] and e['usb'][:2] == ['0e8d','2000'])
    elapsed = verify_elapsed(trigger['host_started'], trigger['host_acknowledged'], reset)
    if abs(reset-observed['host_reset']) > 2:
        raise RuntimeError('Independent reset observers disagree')
    return dict(watchdog_expiry_qualified=True, programmed_timeout=31,
                keepalive_interval=10, seconds_from_trigger_to_preloader=elapsed,
                software_reboot_requested=False, automatic_m69_recovery=True)
