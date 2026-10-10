#!/usr/bin/env python3
"""Preserved no-paging recovery migration through the normal boot supervisor.

No writer or reboot entry point lives here. test-boot.py owns execution. This
temporary recovery has no zram; normal development candidates still require it.
"""
import hashlib
from contextlib import ExitStack
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import shlex
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOST_PROOF = ROOT/'research/ram-only-recovery-20261010.json'
QUALIFICATION_FLAGS = ('profile_qualified', 'ram_only_paging_qualified', 'source_hashes_match', 'no_writer',
    'rtc_startup_qualified', 'runtime_clock_policy_restored', 'rtc_utc_write_read_qualified',
    'rtc_reboot_persistence_qualified', 'rtc_alarm_diagnostics_qualified',
    'ordinary_daemon_build_qualified', 'nix_persistence_qualified')
spec = importlib.util.spec_from_file_location('ram_rescue_builder', ROOT/'tools/build-ram-only-recovery.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_bundle(bundle):
    """Reproduce the immutable artifact and bind its preserved boot components."""
    bundle = Path(bundle).resolve(strict=True)
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-gemini-ram-only-recovery', str(bundle)):
        raise RuntimeError('RAM-only rescue must be an immutable recovery package')
    proof = json.loads(HOST_PROOF.read_text())
    if (proof.get('result') != 'passed' or proof.get('package') != str(bundle) or
            proof.get('source_builder_sha256') != digest(ROOT/'tools/build-ram-only-recovery.py') or
            proof.get('source_test_sha256') != digest(ROOT/'tools/test-ram-only-recovery.py') or
            proof.get('generator', {}).get('returncode') != 0 or
            proof.get('arm64_busybox_syntax', {}).get('returncode') != 0):
        raise RuntimeError('RAM-only recovery host qualification differs')
    record = json.loads((bundle/'build-result.json').read_text())
    if record != proof['build']:
        raise RuntimeError('RAM-only recovery build record differs')
    with tempfile.TemporaryDirectory(prefix='gemini-ram-rescue-') as tmp:
        reproduced = Path(tmp)/'bundle'
        builder.build(Path(record['source_bundle']), reproduced)
        for name in ('boot-padded-p22.img', 'initramfs.cpio.gz', 'MANIFEST', 'build-result.json'):
            if (bundle/name).read_bytes() != (reproduced/name).read_bytes():
                raise RuntimeError('RAM-only recovery reproduction differs: '+name)
        for name in ('system', 'kernel', 'gemini-usb11-host.dtb'):
            if (bundle/name).resolve(strict=True) != (reproduced/name).resolve(strict=True):
                raise RuntimeError('RAM-only recovery component differs: '+name)
    generated = proof['generator']
    if (generated['generated_masks'] != {'early/'+unit: '/dev/null' for unit in builder.MASK_UNITS} or
            digest(generated['program']) != generated['program_sha256'] or
            digest(generated['emulator']) != generated['emulator_sha256']):
        raise RuntimeError('ARM64 generator qualification is not bound to the rescue masks')
    if generated['program'] != str((Path(record['system'])/'systemd').resolve(strict=True)/
                                   'lib/systemd/system-generators/systemd-debug-generator'):
        raise RuntimeError('Generator qualification belongs to another userspace')
    return dict(record, package=str(bundle), notes_sha256=proof['kernel_notes_sha256'],
                host_proof_sha256=digest(HOST_PROOF))


def policy_script(state, record, boot_policy=True):
    boot = state['boot_id']
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot):
        raise ValueError('Invalid no-paging boot identity')
    for key in ('boot_sha256',):
        if not re.fullmatch('[0-9a-f]{64}', state[key]):
            raise ValueError('Invalid no-paging image identity')
    if state['system'] != record['system']:
        raise RuntimeError('No-paging recovery changed its preserved userspace')
    mask_root = '/run/systemd/generator.early' if boot_policy else '/run/systemd/system'
    units = builder.MASK_UNITS if boot_policy else builder.MASK_UNITS[:2]
    masks = ''.join(f'test "$(readlink {shlex.quote(mask_root+"/"+unit)})" = /dev/null\n'
                    f'test "$(systemctl show {shlex.quote(unit)} -p LoadState --value)" = masked\n'
                    for unit in units)
    boot_guard = 'test ! -e /sys/firmware/efi\n' if boot_policy else ''
    resume_guard = ('test "$(cat /sys/power/resume)" = 0:0' if boot_policy else
                    'test "$(cat /sys/power/resume)" = 0:0 || '
                    'test "$(cat /sys/power/resume)" = "$(cat /sys/class/block/mmcblk0p34/dev)"')
    return f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}
