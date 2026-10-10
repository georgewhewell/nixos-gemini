#!/usr/bin/env python3
"""Audit terminal writers, retained storage and the exact accepted boot identity."""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--trial', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--media-observer-unit')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
trial = args.trial.resolve(strict=True)
out = args.out.resolve()
plan = json.loads((trial/'plan.json').read_text())
original = plan['initial_baseline']
promoted = trial/'promoted-baseline.json'
kept = promoted.exists()
baseline = json.loads(promoted.read_text()) if kept else original
current = json.loads((root/'research/accepted-baseline.json').read_text())
if current != original and (not kept or current != baseline):
    raise RuntimeError('Accepted descriptor changed outside this trial')
spec = importlib.util.spec_from_file_location('gnome_terminal_audit', root/'tools/test-boot.py')
boot = importlib.util.module_from_spec(spec); spec.loader.exec_module(boot)
context = boot.p
runner = context.f.q.r
for qualify in (runner.qualify, context.f.q.r.qualify):
    qualify.adopt_baseline(baseline)

with ExitStack() as locks:
    for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
        handle = locks.enter_context((runner.LOCKS/name).open('a'))
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    runner.qualify.check_host_idle()
    units = json.loads((trial/'units.json').read_text())
    if args.media_observer_unit:
        units['media_observer'] = args.media_observer_unit
    if any(context.f.owner_alive(unit) for unit in units.values()):
        raise RuntimeError('Trial still owns live services')
    out.mkdir(mode=0o700)
    (out/'audit-at-execution.py').write_bytes(Path(__file__).read_bytes())
    state = context.f.snapshot('swap')
    context.storage_identity(state)
    expected = json.loads((trial/('candidate-linux.json' if kept else 'after.json')).read_text())
    if state != dict(expected, layout='swap'):
        raise RuntimeError('Final device identity differs from the completed trial')
    result = json.loads((trial/'result.json').read_text())
    if kept:
        if (result.get('result') != 'passed' or result.get('profile_qualified') is not True
                or result.get('promoted') is not True or baseline.get('paging_policy') != 'zram'
                or baseline.get('desktop') != 'gnome'):
            raise RuntimeError('Kept candidate lacks full GNOME and zram qualification')
        evidence = json.loads((trial/'power-swap-evidence.json').read_text())
        if (evidence.get('ram_only_paging_qualified') is not True
                or evidence.get('runtime_policy_writes') is not False
                or evidence.get('paging', {}).get('flash_swap_written_sectors') != 0):
            raise RuntimeError('Candidate lacks real RAM-only paging I/O evidence')
        if (trial/'supervisor.state').read_text().split()[0] != 'supervisor_candidate_self_accepted':
            raise RuntimeError('Supervisor did not acknowledge candidate acceptance')
    if baseline.get('paging_policy') == 'zram':
        policy = boot.zram.policy(context, context.f.q.SSH, state, out, runner.persistence,
                                 runner.qualify, 'final-zram-policy')
    else:
        ram = context.f.q.module('restored_ram_policy', root/'tools/qualify-ram-only-recovery.py')
        policy = ram.accepted_policy(context, runner, state, out)
    outputs = context.retained_all(out, state, trial)
    if (trial/'nix-candidate.json').exists():
        latest = json.loads((trial/'nix-candidate.json').read_text())
        runner.persistent_nix.verify_retained(context.f.q.SSH, state['boot_id'], out,
            runner.qualify, runner.persistence, latest, name='candidate-output')
        outputs[trial.name] = latest['output']
    backend = json.loads((trial/'backend.json').read_text())
    if backend['rollback_sha256'] != original['boot_sha256']:
        raise RuntimeError('Trial staged a different recovery image')
    if runner.qualify.accepted_digest(Path(baseline['image'])) != state['boot_sha256']:
        raise RuntimeError('Final image differs from its device readback')
    plan = json.loads((trial/'plan.json').read_text())
    for name, sha in plan['all_executed_sources_sha256'].items():
        for source in (root/name, trial/'executed-sources'/Path(name).name):
            if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
                raise RuntimeError('Qualification source differs: '+name)
    for name in ('p22-proof-supervisor.sh', 'p22-flash-wrapper.sh', 'p22-mtkclient-backend.py',
                 'trex-gadget-net-watcher.sh', 'p22-trex-transaction-holder.sh'):
        if (trial/name).read_bytes() != (trial/'executed-sources'/name).read_bytes():
            raise RuntimeError('Executed supervisor differs: '+name)
    health = runner.persistence.run(context.f.q.SSH, 'set -eu\ntest "$(cat /proc/sys/kernel/random/boot_id)" = '+state['boot_id']+'\nsystemctl is-system-running\ncat /proc/sys/kernel/tainted\ntest ! -e /sys/module/mt6797_vdec\n', out, 'final-linux-health')
    if health.splitlines() != ['running', '0']:
        raise RuntimeError('Final kernel is not healthy and untainted')
    runner.qualify.check_host_idle()
    if context.f.snapshot('swap') != state:
        raise RuntimeError('Device changed during independent audit')
    runner.qualify.save(out, 'result.json', dict(result='passed', baseline=baseline,
        final_boot_id=state['boot_id'], kept_candidate=kept, no_writer=True,
        all_trial_units_terminal=True, locks_acquired=True, source_hashes_match=True,
        source_count=len(plan['all_executed_sources_sha256']), ordinary_outputs_retained=outputs,
        paging=policy, final_taint=0, temporary_decoder_absent=True, terminal_units=units))
print('PASS: independent terminal, storage, source, output and paging audit')
