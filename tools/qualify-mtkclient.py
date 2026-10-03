#!/usr/bin/env python3
"""Qualify the Gemini's DA read/reboot path; never write to eMMC.

Default: inspect accepted Linux and the host CLI. --execute: catch one normal
reboot, read GPT/boot through the DA, request normal boot, verify fresh Linux.
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
ACK = 'Download agent acknowledged reboot request'
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
    # A fresh working directory prevents accidental reuse of cached DA state.
    # timeout bounds the privileged child even if this observer is interrupted.
    command = ['sudo', '-n', 'env', 'PYTHONUNBUFFERED=1', 'timeout',
               '--kill-after=5s', '180s', str(args.mtk), 'multi', COMMANDS]
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
    deadline = time.monotonic() + 180
    after = None
    while time.monotonic() < deadline:
        try:
            observed = snapshot(ssh)
            save(directory, 'last-linux.json', observed)
            verify_return(before, observed)
            after = observed
            break
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            (directory / 'last-observation-error.txt').write_text(str(error) + '\n')
        time.sleep(3)
    if after is None:
        raise RuntimeError('Fresh healthy M69 was not observed; physical recovery may be needed')
    save(directory, 'after.json', after)
    if returncode != 0 or ACK not in logpath.read_text():
        raise RuntimeError('Linux returned, but mtkclient did not acknowledge reboot successfully')
    verify_reads(directory, before)
    save(directory, 'result.json', {'result': 'passed', 'writes_to_emmc': False})
    print(f'PASS: GPT and boot match; fresh healthy M69. Evidence: {directory}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mtk', type=Path, required=True, help='Patched mtk executable')
    parser.add_argument('--out', type=Path, required=True, help='New evidence directory')
    parser.add_argument('--ssh-key', type=Path, default=Path('/home/grw/.ssh/gemini-stage1-ed25519'))
    parser.add_argument('--lock-dir', type=Path,
                        default=Path('/mnt/Home/src/nixos-gemini-flash-p22-20260829'))
    parser.add_argument('--execute', action='store_true', help='Run the supervised read/reboot trial')
    args = parser.parse_args()
    args.mtk = args.mtk.resolve(strict=True)
    ssh = ['ssh', '-F', '/dev/null', '-i', str(args.ssh_key), '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ControlPath=none',
           '-o', 'StrictHostKeyChecking=yes', 'root@192.168.23.70']
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
        save(directory, 'before.json', before)
        save(directory, 'plan.json', {'mtk': str(args.mtk), 'commands': COMMANDS,
                                      'execute': args.execute})
        if not args.execute:
            print(f'Preflight passed; no reboot or DA access. Evidence: {directory}')
            return
        run(['sudo', '-n', 'true'])
        try:
            trial(args, directory, before, ssh)
        except Exception as error:
            save(directory, 'result.json', {'result': 'failed', 'error': str(error)})
            raise


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        sys.exit(str(error))
