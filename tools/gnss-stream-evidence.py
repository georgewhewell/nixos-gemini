#!/usr/bin/env python3
"""Bounded GNSS power-cycle evidence; no receiver commands or raw capture.

Opening the endpoint powers GNSS on despite O_RDONLY. Closing it must return
the optional LNA vote to zero. Only scalar stream/status metadata is retained;
the receiver protocol and position remain unqualified even when bytes arrive.
"""
import json
from pathlib import Path
import shlex
import subprocess

PYTHON = '/nix/store/81jsmi7hxdbcikna1zxj49qnr856mcra-python3-aarch64-unknown-linux-gnu-3.14.7/bin/python3'

REMOTE_CODE = r'''
import errno, json, os, selectors, signal, stat, sys, time
from pathlib import Path

class CheckError(Exception):
    pass

def require(condition, reason):
    if not condition:
        raise CheckError(reason)

def identity(boot, system):
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot,
            'identity_changed')
    require(str(Path('/run/current-system').resolve()) == system, 'identity_changed')

def registration_state(record):
    record['native_gnss_module_present'] = Path('/sys/module/gnss_mtk_consys').is_dir()
    record['class_registered'] = Path('/sys/class/gnss/gnss0').is_dir()
    record['gnss_node_present'] = Path('/dev/gnss0').exists()
    for device in Path('/sys/bus/platform/devices').iterdir():
        try:
            compatible = (device / 'of_node/compatible').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        if b'mediatek,mt6797-gnss' not in compatible:
            continue
        record['matching_platform_child_present'] = True
        driver = device / 'driver'
        record['driver_bound'] |= driver.is_symlink() and driver.resolve().name == 'mt6797-gnss'

def lna_state():
    matches = []
    for path in Path('/sys/class/regulator').glob('regulator.*'):
        if (path / 'name').read_text().strip() == 'gnss-lna':
            matches.append(path)
    require(len(matches) == 1, 'lna_not_unique')
    path = matches[0]
    state = (path / 'state').read_text().strip()
    require(state in ('enabled', 'disabled'), 'lna_state_unknown')
    return int((path / 'num_users').read_text().strip()), int(state == 'enabled')

class StreamMetadata:
    def __init__(self):
        self.pending = bytearray()
        self.counts = dict(bytes=0, printable_bytes=0, nmea_shapes=0,
                           nmea_checksum_valid=0, nmea_valid_fix_flags=0)

    def feed(self, data):
        self.counts['bytes'] += len(data)
        self.counts['printable_bytes'] += sum(32 <= byte <= 126 for byte in data)
        for byte in data:
            if byte == 36:
                self.pending = bytearray([byte])
            elif self.pending:
                if byte == 10:
                    self.sentence(bytes(self.pending).rstrip(b'\r'))
                    self.pending.clear()
                elif len(self.pending) >= 256 or (byte != 13 and not 32 <= byte <= 126):
                    self.pending.clear()
                else:
                    self.pending.append(byte)

    def sentence(self, line):
        # Public framing/status contract: https://gpsd.io/NMEA.html
        body, marker, checksum = line[1:].rpartition(b'*')
        fields = body.split(b',')
        if not marker or len(checksum) != 2 or len(fields[0]) != 5:
            return
        if not all(65 <= byte <= 90 for byte in fields[0]):
            return
        try:
            supplied = int(checksum, 16)
        except ValueError:
            return
        self.counts['nmea_shapes'] += 1
        calculated = 0
        for byte in body:
            calculated ^= byte
        if supplied != calculated:
            return
        self.counts['nmea_checksum_valid'] += 1
        kind = fields[0][2:]
        if ((kind == b'RMC' and len(fields) >= 12 and fields[2] == b'A') or
                (kind == b'GGA' and len(fields) >= 15 and fields[6] in
                 (b'1', b'2', b'3', b'4', b'5', b'6'))):
            self.counts['nmea_valid_fix_flags'] += 1

def observe(boot, system):
    metadata = StreamMetadata()
    record = dict(schema=1, result='failed', error='none', opened=False, closed=False,
                  errno=0, lna_before_users=None, lna_before_enabled=None,
                  lna_during_users=None, lna_during_enabled=None,
                  lna_after_users=None, lna_after_enabled=None,
                  taint_before=None, taint_after=None, read_window_seconds=10,
                  read_window_complete=False, boot_identity_preserved=False,
                  system_identity_preserved=False, receiver_commands_sent=0,
                  receiver_protocol_qualified=False, position_qualified=False,
                  native_gnss_module_present=False, matching_platform_child_present=False,
                  driver_bound=False, class_registered=False, gnss_node_present=False)
    descriptor = None
    started = time.monotonic()
    try:
        identity(boot, system)
        record['taint_before'] = int(Path('/proc/sys/kernel/tainted').read_text().strip())
        require(record['taint_before'] == 0, 'kernel_tainted')
        registration_state(record)
        require(stat.S_ISCHR(os.stat('/dev/gnss0').st_mode), 'endpoint_missing')
        require(Path('/sys/class/gnss/gnss0/device/driver').resolve().name == 'mt6797-gnss',
                'owner_differs')
        before = lna_state()
        record['lna_before_users'], record['lna_before_enabled'] = before
        require(before == (0, 0), 'lna_initially_active')
        descriptor = os.open('/dev/gnss0', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        record['opened'] = True
        during = lna_state()
        record['lna_during_users'], record['lna_during_enabled'] = during
        require(during == (1, 1), 'lna_on_failed')
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if not selector.select(max(0, deadline - time.monotonic())):
                    break
                try:
                    data = os.read(descriptor, 4096)
                except BlockingIOError:
                    continue
                require(bool(data), 'endpoint_eof')
                metadata.feed(data)
        record['read_window_complete'] = time.monotonic() >= deadline
        require(record['read_window_complete'], 'read_window_short')
    except CheckError as error:
        record['error'] = str(error)
    except OSError as error:
        record['errno'] = error.errno or errno.EIO
        record['error'] = 'os_error'
    except Exception:
        record['error'] = 'unexpected_error'
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
                record['closed'] = True
            except OSError as error:
                record['errno'] = error.errno or errno.EIO
                record['error'] = 'os_error'
        metadata.pending.clear()
        try:
            after = lna_state()
            record['lna_after_users'], record['lna_after_enabled'] = after
            require(after == (0, 0), 'lna_off_failed')
            identity(boot, system)
            record['boot_identity_preserved'] = record['system_identity_preserved'] = True
            record['taint_after'] = int(Path('/proc/sys/kernel/tainted').read_text().strip())
            require(record['taint_after'] == 0, 'kernel_tainted')
        except CheckError as error:
            record['error'] = str(error)
        except Exception:
            record['error'] = 'cleanup_observation_failed'
        record.update(metadata.counts)
        record['elapsed_ms'] = int((time.monotonic() - started) * 1000)
    if record['opened'] and record['closed'] and record['read_window_complete'] and record['error'] == 'none':
        record['result'] = 'passed'
    return record

def interrupted(signum, frame):
    raise CheckError('interrupted')

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    result = observe(sys.argv[1], sys.argv[2])
    print(json.dumps(result, sort_keys=True), flush=True)
    sys.exit(0 if result['result'] == 'passed' else 1)
'''

