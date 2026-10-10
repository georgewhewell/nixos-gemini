#!/usr/bin/env python3
"""Bounded NM directed/wildcard scan evidence; never changes a connection.

Only the existing NetworkManager and its existing supplicant own the radio.
The fixture SSID is synthetic. Network identifiers and journal text stay in
device memory; evidence contains counts, states and connection-preservation
booleans. RequestScan is asynchronous, so its successful reply is not proof
until LastScan advances and the supplicant has finished scanning.
"""
import json
from pathlib import Path
import shlex

REMOTE_CODE = r'''
import json, re, subprocess, sys, time
from pathlib import Path

NM = 'org.freedesktop.NetworkManager'
NMD = NM + '.Device'
NMW = NMD + '.Wireless'
WPA = 'fi.w1.wpa_supplicant1'
WPI = WPA + '.Interface'
started = time.monotonic()
deadline = started + 150
record = {'result': 'failed', 'manual_connection_actions': 0,
          'scan_requests': 0, 'request_mode': 'synthetic_named_plus_wildcard',
          'association_qualified': False, 'data_qualified': False}

class CheckError(Exception):
    pass

def require(condition, reason):
    if not condition:
        raise CheckError(reason)

def command(argv):
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'total_timeout')
    result = subprocess.run(argv, text=True, capture_output=True,
                            timeout=min(8, remaining))
    require(result.returncode == 0, 'device_command_failed')
    return result.stdout.strip()

def identity():
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == sys.argv[1],
            'boot_identity_changed')
    require(str(Path('/run/current-system').resolve()) == sys.argv[2],
            'system_identity_changed')

def prop(service, path, interface, name):
    return command(['busctl', '--system', 'get-property', service, path, interface, name])

def path_reply(value):
    match = re.fullmatch(r'o "(/[A-Za-z0-9_/]*)"', value)
    require(match is not None, 'unexpected_object_path')
    return match[1]

def number(value, signature):
    require(re.fullmatch(signature + r' -?\d+', value) is not None,
            'unexpected_numeric_property')
    return int(value.split()[1])

def unit_pid(unit):
    return number('u ' + command(['systemctl', 'show', unit, '-p', 'MainPID', '--value']), 'u')

def unit_executable(unit):
    value = command(['systemctl', 'show', unit, '-p', 'ExecStart', '--value'])
    match = re.search(r'(?:^|\{\s*)path=([^ ;}]+)', value)
    require(match is not None, 'unit_executable_missing')
    executable = Path(match[1]).resolve(strict=True)
    if executable.name in ('wpa_supplicant', '.wpa_supplicant-wrapped'):
        return executable
    # NixOS uses a unit start script that execs the package binary.
    matches = re.findall(r'^exec\s+((?:/nix/store/[^\s;]+/(?:bin|sbin)/)?(?:wpa_supplicant|\.wpa_supplicant-wrapped))(?=\s|$)',
                         executable.read_text(), re.M)
    require(len(matches) == 1, 'supplicant_unit_binary_not_unique')
    binary = Path(matches[0])
    if binary.is_absolute():
        return binary.resolve(strict=True)
    # NixOS 26.11 uses `exec wpa_supplicant $args`. Resolve that exact
    # command with the running unit's PATH, in shell search order.
    environment = dict(item.split(b'=', 1) for item in
                       Path('/proc', str(unit_pid(unit)), 'environ').read_bytes().split(b'\0')
                       if b'=' in item)
    require(b'PATH' in environment, 'supplicant_unit_path_missing')
    for entry in environment[b'PATH'].decode().split(':'):
        require(entry.startswith('/'), 'supplicant_unit_path_not_absolute')
        candidate = Path(entry) / binary
        if candidate.is_file():
            return candidate.resolve(strict=True)
    raise CheckError('supplicant_unit_binary_missing')

def scanning():
    value = prop(WPA, supplicant, WPI, 'Scanning')
    require(value in ('b true', 'b false'), 'unexpected_scan_state')
    return value == 'b true'

def state():
    return number(prop(NM, device, NMD, 'State'), 'u')

def last_scan():
    return number(prop(NM, device, NMW, 'LastScan'), 'x')

def active_connection():
    return path_reply(prop(NM, device, NMD, 'ActiveConnection'))

def snapshot():
    netdevs = [entry for entry in wifi.joinpath('net').iterdir() if entry.is_dir()]
    bound = wifi.joinpath('driver').resolve().name == 'mt6797-wifi'
    kernel = command(['journalctl', '-k', '-b', '--no-pager', '-o', 'cat'])
    patterns = {
        'hif_faults': r'mt6797-wifi 180f0000.wifi: runtime HIF fault ',
        'hif_restarts': r'mt6797-wifi 180f0000.wifi: WLAN restarted after HIF fault ',
        'wlan_left_down': r'mt6797-wifi 180f0000.wifi: .*leaving it down',
        'radio_fences': r'mt6797-wifi 180f0000.wifi: .*reboot required',
        'shared_radio_fences': r'(?im)^.*(?:mt6797-consys|CONSYS|CONMCU|mt6797-btif|\bbtif\b|Bluetooth).*\b(?:reboot required|fenced|fatal|lifecycle is in ERROR)\b.*$',
    }
    counts = {key: len(re.findall(pattern, kernel)) for key, pattern in patterns.items()}
    counts.update(netdev_count=len(netdevs), driver_bound=bound)
    require(len(netdevs) == 1 and bound, 'wlan_registration_missing')
    return counts

def scan_failures(after_us=0):
    journal = command(['journalctl', '-b', '--no-pager', '-o', 'json',
                       '-u', 'NetworkManager', '-u', 'wpa_supplicant'])
    failures = unsupported = 0
    for line in journal.splitlines():
        entry = json.loads(line)
        if int(entry['__MONOTONIC_TIMESTAMP']) < after_us:
            continue
        message = entry.get('MESSAGE', '')
        if isinstance(message, str) and 'CTRL-EVENT-SCAN-FAILED' in message:
            failures += 1
            unsupported += bool(re.search(r'\b(?:errno|ret)=-?95\b', message))
    return {'scan_failed': failures, 'scan_failed_eopnotsupp': unsupported}

try:
    identity()
    wifi = Path('/sys/bus/platform/devices/180f0000.wifi')
    before = snapshot()
    require(not any(before[key] for key in ('hif_faults', 'hif_restarts',
                                          'wlan_left_down', 'radio_fences', 'shared_radio_fences')),
            'candidate_already_logged_radio_fault')
    interface = [entry.name for entry in wifi.joinpath('net').iterdir()
                 if entry.is_dir()][0]
    require(re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', interface) is not None,
            'unexpected_interface_name')
    for unit in ('NetworkManager', 'wpa_supplicant'):
        require(command(['systemctl', 'is-active', unit]) == 'active', 'owner_inactive')
    nm_pid = unit_pid('NetworkManager')
    pid = unit_pid('wpa_supplicant')
    require(nm_pid > 0, 'networkmanager_mainpid_missing')
    require(pid > 0, 'supplicant_mainpid_missing')
    executable = Path('/proc', str(pid), 'exe').resolve(strict=True)
    require(executable == unit_executable('wpa_supplicant'),
            'supplicant_unit_executable_differs')
    owners = 0
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            owners += process.joinpath('exe').resolve(strict=True) == executable
        except (FileNotFoundError, PermissionError):
            pass
    require(owners == 1, 'supplicant_owner_not_unique')
    device = path_reply(command(['busctl', '--system', 'call', NM,
                        '/org/freedesktop/NetworkManager', NM,
                        'GetDeviceByIpIface', 's', interface]))
    supplicant = path_reply(command(['busctl', '--system', 'call', WPA,
                            '/fi/w1/wpa_supplicant1', WPA, 'GetInterface', 's', interface]))
    require(prop(NM, device, NMD, 'Managed') == 'b true', 'device_not_managed')
    quiet_deadline = time.monotonic() + 35
    while scanning() and time.monotonic() < quiet_deadline:
        time.sleep(1)
    initial_state = state()
    require(not scanning() and initial_state in (30, 40, 50, 60, 100),
            'existing_scan_or_unavailable_device')
    original = active_connection() if initial_state == 100 else None
    record['initially_connected'] = original is not None and original != '/'
    require(initial_state != 100 or original != '/', 'active_connection_missing')
    initial_last_scan = last_scan()
    # Journal timestamps use CLOCK_MONOTONIC; LastScan uses CLOCK_BOOTTIME.
    request_us = time.monotonic_ns() // 1000
    fixture = b'gemini-driver-scan-check'
    argv = ['busctl', '--system', 'call', NM, device, NMW,
            'RequestScan', 'a{sv}', '1', 'ssids', 'aay', '2',
            str(len(fixture)), *[str(byte) for byte in fixture], '0']
    record['request_attempts'] = 0
    for attempt in range(5):
        record['request_attempts'] += 1
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'total_timeout')
        reply = subprocess.run(argv, text=True, capture_output=True,
                               timeout=min(8, remaining))
        if reply.returncode == 0:
            record['scan_requests'] = 1
            break
        # NM may temporarily deny scans during its own association or throttle
        # a recent scan. Only retry this admission denial; change no profiles.
        retryable = bool(re.search(r'NotAllowed|Busy|Scanning not allowed', reply.stderr))
        require(retryable and attempt < 4 and time.monotonic() < quiet_deadline,
                'networkmanager_scan_request_rejected')
        time.sleep(min(8, quiet_deadline - time.monotonic()))
    scan_deadline = time.monotonic() + 90
    observed_scanning = False
    while time.monotonic() < scan_deadline:
        busy = scanning()
        observed_scanning |= busy
        current_last_scan = last_scan()
        if current_last_scan > initial_last_scan and not busy:
            break
        time.sleep(1)
    else:
        raise CheckError('asynchronous_scan_completion_timeout')
    require(original is None or active_connection() == original, 'existing_connection_changed')
    time.sleep(5)
    identity()
    require(unit_pid('NetworkManager') == nm_pid and unit_pid('wpa_supplicant') == pid,
            'network_owner_restarted')
    require(Path('/proc', str(pid), 'exe').resolve(strict=True) == executable and
            unit_executable('wpa_supplicant') == executable,
            'supplicant_unit_executable_changed')
    after = snapshot()
    require(after == before, 'radio_health_changed')
    failures = scan_failures(request_us)
    require(not failures['scan_failed'], 'supplicant_scan_failed')
    require(original is None or (state() == 100 and active_connection() == original),
            'existing_connection_not_preserved')
    record.update(result='passed', last_scan_advanced=True,
                  supplicant_scan_complete=True, scanning_observed=observed_scanning,
                  original_connection_preserved=True, before=before, after=after,
                  scan_failure_counts=failures, final_nm_state=state(),
                  duration_seconds=round(time.monotonic() - started, 3),
                  boot_identity_preserved=True, system_identity_preserved=True)
except CheckError as error:
    record['failure'] = str(error)
except subprocess.TimeoutExpired:
    record['failure'] = 'device_command_timeout'
except Exception:
    record['failure'] = 'unexpected_device_evidence_error'
print(json.dumps(record, sort_keys=True))
sys.exit(0 if record['result'] == 'passed' else 1)
'''


