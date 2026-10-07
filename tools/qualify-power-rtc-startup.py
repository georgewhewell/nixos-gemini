#!/usr/bin/env python3
"""Qualify native RTC startup using retained UTC and a temporary M69 skip.

Default preflight is read-only. Execution skips M69's incompatible shutdown
clock writer for this boot, then uses the complete calendar/recovery trial.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('startup_calendar', ROOT/'tools/qualify-power-rtc-calendar.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
p = c.p
startup = p.f.q.module('rtc_startup', ROOT/'tools/qualify-rtc-startup.py')
p.PROFILE = 'power-rtc-startup'
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES += ('tools/qualify-power-rtc-startup.py', 'tools/qualify-rtc-startup.py')


def configure(watchdog=False, pm_test=None, cycle=False):
    if watchdog or pm_test or cycle:
        raise ValueError('RTC startup profile requires the normal calendar sequence')
    runner = c.q.base_configure()
    runner.backend.MTK = runner.backend.MTK_RTC
    # Probe the native clock after health checks, before calendar.install's
    # explicit RTC_SET_TIME, followed by the original alarm sequence.
    startup.install_probe(p, runner, c.calendar)
    c.calendar.install(p, runner)
    c.q.rtc.install(p, runner)
    return runner
p.configure = configure


def preflight(runner, directory, execute):
    before = c.preflight(runner, directory, execute)
    with c.ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            c.fcntl.flock(handle, c.fcntl.LOCK_EX | c.fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        if p.f.snapshot('swap') != dict(before, layout='swap'):
            raise RuntimeError('Baseline changed before RTC startup preflight')
        startup.prepare(p, runner, c.calendar, directory, before)
    startup.install_transition(p, runner, c.calendar, directory, before)
    return before
p.preflight = preflight


def finish(runner, directory, before, error=None):
    proof = dict(rtc_startup_qualified=False, runtime_clock_policy_restored=False)
    if error is None:
        try:
            startup.verify_final(directory)
            proof['rtc_startup_qualified'] = True
        except (OSError, ValueError, RuntimeError, KeyError) as caught:
            error = caught
    try:
        c.finish(runner, directory, before, error)
    except Exception as caught:
        error = caught
        raise
    finally:
        try:
            proof.update(startup.cleanup(p, runner, directory, before))
        except Exception as caught:
            error = caught
            raise
        finally:
            runner.qualify.save(directory, 'rtc-startup-result.json', proof)
            result_file = directory/'result.json'
            if result_file.exists():
                result = json.loads(result_file.read_text()); result.update(proof)
                passed = error is None and result.get('profile_qualified') is True and all(
                    proof[k] for k in ('rtc_startup_qualified', 'runtime_clock_policy_restored'))
                result.update(result='passed' if passed else 'failed', profile_qualified=passed)
                if error is not None: result['error'] = str(error)
                runner.qualify.save(directory, 'result.json', result)
p.finish = finish


if __name__ == '__main__':
    try: p.main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: sys.exit(str(error))