COUNTS = ('bytes', 'printable_bytes', 'nmea_shapes', 'nmea_checksum_valid',
          'nmea_valid_fix_flags', 'errno', 'elapsed_ms', 'receiver_commands_sent')
LNA = tuple('lna_' + phase + '_' + field for phase in ('before', 'during', 'after')
            for field in ('users', 'enabled'))
BOOLEANS = ('opened', 'closed', 'read_window_complete', 'boot_identity_preserved',
            'system_identity_preserved', 'receiver_protocol_qualified', 'position_qualified')
REGISTRATION = ('native_gnss_module_present', 'matching_platform_child_present',
                'driver_bound', 'class_registered', 'gnss_node_present')
FIELDS = set(COUNTS + LNA + BOOLEANS + REGISTRATION +
             ('schema', 'result', 'error', 'read_window_seconds', 'taint_before', 'taint_after'))


def verify_report(raw):
    if len(raw) > 4096:
        raise RuntimeError('GNSS scalar report exceeds its bound')
    record = json.loads(raw)
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise RuntimeError('GNSS report fields differ from the scalar schema')
    if (record['schema'] != 1 or record['result'] != 'passed' or record['error'] != 'none'
            or record['read_window_seconds'] != 10 or record['errno'] != 0
            or record['receiver_commands_sent'] != 0
            or any(type(record[key]) is not int or record[key] < 0 for key in
                   COUNTS + LNA + ('schema', 'read_window_seconds', 'taint_before', 'taint_after'))
            or any(type(record[key]) is not bool for key in BOOLEANS + REGISTRATION)
            or not all(record[key] for key in REGISTRATION)
            or not all(record[key] for key in BOOLEANS[:5])
            or any(record[key] for key in BOOLEANS[5:])
            or any(record[key] != value for key, value in zip(LNA, (0, 0, 1, 1, 0, 0)))
            or record['taint_before'] != 0 or record['taint_after'] != 0
            or not 10000 <= record['elapsed_ms'] <= 30000
            or record['printable_bytes'] > record['bytes']
            or record['nmea_checksum_valid'] > record['nmea_shapes']
            or record['nmea_valid_fix_flags'] > record['nmea_checksum_valid']):
        raise RuntimeError('GNSS power-cycle evidence is incomplete or failed')
    return record


def evidence(runner, ssh, state, directory, system, cycle):
    if cycle not in (1, 2):
        raise ValueError('GNSS cycle must be 1 or 2')
    out = Path(directory) / f'gnss-cycle-{cycle}'
    out.mkdir(mode=0o700)
    guard = 'set -eu\n'
    guard += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
    guard += 'test "$(readlink /run/current-system)" = ' + shlex.quote(system) + '\n'
    guard += 'test "$(cat /proc/sys/kernel/tainted)" = 0\n'
    script = guard + 'test -x ' + shlex.quote(PYTHON) + '\n'
    script += '! systemctl is-active --quiet gpsd.service\n'
    script += 'timeout --signal=TERM --kill-after=5s 30 ' + shlex.quote(PYTHON) + ' - ' + shlex.join(
        [state['boot_id'], system]) + " <<'GEMINI_GNSS_SCALAR_SOURCE'\n"
    script += REMOTE_CODE + '\nGEMINI_GNSS_SCALAR_SOURCE\n' + guard
    try:
        raw = runner.persistence.run(ssh, script, out, 'cycle', timeout=40)
    except subprocess.SubprocessError as error:
        raise RuntimeError(f'GNSS power cycle {cycle} failed; inspect {out / "cycle.stdout"}') from error
    record = verify_report(raw)
    runner.qualify.save(out, 'result.json', record)
    print(f'PASS: GNSS power cycle {cycle} closes with LNA off; receiver protocol and position unqualified',
          flush=True)
    return record
