#!/usr/bin/env python3
"""Exercise mtkclient rollback ownership before and during U-Boot reset trials.

Default is read-only preflight. Baseline executes two accepted-M69 writes and
normal Linux reboots. Reset/watchdog profiles select pinned M69 U-Boot carriers
and leave the existing durable p22 supervisor responsible for restoring M69.
No candidate is accepted. A successful return proves the recovery path; it
does not, by itself, prove which code initiated the candidate reset.
"""
import argparse
from contextlib import ExitStack
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
LOCKS = Path('/mnt/Home/src/nixos-gemini-flash-p22-20260829')
ACCEPTED = Path('/nix/store/wfqzzdajvbc4fwajplp1a4h9fs3gsc12-gemini-mainline-nixos-padded.img')
PROFILES = {
    'baseline': (ACCEPTED, '913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3'),
    'reset': (WORKSPACE / 'handoff/uboot-m69-fbfix-2/boot-padded-p22.img',
              'e9e0f6f2f44c28d98424420444c9f3466fa593adfe7f5d38c66652c349e8e950'),
    'watchdog': (WORKSPACE / 'handoff/uboot-m69-fbfix-3/boot-padded-p22.img',
                 '5f02a4db11c14fdd604626b48fdd71886db9d90ff699c936d397800a4278c66d'),
}
SUCCESS = 'supervisor_rollback_succeeded_rescue_verified '
P30_SHA = '122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159'
P31_SHA = '1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513'
PHASES = {'0x474d10e0': 'entry', '0x474d10e1': 'lowlevel_init',
          '0x474d10e2': 'board_early_init_f', '0x474d10e3': 'board_init',
          '0x474d10e4': 'board_late_init', '0x474d10e5': 'watchdog_ready',
          '0x474d10ec': 'reset_test', '0x474d10ed': 'watchdog_expiry_test',
          '0x474d10f1': 'watchdog_setup_failure'}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


qualify = module('qualify_mtk', ROOT / 'tools/qualify-mtkclient.py')
backend = module('mtk_backend', ROOT / 'research/p22-mtkclient-backend.py')


def snapshot(ssh):
    result = qualify.snapshot(ssh)
    hashes = qualify.run(ssh + ['sha256sum /dev/mmcblk0p30 /dev/mmcblk0p31']).splitlines()
    if [row.split()[0] for row in hashes] != [P30_SHA, P31_SHA]:
        raise RuntimeError('Alternate boot partitions differ from the accepted baseline')
    result.update(p30_sha256=P30_SHA, p31_sha256=P31_SHA)
    return result


def read_state(path):
    return path.read_text() if path.exists() else ''


def wait_state(path, prefix, seconds, terminal=True):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read_state(path)
        if value.startswith(prefix):
            return value
        if terminal and (value.startswith('flash_rc=') or any(
                word in value for word in ('_failed ', '_timeout ', '_blocked_', '_unverified '))):
            raise RuntimeError(f'{path.name}: {value.strip()}')
        time.sleep(0.1)
    raise RuntimeError(f'{path.name}: {prefix!r} not observed within {seconds}s; last={read_state(path)!r}')


def unit(name, seconds, command):
    qualify.run(['systemd-run', '--user', '--collect', '--quiet', '--unit=' + name,
                 '--property=RuntimeMaxSec=' + str(seconds), '--setenv=PATH=' + os.environ['PATH']]
                + [str(arg) for arg in command])


def reboot(ssh, directory, filename):
    result = subprocess.run(ssh + ['systemctl reboot'], capture_output=True, text=True, timeout=20)
    qualify.save(directory, filename, {'returncode': result.returncode, 'stderr': result.stderr})


