#!/usr/bin/env python3
"""Gate a supervised image trial on desktop radio and audio integration.

Uses the existing boot/storage recovery owner. Bluetooth checks are read-only;
the network check requests one bounded diagnostic scan without changing a
profile or connection. Audio checks inspect the active onboard route. A failed
check prevents candidate promotion. Normal boot runs none of these diagnostics.
"""
import hashlib
import importlib.util
import json
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


boot = load_tool('desktop_boot', 'tools/test-boot.py')
network = load_tool('desktop_network', 'tools/networkmanager-scan-evidence.py')
audio = load_tool('desktop_audio', 'tools/audio-playback-evidence.py')
p = boot.p
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES += (
    'tools/test-network-audio-desktop.py',
    'tools/networkmanager-scan-evidence.py',
    'tools/audio-playback-evidence.py',
    'nixos/audio-routes.nix',
    'nix/test-audio-playback-routing.py',
)


def bluetooth_evidence(runner, ssh, state, directory):
    out = directory / 'bluetooth-desktop'
    out.mkdir(mode=0o700)
    config = Path(p.KERNEL) / 'kernel.config'
    config_bytes = config.read_bytes()
    if b'CONFIG_RFKILL=y' not in config_bytes.splitlines():
        raise RuntimeError('Candidate kernel lacks built-in RFKILL')
    guard = 'set -eu\n'
    guard += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
    guard += 'test "$(readlink /run/current-system)" = ' + shlex.quote(p.SYSTEM) + '\n'
    script = guard + r'''
systemctl is-active --quiet gemini-bluetooth.service bluetooth.service display-manager.service
! systemctl is-active --quiet gemini-bluetooth-trace.service
test -d /sys/class/bluetooth/hci0
test -c /dev/rfkill
uid=$(id -u gemini)
runuser -u gemini -- test -r /dev/rfkill
runuser -u gemini -- test -w /dev/rfkill
printf 'rfkill_device=present\nuser_rfkill_access=read-write\n'
endpoints=0
for path in /sys/class/rfkill/rfkill*; do
 test -d "$path" || continue
 if test "$(cat "$path/type")" = bluetooth && test "$(cat "$path/name")" = hci0; then
  endpoints=$((endpoints + 1))
  test "$(cat "$path/soft")" = 0
  test "$(cat "$path/hard")" = 0
 fi
done
test "$endpoints" = 1
printf 'hci_rfkill_endpoint=present\nrfkill_soft=0\nrfkill_hard=0\n'
user_bus() {
 runuser -u gemini -- env XDG_RUNTIME_DIR=/run/user/$uid \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus \
  busctl --auto-start=no --timeout=3 "$@"
}
powered=$(user_bus --system get-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered)
test "$powered" = 'b true'
printf 'user_bluez_powered=true\n'
session_ready() {
 for property in BluetoothHasAirplaneMode BluetoothAirplaneMode BluetoothHardwareAirplaneMode AirplaneMode; do
  value=$(user_bus --user get-property org.gnome.SettingsDaemon.Rfkill \
   /org/gnome/SettingsDaemon/Rfkill org.gnome.SettingsDaemon.Rfkill "$property" 2>/dev/null) || return 1
  if test "$property" = BluetoothHasAirplaneMode; then expected='b true'; else expected='b false'; fi
  test "$value" = "$expected" || return 1
 done
}
# GDM may have started the seat before all GNOME session daemons own their
# bus names. Wait only for these read-only properties; never activate a service.
deadline=$(( $(date +%s) + 30 ))
until session_ready; do
 test "$(date +%s)" -lt "$deadline"
 sleep 1
done
for property in BluetoothHasAirplaneMode BluetoothAirplaneMode BluetoothHardwareAirplaneMode AirplaneMode; do
 printf 'gnome_%s=' "$property"
 user_bus --user get-property org.gnome.SettingsDaemon.Rfkill \
  /org/gnome/SettingsDaemon/Rfkill org.gnome.SettingsDaemon.Rfkill "$property"
done
printf 'taint='; cat /proc/sys/kernel/tainted
test "$(cat /proc/sys/kernel/tainted)" = 0
echo BLUETOOTH_DESKTOP_PASS
''' + guard
    raw = runner.persistence.run(ssh, script, out, 'desktop-radio', timeout=55)
    records = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    expected = {
        'rfkill_device': 'present', 'user_rfkill_access': 'read-write',
        'hci_rfkill_endpoint': 'present', 'rfkill_soft': '0', 'rfkill_hard': '0',
        'user_bluez_powered': 'true', 'gnome_BluetoothHasAirplaneMode': 'b true',
        'gnome_BluetoothAirplaneMode': 'b false',
        'gnome_BluetoothHardwareAirplaneMode': 'b false',
        'gnome_AirplaneMode': 'b false', 'taint': '0',
    }
    if any(records.get(key) != value for key, value in expected.items()) or raw.count('BLUETOOTH_DESKTOP_PASS\n') != 1:
        raise RuntimeError('GNOME Bluetooth radio inputs differ from the expected candidate state')
    result = dict(
        result='passed', boot_id=state['boot_id'], system=p.SYSTEM,
        kernel=str(p.KERNEL), kernel_config_sha256=hashlib.sha256(config_bytes).hexdigest(),
        desktop_user_bluez_visible=True, controller_powered=True,
        hci_rfkill_unblocked=True, desktop_user_rfkill_access=True,
        gnome_panel_radio_inputs=expected, continuous_hci_trace=False,
        service_or_radio_mutations=False, pairing_profiles_qualified=False,
        sustained_coexistence_qualified=False,
    )
    runner.qualify.save(out, 'result.json', result)
    print('PASS: desktop user sees Bluetooth through BlueZ and GNOME radio controls', flush=True)
    return result


