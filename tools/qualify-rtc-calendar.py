#!/usr/bin/env python3
"""Bounded MT6351 UTC write/read check, plus legacy-decoded reboot retention.

Only called by the pinned calendar candidate. Host UTC independently constrains
system time before hwclock writes; periodic kernel RTC synchronization stays disabled.
The recovered M69 kernel still uses its old epoch, so its readout is decoded
explicitly and is never described as a correct native UTC reading.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

LIMITS = dict(RuntimeMaxUSec='30s', TimeoutStopUSec='3s', KillMode='control-group', RemainAfterExit='yes')


def decode_m69(epoch):
    # Invert the qualified driver's 1900..2027 range rotation first, then
    # interpret the same hardware calendar fields using the firmware epoch.
    value = datetime.fromtimestamp(epoch, timezone.utc)
    if value.year > 2027:
        value = datetime.fromtimestamp(epoch - 4039286400, timezone.utc)
    if not 1900 <= value.year <= 2027:
        raise ValueError('M69 date is outside its hardware register range')
    return int(value.replace(year=value.year + 68).timestamp())


def parse(raw, keys):
    rows = raw.splitlines(); values = dict(row.split('=', 1) for row in rows)
    if len(rows) != len(values) or set(values) != set(keys):
        raise RuntimeError('Calendar evidence keys differ')
    return values


def verify(raw, service, boot, host_start, host_end, elapsed):
    keys = ('boot_id', 'before_rtc', 'before_system', 'after_rtc', 'after_system',
            'tick_rtc', 'tick_system', 'before_uptime', 'tick_uptime', 'alarm_disabled')
    v = parse(raw, keys)
    if v['boot_id'] != boot or v['alarm_disabled'] != 'yes':
        raise RuntimeError('Calendar identity or alarm state differs')
    for k in set(keys) - {'boot_id', 'alarm_disabled', 'before_uptime', 'tick_uptime'}:
        if not v[k].isdigit(): raise RuntimeError('Invalid calendar time')
    if (not all(math.isfinite(x) for x in (host_start, host_end, elapsed)) or
            not 2 <= elapsed <= 20 or abs((host_end - host_start) - elapsed) > 1):
        raise RuntimeError('Host clock or bounded observation changed')
    for k in ('before_system', 'after_system', 'tick_system', 'after_rtc', 'tick_rtc'):
        if not host_start - 2 <= int(v[k]) <= host_end + 2:
            raise RuntimeError('Device clock differs from independently observed host UTC')
    if (abs(int(v['after_rtc']) - int(v['after_system'])) > 1 or
            abs(int(v['tick_rtc']) - int(v['tick_system'])) > 1 or
            not 1 <= int(v['tick_rtc']) - int(v['after_rtc']) <= 4 or
            not 2 <= float(v['tick_uptime']) - float(v['before_uptime']) <= 10):
        raise RuntimeError('RTC write/read or ticking differs')
    if service != dict(LIMITS, ActiveState='active', SubState='exited', MainPID='0',
                       Result='success', ExecMainCode='1', ExecMainStatus='0'):
        raise RuntimeError('Calendar service failed or was not bounded')
    return dict(boot_id=boot, rtc_utc_write_read_qualified=True,
                before_rtc=int(v['before_rtc']), after_rtc=int(v['after_rtc']),
                tick_rtc=int(v['tick_rtc']), host_start=host_start, host_end=host_end,
                elapsed_seconds=elapsed, sleep_requested=False, kernel_periodic_rtc_updates=False)


def script(context, state, owner, stamp, unit):
    if (not re.fullmatch('[0-9a-f-]{36}', state['boot_id']) or
            not re.fullmatch('gemini-rtc-calendar-[0-9]+-[0-9]+', unit) or
            not str(owner['owner_pid']).isdigit() or not str(stamp).isdigit()):
        raise ValueError('Unpinned calendar action')
    common = '#!/bin/sh\nset -eu\n' + '\n'.join(f'{k}={shlex.quote(str(v))}' for k,v in
        dict(boot=state['boot_id'], system=context.SYSTEM, notes=context.NOTES_SHA,
             owner=owner['owner_pid'], stamp=stamp, token=unit).items()) + '''
remote=/run/$token
rtc=/sys/class/rtc/rtc0
same_boot() {
 test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot" &&
 test "$(readlink /run/current-system)" = "$system" &&
 test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = "$notes"
}
cleanup() {
 test -f "$remote/owned" || return 0
 same_boot || return 1
 test "$(cat /run/gemini-rtc-alarm.lock/owner)" = "$token" || return 1
 rm /run/gemini-rtc-alarm.lock/owner
 rmdir /run/gemini-rtc-alarm.lock
 rm "$remote/owned"
}
same_owner() {
 same_boot &&
 test "$(cat /run/unattended-recovery.watchdog-owner)" = "$owner" &&
 test "$(systemctl show gemini-watchdog-takeover.service -p MainPID --value)" = "$owner" &&
 test "$(sed 's/.*) //' /proc/$owner/stat | awk '{print $20}')" = "$stamp" &&
 test "$(cat /sys/class/watchdog/watchdog0/state)" = active
}
'''
    action = common + '''
same_owner
test "$(cat "$rtc/name")" = 'mt6397-rtc mt6351-rtc'
test -z "$(cat "$rtc/wakealarm")"
test "$(cat /sys/power/pm_test)" = '[none] core processors platform devices freezer'
test "$(cat /sys/class/udc/11271000.usb/state)" = configured
test ! -d /run/gemini-pm-test.lock
test ! -d /run/gemini-usb-cycle.lock
zcat /proc/config.gz | grep -qx '# CONFIG_RTC_SYSTOHC is not set'
# A fresh host timestamp is staged immediately before starting this service.
host=$(cat "$remote/host-epoch")
case "$host" in ''|*[!0-9]*) exit 1;; esac
now=$(date -u +%s)
test "$now" -ge "$((host - 2))"
test "$now" -le "$((host + 10))"
mkdir /run/gemini-rtc-alarm.lock
printf '%s' "$token" > /run/gemini-rtc-alarm.lock/owner
touch "$remote/owned"
trap cleanup EXIT
printf 'boot_id=%s\n' "$boot"
printf 'before_rtc='; cat "$rtc/since_epoch"
printf 'before_system='; date -u +%s
printf 'before_uptime='; cut -d' ' -f1 /proc/uptime
touch "$remote/write-requested"
hwclock -w -u -f /dev/rtc0
printf 'after_rtc='; cat "$rtc/since_epoch"
printf 'after_system='; date -u +%s
sleep 2
same_owner
printf 'tick_rtc='; cat "$rtc/since_epoch"
printf 'tick_system='; date -u +%s
printf 'tick_uptime='; cut -d' ' -f1 /proc/uptime
test -z "$(cat "$rtc/wakealarm")"
printf 'alarm_disabled=yes\n'
cleanup
trap - EXIT
'''
    return action, common + 'cleanup\n'


def install(context, runner):
    original = runner.candidate_return
    def candidate_return(ssh, before, directory, profile):
        state = original(ssh, before, directory, profile)
        out = directory/'rtc-calendar'; out.mkdir(mode=0o700)
        owner = context.paging.watchdog(out, state, 'watchdog-before')
        stamp = runner.persistence.run(ssh,
            f"sed 's/.*) //' /proc/{int(owner['owner_pid'])}/stat | awk '{{print $20}}'", out, 'owner-starttime').strip()
        unit = 'gemini-rtc-calendar-'+str(int(time.time()))+'-'+str(os.getpid()); remote = '/run/'+unit
        action, cleanup = script(context, state, owner, stamp, unit)
        source = Path(__file__).read_bytes(); (out/'executed-source.py').write_bytes(source)
        transfer = f'set -eu\ntest "$(cat /proc/sys/kernel/random/boot_id)" = {state["boot_id"]}\numask 077\nmkdir {remote}\n'
        for name, body in (('action', action), ('cleanup', cleanup)):
            (out/(name+'.sh')).write_text(body)
            subprocess.run(['sh', '-n', str(out/(name+'.sh'))], check=True)
            transfer += f"cat > {remote}/{name} <<'SCRIPT'\n{body}\nSCRIPT\nchmod 0500 {remote}/{name}\n"
        runner.qualify.save(out, 'plan.json', dict(unit=unit, limits=LIMITS,
            source_sha256=hashlib.sha256(source).hexdigest(), notes_sha256=context.NOTES_SHA,
            clock_write_requested=True, kernel_periodic_rtc_updates=False))
        runner.persistence.run(ssh, transfer, out, 'stage')
        host_start = time.time(); monotonic = time.monotonic()
        launch = f'''set -eu
printf '%s' {int(host_start)} > {remote}/host-epoch
systemd-run --quiet --unit={unit} --setenv=PATH=/run/current-system/sw/bin \\
 --property=RuntimeMaxSec=30 --property=TimeoutStopSec=3 --property=KillMode=control-group \\
 --property=RemainAfterExit=yes --property=ExecStopPost={remote}/cleanup \\
 --property=StandardOutput=file:{remote}/stdout --property=StandardError=file:{remote}/stderr {remote}/action
'''
        runner.persistence.run(ssh, launch, out, 'launch')
        try:
            time.sleep(4)
            raw = runner.persistence.run(ssh, f'cat {remote}/stdout; cat {remote}/stderr >&2', out, 'output')
            host_end = time.time(); elapsed = time.monotonic() - monotonic
            fields = tuple(LIMITS) + ('ActiveState','SubState','MainPID','Result','ExecMainCode','ExecMainStatus')
            service = runner.persistence.run(ssh, f'systemctl show {unit} '+''.join(' -p '+k for k in fields), out, 'service')
            proof = verify(raw, dict(row.split('=',1) for row in service.splitlines()), state['boot_id'], host_start, host_end, elapsed)
        finally:
            runner.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
systemctl stop {unit}
test "$(systemctl show {unit} -p MainPID --value)" = 0
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
test ! -d /run/gemini-rtc-alarm.lock
''', out, 'stop')
        if (Path(__file__).read_bytes() != source or
                runner.candidate_snapshot(ssh, before, profile) != state or
                context.paging.watchdog(out, state, 'watchdog-after') != owner):
            raise RuntimeError('Calendar source, candidate health or watchdog changed')
        proof.update(same_boot_health=True, watchdog_owner_unchanged=True)
        runner.qualify.save(out, 'result.json', proof)
        print('RTC UTC write/read and ticking passed', flush=True)
        return state
    runner.candidate_return = candidate_return


def verify_candidate(directory):
    proof = json.loads((directory/'rtc-calendar/result.json').read_text())
    candidate = json.loads((directory/'candidate-linux.json').read_text())
    if (proof.get('boot_id') != candidate['boot_id'] or any(proof.get(k) is not True for k in
            ('rtc_utc_write_read_qualified', 'same_boot_health', 'watchdog_owner_unchanged'))):
        raise RuntimeError('Missing candidate calendar proof')
    return proof


def recovered(context, runner, directory):
    baseline = json.loads((directory/'rtc-calendar-baseline.json').read_text())
    result = json.loads((directory/'result.json').read_text())
    candidate = verify_candidate(directory)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        state = context.f.snapshot('swap')
        if state['boot_id'] != result['recovered_boot_id'] or state['boot_id'] == candidate['boot_id']:
            raise RuntimeError('Calendar recovery boot changed')
        start = time.time(); mono = time.monotonic()
        raw = runner.persistence.run(context.f.q.SSH, '''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'notes='; sha256sum /sys/kernel/notes | cut -d' ' -f1
printf 'rtc='; cat /sys/class/rtc/rtc0/since_epoch
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
test ! -d /run/gemini-rtc-alarm.lock
zcat /proc/config.gz | grep -qx '# CONFIG_RTC_SYSTOHC is not set'
''', directory, 'rtc-calendar-recovery')
        end = time.time(); elapsed = time.monotonic() - mono
        values = parse(raw, ('boot_id', 'notes', 'rtc'))
        if values['boot_id'] != state['boot_id'] or values['notes'] != baseline['notes']:
            raise RuntimeError('Legacy RTC decoder identity differs')
        utc = decode_m69(int(values['rtc']))
        proof = dict(recovered_boot_id=state['boot_id'], legacy_rtc_epoch=int(values['rtc']),
            firmware_decoded_utc=utc, host_start=start, host_end=end,
            legacy_m69_decoder=True, native_m69_utc_correct=False,
            rtc_reboot_persistence_qualified=(start-3 <= utc <= end+3 and elapsed <= 10 and abs(end-start-elapsed) <= 1))
        runner.qualify.save(directory, 'rtc-calendar-reboot.json', proof)
        if not proof['rtc_reboot_persistence_qualified']:
            raise RuntimeError('RTC UTC did not persist across firmware and M69 recovery')
        return proof
