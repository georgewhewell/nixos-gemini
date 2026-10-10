#!/usr/bin/env python3
"""Verify firmware-encoded UTC reaches RTC_HCTOSYS before a new clock write.

The legacy M69 shutdown writer is skipped with an owned runtime condition.
The condition disappears on reboot and is removed after an aborted trial.
No persistent clock policy or RTC register is changed by this helper.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import time

UNIT_SHA = 'ad15470f93e9059f0be310b9f11e2c89d602a235426565a9bfdfef68bb969362'
DROP_DIR = '/run/systemd/system/save-hwclock.service.d'
DROP = DROP_DIR + '/50-gemini-rtc-startup.conf'


def policy(boot):
    if not re.fullmatch('[0-9a-f-]{36}', boot):
        raise ValueError('Unpinned clock-policy boot')
    return '[Unit]\nConditionPathExists=/run/gemini-rtc-startup-'+boot+'/allow-save\n'


def shutdown_unit(system):
    """Bind the clock writer to the selected immutable NixOS generation."""
    if not re.fullmatch('/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+', str(system)):
        raise ValueError('Unpinned clock-writer system')
    root = Path(system).resolve(strict=True)
    unit = root/'etc/systemd/system/save-hwclock.service'
    if unit.is_symlink() and not unit.exists():
        raise RuntimeError('Broken clock-writer unit')
    return unit


def unit_guard(drop='', system=None):
    unit = shutdown_unit(system) if system is not None else None
    if unit is not None and not unit.exists():
        if drop:
            raise ValueError('An absent clock writer cannot have a runtime override')
        return '''
test ! -e /etc/systemd/system/save-hwclock.service
test ! -L /etc/systemd/system/save-hwclock.service
test "$(systemctl show save-hwclock.service -p LoadState --value)" = not-found
test "$(systemctl show save-hwclock.service -p ActiveState --value)" = inactive
test "$(systemctl show save-hwclock.service -p ExecMainPID --value)" = 0
test "$(systemctl show save-hwclock.service -p ExecMainStartTimestampMonotonic --value)" = 0
test "$(systemctl show save-hwclock.service -p DropInPaths --value)" = ''
'''
    sha = hashlib.sha256(unit.read_bytes()).hexdigest() if unit is not None else UNIT_SHA
    return f'''
test "$(sha256sum /etc/systemd/system/save-hwclock.service | cut -d' ' -f1)" = {sha}
test "$(systemctl show save-hwclock.service -p UnitFileState --value)" = enabled
test "$(systemctl show save-hwclock.service -p ActiveState --value)" = inactive
test "$(systemctl show save-hwclock.service -p ExecMainPID --value)" = 0
test "$(systemctl show save-hwclock.service -p ExecMainStartTimestampMonotonic --value)" = 0
test "$(systemctl show save-hwclock.service -p DropInPaths --value)" = {shlex.quote(drop)}
'''


def baseline_guard(runner, before, notes):
    if (not re.fullmatch('[0-9a-f-]{36}', before['boot_id']) or
            not re.fullmatch('[0-9a-f]{64}', notes)):
        raise ValueError('Unpinned legacy RTC identity')
    return f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {before['boot_id']}
test "$(readlink /run/current-system)" = {shlex.quote(runner.qualify.ACCEPTED_SYSTEM)}
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = {runner.qualify.ACCEPTED_BOOT}
test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = {notes}
grep -qx unattended_recovery=healthy /run/unattended-recovery.accepted
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
test ! -d /run/gemini-rtc-alarm.lock
'''


def observation(start, end, elapsed):
    if (not all(math.isfinite(x) for x in (start, end, elapsed)) or
            not 0 <= elapsed <= 10 or abs(end-start-elapsed) > 1):
        raise RuntimeError('RTC observation timing differs')


def verify_baseline(calendar, raw, boot, start, end, elapsed):
    v = calendar.parse(raw, ('boot_id', 'rtc', 'system'))
    observation(start, end, elapsed)
    if v['boot_id'] != boot or not all(v[k].isdigit() for k in ('rtc', 'system')):
        raise RuntimeError('Legacy clock identity differs')
    utc = calendar.baseline_utc(int(v['rtc']))
    if not all(start-3 <= t <= end+3 for t in (utc, int(v['system']))):
        raise RuntimeError('Startup trial requires previously retained firmware UTC')
    return dict(boot_id=boot, legacy_rtc_epoch=int(v['rtc']), firmware_decoded_utc=utc,
                host_start=start, host_end=end, retained_utc_verified=True)


def sample(runner, calendar, ssh, directory, name, script, boot):
    start = time.time(); mono = time.monotonic()
    raw = runner.persistence.run(ssh, script, directory, name)
    end = time.time(); elapsed = time.monotonic()-mono
    proof = verify_baseline(calendar, raw, boot, start, end, elapsed)
    runner.qualify.save(directory, name+'.json', proof)
    return proof


CLOCK_READ = '''
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'rtc='; cat /sys/class/rtc/rtc0/since_epoch
printf 'system='; date -u +%s
'''


def prepare(context, runner, calendar, directory, before):
    baseline = json.loads((directory/'rtc-calendar-baseline.json').read_text())
    sample(runner, calendar, context.f.q.SSH, directory, 'rtc-startup-baseline',
           baseline_guard(runner, before, baseline['notes'])+unit_guard(system=runner.qualify.ACCEPTED_SYSTEM)+
           f'test ! -e {DROP_DIR}\n'+CLOCK_READ, before['boot_id'])


def policy_script(runner, before, notes):
    system = runner.qualify.ACCEPTED_SYSTEM
    guard = unit_guard(system=system)
    # Current NixOS has no shutdown clock writer. Prove that absence instead
    # of creating or attempting to start a legacy service.
    if not shutdown_unit(system).exists():
        return baseline_guard(runner, before, notes)+guard+f'test ! -e {DROP_DIR}\n'+CLOCK_READ
    body = shlex.quote(policy(before['boot_id']))
    condition = '/run/gemini-rtc-startup-'+before['boot_id']+'/allow-save'
    return baseline_guard(runner, before, notes)+guard+f'''
test ! -e {DROP_DIR}
test ! -e {condition}
umask 077
owned=no
cleanup_failed_setup() {{
 rc=$?
 if test "$rc" != 0 && test "$owned" = yes; then
  rm -f {DROP}
  rmdir {DROP_DIR}
  systemctl daemon-reload
 fi
}}
trap cleanup_failed_setup EXIT
mkdir {DROP_DIR}
owned=yes
printf '%s' {body} > {DROP}
systemctl daemon-reload
{unit_guard(DROP, system)}
# Exercise the real systemd condition; ExecStart must remain unexecuted.
systemctl start save-hwclock.service
test "$(systemctl show save-hwclock.service -p ConditionResult --value)" = no
{unit_guard(DROP, system)}
{CLOCK_READ}
trap - EXIT
'''


def install_transition(context, runner, calendar, directory, before):
    original = runner.reboot
    def reboot(ssh, out, filename):
        if filename != 'candidate-reboot-request.json':
            return original(ssh, out, filename)
        if out != directory:
            raise RuntimeError('RTC startup trial directory differs')
        units = json.loads((directory/'units.json').read_text())
        for role in ('owner', 'supervisor', 'candidate', 'network'):
            raw = runner.qualify.run(['systemctl', '--user', 'show', units[role], '-p', 'ActiveState', '-p', 'MainPID'])
            state = dict(row.split('=', 1) for row in raw.splitlines())
            if state.get('ActiveState') != 'active' or not state.get('MainPID','').isdigit() or int(state['MainPID']) < 2:
                raise RuntimeError('RTC transition lacks its original recovery services')
        if (not runner.read_state(directory/'supervisor.state').startswith('supervisor_waiting_candidate ') or
                not runner.read_state(directory/'candidate.state').startswith('tool_started ')):
            raise RuntimeError('RTC transition writer is not waiting')
        baseline = json.loads((directory/'rtc-calendar-baseline.json').read_text())
        runner.qualify.save(directory, 'rtc-startup-policy-plan.json', dict(
            boot_id=before['boot_id'], drop_in=DROP, contents=policy(before['boot_id']), persistent_change=False))
        sample(runner, calendar, ssh, directory, 'rtc-startup-policy',
               policy_script(runner, before, baseline['notes']), before['boot_id'])
        return original(ssh, out, filename)
    runner.reboot = reboot


def verify_startup(calendar, raw, kernel, boot, policy_proof, start, end, elapsed):
    v = calendar.parse(raw, ('boot_id', 'rtc', 'system', 'uptime', 'hctosys'))
    observation(start, end, elapsed)
    if v['boot_id'] != boot or v['hctosys'] != '1' or policy_proof.get('retained_utc_verified') is not True:
        raise RuntimeError('RTC startup identity or initial retained UTC differs')
    try:
        rtc = int(v['rtc']); system = int(v['system']); uptime = float(v['uptime'])
    except ValueError as error:
        raise RuntimeError('Invalid startup clock fields') from error
    if not math.isfinite(uptime) or not 0 < uptime <= 600 or not all(start-3 <= t <= end+3 for t in (rtc, system)):
        raise RuntimeError('Native startup RTC does not match host UTC')
    match = re.fullmatch(r'\[\s*([0-9]+\.[0-9]+)\] mt6397-rtc mt6351-rtc: setting system clock to '
                         r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) UTC \((\d+)\)\n?', kernel)
    if not match:
        raise RuntimeError('Missing unique kernel RTC_HCTOSYS evidence')
    monotonic, iso, epoch = float(match[1]), match[2], int(match[3])
    if (not 0 <= monotonic <= uptime or
            int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp()) != epoch or
            not policy_proof['host_start']-3 <= epoch <= start+3 or
            abs(epoch+uptime-monotonic-rtc) > 3):
        raise RuntimeError('Early kernel clock differs from retained UTC and uptime')
    return dict(boot_id=boot, native_rtc_epoch=rtc, kernel_hctosys_epoch=epoch,
                kernel_hctosys_monotonic=monotonic, uptime=uptime,
                host_start=start, host_end=end, rtc_startup_qualified=True,
                before_explicit_clock_write=True, shutdown_writer_unexecuted=True)


def install_probe(context, runner, calendar):
    original = runner.candidate_return
    def candidate_return(ssh, before, directory, profile):
        state = original(ssh, before, directory, profile)
        out = directory/'rtc-startup'; out.mkdir(mode=0o700)
        script = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(readlink /run/current-system)" = {context.SYSTEM}
test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = {context.NOTES_SHA}
test ! -e {DROP_DIR}
{unit_guard(system=context.SYSTEM)}
zcat /proc/config.gz | grep -qx '# CONFIG_RTC_SYSTOHC is not set'
{CLOCK_READ}
printf 'uptime='; cut -d' ' -f1 /proc/uptime
printf 'hctosys='; cat /sys/class/rtc/rtc0/hctosys
'''
        start = time.time(); mono = time.monotonic()
        raw = runner.persistence.run(ssh, script, out, 'clock')
        end = time.time(); elapsed = time.monotonic()-mono
        kernel = runner.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
dmesg | grep 'mt6397-rtc mt6351-rtc: setting system clock to '
''', out, 'kernel')
        proof = verify_startup(calendar, raw, kernel, state['boot_id'],
            json.loads((directory/'rtc-startup-policy.json').read_text()), start, end, elapsed)
        runner.qualify.save(out, 'result.json', proof)
        print('Correct native UTC and kernel RTC_HCTOSYS passed before the clock write', flush=True)
        return state
    runner.candidate_return = candidate_return


def verify_final(directory):
    proof = json.loads((directory/'rtc-startup/result.json').read_text())
    clock = json.loads((directory/'rtc-calendar/result.json').read_text())
    if (any(proof.get(k) is not True for k in ('rtc_startup_qualified', 'before_explicit_clock_write',
            'shutdown_writer_unexecuted')) or proof['boot_id'] != clock['boot_id'] or
            clock['host_start'] < proof['host_end'] or
            not proof['host_start']-3 <= clock['before_rtc'] <= clock['host_end']+3):
        raise RuntimeError('Missing RTC startup proof before clock mutation')
    return proof


def cleanup(context, runner, directory, before):
    # This is also called after failed setup. Only remove our exact runtime
    # file on the original healthy boot; a new boot must already lack it.
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        state = context.f.snapshot('swap')
        body = shlex.quote(policy(before['boot_id']).rstrip('\n'))
        raw = runner.persistence.run(context.f.q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
if test {state['boot_id']} = {before['boot_id']} && test -e {DROP}; then
 test ! -L {DROP}
 test "$(cat {DROP})" = {body}
 rm {DROP}
 rmdir {DROP_DIR}
 systemctl daemon-reload
fi
test ! -e {DROP_DIR}
{unit_guard(system=state.get('system'))}
echo runtime-clock-policy=original
''', directory, 'rtc-startup-policy-cleanup')
        if raw.strip() != 'runtime-clock-policy=original':
            raise RuntimeError('Original clock policy was not restored')
        return dict(runtime_clock_policy_restored=True, boot_id=state['boot_id'])
