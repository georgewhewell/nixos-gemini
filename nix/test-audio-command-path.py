#!/usr/bin/env python3
"""Verify external commands in the built qualification's explicit PATH.

Do not inherit the host PATH: systemd's service environment did not provide
cmp in M28, even though interactive rescue shells had a BusyBox applet.
"""
import os
from pathlib import Path
import re
import sys

script = Path(sys.argv[1]).read_text()
match = re.search(r'^export PATH=(.*):\$PATH$', script, re.M)
assert match, 'missing explicit qualification PATH'
paths = [Path(p) for p in match[1].split(':')]
commands = ['grep', 'systemctl', 'cat', 'mkdir', 'dmesg', 'timeout',
            'amixer', 'aplay', 'arecord', 'cmp', 'alsaucm', 'readlink']
missing = []
for command in commands:
    found = next((p / command for p in paths
                  if (p / command).is_file() and os.access(p / command, os.X_OK)), None)
    if found is None:
        missing.append(command)
assert not missing, f'missing service commands: {missing}'
print('PASS built audio qualification command path:', ', '.join(commands))
