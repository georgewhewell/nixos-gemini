#!/usr/bin/env python3
"""Qualify a pinned firmware-compatible MT6351 calendar, alarms and recovery.

Default is read-only preflight. Execution writes current UTC through RTC_SET_TIME
on the corrected kernel and checks retention through the existing M69 recovery.
"""
from contextlib import ExitStack
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calendar_rtc_profile', ROOT/'tools/qualify-power-rtc.py')
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
p = q.p
calendar = p.f.q.module('rtc_calendar', ROOT/'tools/qualify-rtc-calendar.py')
cache = p.f.q.module('rtc_store_cache', ROOT/'tools/qualify-rtc-store-cache.py')
stage1 = p.f.q.module('rtc_stage1_rescue', ROOT/'tools/qualify-rtc-stage1-rescue.py')
p.PROFILE = 'power-rtc-calendar'
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES += ('tools/qualify-power-rtc-calendar.py', 'tools/qualify-rtc-calendar.py',
                             'tools/qualify-rtc-store-cache.py', 'tools/qualify-rtc-stage1-rescue.py')
p.BUNDLE = Path('/nix/store/h06d3dmfs3j0kdy19j61x8aghcxp8qqr-gemini-mainline-nixos-bundle')
p.KERNEL = Path('/nix/store/x7pps048pisms3b1xpmfpa8khfmndkyq-gemini-mainline-power-rtc-calendar-kernel-7.1.3')
p.SYSTEM = '/nix/store/8zl369z86ddcqwybwi4b700afxw0n4xq-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
p.BOOT_SHA = '92528b092a5ef5caab863c353978da9866046db5d37ebcba824b070b3fd93a79'
p.STORE_SHA = '5377cc00ba1f7eb87d38ba552787362df1f5308daa3dbc0aaf14753785aa8938'
p.STORE_SIZE = 427040768
p.NOTES_SHA = '0de66a120a0d13afcd3f6177cd260daa1426b6d38dc6b738fc1316ae4260eb10'


def configure(watchdog=False, pm_test=None, cycle=False):
    if watchdog or pm_test or cycle:
        raise ValueError('Calendar profile only supports UTC and awake alarm checks')
    runner = q.base_configure()
    # Keep older profiles on their original tool; this image requires RTC
    # retention through both candidate and rescue download-agent reboots.
    runner.backend.MTK = runner.backend.MTK_RTC
    calendar.install(p, runner)
    q.rtc.install(p, runner)
    return runner
p.configure = configure

base_preflight = p.preflight

def preflight(runner, directory, execute):
    before = base_preflight(runner, directory, execute)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        if p.f.snapshot('swap') != dict(before, layout='swap'):
            raise RuntimeError('Baseline changed before calendar preflight')
        raw = runner.persistence.run(p.f.q.SSH, '''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'notes='; sha256sum /sys/kernel/notes | cut -d' ' -f1
printf 'rtc='; cat /sys/class/rtc/rtc0/since_epoch
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
test ! -d /run/gemini-rtc-alarm.lock
''', directory, 'rtc-calendar-baseline')
        values = calendar.parse(raw, ('boot_id', 'notes', 'rtc'))
        if values['boot_id'] != before['boot_id']:
            raise RuntimeError('Calendar baseline boot changed')
        runner.qualify.save(directory, 'rtc-calendar-baseline.json', values)
        cache.prepare(p, runner, directory, before)
    cache.install(p, runner, directory)
    stage1.install(p, runner, directory)
    return before
p.preflight = preflight


def finish(runner, directory, before, error=None):
    proof = dict(rtc_utc_write_read_qualified=False, rtc_reboot_persistence_qualified=False,
                 kernel_periodic_rtc_updates=False, sleep_requested=False)
    if error is None:
        try:
            calendar.verify_candidate(directory)
            proof['rtc_utc_write_read_qualified'] = True
        except (OSError, ValueError, RuntimeError, KeyError) as caught:
            error = caught
    try:
        # This always completes the original alarm proof, recovery and full
        # storage/source/ordinary-output audit, even if calendar checks fail.
        q.finish(runner, directory, before, error)
        proof.update(cache.verify_final(runner, directory))
        reboot = calendar.recovered(p, runner, directory)
        proof['rtc_reboot_persistence_qualified'] = reboot['rtc_reboot_persistence_qualified']
    except Exception as caught:
        error = caught
        raise
    finally:
        runner.qualify.save(directory, 'rtc-calendar-result.json', proof)
        result_file = directory/'result.json'
        if result_file.exists():
            result = json.loads(result_file.read_text()); result.update(proof)
            passed = error is None and result.get('profile_qualified') is True and all(
                proof[k] for k in ('rtc_utc_write_read_qualified', 'rtc_reboot_persistence_qualified'))
            result.update(result='passed' if passed else 'failed', profile_qualified=passed)
            if error is not None: result['error'] = str(error)
            runner.qualify.save(directory, 'result.json', result)
p.finish = finish


if __name__ == '__main__':
    try: p.main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: sys.exit(str(error))
