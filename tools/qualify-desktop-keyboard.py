#!/usr/bin/env python3
"""Pinned compact-US desktop trial, using the existing supervised recovery lane."""
from pathlib import Path
import re
import shlex

WORKSPACE = Path(__file__).resolve().parents[2]
BUNDLE = WORKSPACE / 'handoff/desktop-keyboard-linux'
SYSTEM = '/nix/store/mdfyb9m4vczl0lnvlzjz1jn3jjlp8n3h-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
BOOT_SHA = 'ac9b5091f5410a9e988128197770922396dd27e8aec7fb06cd0149505d7cdf49'
STORE_SHA = '31b4db06c615de5036c513b69ba4e9da887a688ead3e2698fd368ec28242ab6c'
STORE_SIZE = 427036672
CHECK = '/nix/store/a2smp6m2irx68hmapp1k4l9l3j1iv45y-gemini-desktop-keyboard-check-aarch64-unknown-linux-gnu-1/bin/gemini-desktop-keyboard-check'
CHECK_SHA = '008c71ed4f1f87e69b9a95550bdf0c934d862c22f7446b3e4ad5ceba29ff1303'
XKB_ROOT = '/nix/store/3sg9dmy5zqskrcl5hnsgmn2kp4c370pb-gemini-xkb-data/share/X11/xkb'
SYMBOL_SHA = '56baafdde43da9e3d66474f231a9bfd9d8d9fda40cd4c4af939ae1251db426cb'


def store_profile(provisioner):
    return provisioner.StoreProfile(BUNDLE, SYSTEM, STORE_SHA, STORE_SIZE, False)


def verify_report(report):
    lines = report.splitlines()
    if (len(lines) != 3 or
            lines[0] != 'keymap=gemian-us-v1 combinations=416 modifiers=5 caps-toggle=passed' or
            lines[1] != 'compose=passed accents=8 locale=C.UTF-8' or
            not re.fullmatch(r'desktop-keyboard=passed mode=device seat=[A-Za-z0-9_.-]+ physical-key-press=unobserved', lines[2]) or
            'seat=gemini-keymap-fixture ' in lines[2]):
        raise RuntimeError('Complete live desktop keyboard map/composition evidence is missing')


def verify_environment(raw):
    lines = raw.splitlines()
    expected = ['LANG=C.UTF-8', 'LC_CTYPE=C.UTF-8', 'XKB_CONFIG_ROOT=' + XKB_ROOT]
    if sorted(lines) != sorted(expected):
        raise RuntimeError('Live desktop locale or XKB source differs from the candidate')


def evidence(ssh, boot_id, directory, qualify, persistence, persistent_nix):
    guard = f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(readlink /run/current-system)" = {SYSTEM}
systemctl is-active gemini-desktop.service gemini-desktop-qualify.service >/dev/null
test "$(sha256sum {CHECK} | cut -d' ' -f1)" = {CHECK_SHA}
test "$(sha256sum {XKB_ROOT}/symbols/planet_vndr/gemini | cut -d' ' -f1)" = {SYMBOL_SHA}
grep -qx 'keymap_layout=planet_vndr/gemini' /etc/gemini/weston.ini
grep -qx 'keymap_variant=us' /etc/gemini/weston.ini
'''
    startup = persistence.run(ssh, guard + 'cat /run/gemini-desktop/keyboard.txt\n',
                              directory, 'desktop-keyboard-startup')
    verify_report(startup)
    environment = persistence.run(ssh, guard + '''pid=$(systemctl show gemini-desktop.service -p MainPID --value)
test "$pid" -gt 1
tr '\\000' '\\n' < /proc/$pid/environ | grep -E '^(LANG|LC_CTYPE|LC_ALL|XKB_CONFIG_ROOT)='
''', directory, 'desktop-keyboard-environment')
    verify_environment(environment)
    command = guard + f'''{persistent_nix.SYSTEMD}/systemd-run --quiet --wait --pipe --collect --unit=gemini-keyboard-map-check --uid=gemini --gid=users --setenv=XDG_RUNTIME_DIR=/run/gemini-desktop --setenv=WAYLAND_DISPLAY=wayland-0 --setenv=LANG=C.UTF-8 --setenv=LC_CTYPE=C.UTF-8 {CHECK}
'''
    current = persistence.run(ssh, command, directory, 'desktop-keyboard-fresh')
    verify_report(current)
    qualify.save(directory, 'desktop-keyboard-evidence.json', dict(
        boot_id=boot_id, system=SYSTEM, layout='gemian-us-v1', combinations=416,
        physical_modifiers=5, composed_accents=8, locale='C.UTF-8',
        startup_and_fresh_client_verified=True, physical_key_press_observed=False))
