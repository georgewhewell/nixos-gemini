#!/usr/bin/env python3
"""Make a qualified generation the default on the U-Boot/systemd-boot baseline.

The rescue writer restores only the p22 bootloader, so it cannot undo a bad
default generation. Require a passing supervised direct-boot trial of the
exact system first, then install it with the standard NixOS path, reboot once
and require self-acceptance. Both the qualified trial and accepted recovery
must use RAM-only paging. --execute is needed to change the device.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SSH = ['ssh', '-F', '/dev/null', '-i', '/home/grw/.ssh/gemini-stage1-ed25519', '-o', 'IdentitiesOnly=yes',
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ControlPath=none',
       '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlias=192.168.23.70', 'root@10.15.19.82']
NIX_SSHOPTS = ' '.join(SSH[1:-1])


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=600, **kwargs).stdout


def trial_system(trial):
    """System path of a qualified direct-boot trial (bundle profile, no EFI install)."""
    result = json.loads((trial / 'result.json').read_text())
    if result.get('profile_qualified') is not True or result.get('result') != 'passed':
        raise RuntimeError(f'{trial} did not qualify')
    if json.loads((trial / 'final-idle-check.json').read_text()).get('no_writer') is not True:
        raise RuntimeError(f'{trial} lacks a clean final audit')
    # Measured on the candidate itself during the qualified boot.
    evidence = json.loads((trial / 'power-swap-evidence.json').read_text())
    swap = evidence.get('swap', {})
    paging = evidence.get('paging', {})
    if (result.get('paging_policy') != 'zram' or
            result.get('ram_only_paging_qualified') is not True or
            evidence.get('paging_policy') != 'zram' or
            evidence.get('ram_only_paging_qualified') is not True or
            evidence.get('default_policy_paging_qualified') is not True or
            evidence.get('runtime_policy_writes') is not False or
            swap.get('device') != '/dev/zram0' or
            swap.get('flash_swap_active') is not False or
            swap.get('writeback') is not False or
            type(paging.get('flash_swap_written_sectors')) is not int or
            paging['flash_swap_written_sectors'] != 0):
        raise RuntimeError(f'{trial} lacks qualified RAM-only paging evidence')
    system = evidence['system']
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-nixos-system-[A-Za-z0-9.+_-]+', system):
        raise RuntimeError(f'{trial} lacks a candidate system identity')
    if (trial / 'efi-install-result.json').exists():
        raise RuntimeError(f'{trial} installed EFI files; qualify a direct-boot trial')
    return system


def healthy(system):
    out = run(SSH + ['readlink /run/current-system; cat /run/unattended-recovery.accepted; '
                     'systemctl is-system-running; cat /proc/sys/kernel/random/boot_id']).split()
    return out[0] == system and out[1] == 'unattended_recovery=healthy' and out[2] == 'running', out[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True, help='Qualified direct-boot trial directory')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    baseline_file = ROOT / 'research/accepted-baseline.json'
    baseline = json.loads(baseline_file.read_text())
    if baseline.get('boot') != 'uboot-efi':
        raise RuntimeError('Generation updates need the U-Boot/systemd-boot baseline')
    if baseline.get('paging_policy') != 'zram':
        raise RuntimeError('Generation updates require an accepted RAM-only recovery baseline; '
                           'the old flash-backed fallback must be migrated first')
    system = trial_system(args.trial.resolve())
    ok, boot = healthy(baseline['system'])
    if not ok:
        raise RuntimeError('Device is not on the healthy accepted baseline')
    print(f'Qualified by {args.trial}: {system}')
    if not args.execute:
        print('Preflight passed; no device change'); return
    subprocess.run(['nix', 'copy', '--to', 'ssh://root@10.15.19.82?remote-store=local%3Froot%3D%2Fpersist%2Fnixos',
                    system], check=True, env=dict(__import__('os').environ, NIX_SSHOPTS=NIX_SSHOPTS))
    print(run(SSH + [f'''set -eu
grep -qx unattended_recovery=healthy /run/unattended-recovery.accepted
nix-store --check-validity {system}
# The boot volume holds every retained generation's kernel and initrd: keep
# only the running one, which stays as the fallback entry beside the new one.
nix-env --profile /nix/var/nix/profiles/system --delete-generations +1
nix-env --profile /nix/var/nix/profiles/system --set {system}
{system}/bin/switch-to-configuration boot
gemini-boot-install --system {system} --check --json''']).splitlines()[-1])
    subprocess.run(SSH + ['systemctl reboot'], timeout=20)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        time.sleep(15)
        try:
            ok, new_boot = healthy(system)
        except (subprocess.SubprocessError, IndexError):
            continue
        if ok and new_boot != boot:
            baseline.update(system=system, name='update-' + args.trial.name)
            baseline_file.write_text(json.dumps(baseline, indent=2) + '\n')
            print(f'PASS: {system} is the accepted default; commit {baseline_file.relative_to(ROOT)}')
            return
    raise RuntimeError('New default generation did not self-accept within 600s; the device needs attention')


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: sys.exit(str(error))