def healthy_return(ssh, before, directory, name):
    deadline = time.monotonic() + qualify.HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            after = snapshot(ssh)
            qualify.verify_return(before, after)
            qualify.save(directory, name + '.json', after)
            return after
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            (directory / (name + '-last-error.txt')).write_text(str(error) + '\n')
            if isinstance(error, subprocess.CalledProcessError):
                (directory / (name + '-last-stdout.txt')).write_text(error.stdout or '')
        time.sleep(3)
    raise RuntimeError('Fresh healthy accepted M69 did not return within 360s')


def recovery_timing(directory, profile):
    events = []
    for state in ('candidate.state', 'supervisor-rollback.state'):
        evidence = json.loads((directory / (state + '.mtk.json')).read_text())
        events.append(json.loads((Path(evidence['attempt']) / 'usb-events.json').read_text()))
    initial_departure = events[0][-1]['monotonic']
    rescue_entry = next(event['monotonic'] for event in events[1]
                        if event['usb'] and event['usb'][0] == '0e8d')
    elapsed = round(rescue_entry - initial_departure, 3)
    result = dict(seconds_from_initial_boot_preloader_departure_to_rescue_preloader=elapsed)
    if profile == 'watchdog':
        # A return earlier than the programmed timeout disproves this expiry
        # qualification. Meeting the lower bound alone does not prove it.
        result.update(programmed_watchdog_seconds=31,
                      watchdog_elapsed_minimum_met=(elapsed >= 31), watchdog_expiry_proven=False)
    qualify.save(directory, 'recovery-timing.json', result)
    return result


def phase_evidence(before, after, profile):
    phase = PHASES.get(after)
    known_before = isinstance(before, str) and bool(re.fullmatch(r'0x[0-9a-f]{8}', before))
    fresh = profile != 'baseline' and known_before and before != after and phase is not None
    intended = {'reset': 'reset_test', 'watchdog': 'watchdog_expiry_test'}.get(profile)
    return dict(phase_before_candidate=before, phase_at_rescue=after,
                uboot_phase=phase, uboot_execution_proven=fresh,
                intended_test_branch_reached=(fresh and phase == intended))


def profile_qualified(profile, phase, elapsed, host_rescue_reboot_requested):
    if profile == 'baseline':
        return True  # Both complete healthy Linux returns were already checked.
    if host_rescue_reboot_requested or not phase['intended_test_branch_reached']:
        return False
    if profile == 'reset':
        # An ineffective SWRST can fall back to the already armed 31s WDT.
        return 0 < elapsed < 31
    if profile == 'watchdog':
        # Includes LK startup and the subsequent preloader enumeration. The
        # prior measured overhead is ~14s; a late/manual return is not a pass.
        return 31 <= elapsed <= 60
    return False


def stage(directory, profile, before):
    candidate_path, candidate_sha = PROFILES[profile]
    candidate = backend.checked_image(candidate_path.resolve(strict=True), candidate_sha)
    rescue = qualify.accepted_boot_bytes(ACCEPTED)
    for name in ('p22-proof-supervisor.sh', 'trex-gadget-net-watcher.sh',
                 'p22-flash-wrapper.sh', 'p22-mtkclient-backend.py'):
        shutil.copyfile(ROOT / 'research' / name, directory / name)
        (directory / name).chmod(0o700)
    (directory / 'boot.img').write_bytes(candidate)
    (directory / 'rescue.img').write_bytes(rescue)
    (directory / 'rescue.img').chmod(0o400)
    # The common wrapper keeps this unique XML path in argv for authenticated
    # process cleanup. mtkclient uses its fixed boot-only command, not XML.
    shutil.copyfile(LOCKS / 'download-only-strix-4.xml', directory / 'download-only-p22.xml')
    config = dict(version=1, mtk=backend.MTK, stage_image=str(directory / 'boot.img'),
                  candidate_state=str(directory / 'candidate.state'),
                  rollback_state=str(directory / 'supervisor-rollback.state'),
                  candidate_sha256=candidate_sha, rollback_sha256=qualify.ACCEPTED_BOOT,
                  gpt_sha256=before['gpt_sha256'], usb_port='3-2')
    backend.config_for_state(config, directory / 'candidate.state')
    backend.save(directory / 'backend.json', config)
    return config


