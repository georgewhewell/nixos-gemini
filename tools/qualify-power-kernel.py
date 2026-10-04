#!/usr/bin/env python3
"""Normal-operation evidence for the hibernation watchdog kernel candidate.

This helper never requests sleep, writes swap, or stops the watchdog. The
shared supervised p22 runner owns candidate admission and automatic recovery.
"""
import hashlib
from pathlib import Path
import re
import runpy
import shlex

WORKSPACE = Path(__file__).resolve().parents[2]
BUNDLE = WORKSPACE / 'handoff/power-kernel-linux'
# Filled from the completed, reproducible build before any device admission.
SYSTEM = '/nix/store/5fdibxs9yf8yd64gdjvg2a1yan3hapb0-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
KERNEL = Path('/nix/store/vh1pzynqvd9zb4axjapic1rvpsnvnlzk-gemini-mainline-power-kernel-7.1.3')
BOOT_SHA = 'd2bb1ef41563db0bffaa64f5293f979aeae167b93ab85ea5db67c9fe7d1d1fbc'
STORE_SHA = '2edc71a5165f84576d2ad8d913042d7b0e94f1b2ca911304a8c43f7d7f2096cf'
STORE_SIZE = 427044864
PATCH_SHA = '96746fd50b138dd24eaa15a305e89308a0a469cc6d4a0cfda1c0979ff5c31d54'


def store_profile(provisioner):
    return provisioner.StoreProfile(BUNDLE, SYSTEM, STORE_SHA, STORE_SIZE, False)


def notes_sha(kernel=KERNEL):
    # /sys/kernel/notes is the ELF .notes section, including the GNU build ID.
    # Matching it prevents an unchanged config from standing in for new code.
    provenance = runpy.run_path(str(WORKSPACE / 'repo/nix/generate-late-cpu-provenance.py'))
    elf = provenance['Elf64'](kernel / 'vmlinux')
    notes = elf.range_bytes('__start_notes', '__stop_notes')
    provenance['build_id_from_notes'](notes)
    return hashlib.sha256(notes).hexdigest()


def verify_state(raw, boot_id, expected_notes):
    rows = raw.splitlines()
    if any('=' not in row for row in rows):
        raise RuntimeError('Malformed power candidate state')
    state = dict(row.split('=', 1) for row in rows)
    expected = dict(boot_id=boot_id, system=SYSTEM, notes_sha256=expected_notes,
                    watchdog_identity='mtk-wdt', watchdog_state='active',
                    watchdog_timeout='31', watchdog_nowayout='1',
                    watchdog_owned='yes', owner_unit='active', owner_restart='no',
                    pm_test='[none] core processors platform devices freezer',
                    mem_sleep='[s2idle]', disk='[shutdown] reboot suspend test_resume',
                    hibernation='false', suspend_then_hibernate='false', swap_count='0')
    if set(state) != set(expected) | {'owner_pid', 'owner_starttime'}:
        raise RuntimeError('Power candidate evidence is incomplete or duplicated')
    if len(rows) != len(state) or any(state[k] != v for k, v in expected.items()):
        raise RuntimeError('Power candidate identity, watchdog or inactive sleep policy differs')
    if any(not state[k].isdecimal() or int(state[k]) < 2 for k in ('owner_pid', 'owner_starttime')):
        raise RuntimeError('Watchdog owner is not a live identified process')
    return state


def evidence(ssh, boot_id, directory, qualify, persistence):
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+', SYSTEM):
        raise ValueError('Power candidate is not pinned')
    command = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(readlink /run/current-system)" = {SYSTEM}
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'system='; readlink /run/current-system
printf 'notes_sha256='; sha256sum /sys/kernel/notes | cut -d' ' -f1
for name in identity state timeout nowayout; do
 printf 'watchdog_%s=' "$name"; cat /sys/class/watchdog/watchdog0/$name
done
owner=$(cat /run/unattended-recovery.watchdog-owner)
case "$owner" in ''|*[!0-9]*) exit 1;; esac
test "$owner" -gt 1
test "$(systemctl show gemini-watchdog-takeover.service -p MainPID --value)" = "$owner"
kill -0 "$owner"
owned=no
for fd in /proc/$owner/fd/*; do
 case "$(readlink "$fd" || true)" in /dev/watchdog|/dev/watchdog0) owned=yes;; esac
done
printf 'watchdog_owned=%s\\nowner_pid=%s\\n' "$owned" "$owner"
printf 'owner_starttime='; awk '{{ print $22 }}' /proc/$owner/stat
printf 'owner_unit='; systemctl is-active gemini-watchdog-takeover.service
printf 'owner_restart='; systemctl show gemini-watchdog-takeover.service -p Restart --value
for name in pm_test mem_sleep disk; do printf '%s=' "$name"; cat /sys/power/$name; done
printf 'hibernation='; sed -n 's/^AllowHibernation=//p' /etc/systemd/sleep.conf
printf 'suspend_then_hibernate='; sed -n 's/^AllowSuspendThenHibernate=//p' /etc/systemd/sleep.conf
printf 'swap_count='; awk 'END {{ print NR-1 }}' /proc/swaps
test ! -e /sys/firmware/efi
grep -Eq ' [tT] mtk_wdt_pm_notify$' /proc/kallsyms
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
'''
    raw = persistence.run(ssh, command, directory, 'power-candidate-state')
    state = verify_state(raw, boot_id, notes_sha())
    qualify.save(directory, 'power-candidate-evidence.json', dict(
        **state, kernel=str(KERNEL), patch_sha256=PATCH_SHA,
        running_patched_kernel_verified=True, normal_watchdog_owned=True,
        sleep_requested=False, hibernation_io_qualified=False,
        watchdog_expiry_qualified=False))
    return state
