#!/usr/bin/env python3
"""Boot a normal Nix bundle, check it, then restore the known M69 recovery image.

Read-only preflight unless --execute is given. The durable boot-only supervisor
owns both flashes. RTC startup, UTC, alarms, paging and ordinary Nix builds are
checked; --watchdog-expiry substitutes keepalive loss for the alarm sequence.
--bootloader and --efi-files exercise an already installed boot-manager entry.
"""
from contextlib import ExitStack
import fcntl
from functools import partial
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boot_recovery', ROOT/'tools/qualify-power-swap.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
rtc = p.f.q.module('rtc_alarms', ROOT/'tools/qualify-rtc-alarm.py')
calendar = p.f.q.module('rtc_calendar', ROOT/'tools/qualify-rtc-calendar.py')
cache = p.f.q.module('store_cache', ROOT/'tools/qualify-store-cache.py')
stage1 = p.f.q.module('stage1_rescue', ROOT/'tools/qualify-rtc-stage1-rescue.py')
startup = p.f.q.module('rtc_startup', ROOT/'tools/qualify-rtc-startup.py')
installer = p.f.q.module('boot_installer', ROOT/'nix/gemini-boot-install.py')
EFI_FILES = None
EFI_MANIFEST = None
BOOTLOADER = None
INSTALL_EFI = False
p.PROFILE = 'boot-test'
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES = tuple('tools/'+name for name in (
    'test-boot.py', 'qualify-rtc-alarm.py', 'qualify-rtc-calendar.py',
    'qualify-store-cache.py', 'qualify-rtc-stage1-rescue.py', 'qualify-rtc-startup.py')) + (
        'nix/gemini-boot-install.py', 'nix/gemini-efi-publish.sh')
base_configure, base_preflight, base_finish = p.configure, p.preflight, p.finish


def artifacts(bundle, reclaim_cache=None, install_efi=None, bootloader=None, efi_files=None):
    global EFI_FILES, EFI_MANIFEST, BOOTLOADER, INSTALL_EFI
    if bool(bootloader) != bool(efi_files) or (bootloader and (install_efi or reclaim_cache)):
        raise ValueError('--bootloader requires --efi-files and an already installed generation')
    bundle = bundle.resolve(strict=True)
    fields = {}
    for row in (bundle/'MANIFEST').read_text().splitlines():
        if '=' not in row or row.startswith('/'): continue
        key, value = row.split('=', 1)
        if key in fields: raise ValueError('Duplicate bundle manifest key: '+key)
        fields[key] = value
    sha = fields['store-sha256']
    if (not re.fullmatch('[0-9a-f]{64}', sha) or
            fields['store-file'] != 'mainline-nixos-'+sha+'.squashfs' or
            not re.fullmatch('/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+', fields['system'])):
        raise ValueError('Invalid bundle store identity')
    kernel = (bundle/'kernel').resolve(strict=True)
    if kernel.parent != Path('/nix/store') or fields['kernel'] != kernel.name:
        raise ValueError('Bundle kernel identity differs')
    store = bundle/fields['store-file']
    size = int(fields['store-size'])
    if size <= 0 or store.stat().st_size != size or cache.digest(store) != sha:
        raise ValueError('Bundle store content differs from manifest')
    p.BUNDLE, p.KERNEL, p.SYSTEM = bundle, kernel, fields['system']
    p.STORE_SHA, p.STORE_SIZE = sha, size
    p.BOOT_SHA = cache.digest(bundle/'boot-padded-p22.img')
    p.NOTES_SHA = p.f.q.r.power_kernel.notes_sha(kernel)
    p.RECLAIM_CACHE = reclaim_cache.resolve(strict=True) if reclaim_cache else None
    EFI_FILES, EFI_MANIFEST, BOOTLOADER = None, None, None
    INSTALL_EFI = bool(install_efi)
    if install_efi or efi_files:
        package = (install_efi or efi_files).resolve(strict=True)
        with tempfile.TemporaryDirectory() as staging:
            manifest = installer.prepare(package, Path(staging))
        expected = dict(file=fields['store-file'], sha256=sha, size=size, system=p.SYSTEM)
        if manifest['store'] != expected or Path(manifest['linux_payload']).resolve() != bundle:
            raise ValueError('EFI files do not belong to the selected system bundle')
        EFI_FILES, EFI_MANIFEST = package, manifest
    if bootloader:
        BOOTLOADER = bootloader.resolve(strict=True)
        manifest = json.loads((BOOTLOADER/'manifest.json').read_text())
        image = BOOTLOADER/'boot-padded-p22.img'
        if (manifest['profile'] != 'efi-manager' or manifest['recovery_test'] != 0 or
                Path(manifest['linux_payload']).resolve() != bundle or
                not installer.matches(image, manifest['files']['boot-padded-p22.img'])):
            raise ValueError('Bootloader does not contain the selected normal Linux fallback')
        p.BOOT_SHA = cache.digest(image)
        p.f.q.r.entry_dt.verify_carrier(image, p.BOOT_SHA, bundle)


