#!/usr/bin/env python3
"""Gate a supervised HS52 image trial on native storage and desktop integration.

Brackets existing storage checks with native MMC IOS/error observations.
Clock-register acceptance belongs to the native MSDC driver.
Uses the existing boot/storage recovery owner. Bluetooth checks are read-only;
the network check requests one bounded diagnostic scan without changing a
profile or connection. Audio checks inspect the active onboard route. A failed
check prevents candidate promotion. RTC alarm/calendar qualification belongs to
test-boot.py; this focused deployment retains its writer, storage and recovery
checks without repeating the established RTC tests. Normal boot runs none of
these diagnostics.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

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


MMC_REMOTE_CODE = r'''
import json, re, sys
from pathlib import Path

class CheckError(Exception):
    pass

def require(value, reason):
    if not value:
        raise CheckError(reason)

def read(path, limit=256):
    with path.open('rb') as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, 'attribute_too_large')
    return value.decode('ascii').strip()

def uint(value, maximum=2**32-1):
    require(re.fullmatch(r'[0-9]+', value) is not None, 'invalid_number')
    number = int(value)
    require(number <= maximum, 'number_out_of_range')
    return number

def identity(boot_id, system):
    require(read(Path('/proc/sys/kernel/random/boot_id')) == boot_id,
            'boot_identity_changed')
    require(str(Path('/run/current-system').resolve(strict=True)) == system,
            'system_identity_changed')
    require(read(Path('/proc/sys/kernel/tainted')) == '0', 'kernel_tainted')

IOS_FIELDS = ('clock', 'actual clock', 'vdd', 'bus mode', 'chip select',
              'power mode', 'bus width', 'timing spec', 'signal voltage', 'driver type')
ERROR_FIELDS = ('Command Timeout Occurred', 'Command CRC Errors Occurred',
                'Data Timeout Occurred', 'Data CRC Errors Occurred',
                'Auto-Cmd Error Occurred', 'ADMA Error Occurred', 'Tuning Error Occurred',
                'CMDQ RED Errors', 'CMDQ GCE Errors', 'CMDQ ICCE Errors',
                'Request Timedout', 'CMDQ Request Timedout', 'ICE Config Errors',
                'Controller Timedout errors', 'Unexpected IRQ errors')

def rows(path, fields, pattern):
    values = {}
    for line in read(path, 4096).splitlines():
        match = re.fullmatch(pattern, line)
        require(match is not None, 'malformed_attribute')
        key = match[1]
        require(key in fields and key not in values, 'missing_or_duplicate_field')
        values[key] = uint(match[2])
    require(set(values) == set(fields), 'missing_or_duplicate_field')
    return values

def fingerprint(paths):
    result = []
    for path in paths:
        direct, target = path.lstat(), path.stat()
        result.append([direct.st_dev, direct.st_ino, target.st_dev, target.st_ino])
    return result

def snapshot(boot_id, system):
    identity(boot_id, system)
    native = Path('/sys/bus/platform/devices/11230000.mmc')
    require((native / 'driver').resolve(strict=True).name == 'mtk-msdc', 'native_driver_missing')
    require(read(native / 'of_node/compatible') == 'mediatek,mt6797-mmc\0',
            'native_compatible_differs')
    hosts = list(Path('/sys/class/mmc_host').iterdir())
    require(len(hosts) <= 64, 'too_many_hosts')
    hosts = [host for host in hosts if re.fullmatch(r'mmc[0-9]+', host.name) and
             host.resolve(strict=True).parent.parent == native.resolve(strict=True)]
    require(len(hosts) == 1, 'native_host_not_unique')
    host = hosts[0]
    debug = Path('/sys/kernel/debug') / host.name
    source = Path('/sys/kernel/debug/clk/infra_msdc0/clk_rate')
    paths = [native, native / 'driver', native / 'of_node', host,
             debug / 'ios', debug / 'err_stats', source]
    owner = fingerprint(paths)
    ios = rows(debug / 'ios', IOS_FIELDS, r'([^:]+):\s+([0-9]+)(?:\s+[^\r\n]+)?')
    errors = rows(debug / 'err_stats', ERROR_FIELDS, r'# ([^:]+):\s+([0-9]+)')
    source_hz = uint(read(source))
    require(source_hz > 0, 'source_clock_zero')
    require(ios['clock'] == 52000000 and ios['timing spec'] == 1 and
            ios['bus width'] == 3 and ios['signal voltage'] == 1 and
            ios['power mode'] == 2, 'not_standard_hs52')
    # Native MSDC SDR divider; actual_clock is computed, not a frequency meter.
    requested = ios['clock']
    if requested >= source_hz:
        expected = source_hz
    elif requested >= source_hz >> 1:
        expected = source_hz >> 1
    else:
        divisor = (source_hz + requested * 4 - 1) // (requested * 4)
        expected = (source_hz >> 2) // divisor
    require(26000000 < expected <= requested and ios['actual clock'] == expected,
            'computed_clock_differs')
    require(not any(errors.values()), 'native_error_counter_nonzero')
    require(fingerprint(paths) == owner, 'owner_changed_during_snapshot')
    identity(boot_id, system)
    return dict(schema=1, result='passed', error='none', identity_preserved=True,
                host=host.name, owner_fingerprint=owner, ios=ios, source_hz=source_hz,
                errors=[errors[name] for name in ERROR_FIELDS],
                ios_alone_qualifies_raw_clock=False, clock_verification_owner='native_mtk_msdc')

if __name__ == '__main__':
    try:
        record = snapshot(*sys.argv[1:])
    except CheckError as error:
        record = dict(result='failed', error=str(error))
    except Exception:
        record = dict(result='failed', error='mmc_owner_read_failed')
    print(json.dumps(record, sort_keys=True))
    sys.exit(0 if record['result'] == 'passed' else 1)
'''


def verify_mmc_report(raw):
    def unique(pairs):
        record = dict(pairs)
        if len(record) != len(pairs):
            raise ValueError('Duplicate MMC report field')
        return record
    record = json.loads(raw, object_pairs_hook=unique)
    try:
        valid = (record['schema'] == 1 and type(record['schema']) is int and
                 record['result'] == 'passed' and record['error'] == 'none' and
                 record['identity_preserved'] is True and
                 record['ios_alone_qualifies_raw_clock'] is False and
                 record['clock_verification_owner'] == 'native_mtk_msdc')
        valid &= isinstance(record['host'], str) and record['host'].startswith('mmc') and record['host'][3:].isdecimal()
        owner = record['owner_fingerprint']
        valid &= isinstance(owner, list) and len(owner) == 7
        valid &= all(isinstance(row, list) and len(row) == 4 and
                     all(type(n) is int and 0 <= n < 2**64 for n in row) for row in owner)
        valid &= type(record['source_hz']) is int and 0 < record['source_hz'] < 2**32
        ios = record['ios']
        valid &= isinstance(ios, dict) and len(ios) == 10
        valid &= all(type(n) is int and 0 <= n < 2**32 for n in ios.values())
        valid &= all(ios[key] == value for key, value in
                     (('clock', 52000000), ('timing spec', 1), ('bus width', 3),
                      ('signal voltage', 1), ('power mode', 2)))
        valid &= 26000000 < ios['actual clock'] <= ios['clock']
        valid &= record['errors'] == [0] * 15 and all(type(n) is int for n in record['errors'])
    except (KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise RuntimeError('Native MMC high-speed evidence incomplete')
    return record


def mmc_snapshot(runner, ssh, boot_id, system, directory, phase):
    out = Path(directory) / 'mmc-high-speed'
    out.mkdir(mode=0o700, exist_ok=True)
    script = 'set -eu\n' + network.PYTHON_INTERPRETER
    script += 'timeout --signal=TERM --kill-after=2 10 "$python" - ' + shlex.join(
        [boot_id, system]) + " <<'GEMINI_MMC_PY'\n" + MMC_REMOTE_CODE + '\nGEMINI_MMC_PY\n'
    try:
        raw = runner.persistence.run(ssh, script, out, phase, timeout=15)
        record = verify_mmc_report(raw)
    except Exception:
        raise RuntimeError('Native MMC observation failed; see its scalar evidence') from None
    runner.qualify.save(out, phase + '.json', record)
    return record


def install_mmc_gate(runner):
    # configure() gives each trial a fresh runner; leave its shared module intact.
    previous = runner.persistent_nix.evidence
    original = getattr(previous, '_mmc_original', previous)
    runner.persistent_nix = SimpleNamespace(**vars(runner.persistent_nix))

    def evidence(ssh, boot_id, directory, qualify, persistence, **kwargs):
        snapshots = {}
        out = Path(directory) / 'mmc-high-speed'
        out.mkdir(mode=0o700, exist_ok=True)
        try:
            snapshots['before'] = mmc_snapshot(runner, ssh, boot_id, kwargs['system'], directory, 'before')
            result = original(ssh, boot_id, directory, qualify, persistence, **kwargs)
            snapshots['after'] = mmc_snapshot(runner, ssh, boot_id, kwargs['system'], directory, 'after')
            if snapshots['before'] != snapshots['after']:
                raise RuntimeError('Native MMC owner or high-speed state changed across storage checks')
        except Exception as error:
            qualify.save(out, 'result.json', dict(result='failed', snapshots=snapshots,
                                                 error_class=type(error).__name__))
            raise
        qualify.save(out, 'result.json', dict(result='passed', boot_id=boot_id,
            system=kwargs['system'], snapshots=snapshots, existing_storage_checks_completed=True,
            ios_alone_qualifies_raw_clock=False, clock_verification_owner='native_mtk_msdc',
            storage_benchmark_performed=False))
        return result

    evidence._mmc_original = original
    runner.persistent_nix.evidence = evidence


USB_REMOTE_CODE = r'''
import errno, json, re, socket, sys, time
from pathlib import Path

class CheckError(Exception):
    pass

def require(condition, reason):
    if not condition:
        raise CheckError(reason)

def identity():
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == sys.argv[1],
            'boot_identity_changed')
    require(str(Path('/run/current-system').resolve()) == sys.argv[2],
            'system_identity_changed')
    record['taint'] = int(Path('/proc/sys/kernel/tainted').read_text().strip())
    require(record['taint'] == 0, 'kernel_tainted')

def connector_state():
    expected = {('i2c@11008000', b'onsemi,fusb301'): 'left',
                ('i2c@11007000', b'onsemi,fusb301a'): 'right'}
    result = {}
    ports = [p for p in Path('/sys/class/typec').iterdir()
             if re.fullmatch(r'port[0-9]+', p.name)]
    for device in Path('/sys/bus/i2c/devices').iterdir():
        if not re.fullmatch(r'[0-9]+-0025', device.name) or not (device / 'of_node').exists():
            continue
        node = (device / 'of_node').resolve(strict=True)
        compatible = (node / 'compatible').read_bytes().split(b'\0')
        for (parent, kind), label in expected.items():
            if node.name != 'typec@25' or node.parent.name != parent or kind not in compatible:
                continue
            require(label not in result and (device / 'driver').resolve(strict=True).name == 'fusb301',
                    'native_controller_missing_or_duplicate')
            matches = [p for p in ports if device.resolve(strict=True) in p.resolve(strict=True).parents]
            require(len(matches) == 1, 'native_port_not_unique')
            port = matches[0]
            orientation = (port / 'orientation').read_text().strip()
            require(orientation in ('unknown', 'normal', 'reverse'), 'unexpected_orientation')
            data_role = (port / 'data_role').read_text().strip()
            require(data_role == ('[device]' if label == 'left' else '[host]'),
                    'unexpected_data_role')
            result[label] = {'orientation': orientation, 'data_role': data_role[1:-1],
                             'partner': port.with_name(port.name + '-partner').is_dir()}
    require(set(result) == {'left', 'right'} and len(ports) == 2, 'native_controllers_missing')
    roles = list(Path('/sys/class/usb_role').iterdir())
    require(len(roles) == 1, 'usb_role_not_unique')
    native = Path('/sys/bus/platform/devices/11271000.usb')
    require(native.resolve(strict=True) in roles[0].resolve(strict=True).parents and
            (native / 'driver').resolve(strict=True).name == 'mtu3', 'native_usb_role_missing')
    udcs = [u for u in Path('/sys/class/udc').iterdir()
            if native.resolve(strict=True) in u.resolve(strict=True).parents]
    require(len(udcs) == 1, 'native_udc_not_unique')
    result['usb_state'] = (udcs[0] / 'state').read_text().strip()
    require(result['left']['partner'] and result['left']['orientation'] != 'unknown' and
            result['usb_state'] == 'configured', 'usb_session_not_configured')
    return result

# Linux NETLINK_KOBJECT_UEVENT (15), multicast group 1; no udev properties persist.
record = {'result': 'failed', 'error': 'none',
          'counts': {s: {'change': 0, 'other': 0} for s in ('typec', 'usb_role')},
          'monitor_ready': False, 'monitor_closed': False, 'observation_seconds': 0,
          'state_preserved': False, 'identity_preserved': False, 'taint': 0}

def observe():
    identity()
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 15) as monitor:
        monitor.bind((0, 1))
        record['monitor_ready'] = True
        record['before'] = connector_state()
        started = time.monotonic()
        while (remaining := started + 6 - time.monotonic()) > 0:
            monitor.settimeout(remaining)
            try:
                payload, _, flags, peer = monitor.recvmsg(65536)
            except TimeoutError:
                continue
            except OSError as error:
                raise CheckError('uevent_overflow' if error.errno == errno.ENOBUFS
                                 else 'uevent_receive_failed') from None
            require(peer == (0, 1), 'uevent_not_kernel_multicast')
            require(not flags & socket.MSG_TRUNC, 'uevent_truncated')
            fields = payload.split(b'\0')
            require(fields[-1] == b'' and b'@/' in fields[0], 'uevent_malformed')
            selected = {}
            for field in fields[1:]:
                key, sep, value = field.partition(b'=')
                if key in (b'ACTION', b'SUBSYSTEM'):
                    require(sep and value and key not in selected, 'uevent_malformed')
                    selected[key] = value
            require(len(selected) == 2, 'uevent_malformed')
            for name, counts in record['counts'].items():
                if selected[b'SUBSYSTEM'] == name.encode():
                    counts['change' if selected[b'ACTION'] == b'change' else 'other'] += 1
        record['observation_seconds'] = round(time.monotonic() - started, 6)
        record['after'] = connector_state()
        record['state_preserved'] = record['before'] == record['after']
        identity()
        record['identity_preserved'] = True
    record['monitor_closed'] = monitor.fileno() == -1
    require(record['monitor_closed'] and record['state_preserved'], 'connector_state_changed')
    require(not any(n for counts in record['counts'].values() for n in counts.values()),
            'connector_events_repeated')
    record['result'] = 'passed'

if __name__ == '__main__':
    try:
        observe()
    except CheckError as error:
        record['error'] = str(error)
    except Exception:
        record['error'] = 'unexpected_usb_evidence_error'
    print(json.dumps(record, sort_keys=True))
    sys.exit(0 if record['result'] == 'passed' else 1)
'''


def verify_usb_report(raw):
    record = json.loads(raw)
    try:
        valid = record['result'] == 'passed' and record['error'] == 'none'
        valid &= all(record[k] is True for k in
                     ('monitor_ready', 'monitor_closed', 'state_preserved', 'identity_preserved'))
        duration = record['observation_seconds']
        valid &= type(duration) in (int, float) and 6 <= duration < 10
        valid &= type(record['taint']) is int and record['taint'] == 0
        valid &= record['counts'] == {s: {'change': 0, 'other': 0} for s in ('typec', 'usb_role')}
        valid &= all(type(n) is int for counts in record['counts'].values() for n in counts.values())
        valid &= record['before'] == record['after'] and record['before']['usb_state'] == 'configured'
        valid &= all(record['before'][label]['data_role'] == role
                     for label, role in (('left', 'device'), ('right', 'host')))
        valid &= (record['before']['left']['partner'] is True and
                  record['before']['left']['orientation'] in ('normal', 'reverse'))
    except (KeyError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise RuntimeError('Native USB-C steady-state event evidence incomplete')
    return record


def usb_evidence(runner, ssh, state, directory, system):
    out = Path(directory) / 'usb-typec'
    out.mkdir(mode=0o700)
    script = 'set -eu\n'
    script += network.PYTHON_INTERPRETER
    script += 'timeout --signal=TERM --kill-after=2 20 "$python" - ' + shlex.join(
        [state['boot_id'], system]) + " <<'GEMINI_USB_TYPEC_PY'\n"
    script += USB_REMOTE_CODE + '\nGEMINI_USB_TYPEC_PY\n'
    try:
        raw = runner.persistence.run(ssh, script, out, 'observe', timeout=30)
        record = verify_usb_report(raw)
    except Exception:
        if (out / 'observe.stdout').exists():
            try:
                runner.qualify.save(out, 'result.json', json.loads((out / 'observe.stdout').read_text()))
            except (ValueError, OSError):
                pass
        raise RuntimeError('Native USB-C observation failed; see its scalar evidence') from None
    record.update(boot_id=state['boot_id'], system=system,
                  detach_attach_qualified=False, source_power_qualified=False,
                  desktop_responsiveness_qualified=False)
    runner.qualify.save(out, 'result.json', record)
    print('PASS: native USB-C configured session without repeated change events', flush=True)
    return record


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


base_configure = boot.base_configure
p.preflight = boot.boot_preflight
p.finish = boot.boot_finish


def configure(*args, **kwargs):
    runner = base_configure(*args, **kwargs)
    runner.CANDIDATE_DESKTOP = 'gnome'
    runner.backend.MTK = runner.backend.MTK_RTC
    install_mmc_gate(runner)
    candidate = runner.candidate_return

    def qualified(ssh, before, directory, profile):
        state = candidate(ssh, before, directory, profile)
        results = {}
        try:
            results['mmc_high_speed'] = json.loads((directory / 'mmc-high-speed' / 'result.json').read_text())
            results['usb_typec'] = usb_evidence(runner, ssh, state, directory, p.SYSTEM)
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
            rtc_alarm_calendar_diagnostics_run=False,
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
