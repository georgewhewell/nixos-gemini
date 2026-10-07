#!/usr/bin/env python3
"""Qualify RTC delivery/cancellation/rearm on the pinned corrected kernel.

Uses the fixed-swap boot/recovery runner and preserves all prior ordinary
build outputs. Default is read-only preflight. Sleep remains disabled.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rtc_power_swap',ROOT/'tools/qualify-power-swap.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
rtc=p.f.q.module('rtc_alarms',ROOT/'tools/qualify-rtc-alarm.py')
p.PROFILE='power-rtc'
p.ENTRYPOINT=Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES=('tools/qualify-power-rtc.py','tools/qualify-rtc-alarm.py')
p.BUNDLE=Path('/nix/store/7bh3lx2npyddffbyn41bcgrzaambv0qi-gemini-mainline-nixos-bundle')
p.KERNEL=Path('/nix/store/5nghlvadfma5lkqm7zcq1apiairg2i9y-gemini-mainline-power-rtc-kernel-7.1.3')
p.SYSTEM='/nix/store/5ang3jm5vv0nz4aq0m89z2624vbg159p-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
p.BOOT_SHA='18d709f77e7f25630491418b159896c5618160349f4f342ad08c52fc4170f7f3'
p.STORE_SHA='4bfae12544e2d4d885a1a11552ebc27ab0e24d945498d4a44317f497a3316ae5'
p.STORE_SIZE=427040768
p.NOTES_SHA='af7979b3d4dee258d896645fead8c4e72356d9b305871c0992b6ce1ead8c5ddf'

base_configure=p.configure
def configure(watchdog=False,pm_test=None,cycle=False):
    if pm_test or cycle:
        raise ValueError('This RTC profile supports alarm diagnostics or watchdog expiry; PM/USB need new-kernel prerequisites')
    runner=base_configure(watchdog=watchdog)
    if not watchdog:rtc.install(p,runner)
    return runner
p.configure=configure

base_finish=p.finish
def finish(r,directory,before,error=None):
    proof=dict(rtc_alarm_diagnostics_qualified=False,sleep_requested=False,wake_from_suspend_qualified=False)
    if not r.watchdog_expiry_requested and error is None:
        try:proof=rtc.verify_final(directory)
        except (OSError,ValueError,RuntimeError,KeyError) as caught:error=caught
    # Complete automatic recovery and its locked retention/source audit even
    # when the RTC evidence is missing or reports a failed cancellation.
    try:base_finish(r,directory,before,error)
    finally:
        if not r.watchdog_expiry_requested:
            r.qualify.save(directory,'rtc-result.json',proof)
            result_file=directory/'result.json'
            if result_file.exists():
                result=json.loads(result_file.read_text());result.update(proof)
                r.qualify.save(directory,'result.json',result)
p.finish=finish


if __name__=='__main__':
    try:p.main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:sys.exit(str(error))