def trial(directory, profile, before, ssh):
    stamp = str(int(time.time())) + '-' + str(os.getpid())
    owner_unit, supervisor_unit, candidate_unit, net_unit = [f'p22-qual-{role}-{stamp}'
                                                  for role in ('owner', 'supervisor', 'candidate', 'net')]
    qualify.save(directory, 'units.json', dict(owner=owner_unit, supervisor=supervisor_unit,
                                               candidate=candidate_unit, network=net_unit))
    sh = shutil.which('sh')
    unit(owner_unit, 1100, [sh, directory / 'p22-trex-transaction-holder.sh',
                           LOCKS / '.p22-transaction.lock', directory / 'transaction-owner', '1080'])
    wait_state(directory / 'transaction-owner', 'owner=trex-transaction-holder pid=', 15)
    # The holder now owns staging. A second harness cannot change the shared
    # writer lane after preflight. All staged images here are private copies.
    stage(directory, profile, before)
    current = snapshot(ssh)
    if current != before:
        raise RuntimeError('Baseline changed between preflight and transaction ownership')
    unit(net_unit, 1080, [sh, directory / 'trex-gadget-net-watcher.sh',
                         directory / 'host-net.log', directory / 'host-net.state'])
    wrapper = directory / 'p22-flash-wrapper.sh'
    xml = directory / 'download-only-p22.xml'
    config = directory / 'backend.json'
    candidate_state = directory / 'candidate.state'
    supervisor_state = directory / 'supervisor.state'
    unit(supervisor_unit, 1000, [sh, directory / 'p22-proof-supervisor.sh', directory,
         candidate_state, directory / 'rescue.img', qualify.ACCEPTED_BOOT, directory / 'boot.img',
         xml, LOCKS / '.p22-flash-writer.lock', '360', wrapper,
         directory / 'supervisor-rollback.state', directory / 'supervisor-rollback.log',
         supervisor_state, '720', '', '', '300', '300', config])
    wait_state(supervisor_state, 'supervisor_waiting_candidate ', 15)
    # systemd gives the launcher a process group. setsid can therefore fork;
    # --wait keeps the service's main process alive until its session exits.
    unit(candidate_unit, 260, [shutil.which('setsid'), '--wait', sh, wrapper, candidate_state,
         directory / 'candidate.log', xml, directory / 'candidate.pid', directory / 'candidate.pgid',
         LOCKS / '.p22-flash-writer.lock', directory / 'transaction-owner', directory / 'candidate.sid',
         directory / 'candidate.starttime', config])
    wait_state(candidate_state, 'tool_started ', 20)
    pid = (directory / 'candidate.pid').read_text().strip()
    if not pid.isdecimal() or int(pid) < 2 or any(
            (directory / ('candidate.' + suffix)).read_text().strip() != pid for suffix in ('pgid', 'sid')):
        raise RuntimeError('Candidate wrapper lacks its own authenticated process session')
    print(f'{profile}: mtkclient waiting; supervisor owns rollback; rebooting once', flush=True)
    reboot(ssh, directory, 'candidate-reboot-request.json')
    # Preserve supervisor ownership even if the candidate writer fails.
    try:
        wait_state(candidate_state, 'flash_rc=0 ', 250)
        print('Candidate write/readback and first post-DA boot window verified', flush=True)
    except RuntimeError as error:
        (directory / 'candidate-error.txt').write_text(str(error) + '\n')
        print('Candidate did not verify; waiting for the existing rescue supervisor', flush=True)
    if profile == 'baseline' and read_state(candidate_state).startswith('flash_rc=0 '):
        middle = healthy_return(ssh, before, directory, 'baseline-middle')
        wait_state(directory / 'supervisor-rollback.state', 'tool_started ', 30, terminal=False)
        print('Baseline is healthy; rebooting once into the waiting rescue writer', flush=True)
        reboot(ssh, directory, 'rescue-reboot-request.json')
        recovery_before = middle
    else:
        recovery_before = before
    wait_state(supervisor_state, SUCCESS, 680)
    print('Rescue write/readback and reboot verified; waiting for healthy M69', flush=True)
    after = healthy_return(ssh, recovery_before, directory, 'after')
    # Both roles must have actual write, readback and USB ordering evidence.
    phases = []
    for state in (candidate_state, directory / 'supervisor-rollback.state'):
        evidence = json.loads(state.with_name(state.name + '.mtk.json').read_text())
        if evidence.get('returncode') != 0 or evidence.get('first_boot_window_departed') is not True:
            raise RuntimeError('Recovered baseline, but a writer lacks complete evidence')
        phases.append(evidence.get('toprgu_phase_before_write'))
    timing = recovery_timing(directory, profile)
    phase = phase_evidence(*phases, profile)
    qualify.save(directory, 'phase-analysis.json', phase)
    qualified = profile_qualified(profile, phase,
        timing['seconds_from_initial_boot_preloader_departure_to_rescue_preloader'],
        (directory / 'rescue-reboot-request.json').exists())
    result = dict(result='passed', profile=profile, recovered_boot_id=after['boot_id'],
                  proof='candidate-and-rescue-writes-with-automatic-reboot',
                  profile_qualified=qualified, **phase)
    if profile == 'watchdog':
        timing['watchdog_expiry_proven'] = qualified
        qualify.save(directory, 'recovery-timing.json', timing)
    qualify.save(directory, 'result.json', result)
    qualify.run(['systemctl', '--user', 'stop', owner_unit, net_unit])
    print(f'PASS: {profile} recovery path; fresh healthy M69. Evidence: {directory}', flush=True)
    if profile != 'baseline':
        print(f'{profile} profile {"qualified" if qualified else "NOT qualified"}: '
              f'phase={phase["uboot_phase"]}, elapsed='
              f'{timing["seconds_from_initial_boot_preloader_departure_to_rescue_preloader"]}s', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='baseline')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    directory = args.out.resolve()
    ssh = ['ssh', '-F', '/dev/null', '-i', '/home/grw/.ssh/gemini-stage1-ed25519',
           '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
           '-o', 'ControlPath=none', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'HostKeyAlias=192.168.23.70', 'root@10.15.19.82']
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            lock = locks.enter_context((LOCKS / name).open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        qualify.check_host_idle()
        before = snapshot(ssh)
        candidate, sha = PROFILES[args.profile]
        backend.checked_image(candidate.resolve(strict=True), sha)
        qualify.accepted_boot_bytes(ACCEPTED)
        usb = backend.usb_snapshot('3-2')
        if usb is None or usb[:2] != ('0525', 'a4a2'):
            raise RuntimeError('Gemini is not enumerated on the qualified USB port')
        qualify.run(['sudo', '-n', 'true'])
        directory.mkdir(mode=0o700)
        # Stage the holder before it takes over the local preflight lock.
        shutil.copyfile(ROOT / 'research/p22-trex-transaction-holder.sh',
                        directory / 'p22-trex-transaction-holder.sh')
        qualify.save(directory, 'before.json', before)
        qualify.save(directory, 'plan.json', dict(profile=args.profile, candidate=str(candidate),
                     candidate_sha256=sha, rescue=str(ACCEPTED), execute=args.execute,
                     runner_sha256=backend.digest(Path(__file__).read_bytes())))
    if not args.execute:
        print(f'Preflight passed; no reboot or write. Evidence: {directory}')
        return
    try:
        trial(directory, args.profile, before, ssh)
    except Exception as error:
        qualify.save(directory, 'result.json', dict(result='failed', error=str(error), profile=args.profile,
                     note='Durable recovery services keep their bounded ownership; inspect units.json'))
        raise


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
