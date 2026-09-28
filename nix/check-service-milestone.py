#!/usr/bin/env python3
"""Verify built service admission scripts agree with the kernel milestone."""
from pathlib import Path
import re
import sys

config, system = map(Path, sys.argv[1:])
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