def network_evidence(runner, ssh, state, directory, system):
    out = Path(directory) / 'networkmanager-scan'
    out.mkdir(mode=0o700)
    guard = 'set -eu\n'
    guard += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
    guard += 'test "$(readlink /run/current-system)" = ' + shlex.quote(system) + '\n'
    # The image already contains this importer interpreter. Use its systemd
    # executable path rather than assuming Python belongs to systemPackages.
    interpreter = r'''python=$(systemctl show gemini-network-profiles.service -p ExecStart --value | sed -n 's/^{ path=\([^ ;]*\) ;.*$/\1/p')
case "$python" in /nix/store/*/bin/python3) ;; *) exit 1 ;; esac
test -x "$python"
'''
    script = guard + interpreter
    script += 'timeout --signal=TERM --kill-after=2 155 "$python" - ' + shlex.join(
        [state['boot_id'], system]) + " <<'GEMINI_NM_SCAN_PY'\n"
    script += REMOTE_CODE + '\nGEMINI_NM_SCAN_PY\n'
    try:
        raw = runner.persistence.run(ssh, script, out, 'scan', timeout=175)
        record = json.loads(raw)
    except Exception:
        # The remote runner retains only our sanitized JSON/stdout/stderr.
        if (out / 'scan.stdout').exists():
            try:
                runner.qualify.save(out, 'result.json', json.loads((out / 'scan.stdout').read_text()))
            except (ValueError, OSError):
                pass
        raise
    if record.get('result') != 'passed' or record.get('scan_requests') != 1:
        raise RuntimeError('NetworkManager directed/wildcard scan evidence incomplete')
    record.update(boot_id=state['boot_id'], system=system)
    runner.qualify.save(out, 'result.json', record)
    print('PASS: NM directed/wildcard scan completed; WLAN healthy and existing connection preserved', flush=True)
    return record
