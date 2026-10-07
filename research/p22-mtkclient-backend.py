#!/usr/bin/env python3
"""Bounded, verified boot/p22 writer used only through p22-flash-wrapper.sh.

The wrapper owns the writer lock and process session. Its private JSON config
selects one candidate or rescue SHA. Exit 1 means a *device-free* scan timeout;
all connected failures are fatal (2), never a supervisor scan retry.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

MTK = '/nix/store/vl6ynxsir46vp8w3445w342vdf0xm23b-mtkclient-gemini-2.1.4.1/bin/mtk'
MTK_RTC = '/nix/store/siwn7pa37bxykp85jkvb0i9mqwjlzajw-mtkclient-gemini-rtc-2.1.4.1/bin/mtk'
SIZE = 16777216
ACK = 'Download agent acknowledged reboot request'
WRITE_ACK = 'Wrote boot.img to sector 362496 with sector count 32768.'
COMMANDS = ('da peek 0x10007024 4 --filename boot-phase.bin;'
            'da peek 0x44410000 0xe0000 --filename ramoops.bin;'
            'printgpt;ro 0 0x8000 gpt-primary.bin;w boot boot.img;'
            'r boot boot-readback.img;reset --bootmode reboot')
KEYS = {'version', 'mtk', 'stage_image', 'candidate_state', 'rollback_state',
        'candidate_sha256', 'rollback_sha256', 'gpt_sha256', 'usb_port'}
UNKNOWN = ('unknown', '', '')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def config_for_state(config, state):
    if set(config) != KEYS or config['version'] != 1 or config['mtk'] not in (MTK, MTK_RTC):
        raise ValueError('Unqualified mtkclient or invalid backend configuration')
    for key in ('candidate_sha256', 'rollback_sha256', 'gpt_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', config[key]):
            raise ValueError('Invalid SHA-256: ' + key)
    if not re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*', config['usb_port']):
        raise ValueError('Invalid physical USB port')
    for key in ('stage_image', 'candidate_state', 'rollback_state'):
        if not Path(config[key]).is_absolute():
            raise ValueError('Backend paths must be absolute')
    if config['candidate_state'] == config['rollback_state']:
        raise ValueError('Candidate and rollback state must differ')
    for role in ('candidate', 'rollback'):
        if str(state) == config[role + '_state']:
            return config[role + '_sha256']
    raise ValueError('State does not identify this candidate or rollback attempt')


def command_sequence(tool):
    if tool == MTK_RTC:
        return COMMANDS + ' --preserve-rtc'
    if tool == MTK:
        return COMMANDS
    raise ValueError('Unpinned mtkclient command sequence')


def checked_image(path, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != SIZE:
        raise ValueError('Stage image must be a regular, complete 16 MiB file')
    data = path.read_bytes()
    if len(data) != SIZE or digest(data) != expected:
        raise ValueError('Stage image SHA-256 mismatch')
    return data


def usb_snapshot(port):
    path = Path('/sys/bus/usb/devices') / port
    try:
        number = (path / 'devnum').read_text().strip()
        state = ((path / 'idVendor').read_text().strip(),
                 (path / 'idProduct').read_text().strip(), number)
        return state if (path / 'devnum').read_text().strip() == number else UNKNOWN
    except OSError as error:
        if error.errno not in (errno.ENOENT, errno.ENODEV):
            raise
        # Incomplete sysfs publication is not proof of USB departure.
        # A disappearing device can return ENODEV before its files vanish.
        return UNKNOWN if path.exists() else None


class BootWindow:
    """Observe DA -> absent -> first normal preloader -> departed.

    Publishing completion at DA ACK, or sleeping a fixed interval, can let
    rescue catch the first normal preloader and erase an unexecuted candidate.
    Keep sampling from before DA entry, including while the child exits.
    """
    def __init__(self):
        self.da = None
        self.first_boot = None
        self.da_departed = False
        self.complete = False
        self.acknowledged = False
        self.events = []

    def observe(self, state, stamp):
        if state == UNKNOWN:
            return
        if not self.events or self.events[-1]['usb'] != state:
            self.events.append({'monotonic': stamp, 'usb': state})
        is_mtk = state is not None and state[0] == '0e8d'
        if self.da is None:
            if is_mtk:
                self.da = state
            return
        if state != self.da:
            self.da_departed = True
        if self.first_boot is None:
            if is_mtk and state != self.da:
                if not self.acknowledged:
                    raise RuntimeError('Unexpected USB re-enumeration before reboot acknowledgement')
                if state[1] != '2000':
                    raise RuntimeError('First post-DA device is not normal preloader')
                self.first_boot = state
        elif state != self.first_boot:
            self.complete = True


def verify_result(returncode, log, directory, expected, gpt_sha):
    if returncode != 0 or ACK not in log or WRITE_ACK not in log.splitlines():
        raise RuntimeError('Missing successful exact boot write or reboot acknowledgement')
    for name, size, sha in (('boot-readback.img', SIZE, expected),
                            ('gpt-primary.bin', 32768, gpt_sha)):
        path = directory / name
        if path.stat().st_size != size or digest(path.read_bytes()) != sha:
            raise RuntimeError(name + ': readback length or SHA-256 mismatch')
    if (directory / 'boot-phase.bin').stat().st_size != 4:
        raise RuntimeError('TOPRGU phase read must return exactly four bytes')
    if (directory / 'ramoops.bin').stat().st_size != 0xe0000:
        raise RuntimeError('Ramoops RAM capture is incomplete')


def scan_missed(returncode, log, window):
    # Upstream exit 1 can also mean a write failure. Only GNU timeout with no
    # observed MediaTek device and no handshake evidence is retryable.
    return (returncode == 124 and window.da is None and
            'Waiting for PreLoader' in log and 'Detected' not in log and
            'HW code:' not in log and 'DAXFlash' not in log)


def attempt(config, state, directory, expected):
    image = checked_image(Path(config['stage_image']), expected)
    (directory / 'boot.img').write_bytes(image)
    (directory / 'boot.img').chmod(0o400)
    for name in ('gpt-primary.bin', 'boot-readback.img', 'boot-phase.bin', 'ramoops.bin'):
        (directory / name).touch(exist_ok=False)
    window = BootWindow()
    window.observe(usb_snapshot(config['usb_port']), time.monotonic())
    for vendor in Path('/sys/bus/usb/devices').glob('*/idVendor'):
        if vendor.parent.name != config['usb_port'] and vendor.read_text().strip() == '0e8d':
            raise RuntimeError('A MediaTek device is exposed on another physical port')
    logpath = directory / 'mtk.log'
    command = ['sudo', '-n', 'env', 'PYTHONUNBUFFERED=1', 'timeout', '--foreground',
               '--kill-after=5s', '180s', config['mtk'], 'multi', command_sequence(config['mtk'])]
    save(directory / 'command.json', command)
    ready = False
    error = None
    with logpath.open('w') as output:
        # sudo normally closes descriptors >=3. Duplicate the writer lock to
        # stdin so the bounded privileged client itself retains it if its
        # observer/wrapper is lost. The fixed multi command needs no input.
        child = subprocess.Popen(command, cwd=directory, stdout=output,
                                 stderr=subprocess.STDOUT, stdin=9)
        try:
            while child.poll() is None:
                log = logpath.read_text(errors='replace')
                window.acknowledged |= ACK in log
                window.observe(usb_snapshot(config['usb_port']), time.monotonic())
                if not ready and 'Waiting for PreLoader' in log:
                    state.write_text('tool_started ' + time.strftime('%FT%T%z') + '\n')
                    ready = True
                time.sleep(0.05)
        except Exception as caught:
            error = caught
        finally:
            # The privileged timeout reaps its client before any terminal
            # state releases the supervisor to another attempt.
            child.wait(timeout=190)
    log = logpath.read_text(errors='replace')
    window.acknowledged |= ACK in log
    save(directory / 'exit.json', {'returncode': child.returncode})
    try:
        if error is not None:
            raise error
        if scan_missed(child.returncode, log, window):
            return 1
        verify_result(child.returncode, log, directory, expected, config['gpt_sha256'])
        deadline = time.monotonic() + 30
        while not window.complete and time.monotonic() < deadline:
            window.observe(usb_snapshot(config['usb_port']), time.monotonic())
            time.sleep(0.05)
        if not window.complete or not window.da_departed:
            raise RuntimeError('First post-DA preloader departure was not observed')
        return 0
    finally:
        save(directory / 'usb-events.json', window.events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    # Require the wrapper's inherited, already locked descriptor.
    os.fstat(9)
    if args.config.is_symlink() or args.config.stat().st_nlink != 1:
        raise ValueError('Backend config must be a private regular file')
    config = json.loads(args.config.read_text())
    expected = config_for_state(config, args.state)
    directory = Path(tempfile.mkdtemp(prefix=args.state.name + '-mtk-', dir=args.state.parent))
    result = {'attempt': str(directory), 'expected_sha256': expected,
              'backend': 'mtkclient', 'first_boot_window_departed': False}
    rc = 2
    try:
        rc = attempt(config, args.state, directory, expected)
        result.update(returncode=rc, first_boot_window_departed=(rc == 0))
        if rc == 0:
            phase = int.from_bytes((directory / 'boot-phase.bin').read_bytes(), 'little')
            result['toprgu_phase_before_write'] = f'0x{phase:08x}'
    except Exception as error:
        result['error'] = str(error)
        print(str(error), file=sys.stderr, flush=True)
    finally:
        result['returncode'] = rc
        save(args.state.with_name(args.state.name + '.mtk.json'), result)
    return rc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