def verify_efi(runner, ssh, state, directory, name):
    profile = runner.efi_files.FilesProfile(EFI_FILES, EFI_MANIFEST['archive']['sha256'],
                                            EFI_MANIFEST['archive']['size'], 6)
    runner.efi_files.evidence(ssh, state['boot_id'], directory, runner.qualify,
                             require_verified=False, name=name, profile=profile)
    runner.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(sha256sum /gemian/nixos/{EFI_MANIFEST['store']['file']} | cut -d' ' -f1)" = {p.STORE_SHA}
''', directory, name.removesuffix('.json')+'-store')


def install_efi(runner, ssh, state, directory):
    """Upload to RAM only; the installed product owns persistent publication."""
    remote = '/run/gemini-boot-install-'+EFI_MANIFEST['payload_identity']
    guard = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(readlink /run/current-system)" = {shlex.quote(p.SYSTEM)}
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = {p.BOOT_SHA}
'''
    runner.persistence.run(ssh, guard+f'umask 077\nmkdir {remote}\n', directory, 'efi-upload-directory')
    for name in ('manifest.json', 'files.manifest', 'boot-files.tar'):
        source = EFI_FILES/name
        command = guard+f'''umask 077
(set -C; cat > {remote}/{name})
test "$(stat -c %s {remote}/{name})" = {source.stat().st_size}
test "$(sha256sum {remote}/{name} | cut -d' ' -f1)" = {cache.digest(source)}
'''
        with source.open('rb') as src, (directory/('efi-upload-'+name+'.log')).open('w') as log:
            subprocess.run(ssh+[command], stdin=src, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    raw = runner.persistence.run(ssh, guard+f'gemini-boot-install {remote} --json\n',
                                 directory, 'efi-install', timeout=240)
    result = json.loads(raw)
    if any(result.get(k) != v for k,v in dict(entry=EFI_MANIFEST['entry'], system=p.SYSTEM,
            store_sha256=p.STORE_SHA, read_only=True, payload_identity=EFI_MANIFEST['payload_identity']).items()):
        raise RuntimeError('Installed EFI generation differs from the selected bundle')
    verify_efi(runner, ssh, state, directory, 'installed-efi-files.json')
    runner.qualify.save(directory, 'efi-install-result.json', result)


def verify_manager_handoff(runner, before, after, profile):
    runner.verify_memory_handoff(before, after)
    if after.get(runner.HANDOFF_MARKER) != b'efi\0'.hex():
        raise RuntimeError('The normal bootloader did not hand off through EFI')
    runner.efi_manager.verify_tree(after, EFI_MANIFEST['files'][installer.MANAGER]['sha256'])
    obsolete = set(runner.MARKERS)-{runner.HANDOFF_MARKER,*runner.efi_manager.MARKERS}
    if any(key in after for key in obsolete):
        raise RuntimeError('The normal bootloader unexpectedly ran a historical diagnostic app')


def manager_evidence(runner, ssh, state, directory):
    tree = json.loads((directory/'candidate-tree.json').read_text())
    runner.efi_manager.evidence(ssh, state['boot_id'], directory, runner.qualify, tree,
        entry=EFI_MANIFEST['entry'], kernel=p.KERNEL, sha=EFI_MANIFEST['files'][installer.MANAGER]['sha256'])
    source = EFI_FILES/'tree'/EFI_MANIFEST['entry_device_tree']
    if not installer.matches(source, EFI_MANIFEST['files'][EFI_MANIFEST['entry_device_tree']]):
        raise ValueError('Entry device tree differs from its EFI package')
    proof = runner.entry_dt.verify_native(source, directory/'candidate-fdt.dtb', EFI_MANIFEST['payload_identity'])
    runner.persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
test "$(cat /sys/devices/system/cpu/cpu8/online)" = 1
test "$(cat /sys/devices/system/cpu/cpu9/online)" = 1
''', directory, 'efi-native-cpus')
    runner.qualify.save(directory, 'entry-dt-evidence.json', dict(boot_id=state['boot_id'], **proof))
    verify_efi(runner, ssh, state, directory, 'selected-efi-files.json')


def configure(watchdog=False, pm_test=None, cycle=False):
    if pm_test or cycle:
        raise ValueError('Boot test supports alarms or watchdog expiry; PM/USB need separate recovery checks')
    runner = base_configure()
    runner.backend.MTK = runner.backend.MTK_RTC
    if BOOTLOADER is not None:
        runner.PROFILES[p.PROFILE] = (BOOTLOADER/'boot-padded-p22.img', p.BOOT_SHA)
        runner.DIRECT_NIX_PROFILES = tuple(v for v in runner.DIRECT_NIX_PROFILES if v != p.PROFILE)
        for name in ('NIX_EFI_PROFILES', 'EFI_LINUX_PROFILES', 'UBOOT_LINUX_PROFILES'):
            setattr(runner, name, getattr(runner, name)+(p.PROFILE,))
        runner.verify_handoff_tree = partial(verify_manager_handoff, runner)
        runner.power_kernel.evidence = partial(p.evidence, require_efi=True)
        runner.power_kernel.store_profile = lambda provisioner: p.store_profile(provisioner)._replace(require_efi=True)
        runner.efi_linux.evidence = partial(runner.efi_linux.evidence, legacy_cpu_identity=False)
        candidate = runner.candidate_return
        def booted_candidate(ssh, before, directory, profile):
            state = candidate(ssh, before, directory, profile)
            manager_evidence(runner, ssh, state, directory)
            return state
        runner.candidate_return = booted_candidate
    elif INSTALL_EFI:
        candidate = runner.candidate_return
        def publish_candidate(ssh, before, directory, profile):
            state = candidate(ssh, before, directory, profile)
            install_efi(runner, ssh, state, directory)
            return state
        runner.candidate_return = publish_candidate
    # Probe the native clock after health checks, before calendar.install's
    # explicit RTC_SET_TIME, followed by the original alarm sequence.
    startup.install_probe(p, runner, calendar)
    calendar.install(p, runner)
    if watchdog:
        # Compose expiry last: the base watchdog wrapper would otherwise reset
        # Linux before startup/UTC evidence could be collected.
        runner.watchdog_expiry_requested = True
        p.watchdog_expiry.install(p, runner)
    else:
        rtc.install(p, runner)
    return runner
p.configure = configure


def calendar_preflight(runner, directory, execute):
    before = base_preflight(runner, directory, execute)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        if p.f.snapshot('swap') != dict(before, layout='swap'):
            raise RuntimeError('Baseline changed before calendar preflight')
        raw = runner.persistence.run(p.f.q.SSH, '''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'notes='; sha256sum /sys/kernel/notes | cut -d' ' -f1
printf 'rtc='; cat /sys/class/rtc/rtc0/since_epoch
test -z "$(cat /sys/class/rtc/rtc0/wakealarm)"
test ! -d /run/gemini-rtc-alarm.lock
''', directory, 'rtc-calendar-baseline')
        values = calendar.parse(raw, ('boot_id', 'notes', 'rtc'))
        if values['boot_id'] != before['boot_id']:
            raise RuntimeError('Calendar baseline boot changed')
        runner.qualify.save(directory, 'rtc-calendar-baseline.json', values)
        cache.prepare(p, runner, directory, before)
    cache.install(p, runner, directory)
    stage1.install(p, runner, directory)
    return before


def preflight(runner, directory, execute):
    before = calendar_preflight(runner, directory, execute)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        if p.f.snapshot('swap') != dict(before, layout='swap'):
            raise RuntimeError('Baseline changed before RTC startup preflight')
        startup.prepare(p, runner, calendar, directory, before)
        if BOOTLOADER is not None:
            verify_efi(runner, p.f.q.SSH, before, directory, 'before-selected-efi-files.json')
    startup.install_transition(p, runner, calendar, directory, before)
    if EFI_FILES is not None:
        runner.qualify.save(directory, 'efi-install-package.json', EFI_MANIFEST)
    return before
p.preflight = preflight


def alarm_finish(r,directory,before,error=None):
    proof=dict(rtc_alarm_diagnostics_qualified=False,sleep_requested=False,wake_from_suspend_qualified=False)
    if not r.watchdog_expiry_requested and error is None:
        try:proof=rtc.verify_final(directory)
        except (OSError,ValueError,RuntimeError,KeyError) as caught:error=caught
    # Complete automatic recovery and its locked retention/source audit even
    # when the RTC evidence is missing or reports a failed cancellation.
    try:base_finish(r,directory,before,error)
    finally:
        if not r.watchdog_expiry_requested:
            r.qualify.save(directory,'rtc-result.json',proof)
            result_file=directory/'result.json'
            if result_file.exists():
                result=json.loads(result_file.read_text());result.update(proof)
                r.qualify.save(directory,'result.json',result)


def calendar_finish(runner, directory, before, error=None):
    proof = dict(rtc_utc_write_read_qualified=False, rtc_reboot_persistence_qualified=False,
                 kernel_periodic_rtc_updates=False, sleep_requested=False)
    if error is None:
        try:
            calendar.verify_candidate(directory)
            proof['rtc_utc_write_read_qualified'] = True
        except (OSError, ValueError, RuntimeError, KeyError) as caught:
            error = caught
    try:
        # This always completes the original alarm proof, recovery and full
        # storage/source/ordinary-output audit, even if calendar checks fail.
        alarm_finish(runner, directory, before, error)
        proof.update(cache.verify_final(runner, directory))
        reboot = calendar.recovered(p, runner, directory)
        proof['rtc_reboot_persistence_qualified'] = reboot['rtc_reboot_persistence_qualified']
    except Exception as caught:
        error = caught
        raise
    finally:
        runner.qualify.save(directory, 'rtc-calendar-result.json', proof)
        result_file = directory/'result.json'
        if result_file.exists():
            result = json.loads(result_file.read_text()); result.update(proof)
            passed = error is None and result.get('profile_qualified') is True and all(
                proof[k] for k in ('rtc_utc_write_read_qualified', 'rtc_reboot_persistence_qualified'))
            result.update(result='passed' if passed else 'failed', profile_qualified=passed)
            if error is not None: result['error'] = str(error)
            runner.qualify.save(directory, 'result.json', result)


def finish(runner, directory, before, error=None):
    proof = dict(rtc_startup_qualified=False, runtime_clock_policy_restored=False)
    if error is None:
        try:
            startup.verify_final(directory)
            proof['rtc_startup_qualified'] = True
        except (OSError, ValueError, RuntimeError, KeyError) as caught:
            error = caught
    try:
        calendar_finish(runner, directory, before, error)
    except Exception as caught:
        error = caught
        raise
    finally:
        try:
            proof.update(startup.cleanup(p, runner, directory, before))
            if EFI_FILES is not None:
                proof_key = 'efi_install_qualified' if INSTALL_EFI else 'efi_boot_qualified'
                proof[proof_key] = False
                if error is None or (directory/'efi-install-result.json').exists():
                    state = p.f.snapshot('swap')
                    verify_efi(runner, p.f.q.SSH, state, directory, 'recovered-installed-efi-files.json')
                    if BOOTLOADER is not None:
                        candidate = json.loads((directory/'candidate-linux.json').read_text())
                        manager = json.loads((directory/'manager-evidence.json').read_text())
                        entry_dt = json.loads((directory/'entry-dt-evidence.json').read_text())
                        if (manager['boot_id'] != candidate['boot_id'] or entry_dt['boot_id'] != candidate['boot_id'] or
                                manager['efi_variables']['LoaderEntrySelected'] != EFI_MANIFEST['entry'] or
                                entry_dt['identity'] != EFI_MANIFEST['payload_identity']):
                            raise RuntimeError('Missing matching boot-manager and selected native DT evidence')
                    proof[proof_key] = True
        except Exception as caught:
            error = caught
            raise
        finally:
            runner.qualify.save(directory, 'rtc-startup-result.json', proof)
            result_file = directory/'result.json'
            if result_file.exists():
                result = json.loads(result_file.read_text()); result.update(proof)
                passed = error is None and result.get('profile_qualified') is True and all(
                    proof[k] for k in ('rtc_startup_qualified', 'runtime_clock_policy_restored'))
                result.update(result='passed' if passed else 'failed', profile_qualified=passed)
                if error is not None: result['error'] = str(error)
                runner.qualify.save(directory, 'result.json', result)
p.finish = finish


if __name__ == '__main__':
    try: p.main(artifacts)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error: sys.exit(str(error))
