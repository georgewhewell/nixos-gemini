#!/usr/bin/env python3
"""Qualify the Gemini's DA read/reboot path, optionally rewriting accepted boot.

Default: inspect accepted Linux and the host CLI. --execute: catch one normal
reboot, read GPT/boot through the DA, request normal boot, verify fresh Linux.
--rewrite-accepted-boot IMAGE additionally writes the exact accepted M69 image
to boot only; it rejects every other image. It still requires --execute.
Use --execute with someone available to force-restart the Gemini if it hangs.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ACCEPTED_BOOT = '913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3'
ACCEPTED_SYSTEM = '/nix/store/0xbrhrl8ym703g1449gni51dkv7jwlqv-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
COMMANDS = 'printgpt;ro 0 0x8000 gpt-primary.bin;r boot boot-readback.img;reset --bootmode reboot'
WRITE_COMMANDS = ('printgpt;ro 0 0x8000 gpt-primary.bin;w boot accepted-boot.img;'
                  'r boot boot-readback.img;reset --bootmode reboot')
ACK = 'Download agent acknowledged reboot request'
WRITE_ACK = 'Wrote accepted-boot.img to sector 362496 with sector count 32768.'
PHASE_READ = 'da peek 0x10007024 4 --filename boot-phase.bin'
RAMOOPS_READ = 'da peek 0x44410000 0xe0000 --filename ramoops.bin'
# M69 runs cellular, GPU, audio, connectivity and desktop checks before
# self-acceptance. A successful DA reboot exceeded the original 180s window.
HEALTH_TIMEOUT = 360
SNAPSHOT = r'''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'system='; readlink /run/current-system
printf 'boot_sha256='; sha256sum /dev/mmcblk0p22 | cut -d' ' -f1
printf 'gpt_sha256='; head -c 32768 /dev/mmcblk0 | sha256sum | cut -d' ' -f1
test "$(cat /sys/class/block/mmcblk0/size)" = 122142720
test "$(cat /sys/class/block/mmcblk0p22/start)" = 362496
test "$(cat /sys/class/block/mmcblk0p22/size)" = 32768
test "$(cat /sys/class/block/mmcblk0p32/size)" = 32737247
test ! -e /sys/class/block/mmcblk0p34
grep -qx 'unattended_recovery=healthy' /run/unattended-recovery.accepted
systemctl is-active gemini-desktop gemini-jpeg gemini-gpu gemini-wifi gemini-audio >/dev/null
test -z "$(systemctl --failed --no-legend --plain)"
printf 'healthy=yes\n'
'''


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          timeout=25, **kwargs).stdout


def snapshot(ssh):
    result = dict(line.split('=', 1) for line in run(ssh + [SNAPSHOT]).splitlines())
    if (result.get('boot_sha256') != ACCEPTED_BOOT or
            result.get('system') != ACCEPTED_SYSTEM or result.get('healthy') != 'yes'):
        raise RuntimeError('Gemini is not on healthy accepted M69')
    if not re.fullmatch(r'[0-9a-f-]{36}', result.get('boot_id', '')):
        raise RuntimeError('Missing boot identity')
    if not re.fullmatch(r'[0-9a-f]{64}', result.get('gpt_sha256', '')):
        raise RuntimeError('Missing GPT hash')
    return result


def verify_reads(directory, before):
    # Upstream read commands can return exit status zero on failure. Require
    # complete bytes matching the Linux preflight, independently of that code.
    for name, size, expected in (
            ('boot-readback.img', 16 * 1024 * 1024, before['boot_sha256']),
            ('gpt-primary.bin', 32768, before['gpt_sha256'])):
        path = directory / name
        if path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'{name}: length or SHA-256 mismatch')


def accepted_boot_bytes(path):
    if path.stat().st_size != 16 * 1024 * 1024:
        raise RuntimeError('Write input must be the complete 16 MiB accepted M69 boot image')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != ACCEPTED_BOOT:
        raise RuntimeError('Write input does not match the accepted M69 boot SHA-256')
    return data


def commands_for(writing, capture_phase, capture_ramoops=False):
    commands = WRITE_COMMANDS if writing else COMMANDS
    if capture_ramoops:
        commands = RAMOOPS_READ + ';' + commands
    return PHASE_READ + ';' + commands if capture_phase else commands


def phase_readback(directory):
    data = (directory / 'boot-phase.bin').read_bytes()
    if len(data) != 4:
        raise RuntimeError('TOPRGU phase read must return exactly four bytes')
    return {'address': '0x10007024', 'value_hex': f'0x{int.from_bytes(data, "little"):08x}',
            'retention_across_vendor_boot_stages_qualified': False}


def verify_da_result(returncode, log, writing):
    if returncode != 0 or ACK not in log:
        raise RuntimeError('Linux returned, but mtkclient did not acknowledge reboot successfully')
    # An identical-image readback alone cannot prove that a write succeeded.
    # This line is emitted only after the patched DA backend reports success.
    if writing and WRITE_ACK not in log.splitlines():
        raise RuntimeError('No acknowledged write to the exact accepted boot extent')


def verify_return(before, after):
    if before['boot_id'] == after['boot_id']:
        raise RuntimeError('SSH still reports the original boot')
    for key in ('boot_sha256', 'gpt_sha256', 'system', 'healthy'):
        if before[key] != after[key]:
            raise RuntimeError(f'Linux returned with changed {key}')


def save(directory, name, value):
    (directory / name).write_text(json.dumps(value, indent=2) + '\n')


def check_host_idle():
    rows = [line.split(None, 2) for line in run(['ps', '-eo', 'pid=,ppid=,args=']).splitlines()]
    parents = {int(pid): int(parent) for pid, parent, _ in rows}
    ancestors = set()
    pid = os.getpid()
    while pid and pid not in ancestors:
        ancestors.add(pid)
        pid = parents.get(pid, 0)
    for pid, _, command in rows:
        if int(pid) not in ancestors and re.search(
                r'(^|[ /])(\.?mtk(?:-wrapped|\.py)?|flash_tool|p22-proof-supervisor)(\s|$)', command):
            raise RuntimeError(f'An existing download/flash process is running (PID {pid})')
    for vendor in Path('/sys/bus/usb/devices').glob('*/idVendor'):
        if vendor.read_text().strip() == '0e8d':
            raise RuntimeError('A MediaTek USB device is already exposed; inspect before starting')


def trial(args, directory, before, ssh):
    writing = getattr(args, 'rewrite_accepted_boot', None) is not None
    capture_phase = getattr(args, 'capture_boot_phase', False)
    capture_ramoops = getattr(args, 'capture_ramoops', False)
    if writing:
        # Verify the private staged copy immediately before starting the DA.
        accepted_boot_bytes(directory / 'accepted-boot.img')
    commands = commands_for(writing, capture_phase, capture_ramoops)
    # A fresh working directory prevents accidental reuse of cached DA state.
    # The DA client runs as root and inherits umask 077. Create its readback
    # files as the invoking user so verification can read them afterwards.
    # Exclusive creation also prevents following a pre-existing symlink.
    readbacks = ['gpt-primary.bin', 'boot-readback.img']
    if capture_phase:
        readbacks.append('boot-phase.bin')
    if capture_ramoops:
        readbacks.append('ramoops.bin')
    for name in readbacks:
        with (directory / name).open('xb'):
            pass
    # timeout bounds the privileged child even if this observer is interrupted.
    command = ['sudo', '-n', 'env', 'PYTHONUNBUFFERED=1', 'timeout',
               '--kill-after=5s', '180s', str(args.mtk), 'multi', commands]
    logpath = directory / 'mtk.log'
    with logpath.open('w') as logfile:
        child = subprocess.Popen(command, cwd=directory, stdout=logfile,
                                 stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError('mtkclient exited before the reboot; inspect mtk.log')
                if 'Waiting for PreLoader' in logpath.read_text():
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError('mtkclient did not become ready; Linux was not rebooted')
            print('mtkclient is waiting; rebooting accepted Linux once', flush=True)
            # SSH may disconnect after systemd accepts the request; the later
            # fresh-boot check is the proof, not SSH's exit status here.
            result = subprocess.run(ssh + ['systemctl reboot'], capture_output=True,
                                    text=True, timeout=20)
            save(directory, 'reboot-request.json',
                 {'returncode': result.returncode, 'stderr': result.stderr})
            returncode = child.wait(timeout=185)
        finally:
            # Let the bounded timeout reap its own privileged process before
            # releasing the device locks, even on an observer-side exception.
            if child.poll() is None:
                print('Waiting for the bounded mtkclient process to exit', flush=True)
                child.wait(timeout=190)
    save(directory, 'mtk-exit.json', {'returncode': returncode})
    # Observe Linux even when mtkclient failed so the report records whether a
    # physical recovery is necessary. Do not start another DA session or write.
    observation_start = time.monotonic()
    deadline = observation_start + HEALTH_TIMEOUT
    after = None
    while time.monotonic() < deadline:
        try:
            observed = snapshot(ssh)
            save(directory, 'last-linux.json', observed)
            verify_return(before, observed)
            after = observed
            break
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            detail = str(error)
            if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                detail += '\n' + error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError) and error.stdout:
                (directory / 'last-observation-stdout.txt').write_text(error.stdout)
            (directory / 'last-observation-error.txt').write_text(detail + '\n')
        time.sleep(3)
    if after is None:
        raise RuntimeError(f'Fresh healthy M69 was not observed within {HEALTH_TIMEOUT}s; '
                           'inspect the saved observations before recovery')
    save(directory, 'after.json', after)
    verify_da_result(returncode, logpath.read_text(), writing)
    verify_reads(directory, before)
    if capture_phase:
        save(directory, 'boot-phase.json', phase_readback(directory))
    if capture_ramoops and (directory / 'ramoops.bin').stat().st_size != 0xe0000:
        raise RuntimeError('Ramoops memory read is incomplete')
    save(directory, 'result.json', {'result': 'passed', 'writes_to_emmc': writing,
                                    'health_timeout_seconds': HEALTH_TIMEOUT,
                                    'seconds_to_healthy_linux': round(time.monotonic() - observation_start, 1)})
    print(f'PASS: {"boot write acknowledged; " if writing else ""}'
          f'GPT and boot match; fresh healthy M69. Evidence: {directory}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mtk', type=Path, required=True, help='Patched mtk executable')
    parser.add_argument('--out', type=Path, required=True, help='New evidence directory')
    parser.add_argument('--ssh-key', type=Path, default=Path('/home/grw/.ssh/gemini-stage1-ed25519'))
    parser.add_argument('--ssh-host', default='192.168.23.70', help='Accepted M69 SSH address')
    parser.add_argument('--ssh-host-key-alias', help='Known-host identity when using another address')
    parser.add_argument('--rewrite-accepted-boot', type=Path,
                        help='Additionally rewrite boot with this exact accepted M69 image')
    parser.add_argument('--capture-boot-phase', action='store_true',
                        help='Additionally read the four-byte TOPRGU non-reset phase register')
    parser.add_argument('--capture-ramoops', action='store_true',
                        help='Read the fixed 896 KiB ramoops RAM region before flash reads')
    parser.add_argument('--lock-dir', type=Path,
                        default=Path('/mnt/Home/src/nixos-gemini-flash-p22-20260829'))
    parser.add_argument('--execute', action='store_true', help='Run the supervised read/reboot trial')
    args = parser.parse_args()
    args.mtk = args.mtk.resolve(strict=True)
    payload = None
    if args.rewrite_accepted_boot is not None:
        args.rewrite_accepted_boot = args.rewrite_accepted_boot.resolve(strict=True)
        payload = accepted_boot_bytes(args.rewrite_accepted_boot)
    ssh = ['ssh', '-F', '/dev/null', '-i', str(args.ssh_key), '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ControlPath=none',
           '-o', 'StrictHostKeyChecking=yes']
    if args.ssh_host_key_alias:
        ssh += ['-o', 'HostKeyAlias=' + args.ssh_host_key_alias]
    ssh += ['root@' + args.ssh_host]
    os.umask(0o077)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            lock = locks.enter_context((args.lock_dir / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check_host_idle()
        helptext = run([str(args.mtk), 'reset', '--help'])
        if '--bootmode {shutdown,reboot,fastboot}' not in helptext:
            raise RuntimeError('mtkclient lacks the explicit reboot patch')
        before = snapshot(ssh)
        directory = args.out.resolve()
        directory.mkdir(mode=0o700)
        if payload is not None:
            staged = directory / 'accepted-boot.img'
            with staged.open('xb') as output:
                output.write(payload)
            staged.chmod(0o400)
        save(directory, 'before.json', before)
        save(directory, 'plan.json', {'mtk': str(args.mtk),
                                      'commands': commands_for(payload is not None, args.capture_boot_phase,
                                                               args.capture_ramoops),
                                      'write_requested': payload is not None,
                                      'write_source': str(args.rewrite_accepted_boot) if payload is not None else None,
                                      'execute': args.execute, 'ssh_host': args.ssh_host,
                                      'ssh_host_key_alias': args.ssh_host_key_alias})
        if not args.execute:
            print(f'Preflight passed; no reboot or DA access. Evidence: {directory}')
            return
        run(['sudo', '-n', 'true'])
        try:
            trial(args, directory, before, ssh)
        except Exception as error:
            save(directory, 'result.json', {'result': 'failed', 'error': str(error),
                                           'write_requested': payload is not None})
            raise


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        sys.exit(str(error))
