#!/usr/bin/env python3
"""Exercise mtkclient rollback ownership for pinned Linux and U-Boot trials.

Default is read-only preflight. Baseline executes two accepted-M69 writes and
normal Linux reboots. Reset/watchdog profiles select pinned M69 U-Boot carriers
and leave the existing durable p22 supervisor responsible for restoring M69.
Handoff/EFI smoke profiles inspect Linux before rebooting into that rescue.
The persistent-nix profile tests an ordinary unprivileged daemon build and
its data retention through rescue, using a separately pinned kernel/system.
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
    'efi-nix-dt-cross-manager': (WORKSPACE / 'handoff/efi-cross-entry-dt-manager/boot-padded-p22.img',
                                 'd399b431e2683039848550bd64e2c43be343522b0d14cf1551a06511d02615d4'),
    'efi-nix-dt-provision': (WORKSPACE / 'handoff/nix-efi-entry-dt-candidates-1/boot-padded-p22.img',
                             'ac6f70b9655f0a8c181901966ab0c03a37d485df6ccbf59cdb62905aae7b1adc'),
    'efi-nix-dt-manager': (WORKSPACE / 'handoff/nix-efi-entry-dt-manager-pad/boot-padded-p22.img',
                           'ef5c215b95da370e993710785d23c84c57dda47e40dab600b2ee302ef1d4ec19'),
    'efi-nix-provision': (WORKSPACE / 'handoff/nix-efi-provision-reproducible/boot-padded-p22.img',
                          '238072a0243de05435dcee15f60aa8304c36c07fe8431c49dfd5f6e03b9aa121'),
    'efi-nix-manager': (WORKSPACE / 'handoff/nix-efi-candidates-2/boot-padded-p22.img',
                        '004def7151492f54d3e34bc84ddef33de4bfd378def703a5e7858a09e8f37093'),
    'persistent-nix': (WORKSPACE / 'handoff/persistent-nix-candidate/boot-padded-p22.img',
                        '0cd222881c2dcc56d8da25f54903f70cf4d93475bc591175251403ba971be50e'),
    'efi-manager': (WORKSPACE / 'handoff/uboot-efi-manager-partuuid/boot-padded-p22.img',
                    'fd6e29e1727209d1445c85380417ed06470bfd61da429ff7e1cd0f7a1fe43a20'),
    'efi-provision': (WORKSPACE / 'handoff/uboot-efi-provision/boot-padded-p22.img',
                      'eabf8e42eeca5d08a7f7564dee82b44b44bb485235b74e1d6a81b08ba6dc97eb'),
    'efi-storage': (WORKSPACE / 'handoff/uboot-efi-storage-eof/boot-padded-p22.img',
                    '73095ee31d2128c6cadf920b8cc9e451f1900010dcda8c252376126d07779a0f'),
    'efi-mmc': (WORKSPACE / 'handoff/uboot-efi-mmc/boot-padded-p22.img',
                '88c6aa8a2e466dd153c0fc19b0f2d17c5ddcdda5d1cd415bc3a166e0d681d5f4'),
    'efi-keyboard': (WORKSPACE / 'handoff/uboot-efi-keyboard/boot-padded-p22.img',
                     '2b66cccaba6e4fe52e2f172af09896c91ec7ad0fa4b34d79a195482e17e2e9d5'),
    'efi-console': (WORKSPACE / 'handoff/uboot-efi-console/boot-padded-p22.img',
                    '0b104d094c012a8c5c00e4284368c153a831b94a7e39fc4e55f50ce0fe762f3a'),
    'efi-linux': (WORKSPACE / 'handoff/uboot-no-debug/boot-padded-p22.img',
                  '1d463996c9506cff718f83ff3e702e68240dbcfb90aea1f6425d747bdc2f2c7e'),
    'baseline': (ACCEPTED, '913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3'),
    'reset': (WORKSPACE / 'handoff/uboot-m69-efi-order-2/boot-padded-p22.img',
              'e9e0f6f2f44c28d98424420444c9f3466fa593adfe7f5d38c66652c349e8e950'),
    'watchdog': (WORKSPACE / 'handoff/uboot-m69-efi-order-3/boot-padded-p22.img',
                 '5f02a4db11c14fdd604626b48fdd71886db9d90ff699c936d397800a4278c66d'),
    'handoff': (WORKSPACE / 'handoff/uboot-m69-efi-order/boot-padded-p22.img',
                '365ac36a96e095a93e0b7071241c4569f5e052164bd8de8bf793dbbd4bd9ff8c'),
    'efi-smoke': (WORKSPACE / 'handoff/uboot-m69-efi-order-1/boot-padded-p22.img',
                  '3ab7a708611fa221e2f875b1d5a7a7f7041c2874e2ef6f4cca8e8714ac1d7e74'),
}
ENTRY_DT_PROFILES = ('efi-nix-dt-provision', 'efi-nix-dt-manager', 'efi-nix-dt-cross-manager')
NIX_EFI_PROFILES = ('efi-nix-provision', 'efi-nix-manager') + ENTRY_DT_PROFILES
NIX_PROFILES = ('persistent-nix',) + NIX_EFI_PROFILES
EFI_LINUX_PROFILES = ('efi-linux', 'efi-console', 'efi-keyboard', 'efi-mmc', 'efi-storage', 'efi-provision', 'efi-manager') + NIX_EFI_PROFILES
UBOOT_LINUX_PROFILES = ('handoff', 'efi-smoke') + EFI_LINUX_PROFILES
LINUX_PROFILES = UBOOT_LINUX_PROFILES + ('persistent-nix',)
SUCCESS = 'supervisor_rollback_succeeded_rescue_verified '
MMC_GPT_SHA = '6addff62cc67f5b5fac9bd87194b6643f4029262251c51c1e43e1b5b64cb887d'
MMC_FILE_SHA = 'fb9d072b57e41d245ace3e2256ac57ab4dfd42cf4c010993b4d6c3e67b44e16d'
P30_SHA = '122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159'
P31_SHA = '1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513'
PHASES = {'0x474d4000': 'efi_manager_start', '0x474d10e0': 'entry', '0x474d10e1': 'lowlevel_init',
          '0x474d4001': 'efi_prepare_begin', '0x474d4002': 'efi_mmc_qualification',
          '0x474d4003': 'efi_object_initialization', '0x474d4010': 'efi_console_application',
          '0x474d4011': 'efi_storage_application', '0x474d4012': 'efi_exit_event_registration',
          '0x474d4020': 'efi_manager_storage_proof', '0x474d4021': 'efi_manager_file_size',
          '0x474d4022': 'efi_manager_allocation', '0x474d4023': 'efi_manager_file_read',
          '0x474d4024': 'efi_manager_file_hash', '0x474d4025': 'efi_manager_device_path',
          '0x474d4026': 'efi_manager_fdt_metadata', '0x474d4027': 'efi_manager_return_cleanup',
          '0x474d4030': 'efi_bootdev_clear', '0x474d4031': 'efi_bootdev_cleared',
          '0x474d4033': 'efi_dp_from_name', '0x474d4034': 'efi_dp_split',
          '0x474d4035': 'efi_dp_split_done', '0x474d4036': 'efi_bootdev_paths_done',
          '0x474d4037': 'efi_dp_partition_lookup', '0x474d4038': 'efi_dp_from_partition',
          '0x474d4039': 'efi_dp_from_file',
          '0x474d4040': 'efi_dp_file_size', '0x474d4041': 'efi_dp_file_allocate',
          '0x474d4042': 'efi_dp_file_allocated', '0x474d4043': 'efi_dp_file_encode',
          '0x474d4044': 'efi_dp_file_encoded', '0x474d4045': 'efi_dp_file_complete',
          '0x474d10e2': 'board_early_init_f', '0x474d10e3': 'board_init',
          '0x474d10e4': 'board_late_init', '0x474d10e5': 'watchdog_ready',
          '0x474d10e6': 'fit_valid', '0x474d10e7': 'bootm_call',
          '0x474d10e8': 'os_prepared', '0x474d10e9': 'os_jump',
          '0x474d10ea': 'efi_enter', '0x474d10eb': 'efi_return',
          '0x474d10ee': 'efi_exit_boot_services', '0x474d10ef': 'efi_linux_ready',
          '0x474d10f6': 'efi_map_failure', '0x474d10ec': 'reset_test', '0x474d10ed': 'watchdog_expiry_test',
          '0x474d10f1': 'watchdog_setup_failure', '0x474d10f2': 'fit_failure',
          '0x474d10f3': 'efi_fdt_failure', '0x474d10f4': 'lk_fdt_failure',
          '0x474d10f5': 'handoff_failure', '0x474d10f7': 'console_framebuffer_failure',
          '0x474d10f8': 'keyboard_resource_failure',
          '0x474d1e01': 'efi_command_failure'}
HANDOFF_TREE = r'''set -eu
dt=/sys/firmware/devicetree/base
dump_property() {
    test -f "$1"
    printf '%s=' "${1#"$dt"/}"
    od -An -v -tx1 "$1" | tr -d ' \n'
    printf '\n'
}
for property in "$dt"/memory*/reg "$dt/chosen/ccci,modem_info_v2"; do
    dump_property "$property"
done
find "$dt/reserved-memory" -type f | LC_ALL=C sort | while IFS= read -r property; do
    dump_property "$property"
done
for marker in gemini,uboot-handoff gemini,uefi-hello-result gemini,uefi-console-result gemini,uefi-keyboard-result gemini,uefi-keyboard-scans gemini,uefi-keyboard-error gemini,uefi-mmc-result gemini,uefi-mmc-stage gemini,uefi-mmc-error gemini,uefi-mmc-elapsed-ms gemini,uefi-mmc-clock gemini,uefi-mmc-width gemini,uefi-mmc-gpt-sha256 gemini,uefi-mmc-boot-sha256 gemini,uefi-mmc-boot2-sha256 gemini,uefi-mmc-boot3-sha256 gemini,uefi-mmc-file-sha256 gemini,uefi-storage-result gemini,uefi-storage-status gemini,uefi-manager-result gemini,uefi-manager-stage gemini,uefi-manager-status gemini,uefi-manager-sha256; do
    if test -e "$dt/chosen/$marker"; then dump_property "$dt/chosen/$marker"; fi
done
awk '/^MemTotal:/ {print "memtotal_kib=" $2}' /proc/meminfo
'''
HANDOFF_MARKER = 'chosen/gemini,uboot-handoff'
EFI_MARKER = 'chosen/gemini,uefi-hello-result'
CONSOLE_MARKER = 'chosen/gemini,uefi-console-result'
KEYBOARD_MARKER = 'chosen/gemini,uefi-keyboard-result'
KEYBOARD_SCANS = 'chosen/gemini,uefi-keyboard-scans'
KEYBOARD_ERROR = 'chosen/gemini,uefi-keyboard-error'
MMC_MARKERS = tuple("chosen/gemini,uefi-mmc-" + name for name in
                    ('result', 'stage', 'error', 'elapsed-ms', 'clock', 'width', 'gpt-sha256', 'boot-sha256', 'boot2-sha256', 'boot3-sha256', 'file-sha256'))
STORAGE_MARKER = "chosen/gemini,uefi-storage-result"
STORAGE_STATUS = "chosen/gemini,uefi-storage-status"
MARKERS = (HANDOFF_MARKER, EFI_MARKER, CONSOLE_MARKER, KEYBOARD_MARKER, KEYBOARD_SCANS, KEYBOARD_ERROR, STORAGE_MARKER, STORAGE_STATUS) + MMC_MARKERS + tuple("chosen/gemini,uefi-manager-" + name for name in ("result", "stage", "status", "sha256"))


def handoff_tree(ssh):
    result = dict(line.split('=', 1) for line in qualify.run(ssh + [HANDOFF_TREE]).splitlines())
    memory = [value for key, value in result.items() if key.startswith('memory') and key.endswith('/reg')]
    if memory != ['00000000400000000000000100000000']:
        raise RuntimeError('Linux device tree does not retain the full 4 GiB LK memory bank')
    if len(bytes.fromhex(result.get('chosen/ccci,modem_info_v2', ''))) != 48:
        raise RuntimeError('Linux device tree lacks the complete LK modem table')
    for index in (5, 6, 7):
        if not result.get(f'reserved-memory/mblock-{index}-ccci/reg'):
            raise RuntimeError('Linux device tree lacks an LK modem reservation')
    if int(result.get('memtotal_kib', '0')) < 3 * 1024 * 1024:
        raise RuntimeError('Linux reports less than 3 GiB usable memory')
    return result


def profile_kind(profile):
    return {'efi-nix-provision': 'efi-provision', 'efi-nix-manager': 'efi-manager',
            'efi-nix-dt-provision': 'efi-provision', 'efi-nix-dt-manager': 'efi-manager',
            'efi-nix-dt-cross-manager': 'efi-manager'}.get(profile, profile)


def verify_handoff_tree(before, after, profile):
    kind = profile_kind(profile)
    if any(key in before for key in MARKERS):
        raise RuntimeError('Direct-Linux baseline unexpectedly contains a U-Boot marker')
    for key, value in before.items():
        if key == 'reserved-memory/reserve-memory-dram_r0_dummy_read/alloc-ranges':
            # LK begins this allocation window after the Android ramdisk.
            # The FIT carrier is larger than the direct-Linux initramfs.
            raw = bytes.fromhex(after.get(key, ''))
            start, size = int.from_bytes(raw[:8], 'big'), int.from_bytes(raw[8:], 'big')
            if len(raw) != 16 or start < 0x40000000 or size < 4096 or start + size > 0x7dfb0000:
                raise RuntimeError('LK dummy-read allocation range is outside low RAM')
            continue
        if key != 'memtotal_kib' and after.get(key) != value:
            raise RuntimeError(f'Linux handoff changed LK property {key}')
    if profile == 'persistent-nix':
        if any(key in after for key in MARKERS):
            raise RuntimeError('Direct persistent-Nix profile contains a U-Boot marker')
        return
    marker = b'efi\0' if profile in EFI_LINUX_PROFILES else b'fit\0'
    if after.get(HANDOFF_MARKER) != marker.hex():
        raise RuntimeError('Linux lacks the U-Boot FIT handoff marker')
    expected_efi = b'passed\0'.hex() if profile == 'efi-smoke' else None
    if after.get(EFI_MARKER) != expected_efi:
        raise RuntimeError('Linux EFI marker does not match the requested profile')
    expected_console = b'passed\0'.hex() if kind in ('efi-console', 'efi-keyboard', 'efi-mmc', 'efi-storage', 'efi-provision', 'efi-manager') else None
    if after.get(CONSOLE_MARKER) != expected_console:
        raise RuntimeError('EFI graphics/text application did not pass for the requested profile')
    if kind in ('efi-keyboard', 'efi-mmc', 'efi-storage', 'efi-provision', 'efi-manager'):
        scans = bytes.fromhex(after.get(KEYBOARD_SCANS, ''))
        if (after.get(KEYBOARD_MARKER) != b'scanned\0'.hex() or
                after.get(KEYBOARD_ERROR) != '00000000' or
                len(scans) != 4 or int.from_bytes(scans, 'big') < 20):
            raise RuntimeError('Native EFI keyboard polling failed: ' + repr(
                {key: after.get(key) for key in (KEYBOARD_MARKER, KEYBOARD_SCANS, KEYBOARD_ERROR)}))
    elif any(key in after for key in (KEYBOARD_MARKER, KEYBOARD_SCANS, KEYBOARD_ERROR)):
        raise RuntimeError('Unexpected EFI keyboard evidence in another profile')

    if kind in ('efi-mmc', 'efi-storage', 'efi-provision', 'efi-manager'):
        verify_mmc_tree(after, profile)
    elif any(key in after for key in MMC_MARKERS):
        raise RuntimeError('Unexpected native MMC evidence in another profile')
    if kind in ('efi-storage', 'efi-provision', 'efi-manager'):
        if after.get(STORAGE_MARKER) != b'passed\0'.hex() or after.get(STORAGE_STATUS) != '0000000000000000':
            raise RuntimeError('EFI storage protocol application failed: ' + repr(
                {key: after.get(key) for key in (STORAGE_MARKER, STORAGE_STATUS)}))
    elif any(key in after for key in (STORAGE_MARKER, STORAGE_STATUS)):
        raise RuntimeError('Unexpected EFI storage protocol evidence in another profile')
    if kind == 'efi-manager':
        efi_manager.verify_tree(after)
    elif any(key in after for key in efi_manager.MARKERS):
        raise RuntimeError('Unexpected distro manager evidence in another profile')


def verify_mmc_tree(tree, profile):
    values = {name.removeprefix('chosen/gemini,uefi-mmc-'): tree.get(name) for name in MMC_MARKERS}
    expected = {'result': b'passed\0'.hex(), 'stage': b'filesystem\0'.hex(),
                'error': '00000000', 'width': '00000008',
                'gpt-sha256': MMC_GPT_SHA, 'boot-sha256': PROFILES[profile][1],
                'boot2-sha256': P30_SHA, 'boot3-sha256': P31_SHA, 'file-sha256': MMC_FILE_SHA}
    if any(values[key] != value for key, value in expected.items()):
        raise RuntimeError('Native MMC qualification failed or returned different bytes: ' + repr(values))
    for key, maximum in (('clock', 25000000), ('elapsed-ms', 60000)):
        value = values[key]
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{8}', value) or not 0 < int(value, 16) <= maximum:
            raise RuntimeError('Native MMC qualification has an invalid ' + key + ': ' + repr(value))



def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


qualify = module('qualify_mtk', ROOT / 'tools/qualify-mtkclient.py')
backend = module('mtk_backend', ROOT / 'research/p22-mtkclient-backend.py')
efi_linux = module('efi_linux', ROOT / 'tools/qualify-efi-linux.py')
efi_files = module('efi_files', ROOT / 'tools/qualify-efi-files.py')
efi_manager = module('efi_manager', ROOT / 'tools/qualify-efi-manager.py')
persistence = module('persistence', ROOT / 'tools/qualify-gemini-persistence.py')
persistent_nix = module('persistent_nix', ROOT / 'tools/qualify-persistent-nix.py')
entry_dt = module('entry_dt', ROOT / 'tools/qualify-efi-entry-dt.py')


def files_profile_for(profile):
    if profile in ENTRY_DT_PROFILES:
        return entry_dt.files_profile(efi_files)
    return persistent_nix.files_profile(efi_files) if profile in NIX_EFI_PROFILES else None


def previous_files_evidence(ssh,boot_id,directory,profile,name):
    persistent_nix.activation_evidence(ssh,boot_id,directory,qualify,persistence,name=name)
    if profile in ENTRY_DT_PROFILES:
        entry_dt.previous_files(ssh,boot_id,directory,qualify,persistence,
                                persistent_nix,efi_files,name+'-nix')


def candidate_system(before, profile):
    if profile in NIX_PROFILES:
        return persistent_nix.SYSTEM
    return efi_linux.SYSTEM if profile in EFI_LINUX_PROFILES else before['system']


def rescue_identity(before, candidate):
    return dict(before, boot_id=candidate['boot_id'])


def snapshot(ssh):
    result = qualify.snapshot(ssh)
    hashes = qualify.run(ssh + ['sha256sum /dev/mmcblk0p30 /dev/mmcblk0p31']).splitlines()
    if [row.split()[0] for row in hashes] != [P30_SHA, P31_SHA]:
        raise RuntimeError('Alternate boot partitions differ from the accepted baseline')
    result.update(p30_sha256=P30_SHA, p31_sha256=P31_SHA)
    return result


def candidate_snapshot(ssh, before, profile):
    if profile not in LINUX_PROFILES:
        raise ValueError('Candidate Linux checks require a pinned Linux handoff profile')
    result = dict(line.split('=', 1) for line in qualify.run(ssh + [qualify.SNAPSHOT]).splitlines())
    expected = dict(before, boot_sha256=PROFILES[profile][1],
                    system=candidate_system(before, profile))
    qualify.verify_return(expected, result)
    if not re.fullmatch(r'[0-9a-f-]{36}', result.get('boot_id', '')):
        raise RuntimeError('Candidate lacks a boot identity')
    hashes = qualify.run(ssh + ['sha256sum /dev/mmcblk0p30 /dev/mmcblk0p31']).splitlines()
    if [row.split()[0] for row in hashes] != [P30_SHA, P31_SHA]:
        raise RuntimeError('Candidate changed an alternate boot partition')
    result.update(p30_sha256=P30_SHA, p31_sha256=P31_SHA)
    return result


def candidate_return(ssh, before, directory, profile):
    deadline = time.monotonic() + qualify.HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        if read_state(directory / 'supervisor.state').startswith(SUCCESS):
            raise RuntimeError('Automatic rescue ran before healthy candidate Linux was observed')
        try:
            after = candidate_snapshot(ssh, before, profile)
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            (directory / 'candidate-linux-last-error.txt').write_text(str(error) + '\n')
            time.sleep(3)
            continue
        qualify.save(directory, 'candidate-linux.json', after)
        tree = handoff_tree(ssh)
        qualify.save(directory, 'candidate-tree.json', tree)
        verify_handoff_tree(json.loads((directory / 'before-tree.json').read_text()), tree, profile)
        if profile in EFI_LINUX_PROFILES:
            efi_linux.evidence(ssh, directory, qualify, tree)
        files = files_profile_for(profile)
        if profile_kind(profile) == 'efi-provision':
            efi_files.evidence(ssh, after['boot_id'], directory, qualify, profile=files)
        if profile_kind(profile) == 'efi-manager':
            kwargs = dict(entry=persistent_nix.EFI_ENTRY, kernel=persistent_nix.KERNEL) if profile in NIX_EFI_PROFILES else {}
            if profile in ENTRY_DT_PROFILES:
                kwargs['entry']=entry_dt.ENTRY
            efi_manager.evidence(ssh, after['boot_id'], directory, qualify, tree, **kwargs)
            efi_files.evidence(ssh, after['boot_id'], directory, qualify, require_verified=False, profile=files)
            if profile in ENTRY_DT_PROFILES:
                entry_dt.evidence(directory,after['boot_id'],efi_files,qualify)
            if profile == 'efi-nix-dt-cross-manager':
                entry_dt.cross_evidence(directory,after['boot_id'],efi_files,qualify,*PROFILES[profile])
        if profile in NIX_PROFILES:
            persistent_nix.evidence(ssh, after['boot_id'], directory, qualify, persistence,
                                    require_efi=profile in NIX_EFI_PROFILES)
            if profile in NIX_EFI_PROFILES:
                previous_files_evidence(ssh,after['boot_id'],directory,profile,'previous-efi-files')
            if candidate_snapshot(ssh, before, profile) != after:
                raise RuntimeError('Candidate health or protected identity changed after Nix build')
        return after
    raise RuntimeError('Healthy candidate Linux did not return within 360s')


def candidate_needs_rescue_reboot(ssh, before, profile):
    # Even when Linux fails its service checks, restore the accepted image if
    # this is still the exact candidate boot. An already recovered M69 does
    # not need another reboot. Never reboot an unidentified Linux instance.
    command = "cat /proc/sys/kernel/random/boot_id; readlink /run/current-system; " \
              "sha256sum /dev/mmcblk0p22; head -c 32768 /dev/mmcblk0 | sha256sum"
    try:
        rows = qualify.run(ssh + [command]).splitlines()
    except subprocess.SubprocessError:
        return False
    return (len(rows) == 4 and rows[0] != before['boot_id'] and
            bool(re.fullmatch(r'[0-9a-f-]{36}', rows[0])) and rows[1] == candidate_system(before, profile) and
            rows[2].split()[:1] == [PROFILES[profile][1]] and
            rows[3].split()[:1] == [before['gpt_sha256']])


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
    fault = {}
    if profile_kind(profile) == 'efi-manager' and isinstance(after,str) and re.fullmatch(r'0x[89a-f][0-9a-f]{7}',after):
        record=int(after,16)
        pc=0x40200000+((record&0x7ffff)<<2)
        ec=(record>>25)&0x3f
        iss=(record>>19)&0x3f
        fault=dict(exception_pc=hex(pc),exception_class=hex(ec),exception_iss_low6=hex(iss))
        phase=f'uboot_exception_pc_{pc:#x}_ec_{ec:#x}_iss_low6_{iss:#x}'
    if isinstance(after, str) and re.fullmatch('0x474d30[0-9a-f]{2}', after):
        phase = 'mmc_resource_failure_errno_' + str(int(after[-2:], 16))
    known_before = isinstance(before, str) and bool(re.fullmatch(r'0x[0-9a-f]{8}', before))
    fresh = profile not in ('baseline', 'persistent-nix') and known_before and before != after and phase is not None
    intended = {'reset': 'reset_test', 'watchdog': 'watchdog_expiry_test'}.get(profile)
    return dict(phase_before_candidate=before, phase_at_rescue=after,
                uboot_phase=phase, uboot_execution_proven=fresh,
                intended_test_branch_reached=(fresh and phase == intended), **fault)


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


def trial(directory, profile, before, ssh, verify_persistence=False):
    if verify_persistence and profile != 'baseline':
        raise ValueError('Persistence qualification requires the accepted baseline profile')
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
    candidate_qualified = False
    persistent_before = None
    persistent_after = None
    recovery_before = before
    if profile in LINUX_PROFILES and read_state(candidate_state).startswith('flash_rc=0 '):
        try:
            if profile_kind(profile) == 'efi-provision':
                efi_files.provision(ssh, before, PROFILES[profile][1], directory, qualify,
                    lambda: read_state(directory / 'supervisor.state').startswith(SUCCESS),
                    profile=files_profile_for(profile))
            if profile in EFI_LINUX_PROFILES and profile not in NIX_PROFILES:
                efi_linux.provision(ssh, before, PROFILES[profile][1], directory, qualify,
                    lambda: read_state(directory / 'supervisor.state').startswith(SUCCESS))
            if profile in NIX_PROFILES:
                efi_linux.provision(ssh, before, PROFILES[profile][1], directory, qualify,
                    lambda: read_state(directory / 'supervisor.state').startswith(SUCCESS),
                    profile=persistent_nix.store_profile(efi_linux,require_efi=profile in NIX_EFI_PROFILES))
            middle = candidate_return(ssh, before, directory, profile)
            # Require rescue to be a different boot from the observed candidate
            # as well as restoring the accepted direct-Linux image.
            recovery_before = rescue_identity(before, middle)
            candidate_qualified = True
            print('Candidate Linux health, requested handoff, RAM and LK reservations verified', flush=True)
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            (directory / 'candidate-linux-error.txt').write_text(str(error) + '\n')
            print(f'Candidate Linux NOT qualified: {error}', flush=True)
        if candidate_needs_rescue_reboot(ssh, before, profile):
            wait_state(directory / 'supervisor-rollback.state', 'tool_started ', 30, terminal=False)
            print('Rebooting the identified candidate into the waiting rescue writer', flush=True)
            reboot(ssh, directory, 'rescue-reboot-request.json')
    elif profile == 'baseline' and read_state(candidate_state).startswith('flash_rc=0 '):
        middle = healthy_return(ssh, before, directory, 'baseline-middle')
        if verify_persistence:
            try:
                persistent_before = persistence.evidence(ssh, middle['boot_id'], directory, qualify)
                print('Persistent mounts, home test file and offline fixed-output Nix build verified', flush=True)
            except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
                (directory / 'persistence-before-error.txt').write_text(str(error) + '\n')
                print(f'Persistence NOT qualified; continuing supervised recovery: {error}', flush=True)
        wait_state(directory / 'supervisor-rollback.state', 'tool_started ', 30, terminal=False)
        print('Baseline is healthy; rebooting once into the waiting rescue writer', flush=True)
        reboot(ssh, directory, 'rescue-reboot-request.json')
        recovery_before = middle
    else:
        recovery_before = before
    wait_state(supervisor_state, SUCCESS, 680)
    print('Rescue write/readback and reboot verified; waiting for healthy M69', flush=True)
    after = healthy_return(ssh, recovery_before, directory, 'after')
    nix_retained = False
    if profile in NIX_PROFILES:
        try:
            if candidate_qualified:
                persistent_nix.after_recovery(ssh, after['boot_id'], directory, qualify, persistence)
                if profile in NIX_EFI_PROFILES:
                    efi_files.evidence(ssh, after['boot_id'], directory, qualify, require_verified=False,
                        name='recovered-boot-files.json', profile=files_profile_for(profile))
                    previous_files_evidence(ssh,after['boot_id'],directory,profile,'recovered-previous-efi-files')
                nix_retained = True
            else:
                persistent_nix.old_persistence(ssh, after['boot_id'], directory, qualify, persistence,
                    qualify.ACCEPTED_SYSTEM, 'recovered-old-persistence')
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            (directory / 'nix-recovered-error.txt').write_text(str(error) + '\n')
            print(f'Nix persistence after recovery NOT qualified: {error}', flush=True)
    if persistent_before is not None:
        try:
            persistent_after = persistence.evidence(ssh, after['boot_id'], directory, qualify,
                                                     previous=persistent_before)
        except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
            (directory / 'persistence-after-error.txt').write_text(str(error) + '\n')
            print(f'Persistence did not survive recovery: {error}', flush=True)
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
    if profile in LINUX_PROFILES:
        qualified = candidate_qualified
    if profile in NIX_PROFILES:
        qualified = candidate_qualified and nix_retained
    result = dict(result='passed', profile=profile, recovered_boot_id=after['boot_id'],
                  proof='candidate-and-rescue-writes-with-automatic-reboot',
                  profile_qualified=qualified, **phase)
    if profile in LINUX_PROFILES:
        result.update(linux_handoff_proven=candidate_qualified)
    if profile in UBOOT_LINUX_PROFILES:
        result.update(uboot_execution_proven=candidate_qualified or phase['uboot_execution_proven'])
    if profile in NIX_PROFILES:
        result.update(ordinary_daemon_build_qualified=candidate_qualified,
                      nix_persistence_qualified=nix_retained)
    if profile in ENTRY_DT_PROFILES:
        result.update(entry_dt_handoff_qualified=profile_kind(profile)=='efi-manager' and qualified,
                      cross_kernel_generation_selection_qualified=profile=='efi-nix-dt-cross-manager' and qualified)
    if verify_persistence:
        result['persistence_qualified'] = persistent_after is not None
    if profile == 'watchdog':
        timing['watchdog_expiry_proven'] = qualified
        qualify.save(directory, 'recovery-timing.json', timing)
    qualify.save(directory, 'result.json', result)
    qualify.run(['systemctl', '--user', 'stop', owner_unit, net_unit])
    print(f'PASS: {profile} recovery path; fresh healthy M69. Evidence: {directory}', flush=True)
    if verify_persistence:
        print('Persistence across reboot: ' + ('PASS' if persistent_after else 'NOT qualified'), flush=True)
    if profile != 'baseline':
        print(f'{profile} profile {"qualified" if qualified else "NOT qualified"}: '
              f'phase={phase["uboot_phase"]}, elapsed='
              f'{timing["seconds_from_initial_boot_preloader_departure_to_rescue_preloader"]}s', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='baseline')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--verify-persistence', action='store_true',
                        help='Retain a local fixed-output Nix build and home file across baseline boots')
    args = parser.parse_args()
    if args.verify_persistence and args.profile != 'baseline':
        parser.error('--verify-persistence requires --profile baseline')
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
        tree = handoff_tree(ssh) if args.profile in LINUX_PROFILES else None
        if tree is not None and any(key in tree for key in MARKERS):
            raise RuntimeError('Baseline contains a stale U-Boot/EFI marker')
        candidate, sha = PROFILES[args.profile]
        backend.checked_image(candidate.resolve(strict=True), sha)
        if args.profile in EFI_LINUX_PROFILES and args.profile not in NIX_PROFILES:
            efi_linux.payload()
        if args.profile in NIX_PROFILES:
            efi_linux.payload(persistent_nix.store_profile(efi_linux,require_efi=args.profile in NIX_EFI_PROFILES))
        if profile_kind(args.profile) in ('efi-provision','efi-manager'):
            efi_files.payload(files_profile_for(args.profile))
        if args.profile == 'efi-nix-dt-cross-manager':
            _,manifest=efi_files.payload(files_profile_for(args.profile))
            entry_dt.cross_carrier(candidate,sha,entry_dt.BUNDLE/'tree'/manifest['entry_device_tree'])
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
        if args.profile in NIX_PROFILES:
            persistent_nix.old_persistence(ssh, before['boot_id'], directory, qualify, persistence,
                qualify.ACCEPTED_SYSTEM, 'before-old-persistence')
        if args.profile in ('efi-nix-provision','efi-nix-dt-provision'):
            try:
                efi_files.evidence(ssh, before['boot_id'], directory, qualify, require_verified=False,
                    name='before-new-boot-files.json', profile=files_profile_for(args.profile))
                previous_files_evidence(ssh,before['boot_id'],directory,args.profile,'before-previous-efi-files')
            except (subprocess.SubprocessError, RuntimeError, ValueError):
                efi_files.evidence(ssh, before['boot_id'], directory, qualify, require_verified=False,
                    name='before-old-boot-files.json',
                    profile=persistent_nix.files_profile(efi_files) if args.profile in ENTRY_DT_PROFILES else None)
        if profile_kind(args.profile) == 'efi-manager':
            efi_files.evidence(ssh, before['boot_id'], directory, qualify,
                               require_verified=False, name='before-boot-files.json',
                               profile=files_profile_for(args.profile))
            if args.profile in ENTRY_DT_PROFILES:
                previous_files_evidence(ssh,before['boot_id'],directory,args.profile,'before-previous-efi-files')
        if tree is not None:
            qualify.save(directory, 'before-tree.json', tree)
        sources = directory / 'executed-sources'
        sources.mkdir(mode=0o700)
        source_hashes = {}
        for name in ('qualify-uboot-recovery.py', 'qualify-mtkclient.py', 'qualify-efi-linux.py',
                     'qualify-efi-files.py', 'qualify-efi-manager.py', 'qualify-efi-entry-dt.py', 'qualify-gemini-persistence.py',
                     'qualify-persistent-nix.py'):
            raw = (ROOT / 'tools' / name).read_bytes()
            (sources / name).write_bytes(raw)
            source_hashes[name] = backend.digest(raw)
        qualify.save(directory, 'plan.json', dict(profile=args.profile, candidate=str(candidate),
                     candidate_sha256=sha, rescue=str(ACCEPTED), execute=args.execute,
                     verify_persistence=args.verify_persistence,
                     executed_sources_sha256=source_hashes,
                     nix_verifier_sha256=backend.digest(
                         (ROOT / 'tools/qualify-persistent-nix.py').read_bytes()) if args.profile in NIX_PROFILES else None,
                     persistence_verifier_sha256=backend.digest(
                         (ROOT / 'tools/qualify-gemini-persistence.py').read_bytes()) if args.verify_persistence or args.profile in NIX_PROFILES else None,
                     store_provisioner_sha256=backend.digest(
                         (ROOT / 'tools/qualify-efi-linux.py').read_bytes()) if args.profile in EFI_LINUX_PROFILES or args.profile in NIX_PROFILES else None,
                     runner_sha256=backend.digest(Path(__file__).read_bytes())))
    if not args.execute:
        print(f'Preflight passed; no reboot or write. Evidence: {directory}')
        return
    try:
        trial(directory, args.profile, before, ssh, args.verify_persistence)
    except Exception as error:
        qualify.save(directory, 'result.json', dict(result='failed', error=str(error), profile=args.profile,
                     note='Durable recovery services keep their bounded ownership; inspect units.json'))
        raise


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