test "$(readlink /run/current-system)" = {shlex.quote(record['system'])}
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = {state['boot_sha256']}
test "$(sha256sum /sys/kernel/notes | cut -d' ' -f1)" = {record['notes_sha256']}
test "$(zcat /proc/config.gz | sha256sum | cut -d' ' -f1)" = {record['kernel_config_sha256']}
test "$(cat /sys/module/zswap/parameters/enabled)" = N
{resume_guard}
awk 'END {{ exit !(NR == 1) }}' /proc/swaps
test ! -e /sys/class/block/zram0
test "$(sed -n 's/^AllowHibernation=//p' /etc/systemd/sleep.conf)" = false
test "$(sed -n 's/^AllowSuspendThenHibernate=//p' /etc/systemd/sleep.conf)" = false
test "$(sed -n 's/^AllowHybridSleep=//p' /etc/systemd/sleep.conf)" = no
{boot_guard}{masks}printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'cmdline='; cat /proc/cmdline
printf 'p34_stat='; cat /sys/class/block/mmcblk0p34/stat
printf 'swap_rows='; awk 'END {{ print NR-1 }}' /proc/swaps
printf 'zswap='; cat /sys/module/zswap/parameters/enabled
printf 'resume='; cat /sys/power/resume
printf 'p34_dev='; cat /sys/class/block/mmcblk0p34/dev
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot}
'''


def verify_policy(raw, state, record, boot_policy=True):
    rows = raw.splitlines()
    values = dict(row.split('=', 1) for row in rows)
    if (len(rows) != len(values) or set(values) !=
            {'boot_id', 'cmdline', 'p34_stat', 'swap_rows', 'zswap', 'resume', 'p34_dev'} or
            values['boot_id'] != state['boot_id'] or values['swap_rows'] != '0' or
            values['zswap'] != 'N' or not re.fullmatch(r'[0-9]+:[0-9]+', values['p34_dev']) or
            values['resume'] not in (('0:0',) if boot_policy else ('0:0', values['p34_dev']))):
        raise RuntimeError('No-paging recovery runtime policy differs')
    stats = values['p34_stat'].split()
    if (len(stats) != 17 or not all(v.isdecimal() for v in stats) or
            any(int(stats[i]) for i in (4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 16))):
        raise RuntimeError('Reserved eMMC swap partition received writes, discard or flush I/O')
    if boot_policy:
        words = values['cmdline'].split()
        expected = record['command_line'].split()
        for word in expected:
            if words.count(word) != 1:
                raise RuntimeError('No-paging command line is missing or duplicates a policy argument')
        if any(word.startswith(('resume=', 'zswap.', 'systemd.mask=', 'systemd.gpt_auto=')) and
               word not in expected for word in words):
            raise RuntimeError('No-paging command line contains a conflicting policy argument')
    return dict(**values, paging_policy='none', active_swap=False, flash_swap_active=False,
                flash_swap_written_sectors=0, masks_from_boot=boot_policy,
                runtime_policy_writes=False)


def policy(context, runner, state, directory, record, name, boot_policy=True):
    raw = runner.persistence.run(context.f.q.SSH, policy_script(state, record, boot_policy), directory, name)
    result = verify_policy(raw, state, record, boot_policy)
    runner.qualify.save(directory, name+'.json', result)
    return result


def install(context, record):
    initial = dict(context.f.q.r.qualify.BASELINE)
    if (initial['system'] != record['system'] or initial.get('paging_policy') in ('none', 'zram') or
            initial['boot_sha256'] == record['image_sha256']):
        raise RuntimeError('Recovery migration must start from the recorded historical userspace and image')
    context.PAGING_POLICY = 'none'
    context.probe_identity = lambda: record['host_proof_sha256']
    target = dict(name='ram-only-rescue-awaiting-qualification', image=record['package']+'/boot-padded-p22.img',
                  boot_sha256=record['image_sha256'], system=record['system'], store=initial['store'],
                  boot='direct', rtc_epoch=initial['rtc_epoch'], zswap_enabled=False,
                  paging_policy='none', previous=initial['name'])

    def baseline_paging(runner, directory, state):
        if state['boot_sha256'] == initial['boot_sha256']:
            return policy(context, runner, state, directory, record, 'baseline-no-paging-policy', False)
        if state['boot_sha256'] != record['image_sha256']:
            raise RuntimeError('Migration baseline has an unidentified recovery image')
        return policy(context, runner, state, directory, record, 'baseline-no-paging-policy')

    def evidence(ssh, boot_id, directory, qualify, persistence, require_efi=False):
        if require_efi:
            raise RuntimeError('Temporary RAM-only recovery must boot directly')
        runner = type('PolicyRunner', (), dict(qualify=qualify, persistence=persistence))
        state = dict(boot_id=boot_id, system=record['system'], boot_sha256=record['image_sha256'])
        current = policy(context, runner, state, directory, record, 'candidate-no-paging-policy')
        watchdog = context.paging.watchdog(directory, state, 'candidate-watchdog')
        qualify.save(directory, 'power-swap-evidence.json', dict(**state, watchdog=watchdog, paging=current,
            paging_policy='none', default_policy_paging_qualified=True, ram_only_paging_qualified=True,
            sleep_requested=False, hibernation_io_qualified=False, runtime_policy_writes=False))
        return state

    context.baseline_paging, context.evidence = baseline_paging, evidence
    return initial, target


def configure(context, runner, record, initial, target):
    runner.RESCUE_BASELINE = target
    runner.CANDIDATE_DESKTOP = None
    expect = runner.expect_verified_rescue

    def prepare_recovery_audit(directory, before):
        expected = expect(directory, before)
        # The other snapshot adapter is independent of the trial module.
        context.f.q.r.qualify.adopt_baseline(target)
        return expected
    runner.expect_verified_rescue = prepare_recovery_audit
    runner.prepare_recovery_audit = prepare_recovery_audit
    candidate = runner.candidate_return

    def candidate_return(ssh, before, directory, profile):
        # Admission is repeated immediately before qualification; no volatile
        # swap mutation can substitute for the artifact's boot-time masks.
        state = candidate(ssh, before, directory, profile)
        policy(context, runner, state, directory, record, 'candidate-no-paging-policy-final')
        return state
    runner.candidate_return = candidate_return


def qualified_baseline(context, runner, directory, record, initial, target):
    """Publish a reviewable descriptor only after the independent final audit."""
    result = json.loads((directory/'result.json').read_text())
    if result.get('result') != 'passed' or any(result.get(k) is not True for k in QUALIFICATION_FLAGS):
        raise RuntimeError('RAM-only recovery lacks full platform and recovery qualification')
    before = json.loads((directory/'before.json').read_text())
    candidate = json.loads((directory/'candidate-linux.json').read_text())
    after = json.loads((directory/'after.json').read_text())
    if (before['boot_sha256'] != initial['boot_sha256'] or
            len({v['boot_id'] for v in (before, candidate, after)}) != 3 or
            any(v['boot_sha256'] != record['image_sha256'] or v['system'] != record['system']
                for v in (candidate, after))):
        raise RuntimeError('Migration requires distinct initial, candidate and rescue boots')
    runner.expect_verified_rescue(directory, before)
    for name in ('candidate.state', 'supervisor-rollback.state'):
        proof = json.loads((directory/(name+'.mtk.json')).read_text())
        if (proof.get('returncode') != 0 or proof.get('first_boot_window_departed') is not True or
                proof.get('expected_sha256') != record['image_sha256']):
            raise RuntimeError('RAM-only recovery lacks both completed writes')
        attempt = Path(proof['attempt']).resolve(strict=True)
        if attempt.parent != directory.resolve() or not attempt.name.startswith(name+'-mtk-'):
            raise RuntimeError('Migration writer proof is outside the owned trial')
        runner.backend.checked_image(attempt/'boot-readback.img', record['image_sha256'])
    audit = json.loads((directory/'final-idle-check.json').read_text())
    if any(audit.get(k) is not True for k in ('no_writer', 'locks_acquired', 'source_hashes_match')) or audit['healthy_boot'] != after['boot_id']:
        raise RuntimeError('RAM-only recovery lacks its terminal independent audit')
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((runner.LOCKS/name).open('a'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.qualify.check_host_idle()
        units = json.loads((directory/'units.json').read_text())
        if any(context.f.owner_alive(unit) for unit in units.values()):
            raise RuntimeError('Recovery migration still has a live owner or service')
        current = context.f.snapshot('swap')
        if current != dict(after, layout='swap'):
            raise RuntimeError('Recovery changed after its terminal audit')
        policy(context, runner, current, directory, record, 'qualified-no-paging-policy')
    target = dict(target, name=directory.name)
    bound_files = ('result.json', 'before.json', 'candidate-linux.json', 'after.json', 'final-idle-check.json',
                   'qualified-no-paging-policy.json', 'plan.json', 'backend.json',
                   'candidate.state.mtk.json', 'supervisor-rollback.state.mtk.json')
    target['ram_only_recovery'] = dict(package=record['package'], host_proof_sha256=record['host_proof_sha256'],
        trial=str(directory.resolve()), evidence_sha256={name: digest(directory/name) for name in bound_files})
    runner.qualify.save(directory, 'qualified-ram-only-baseline.json', target)
    return target


def accepted_policy(context, runner, state, directory):
    """Admit a no-paging fallback only with its complete migration proof."""
    baseline = runner.qualify.BASELINE
    binding = baseline.get('ram_only_recovery', {})
    if baseline.get('paging_policy') != 'none' or not binding.get('evidence_sha256'):
        raise RuntimeError('No-paging recovery lacks qualified migration evidence')
    record = validate_bundle(Path(binding['package']))
    if (binding['host_proof_sha256'] != record['host_proof_sha256'] or
            baseline['image'] != record['package']+'/boot-padded-p22.img' or
            baseline['boot_sha256'] != record['image_sha256'] or baseline['system'] != record['system']):
        raise RuntimeError('Qualified no-paging recovery artifact differs')
    trial = Path(binding['trial']).resolve(strict=True)
    required = {'result.json', 'before.json', 'candidate-linux.json', 'after.json', 'final-idle-check.json',
                'qualified-no-paging-policy.json', 'plan.json', 'backend.json',
                'candidate.state.mtk.json', 'supervisor-rollback.state.mtk.json'}
    if set(binding['evidence_sha256']) != required:
        raise RuntimeError('Qualified no-paging recovery evidence set differs')
    for name, sha in binding['evidence_sha256'].items():
        if digest(trial/name) != sha:
            raise RuntimeError('Qualified no-paging recovery evidence changed: '+name)
    result = json.loads((trial/'result.json').read_text())
    if (result.get('result') != 'passed' or result.get('paging_policy') != 'none' or
            any(result.get(k) is not True for k in QUALIFICATION_FLAGS)):
        raise RuntimeError('No-paging recovery was not hardware qualified')
    boots = [json.loads((trial/name).read_text()) for name in ('before.json', 'candidate-linux.json', 'after.json')]
    plan = json.loads((trial/'plan.json').read_text())
    config = json.loads((trial/'backend.json').read_text())
    if (len({v['boot_id'] for v in boots}) != 3 or
            boots[0]['boot_sha256'] != plan['initial_baseline']['boot_sha256'] or
            any(v['boot_sha256'] != record['image_sha256'] or v['system'] != record['system'] for v in boots[1:]) or
            any(plan[k] != record['image_sha256'] for k in ('candidate_sha256', 'rescue_sha256')) or
            any(config[k] != record['image_sha256'] for k in ('candidate_sha256', 'rollback_sha256'))):
        raise RuntimeError('Qualified no-paging recovery boot and writer identities differ')
    final_policy = json.loads((trial/'qualified-no-paging-policy.json').read_text())
    if final_policy.get('masks_from_boot') is not True:
        raise RuntimeError('Qualified no-paging recovery used volatile masks')
    raw = '\n'.join(key+'='+final_policy[key] for key in ('boot_id', 'cmdline', 'p34_stat', 'swap_rows', 'zswap', 'resume', 'p34_dev'))
    verify_policy(raw, boots[2], record)
    return policy(context, runner, state, directory, record, 'baseline-no-paging-policy')
