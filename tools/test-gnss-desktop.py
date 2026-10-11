#!/usr/bin/env python3
"""Supervised GNSS power cycles followed by existing GNOME BT/NM checks.

Reuses the boot writer, storage admission and recovery owner. Two bounded
10-second endpoint opens exercise GNSS power-on/off; they send no receiver
commands and retain no raw stream or location. No RTC diagnostics or normal
boot units are added. Passing does not qualify the receiver protocol or a fix.
"""
import importlib.util
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


desktop = load_tool('gnss_desktop', 'tools/test-network-audio-desktop.py')
gnss = load_tool('gnss_stream', 'tools/gnss-stream-evidence.py')
p = desktop.p
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES += ('tools/test-gnss-desktop.py', 'tools/gnss-stream-evidence.py')
p.preflight = desktop.boot.base_preflight
p.finish = desktop.boot.base_finish
base_configure = desktop.base_configure


def configure(*args, **kwargs):
    runner = base_configure(*args, **kwargs)
    runner.CANDIDATE_DESKTOP = 'gnome'
    runner.backend.MTK = runner.backend.MTK_RTC
    candidate = runner.candidate_return

    def qualified(ssh, before, directory, profile):
        state = candidate(ssh, before, directory, profile)
        results = {}
        try:
            config = (Path(p.KERNEL) / 'kernel.config').read_bytes().splitlines()
            required = (b'CONFIG_GNSS=y', b'CONFIG_GNSS_MTK_CONSYS=m',
                        b'CONFIG_MTK_MT6797_CONSYS_INVENTORY=m', b'CONFIG_REGULATOR_FIXED_VOLTAGE=y')
            if any(value not in config for value in required):
                raise RuntimeError('Candidate kernel lacks the native GNSS provider configuration')
            for cycle in (1, 2):
                results[f'gnss_cycle_{cycle}'] = gnss.evidence(runner, ssh, state, directory, p.SYSTEM, cycle)
            results['bluetooth'] = desktop.bluetooth_evidence(runner, ssh, state, directory)
            results['network'] = desktop.network.network_evidence(runner, ssh, state, directory, p.SYSTEM)
            if any(record.get('result') != 'passed' for record in results.values()):
                raise RuntimeError('GNSS/desktop radio checks are incomplete')
            guard = 'set -eu\n'
            guard += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
            guard += 'test "$(readlink /run/current-system)" = ' + shlex.quote(p.SYSTEM) + '\n'
            guard += 'test "$(cat /proc/sys/kernel/tainted)" = 0\necho GNSS_DESKTOP_IDENTITY_PASS\n'
            raw = runner.persistence.run(ssh, guard, directory, 'gnss-final-identity', timeout=15)
            if raw != 'GNSS_DESKTOP_IDENTITY_PASS\n':
                raise RuntimeError('Candidate identity differs after GNSS/desktop checks')
        except Exception as error:
            runner.qualify.save(directory, 'gnss-desktop-result.json', dict(
                result='failed', completed_checks=results, error=str(error)))
            raise
        runner.qualify.save(directory, 'gnss-desktop-result.json', dict(
            result='passed', checks=results, gnss_power_cycles=2, receiver_commands_sent=0,
            receiver_protocol_qualified=False, position_qualified=False,
            connection_actions_performed=False, rtc_alarm_calendar_diagnostics_run=False))
        print('PASS: two GNSS power cycles and subsequent GNOME BT/NM checks; position unqualified', flush=True)
        return state

    runner.candidate_return = qualified
    return runner


p.configure = configure
if __name__ == '__main__':
    try:
        p.main(desktop.boot.artifacts, desktop.boot.migration_artifacts)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
