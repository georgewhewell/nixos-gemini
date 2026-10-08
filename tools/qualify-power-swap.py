#!/usr/bin/env python3
"""Boot the pinned power/swap kernel and recover M69 on the exact swap layout.

Default is read-only preflight. --execute uses the existing durable boot-only
supervisor, with explicit storage admission for both candidate and recovery.
The candidate must page successfully using its boot-time zswap policy.
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
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('paging', ROOT/'tools/qualify-swap-io.py')
paging = importlib.util.module_from_spec(spec); spec.loader.exec_module(paging)
f = paging.f
watchdog_expiry = f.q.module('linux_watchdog', ROOT/'tools/qualify-linux-watchdog.py')
pm_stages = f.q.module('pm_stages', ROOT/'tools/qualify-pm-stages.py')
usb_cycle = f.q.module('usb_cycle', ROOT/'tools/qualify-usb-cycle.py')
PROFILE = 'power-swap'
ENTRYPOINT = Path(__file__).resolve()
EXTRA_EXECUTED_SOURCES = ()
BUNDLE = Path('/nix/store/mb5adwsfnri1jswcxhs6vl23hnj3jy5m-gemini-mainline-nixos-bundle')
KERNEL = Path('/nix/store/b26xkc1n67c1xiz90fnzqg17w5dhvff3-gemini-mainline-power-swap-kernel-7.1.3')
SYSTEM = '/nix/store/7vg1vqfn8v19px9k8bhcyi4yvndpszzb-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
BOOT_SHA = 'fb8d164dfd9b658bb3c247fd7ec39106ed30ca4656c09d94a6c1efcc50a31f9a'
STORE_SHA = 'f52643cb9360a48ca4b9058d34d1aa579535ffdcae7386a8cbcdb955195605a7'
STORE_SIZE = 427048960
NOTES_SHA = '1bffbfeaa804fe8e0bd6735250ed38214b99b27efc86dca595b02d29940748b3'
FLASHINFO_SHA = 'c869d0319177b87fdf2415015905d1321670c5d2863d1c43eb18831e2c2742e2'
STORAGE = dict(gpt_sha256=f.GEOMETRY['swap'][0], backup_gpt_sha256=f.GEOMETRY['swap'][1],
    swap_header_sha256=f.GEOMETRY['swap'][2], p30_sha256=f.q.r.P30_SHA,
    p31_sha256=f.q.r.P31_SHA, flashinfo_sha256=FLASHINFO_SHA)


def storage_identity(state):
    if any(state.get(k) != v for k, v in STORAGE.items()):
        raise RuntimeError('Candidate/recovery does not preserve the exact fixed-swap layout and protected data')


def store_profile(provisioner):
    return provisioner.StoreProfile(BUNDLE, SYSTEM, STORE_SHA, STORE_SIZE, False)


def prior_outputs(root=ROOT.parent/'handoff', exclude=None):
    retained = {}
    for path in sorted(root.glob('*/nix-candidate.json')):
        if path.parent == exclude or not re.fullmatch(r'(power-(swap|rtc|rtc-calendar|rtc-startup)|boot-test)-[0-9]+', path.parent.name): continue
        proof = json.loads(path.read_text()); token = proof.get('token', '')
        if (proof.get('ordinary_daemon_build_qualified') is not True or
                not re.fullmatch('[0-9a-f]{32}', token) or
                not re.fullmatch('/nix/store/[0-9a-z]{32}-gemini-daemon-'+token, proof.get('output', '')) or
                proof.get('output_link') != '/home/gemini/.gemini-daemon-build-'+token+'/result' or
                not re.fullmatch('[0-9a-f]{64}', proof.get('proof_sha256', ''))):
            raise RuntimeError('Invalid earlier power/swap build proof: '+str(path))
        retained[path.parent.name] = proof
    return retained


def retained_all(directory, state, exclude):
    outputs = f.retained(directory, state)
    for name, proof in prior_outputs(exclude=exclude).items():
        f.q.r.persistent_nix.verify_retained(f.q.SSH, state['boot_id'], directory,
            f.q.r.qualify, f.q.r.persistence, proof, name=name)
        outputs[name] = proof['output']
    return outputs


def verify_power_state(raw, boot_id):
    rows = raw.splitlines()
    state = dict(row.split('=', 1) for row in rows)
    expected = dict(boot_id=boot_id, system=SYSTEM, notes_sha256=NOTES_SHA,
        config_sha256=hashlib.sha256((KERNEL/'kernel.config').read_bytes()).hexdigest(),
        pm_test='[none] core processors platform devices freezer', mem_sleep='[s2idle]',
        disk='[shutdown] reboot suspend test_resume', hibernation='false',
        suspend_then_hibernate='false', zswap='Y', shrinker='Y')
    if len(rows) != len(state) or state != expected:
        raise RuntimeError('Selected kernel, sleep policy or default zswap configuration differs')
    return state


def evidence(ssh, boot_id, directory, qualify, persistence, require_efi=False):
    boot_guard = ('test "$(cat /sys/firmware/efi/fw_platform_size)" = 64'
                  if require_efi else 'test ! -e /sys/firmware/efi')
    raw = persistence.run(ssh, f'''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'system='; readlink /run/current-system
printf 'notes_sha256='; sha256sum /sys/kernel/notes | cut -d' ' -f1
printf 'config_sha256='; zcat /proc/config.gz | sha256sum | cut -d' ' -f1
for name in pm_test mem_sleep disk; do printf '%s=' "$name"; cat /sys/power/$name; done
printf 'hibernation='; sed -n 's/^AllowHibernation=//p' /etc/systemd/sleep.conf
printf 'suspend_then_hibernate='; sed -n 's/^AllowSuspendThenHibernate=//p' /etc/systemd/sleep.conf
printf 'zswap='; cat /sys/module/zswap/parameters/enabled
printf 'shrinker='; cat /sys/module/zswap/parameters/shrinker_enabled
{boot_guard}
grep -Eq ' [tT] mtk_wdt_pm_notify$' /proc/kallsyms
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot_id}
''', directory, 'power-swap-state')
    state = verify_power_state(raw, boot_id)
    watchdog = paging.watchdog(directory, state, 'candidate-watchdog')
    f.swap_evidence(directory, state)
    out = directory/'candidate-paging'; out.mkdir(mode=0o700)
    probe = paging.PROBE.read_bytes()
    if hashlib.sha256(probe).hexdigest() != paging.PROBE_SHA:
        raise RuntimeError('Paging executable changed')
    (out/'probe').write_bytes(probe); (out/'probe').chmod(0o400)
    result = paging.run_probe(out, state, 'gemini-swap-io-'+str(int(time.time()))+'-'+str(os.getpid()), runtime_policy=False)
    # Independent post-probe observation: no setup/cleanup callback is allowed
    # to supply the policy which this profile claims comes from the kernel.
    persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot_id}
test "$(cat /sys/module/zswap/parameters/shrinker_enabled)" = Y
test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = {NOTES_SHA}
''', directory, 'power-swap-after-paging')
    qualify.save(directory, 'power-swap-evidence.json', dict(**state, watchdog=watchdog,
        paging=result, default_policy_paging_qualified=True, sleep_requested=False,
        hibernation_io_qualified=False, runtime_policy_writes=False))
    return state


def configure(watchdog=False, pm_test=None, cycle=False):
    if sum((bool(watchdog), bool(pm_test), bool(cycle))) > 1:
        raise ValueError('Select watchdog expiry, PM diagnostics or USB cycle separately')
    # A separate module instance keeps old factory-layout profiles unchanged.
    r = f.q.module('power_swap_recovery', ROOT/'tools/qualify-uboot-recovery.py')
    if r.power_kernel.notes_sha(KERNEL) != NOTES_SHA:
        raise RuntimeError('Built power/swap kernel identity differs')
    r.PROFILES = {PROFILE: (BUNDLE/'boot-padded-p22.img', BOOT_SHA)}
    for name in ('POWER_PROFILES', 'CURRENT_FILES_PROFILES', 'DIRECT_NIX_PROFILES', 'NIX_PROFILES', 'LINUX_PROFILES'):
        setattr(r, name, getattr(r, name) + (PROFILE,))
    r.power_kernel = SimpleNamespace(SYSTEM=SYSTEM, KERNEL=KERNEL,
                                    store_profile=store_profile, evidence=evidence)
    r.qualify.SNAPSHOT = f.script('swap')
    original_snapshot = r.qualify.snapshot
    original_return = r.qualify.verify_return

    def snapshot(ssh):
        state = original_snapshot(ssh)
        storage_identity(state)
        return state

    def verify_return(before, after):
        original_return(before, after)
        storage_identity(before); storage_identity(after)

    r.qualify.snapshot = snapshot
    r.qualify.verify_return = verify_return
    r.watchdog_expiry_requested = watchdog
    r.pm_test_last_stage = pm_test
    r.usb_cycle_requested = cycle
    context = SimpleNamespace(ROOT=ROOT, f=f, paging=paging, SYSTEM=SYSTEM,
                              NOTES_SHA=NOTES_SHA, KERNEL=KERNEL, BOOT_SHA=BOOT_SHA, PROFILE=PROFILE,
                              usb_cycle=usb_cycle)
    if watchdog:
        watchdog_expiry.install(context, r)
    if pm_test: pm_stages.install(context, r, pm_test)
    if cycle: usb_cycle.install(context, r)
    return r


def preflight(r, directory, execute):
    argv = sys.argv
    try:
        sys.argv = [str(ROOT/'tools/qualify-uboot-recovery.py'), '--profile', PROFILE, '--out', str(directory)]
        r.main()
    finally: sys.argv = argv
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((r.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        r.qualify.check_host_idle()
        before = json.loads((directory/'before.json').read_text())
        current = f.snapshot('swap')
        if current != dict(before, layout='swap'): raise RuntimeError('Device changed during extended preflight')
        if (r.qualify.run(f.q.SSH+['cat /sys/module/zswap/parameters/shrinker_enabled']).strip() !=
                r.qualify.BASELINE['zswap_shrinker']):
            raise RuntimeError('Baseline recovery zswap policy differs')
        old = directory/'before-all-data'; old.mkdir(mode=0o700)
        retained_all(old, current, directory)
        if r.pm_test_last_stage or r.usb_cycle_requested:
            r.qualify.save(directory, 'pm-prerequisites.json', pm_stages.prerequisites(
                SimpleNamespace(ROOT=ROOT, SYSTEM=SYSTEM, KERNEL=KERNEL, NOTES_SHA=NOTES_SHA, BOOT_SHA=BOOT_SHA)))
        if r.pm_test_last_stage == 'devices':
            r.qualify.save(directory, 'usb-prerequisites.json', usb_cycle.prerequisites(
                SimpleNamespace(ROOT=ROOT, SYSTEM=SYSTEM, NOTES_SHA=NOTES_SHA, BOOT_SHA=BOOT_SHA)))
        plan = json.loads((directory/'plan.json').read_text())
        names = {('nix/' if name == 'generate-late-cpu-provenance.py' else 'tools/') + name
                 for name in plan['executed_sources_sha256']}
        names.update(json.loads((ROOT.parent/'handoff/fixed-swap-04/plan.json').read_text())['executed_sources_sha256'])
        names.update(('tools/qualify-power-swap.py', 'tools/qualify-swap-io.py',
                      'tools/qualify-linux-watchdog.py', 'tools/qualify-pm-stages.py',
                      'tools/qualify-usb-cycle.py', 'nix/gemini-swap-probe.c'))
        names.update(EXTRA_EXECUTED_SOURCES)
        names.update('research/'+name for name in ('p22-proof-supervisor.sh', 'p22-flash-wrapper.sh',
            'p22-mtkclient-backend.py', 'trex-gadget-net-watcher.sh', 'p22-trex-transaction-holder.sh'))
        hashes = {}
        for name in sorted(names):
            raw = (ROOT/name).read_bytes()
            (directory/'executed-sources'/Path(name).name).write_bytes(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        (directory/'storage-snapshot.sh').write_text(r.qualify.SNAPSHOT)
        plan.update(execute=execute, storage_layout='fixed-swap', storage_identity=STORAGE,
            all_executed_sources_sha256=hashes, default_zswap_shrinker=True,
            paging_probe_sha256=paging.PROBE_SHA, runtime_policy_writes=False,
            watchdog_expiry_requested=r.watchdog_expiry_requested, pm_test_last_stage=r.pm_test_last_stage,
            usb_cycle_requested=r.usb_cycle_requested)
        plan['observe_seconds'] = r.OBSERVE_SECONDS
        r.qualify.save(directory, 'plan.json', plan)
        return before


def stop_owned_unit(r, unit):
    # The legacy trial already stops these transient units on success. A
    # second stop can return 5 once --collect has unloaded them. Inspect the
    # terminal state explicitly, including after a concurrent collection.
    def terminal():
        raw = r.qualify.run(['systemctl', '--user', 'show', unit,
                            '-p', 'ActiveState', '-p', 'MainPID'])
        rows = raw.splitlines(); state = dict(row.split('=', 1) for row in rows)
        if (len(rows) != 2 or set(state) != {'ActiveState', 'MainPID'} or
                state['ActiveState'] not in ('active', 'activating', 'deactivating', 'inactive', 'failed') or
                not state['MainPID'].isdigit()):
            raise RuntimeError('Unknown ownership/network service state: '+unit)
        return state['ActiveState'] in ('inactive', 'failed') and state['MainPID'] == '0'

    if terminal(): return
    try:
        r.qualify.run(['systemctl', '--user', 'stop', unit])
    except subprocess.CalledProcessError as error:
        if error.returncode != 5 or not terminal(): raise
        return
    if not terminal(): raise RuntimeError('Ownership/network service is still running: '+unit)


def finish(r, directory, before, error=None):
    promoted = directory/'promoted-baseline.json'
    if promoted.exists():
        # The kept candidate, not the old baseline, is what must be healthy.
        baseline = json.loads(promoted.read_text())
        for qualify in (r.qualify, f.q.r.qualify):
            qualify.adopt_baseline(baseline)
    units_path = directory/'units.json'
    if units_path.exists():
        units = json.loads(units_path.read_text())
        deadline = time.monotonic()+1100
        while any(f.owner_alive(units[key]) for key in ('candidate', 'supervisor')):
            if time.monotonic() > deadline: raise RuntimeError('Existing candidate/recovery service is still active')
            time.sleep(1)
        # Never stop ownership or networking until Linux and the absence of
        # a connected writer are independently verified.
        deadline = time.monotonic()+360
        while True:
            try:
                after = f.snapshot('swap'); r.qualify.check_host_idle(); break
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                if time.monotonic() > deadline: raise RuntimeError('Healthy baseline with fixed swap did not return')
                time.sleep(3)
        for key in ('owner', 'network'): stop_owned_unit(r, units[key])
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((r.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        r.qualify.check_host_idle(); after = f.snapshot('swap')
        audit = directory/'final-audit'; audit.mkdir(mode=0o700)
        outputs = retained_all(audit, after, directory)
        f.swap_evidence(audit, after); paging.watchdog(audit, after, 'watchdog')
        if (r.qualify.run(f.q.SSH+['cat /sys/module/zswap/parameters/shrinker_enabled']).strip() !=
                r.qualify.BASELINE['zswap_shrinker']):
            raise RuntimeError('Recovered baseline no longer has its original zswap policy')
        if (directory/'nix-candidate.json').exists():
            latest = json.loads((directory/'nix-candidate.json').read_text())
            r.persistent_nix.verify_retained(f.q.SSH, after['boot_id'], audit, r.qualify,
                r.persistence, latest, name='new-candidate-output')
            outputs[directory.name] = latest['output']
        plan = json.loads((directory/'plan.json').read_text())
        for name, sha in plan['all_executed_sources_sha256'].items():
            if (hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != sha or
                    hashlib.sha256((directory/'executed-sources'/Path(name).name).read_bytes()).hexdigest() != sha):
                raise RuntimeError('Executed qualification source changed: '+name)
        for name in ('p22-proof-supervisor.sh', 'p22-flash-wrapper.sh', 'p22-mtkclient-backend.py',
                     'trex-gadget-net-watcher.sh', 'p22-trex-transaction-holder.sh'):
            if (directory/name).exists() and (directory/name).read_bytes() != (directory/'executed-sources'/name).read_bytes():
                raise RuntimeError('Executed supervisor copy differs: '+name)
        result = json.loads((directory/'result.json').read_text()) if (directory/'result.json').exists() else {}
        passed = error is None and result.get('profile_qualified') is True
        if passed:
            proof = json.loads((directory/'power-swap-evidence.json').read_text())
            passed = proof.get('default_policy_paging_qualified') is True and proof.get('runtime_policy_writes') is False
        if plan.get('watchdog_expiry_requested'):
            expiry = dict(watchdog_expiry_qualified=False)
            if passed:
                try:
                    expiry = watchdog_expiry.verify_final(SimpleNamespace(f=f, SYSTEM=SYSTEM), directory)
                except (OSError, ValueError, RuntimeError, KeyError, StopIteration) as caught:
                    passed = False; error = caught
            r.qualify.save(directory, 'watchdog-result.json', expiry)
            result.update(expiry)
        if plan.get('pm_test_last_stage'):
            pm_result = dict(pm_diagnostics_qualified=False, sleep_requested=True, full_suspend_requested=False)
            if passed:
                try: pm_result = pm_stages.verify_final(directory, plan['pm_test_last_stage'])
                except (OSError, ValueError, RuntimeError, KeyError) as caught:
                    passed = False; error = caught
            r.qualify.save(directory, 'pm-result.json', pm_result)
            result.update(pm_result)
        if plan.get('usb_cycle_requested'):
            cycle_result = dict(usb_cycle_qualified=False, sleep_requested=False)
            if passed:
                try: cycle_result = usb_cycle.verify_final(directory)
                except (OSError, ValueError, RuntimeError, KeyError) as caught:
                    passed = False; error = caught
            r.qualify.save(directory, 'usb-cycle-result.json', cycle_result)
            result.update(cycle_result)
        result.update(result='passed' if passed else 'failed',
            profile_qualified=passed,
            fixed_swap_preserved=True, default_policy_paging_qualified=passed,
            recovered_boot_id=after['boot_id'], ordinary_outputs_retained=outputs,
            source_hashes_match=True, no_writer=True)
        if error is not None: result['error'] = str(error)
        r.qualify.save(directory, 'result.json', result)
        r.qualify.save(directory, 'final-idle-check.json', dict(healthy_boot=after['boot_id'],
            layout='swap', no_writer=True, locks_acquired=True, source_hashes_match=True,
            source_count=len(plan['all_executed_sources_sha256']), ordinary_outputs_retained=outputs))
        if not passed: raise RuntimeError('Power/swap candidate did not qualify; M69 recovery and retained evidence are recorded')


def main(configure_artifacts=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--observe-seconds', type=int, default=0, metavar='0..90',
                        help='Observe accepted candidate before strict checks; recovery deadlines stay unchanged')
    parser.add_argument('--keep', action='store_true',
                        help='Keep a fully qualified candidate installed as the new accepted baseline')
    diagnostic = parser.add_mutually_exclusive_group()
    diagnostic.add_argument('--watchdog-expiry', action='store_true',
                        help='After full candidate checks, qualify keepalive loss and automatic recovery')
    diagnostic.add_argument('--pm-test', choices=pm_stages.STAGES,
                            help='Run PM diagnostics through this stage, starting with freezer')
    diagnostic.add_argument('--usb-cycle', action='store_true',
                            help='Qualify guarded software USB detach/reconnect without requesting sleep')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    if configure_artifacts is not None:
        parser.description = 'Test the normal Gemini bundle with automatic M69 recovery'
        parser.add_argument('--bundle', type=Path, default=ROOT/'result')
        parser.add_argument('--reclaim-cache', type=Path,
                            help='Host copy of an unused squashfs to archive and remove if space is needed')
        parser.add_argument('--install-efi', type=Path,
                            help='Install matching efiBootFiles through the healthy candidate before recovery')
        parser.add_argument('--bootloader', type=Path,
                            help='Boot the installed EFI entry through this normal bootloader package')
        parser.add_argument('--efi-files', type=Path,
                            help='Matching installed efiBootFiles to verify with --bootloader')
    args = parser.parse_args(); directory = args.out.resolve()
    if not 0 <= args.observe_seconds <= 90:
        parser.error('--observe-seconds must be between 0 and 90')
    artifact_args = []
    if configure_artifacts is not None:
        args.bundle = args.bundle.resolve(strict=True)
        if args.reclaim_cache: args.reclaim_cache = args.reclaim_cache.resolve(strict=True)
        if args.install_efi: args.install_efi = args.install_efi.resolve(strict=True)
        if args.bootloader: args.bootloader = args.bootloader.resolve(strict=True)
        if args.efi_files: args.efi_files = args.efi_files.resolve(strict=True)
        configure_artifacts(args.bundle, args.reclaim_cache, args.install_efi, args.bootloader, args.efi_files)
        artifact_args = ['--bundle', str(args.bundle)]
        if args.reclaim_cache: artifact_args += ['--reclaim-cache', str(args.reclaim_cache)]
        if args.install_efi: artifact_args += ['--install-efi', str(args.install_efi)]
        if args.bootloader: artifact_args += ['--bootloader', str(args.bootloader)]
        if args.efi_files: artifact_args += ['--efi-files', str(args.efi_files)]
    if args.execute and not args.worker:
        unit = PROFILE+'-'+str(int(time.time()))+'-'+str(os.getpid())
        print('Starting durable power/swap worker '+unit, flush=True)
        child = subprocess.run(['systemd-run', '--user', '--collect', '--wait', '--pipe', '--quiet', '--unit='+unit,
            '--property=RuntimeMaxSec=2400', '--setenv=PATH='+os.environ['PATH'], '--setenv=GEMINI_POWER_SWAP_UNIT='+unit,
            sys.executable, str(ENTRYPOINT), '--worker', '--out', str(directory)] +
            (['--watchdog-expiry'] if args.watchdog_expiry else []) +
            (['--pm-test', args.pm_test] if args.pm_test else []) +
            (['--usb-cycle'] if args.usb_cycle else []) +
            (['--keep'] if args.keep else []) +
            ['--observe-seconds', str(args.observe_seconds)] + artifact_args)
        if child.returncode: raise RuntimeError('Power/swap worker failed; inspect its retained trial and recovery evidence')
        return
    if args.worker:
        unit = os.environ.get('GEMINI_POWER_SWAP_UNIT', '')
        if (not re.fullmatch(re.escape(PROFILE)+r'-[0-9]+-[0-9]+', unit) or not os.environ.get('INVOCATION_ID') or
                f.q.r.qualify.run(['systemctl', '--user', 'show', unit, '-p', 'MainPID', '--value']).strip() != str(os.getpid())):
            raise RuntimeError('Candidate trial lacks its durable owner')
    os.umask(0o077)
    r = configure(args.watchdog_expiry, args.pm_test, args.usb_cycle)
    r.OBSERVE_SECONDS = args.observe_seconds
    if args.keep and (args.watchdog_expiry or args.pm_test or args.usb_cycle):
        raise ValueError('--keep promotes a plain qualification; diagnostics always roll back')
    r.KEEP = args.keep
    before = preflight(r, directory, args.worker)
    if not args.worker:
        print('Power/swap preflight passed; no device writes or reboot'); return
    error = None
    try: r.trial(directory, PROFILE, before, f.q.SSH)
    except Exception as caught:
        error = caught
        (directory/'worker-error.txt').write_text(str(caught)+'\n')
        print('Candidate observer failed; awaiting the existing recovery services', flush=True)
    finish(r, directory, before, error)
    print('PASS: built-in zswap policy, real paging, ordinary Nix build and M69 recovery', flush=True)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: sys.exit(str(error))
