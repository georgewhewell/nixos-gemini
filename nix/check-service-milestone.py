#!/usr/bin/env python3
"""Verify native module discovery and built service admission match the kernel."""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

kernel, system, modprobe, cross_check = map(Path, sys.argv[1:])
config = kernel/'kernel.config'
manifest = (kernel/'BUILD-MANIFEST').read_text()
release = re.search(r'^kernel-release=(.+)$', manifest, re.M)
assert release, 'missing built kernel release'
release = release[1]
tree = system/'kernel-modules'
assert tree.is_symlink() and tree.is_dir(), 'missing standard kernel-modules link'
assert (system/'kernel').resolve() == (kernel/'Image').resolve(), 'system kernel differs'
assert sorted(path.name for path in (tree/'lib/modules').iterdir()) == [release], \
    'module release differs'

spec = importlib.util.spec_from_file_location('gemini_cross_runtime', cross_check)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
check = runtime.Check()
check.file(system/'sw/bin/modprobe', executable=True)
environment = os.environ.copy()
for name in ('MODPROBE_OPTIONS', 'MODULE_DIR'):
    environment.pop(name, None)


def dependencies(name):
    result = subprocess.run([str(modprobe), '--show-depends', '--use-blacklist',
        '--dirname', str(tree), '--set-version', release,
        '--config', str(system/'etc/modprobe.d'), name],
        env=environment, check=True, capture_output=True, text=True, timeout=15)
    return [shlex.split(line) for line in result.stdout.splitlines()]


resolved = dependencies('of:NgnssT(null)Cmediatek,mt6797-gnss')
assert resolved and all(parts[0] == 'insmod' and len(parts) == 2 for parts in resolved), \
    'GNSS alias has no native module chain'
paths = [Path(parts[1]) for parts in resolved]
assert paths[-1].name == 'gnss-mtk-consys.ko', 'GNSS alias selected a different provider'
for path in paths:
    relative = path.relative_to(tree/'lib/modules'/release)
    assert path.resolve() == (kernel/'lib/modules'/release/relative).resolve(), \
        'module differs from maintained kernel'
    check.file(path)
assert not check.errors, f'ARM64 module runtime differs: {check.errors}'
for name in ('panfrost', 'cpufreq_dt', 'mtk_jpeg', 'mt6797_consys',
             'mt6797_btif_pio_platform', 'mt6797_wifi'):
    assert not dependencies(name), f'{name}: autoload bypasses ordered startup'
cmdline = re.search(r'^CONFIG_CMDLINE="(.*)"$', config.read_text(), re.M)
assert cmdline and re.search(r'\bmodprobe\.blacklist=[^ ]*\bmt6797_spm\b', cmdline[1]), \
    'SPM scoped firmware startup is not protected'
print('module-discovery=passed native-GNSS-alias-and-ordered-startup')
command = re.search(r'^CONFIG_CMDLINE="(.*)"$', config.read_text(), re.M)
assert command, 'missing kernel command line'
tokens = re.findall(r'\bGEMINI_A72_CI9_M\d+\b', command[1])
if not tokens:
    print('service-milestone=not-applicable')
    raise SystemExit(0)
assert len(tokens) == 1, 'ambiguous kernel milestone'
expected = set(tokens)
units = ('gemini-a72-preflight', 'gemini-cellular', 'gemini-gpu',
         'gemini-connectivity', 'gemini-audio', 'gemini-desktop-qualify',
         'gemini-m39')
for name in units:
    unit = system/'etc/systemd/system'/(name+'.service')
    entry = re.search(r'^ExecStart=(/[^\s]+)', unit.read_text(), re.M)
    assert entry, f'{name}: missing executable entry point'
    queue, seen, observed = [Path(entry[1])], set(), set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        assert len(seen) < 200, f'{name}: excessive script references'
        if not path.is_file() or path.stat().st_size > 1024*1024:
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        try:
            text = data.decode()
        except UnicodeDecodeError:
            continue
        observed.update(re.findall(r'\bGEMINI_A72_CI9_M\d+\b', text))
        queue.extend(Path(p) for p in re.findall(r'/nix/store/[a-zA-Z0-9/_.+-]+', text))
    assert observed == expected, f'{name}: kernel={expected}, scripts={observed}'
    print(f'{name}: milestone={tokens[0]}')
print('service-milestone=passed kernel-and-seven-built-service-entry-points')
