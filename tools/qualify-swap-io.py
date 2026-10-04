#!/usr/bin/env python3
"""Qualify bounded swap I/O under memory-cgroup pressure on accepted M69.

Default is read-only preflight. Execution uses a durable host worker, a
bounded target service and independent recovery. Recovery preserves a fully
verified healthy swap layout, falling back to qualified factory restoration.
The target service temporarily enables zswap's shrinker, restoring its original
disabled value through ExecStopPost. This qualifies that runtime correction,
not the unmodified default kernel policy.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixed_swap', ROOT / 'tools/qualify-fixed-swap.py')
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
PROBE = Path('/nix/store/dmgf8bkw6r04alka7xlrf487aracfddj-gemini-swap-probe-static-aarch64-unknown-linux-musl-1/bin/gemini-swap-probe')
PROBE_SHA = 'e2d910dc9ccacf3521f091089890cac47e12ee06a1f6df2b98d8ffe859862867'
SOURCE_SHA = '33e22f47b890938295141e98a45e1b8c50e2ba275dfbd196613f48f0f6387cbb'
INSTALL = ROOT.parent / 'handoff/fixed-swap-04'
LIMITS = dict(MemoryMax='67108864', MemorySwapMax='268435456',
              RuntimeMaxUSec='1min 30s', TimeoutStopUSec='5s', KillMode='control-group')
save = f.q.r.qualify.save


def policy_scripts(remote, parameter='/sys/module/zswap/parameters/shrinker_enabled'):
    value = shlex.quote(str(parameter))
    armed = shlex.quote(str(remote) + '/policy-armed')
    restored = shlex.quote(str(remote) + '/policy-restored')
    enable = f'''#!/bin/sh
set -eu
test "$(cat {value})" = N
touch {armed}
printf Y > {value}
test "$(cat {value})" = Y
'''
    restore = f'''#!/bin/sh
set -eu
if test -f {armed}; then
 printf N > {value}
 test "$(cat {value})" = N
 printf 'restored=N\n' > {restored}
fi
'''
    return enable, restore


def watchdog(directory, state, name):
    raw = f.q.r.persistence.run(f.q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(state['boot_id'])}
grep -qw memory /sys/fs/cgroup/cgroup.controllers
for field in identity state timeout nowayout; do
 printf '%s=' "$field"; cat "/sys/class/watchdog/watchdog0/$field"
done
owner=$(cat /run/unattended-recovery.watchdog-owner)
case "$owner" in ''|*[!0-9]*) exit 1;; esac
test "$owner" -gt 1
kill -0 "$owner"
test "$(systemctl show gemini-watchdog-takeover.service -p MainPID --value)" = "$owner"
owned=no
for fd in /proc/"$owner"/fd/*; do
 case "$(readlink "$fd" || true)" in /dev/watchdog|/dev/watchdog0) owned=yes;; esac
done
printf 'owned=%s\nowner_pid=%s\n' "$owned" "$owner"
printf 'owner_unit='; systemctl is-active gemini-watchdog-takeover.service
printf 'owner_restart='; systemctl show gemini-watchdog-takeover.service -p Restart --value
''', directory, name)
    values = dict(row.split('=', 1) for row in raw.splitlines())
    expected = dict(identity='mtk-wdt', state='active', timeout='31', nowayout='1',
                    owned='yes', owner_unit='active', owner_restart='no')
    if any(values.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Active watchdog ownership or memory-cgroup prerequisite differs')
    save(directory, name + '.json', values)
    return values


def verify_probe(raw, service, status):
    if status != 0 or any(service.get(k) != v for k, v in LIMITS.items()):
        raise RuntimeError('Probe exit or enforced service limits differ')
    expected = dict(ActiveState='active', SubState='exited', MainPID='0',
                    Result='success', ExecMainCode='1', ExecMainStatus='0', RemainAfterExit='yes')
    if any(service.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Probe did not terminate successfully')
    result = json.loads(raw)
    if (not isinstance(result, dict) or result.get('pattern_verified') is not True or
            type(result.get('bytes')) is not int or result['bytes'] != 134217728 or
            any(type(result.get(k)) is not int for k in ('swapped_kib', 'read_sectors', 'written_sectors')) or
            # VmSwap also counts the probe's stack and allocator pages. Its
            # upper bound is the enforced cgroup swap limit, not just mmap().
            not 65536 <= result['swapped_kib'] <= int(LIMITS['MemorySwapMax']) // 1024 or
            result['read_sectors'] < 131072 or result['written_sectors'] < 131072):
        raise RuntimeError('Missing complete memory pattern and backing-device I/O evidence')
    return result


def stage(directory, before, execute):
    directory.mkdir(mode=0o700)
    save(directory, 'before.json', before)
    prior = json.loads((INSTALL / 'commit.json').read_text())
    if not f.committed(INSTALL) or prior.get('layout') != 'swap':
        raise RuntimeError('Qualified fixed-swap installation and reboot evidence is missing')
    restoration = f.prior_restoration()
    probe = PROBE.read_bytes()
    if hashlib.sha256(probe).hexdigest() != PROBE_SHA or hashlib.sha256((ROOT / 'nix/gemini-swap-probe.c').read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError('Probe source or executable differs')
    (directory / 'probe').write_bytes(probe); (directory / 'probe').chmod(0o400)
    f.copy_inputs(directory / 'emergency-restore')
    sources = directory / 'executed-sources'; sources.mkdir(mode=0o700)
    previous = json.loads((INSTALL / 'plan.json').read_text())
    names = tuple(previous['executed_sources_sha256']) + ('tools/qualify-swap-io.py', 'nix/gemini-swap-probe.c')
    hashes = {}
    for name in names:
        raw = (ROOT / name).read_bytes()
        if name in previous['executed_sources_sha256'] and hashlib.sha256(raw).hexdigest() != previous['executed_sources_sha256'][name]:
            raise RuntimeError('Previously qualified recovery source changed: ' + name)
        (sources / Path(name).name).write_bytes(raw); hashes[name] = hashlib.sha256(raw).hexdigest()
    save(directory, 'plan.json', dict(execute=execute, probe=str(PROBE), probe_sha256=PROBE_SHA,
        limits=LIMITS, prior_install=str(INSTALL), prior_commit_sha256=hashlib.sha256((INSTALL / 'commit.json').read_bytes()).hexdigest(),
        qualified_prior_restoration=restoration, executed_sources_sha256=hashes,
        zswap_shrinker=dict(original='N', during_probe='Y', cleanup='ExecStopPost'),
        automatic_failure_action='verify-healthy-swap-or-restore-factory'))
    f.swap_evidence(directory, before)
    watchdog(directory, before, 'watchdog-before')
    policy = f.q.r.persistence.run(f.q.SSH, '''set -eu
printf 'enabled='; cat /sys/module/zswap/parameters/enabled
printf 'shrinker_enabled='; cat /sys/module/zswap/parameters/shrinker_enabled
printf 'swappiness='; cat /proc/sys/vm/swappiness
printf 'writeback='; cat /sys/fs/cgroup/system.slice/memory.zswap.writeback
''', directory, 'memory-policy-before')
    values = dict(row.split('=', 1) for row in policy.splitlines())
    if values != dict(enabled='Y', shrinker_enabled='N', swappiness='60', writeback='1'):
        raise RuntimeError('Original zswap policy differs from the reviewed correction')
    save(directory, 'memory-policy-before.json', values)
    f.q.preserved_files(before['boot_id'], directory, 'before')


def run_probe(directory, before, unit):
    if not re.fullmatch(r'gemini-swap-io-[0-9]+-[0-9]+', unit):
        raise ValueError('Invalid target service name')
    remote = '/run/' + unit
    enable, restore = policy_scripts(remote)
    transfer = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(before['boot_id'])}
umask 077
mkdir {remote}
cat > {remote}/probe
chmod 0500 {remote}/probe
test "$(sha256sum {remote}/probe | cut -d' ' -f1)" = {PROBE_SHA}
cat > {remote}/enable-shrinker <<'ENABLE'
{enable}
ENABLE
cat > {remote}/restore-shrinker <<'RESTORE'
{restore}
RESTORE
chmod 0500 {remote}/enable-shrinker {remote}/restore-shrinker
'''
    (directory / 'transfer.sh').write_text(transfer)
    sent = subprocess.run(f.q.SSH + [transfer], input=(directory / 'probe').read_bytes(), capture_output=True, timeout=30)
    save(directory, 'transfer.json', dict(returncode=sent.returncode, stderr=sent.stderr.decode(errors='replace')))
    sent.check_returncode()
    command = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(before['boot_id'])}
test "$(sha256sum {remote}/probe | cut -d' ' -f1)" = {PROBE_SHA}
systemd-run --quiet --unit={unit} --setenv=PATH=/run/current-system/sw/bin \
 --property=RuntimeMaxSec=90 --property=RemainAfterExit=yes \
 --property=TimeoutStopSec=5 --property=MemoryMax=67108864 \
 --property=MemorySwapMax=268435456 --property=KillMode=control-group \
 --property=ExecStartPre={remote}/enable-shrinker --property=ExecStopPost={remote}/restore-shrinker \
 --property=StandardOutput=file:{remote}/stdout --property=StandardError=file:{remote}/stderr \
 {remote}/probe
'''
    (directory / 'probe.sh').write_text(command)
    result = subprocess.run(f.q.SSH + [command], capture_output=True, text=True, timeout=30)
    save(directory, 'probe-launch.json', dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
    deadline = time.monotonic() + 110
    while time.monotonic() < deadline:
        raw = f.q.r.persistence.run(f.q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(before['boot_id'])}
systemctl show {unit}.service -p ActiveState -p Result -p ExecMainCode -p ExecMainStatus \
 -p SubState -p MainPID -p RemainAfterExit -p MemoryMax -p MemorySwapMax \
 -p RuntimeMaxUSec -p TimeoutStopUSec -p KillMode
''', directory, 'target-service', timeout=25)
        service = dict(row.split('=', 1) for row in raw.splitlines())
        if service.get('SubState') in ('exited', 'dead', 'failed'): break
        time.sleep(0.5)
    else: raise RuntimeError('Bounded target service has not terminated; rescue remains armed')
    save(directory, 'target-service.json', service)
    stdout = f.q.r.persistence.run(f.q.SSH, f'cat {remote}/stdout', directory, 'probe-output')
    f.q.r.persistence.run(f.q.SSH, f'cat {remote}/stderr', directory, 'probe-errors')
    f.q.r.persistence.run(f.q.SSH, f'''set -eu
printf 'shrinker_enabled='; cat /sys/module/zswap/parameters/shrinker_enabled
awk '/^pswpin |^pswpout / {{print}}' /proc/vmstat
for field in memory.current memory.swap.current memory.zswap.current memory.events memory.stat; do
 path=/sys/fs/cgroup/system.slice/{unit}.service/$field
 if test -r "$path"; then printf '%s\n' "$field"; cat "$path"; fi
done
journalctl -k -b --no-pager -n 160
''', directory, 'kernel-diagnostics')
    verified = verify_probe(stdout, service, result.returncode)
    policy = f.q.r.persistence.run(f.q.SSH,
        'cat /sys/module/zswap/parameters/shrinker_enabled', directory, 'memory-policy-during').strip()
    if policy != 'Y': raise RuntimeError('Paging was not tested with the corrected zswap policy')
    save(directory, 'paging.json', verified)
    # RemainAfterExit retains the exited process's result for inspection; it
    # does not keep the probe running. Release the unit after collecting it.
    f.q.r.persistence.run(f.q.SSH, f'systemctl stop {unit}.service', directory, 'target-stop')
    restored = f.q.r.persistence.run(f.q.SSH, f'''set -eu
test "$(cat {remote}/policy-restored)" = restored=N
cat /sys/module/zswap/parameters/shrinker_enabled
''', directory, 'memory-policy-restored').strip()
    if restored != 'N': raise RuntimeError('Original zswap runtime policy was not restored')
    return verified


def committed(directory):
    if not f.committed(directory): return False
    result = json.loads((directory/'commit.json').read_text())
    return all(result.get(k) is True for k in
               ('paging_io_qualified', 'swap_io_under_pressure_qualified', 'original_zswap_policy_restored'))


def cleanup_target(directory, unit, state):
    if not re.fullmatch(r'swap-io-[0-9]+-[0-9]+', unit): raise ValueError('Invalid probe owner')
    target = 'gemini-' + unit + '.service'
    f.q.r.persistence.run(f.q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(state['boot_id'])}
case "$(systemctl show {target} -p LoadState --value)" in
 loaded)
  systemctl stop {target}
  test "$(systemctl show {target} -p MainPID --value)" = 0
  systemctl reset-failed {target} 2>/dev/null || test "$(systemctl show {target} -p LoadState --value)" = not-found
  ;;
 not-found) ;;
 *) exit 1;;
esac
test "$(cat /sys/module/zswap/parameters/shrinker_enabled)" = N
''', directory, 'rescue-probe-cleanup', timeout=30)


def rescue(directory):
    units = json.loads((directory/'units.json').read_text())
    (directory/'rescue.ready').write_text(str(os.getpid())+'\n')
    deadline = time.monotonic()+650
    while time.monotonic() < deadline:
        if committed(directory):
            save(directory, 'rescue-result.json', dict(result='committed', factory_restored=False)); return
        try:
            if not f.owner_alive(units['worker']): break
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            (directory/'rescue-owner-observer-error.txt').write_text(str(error)+'\n')
        time.sleep(0.5)
    else: raise RuntimeError('Probe worker did not terminate before its service deadline')
    with ExitStack() as locks:
        deadline = time.monotonic()+30
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((f.q.r.LOCKS/name).open('a'))
            while True:
                try: fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() > deadline: raise RuntimeError('A previous writer still owns a flash lock')
                    time.sleep(0.2)
        if committed(directory):
            save(directory, 'rescue-result.json', dict(result='committed', factory_restored=False)); return
        before = json.loads((directory/'before.json').read_text())
        swap = None
        try:
            observed = f.snapshot('swap', healthy=False)
            if observed['flashinfo_sha256'] != before['flashinfo_sha256']: raise RuntimeError('Flashinfo changed')
            cleanup_target(directory, units['worker'], observed)
            swap = f.snapshot('swap')
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            (directory/'rescue-swap-health-error.txt').write_text(str(error)+'\n')
        if swap is not None:
            out = directory/'preserved-swap'; out.mkdir(mode=0o700)
            f.swap_evidence(out, swap)
            outputs = f.retained(out, swap)
            save(out, 'after.json', swap); f.q.r.qualify.check_host_idle()
            save(directory, 'rescue-result.json', dict(result='preserved', factory_restored=False,
                swap_active=True, healthy_boot=swap['boot_id'], ordinary_outputs_retained=outputs))
            return
        print('Healthy swap could not be verified; restoring the factory GPT/header', flush=True)
        out = directory/'emergency-restore'
        rc, window, error = f.run_da(out, handle, restore=True)
        after = f.healthy_return(out, 'factory', before)
        if error: raise error
        f.verify_da(out, before, 'factory', rc, window)
        outputs = f.retained(out, after); f.q.r.qualify.check_host_idle()
        save(directory, 'rescue-result.json', dict(result='restored', factory_restored=True,
            healthy_boot=after['boot_id'], ordinary_outputs_retained=outputs))


def work(directory, execute):
    os.umask(0o077)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((f.q.r.LOCKS / name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.q.r.qualify.check_host_idle(); before = f.snapshot('swap')
        f.q.r.qualify.run(['sudo', '-n', 'true'])
        stage(directory, before, execute)
        if not execute:
            print('Swap I/O preflight passed; no target changes: ' + str(directory)); return
        worker = os.environ['GEMINI_SWAP_IO_UNIT']
        units = dict(worker=worker, rescue=worker+'-rescue', network=worker+'-net')
        save(directory, 'units.json', units)
        f.q.r.unit(units['network'], 3400, [shutil.which('sh'), directory/'executed-sources/trex-gadget-net-watcher.sh', directory/'host-net.log', directory/'host-net.state'])
        f.q.r.unit(units['rescue'], 3300, [sys.executable, str(Path(__file__).resolve()), '--rescue-worker', '--out', directory])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if (directory/'rescue.ready').exists() and f.owner_alive(units['rescue']): break
            time.sleep(0.1)
        else: raise RuntimeError('Independent rescue did not become ready')
        try:
            if f.snapshot('swap') != before: raise RuntimeError('Device changed before the paging trial')
            print('Starting 128 MiB paging probe with 64 MiB memory limit; independent rescue is armed', flush=True)
            paging = run_probe(directory, before, 'gemini-' + worker)
            after = f.snapshot('swap')
            if after != before: raise RuntimeError('Device identity changed during paging')
            watchdog(directory, after, 'watchdog-after')
            check = directory/'after-check'; check.mkdir(mode=0o700)
            f.swap_evidence(check, after); outputs = f.retained(check, after)
            save(directory, 'after.json', after)
            f.q.r.qualify.check_host_idle()
            result = dict(result='passed', paging_io_qualified=True, swap_io_under_pressure_qualified=True,
                paging=paging, healthy_boot=after['boot_id'], ordinary_outputs_retained=outputs,
                layout='swap', no_writer=True, hibernation_qualified=False,
                zswap_shrinker_during_probe=True, original_zswap_policy_restored=True,
                unmodified_default_pressure_qualified=False,
                swap_active=True, factory_restore_qualified=True, reboot_persistence_qualified=True,
                prior_install_evidence=str(INSTALL), reboot_performed=False)
            save(directory, 'result.json', result)
            with (directory/'commit.tmp').open('x') as stream:
                json.dump(result, stream); stream.flush(); os.fsync(stream.fileno())
            (directory/'commit.tmp').rename(directory/'commit.json')
            print('PASS: memory-cgroup pressure caused verified p34 paging; health and retained data pass', flush=True)
        except Exception as error:
            save(directory, 'result.json', dict(result='failed', error=str(error), paging_io_qualified=False))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--rescue-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(); directory = args.out.resolve()
    if args.rescue_worker:
        units = json.loads((directory/'units.json').read_text())
        if not os.environ.get('INVOCATION_ID') or f.q.r.qualify.run(['systemctl', '--user', 'show', units['rescue'], '-p', 'MainPID', '--value']).strip() != str(os.getpid()):
            raise RuntimeError('Rescue lacks its independent service owner')
        try: rescue(directory)
        except Exception as error:
            save(directory, 'rescue-result.json', dict(result='failed', error=str(error))); raise
        finally: f.q.r.qualify.run(['systemctl', '--user', 'stop', units['network']])
    elif args.worker:
        unit = os.environ.get('GEMINI_SWAP_IO_UNIT', '')
        if not re.fullmatch(r'swap-io-[0-9]+-[0-9]+', unit) or not os.environ.get('INVOCATION_ID'):
            raise RuntimeError('Execution requires its durable worker')
        if f.q.r.qualify.run(['systemctl', '--user', 'show', unit, '-p', 'MainPID', '--value']).strip() != str(os.getpid()):
            raise RuntimeError('Worker ownership differs')
        work(directory, True)
    elif args.execute:
        unit = 'swap-io-' + str(int(time.time())) + '-' + str(os.getpid())
        print('Starting durable swap I/O worker ' + unit, flush=True)
        child = subprocess.run(['systemd-run', '--user', '--collect', '--wait', '--pipe', '--quiet', '--unit='+unit,
            '--property=RuntimeMaxSec=600', '--setenv=PATH='+os.environ['PATH'], '--setenv=GEMINI_SWAP_IO_UNIT='+unit,
            sys.executable, str(Path(__file__).resolve()), '--worker', '--out', str(directory)])
        if (directory/'units.json').exists():
            units = json.loads((directory/'units.json').read_text()); deadline = time.monotonic()+1750
            while f.owner_alive(units['rescue']):
                if time.monotonic() > deadline: raise RuntimeError('Rescue still running; inspect the same unit')
                time.sleep(1)
            status = json.loads((directory/'rescue-result.json').read_text())
            print('Independent rescue result: '+status['result'], flush=True)
            if status['result'] not in ('committed', 'preserved', 'restored'): raise RuntimeError('Recovery failed')
        if child.returncode: raise RuntimeError('Paging trial failed; inspect retained worker/rescue evidence')
    else: work(directory, False)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: sys.exit(str(error))