base_configure = p.configure


def configure(*args, **kwargs):
    runner = base_configure(*args, **kwargs)
    candidate = runner.candidate_return

    def qualified(ssh, before, directory, profile):
        state = candidate(ssh, before, directory, profile)
        results = {}
        try:
            results['bluetooth'] = bluetooth_evidence(runner, ssh, state, directory)
            results['network'] = network.network_evidence(runner, ssh, state, directory, p.SYSTEM)
            audio.audio_evidence(runner, ssh, state, directory, p.SYSTEM)
            results['audio'] = json.loads((directory / 'audio-playback-routing' / 'result.json').read_text())
            if any(value.get('result') != 'passed' for value in results.values()):
                raise RuntimeError('Desktop integration evidence is incomplete')
            guard = 'set -eu\n'
            guard += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
            guard += 'test "$(readlink /run/current-system)" = ' + shlex.quote(p.SYSTEM) + '\n'
            guard += 'test "$(cat /proc/sys/kernel/tainted)" = 0\necho DESKTOP_IDENTITY_PASS\n'
            raw = runner.persistence.run(ssh, guard, directory, 'desktop-final-identity', timeout=15)
            if raw != 'DESKTOP_IDENTITY_PASS\n':
                raise RuntimeError('Candidate identity differs after desktop integration checks')
        except Exception as error:
            runner.qualify.save(directory, 'desktop-integration-result.json', dict(
                result='failed', boot_id=state['boot_id'], system=p.SYSTEM,
                completed_checks=results, error=str(error),
            ))
            raise
        runner.qualify.save(directory, 'desktop-integration-result.json', dict(
            result='passed', boot_id=state['boot_id'], system=p.SYSTEM,
            kernel=str(p.KERNEL), checks=results,
            connection_actions_performed=False, audible_playback_performed=False,
            pairing_profiles_qualified=False, physical_audio_orientation_qualified=False,
        ))
        print('PASS: GNOME Bluetooth, directed network scan and onboard audio mapping integration', flush=True)
        return state

    runner.candidate_return = qualified
    return runner


p.configure = configure
if __name__ == '__main__':
    try:
        p.main(boot.artifacts, boot.migration_artifacts)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
