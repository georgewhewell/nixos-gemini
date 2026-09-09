#!/usr/bin/env python3
"""Exercise the built audio USB guard with temporary sysfs-like fixtures."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

script = Path(sys.argv[1]).read_text()
match = re.search(r'^check_usb\(\) \{\n.*?^\}', script, re.M | re.S)
assert match, 'built USB preservation guard missing'
guard = match[0]
with tempfile.TemporaryDirectory(prefix='gemini-audio-usb-') as temporary:
    root = Path(temporary)
    net, device, replacement, rail = [root / name for name in
                                      ('net', 'device', 'replacement', 'rail')]
    for path in (net, device, replacement, rail):
        path.mkdir()
    (net / 'device').symlink_to(device)
    baseline = {net / 'ifindex': '5\n', net / 'carrier': '1\n',
                rail / 'state': 'enabled\n', rail / 'num_users': '2\n'}
    for path, value in baseline.items():
        path.write_text(value)
    environment = os.environ | {'right_net': str(net),
                                'right_device': str(device),
                                'right_ifindex': '5',
                                'shared_rail': str(rail), 'usb_users': '2'}

    def check(expected, description):
        result = subprocess.run(['bash', '-c', 'set -eu\n' + guard + '\ncheck_usb'],
                                env=environment, capture_output=True, text=True)
        assert (result.returncode == 0) == expected, (description, result)
        print('PASS', description)

    check(True, 'same USB device and both supply claims survive')
    for path, value, description in (
        (net / 'ifindex', '6\n', 're-enumerated network interface rejected'),
        (net / 'carrier', '0\n', 'carrier loss rejected'),
        (rail / 'state', 'disabled\n', 'disabled shared rail rejected'),
        (rail / 'num_users', '1\n', 'lost USB supply claim rejected'),
        (rail / 'num_users', '3\n', 'leaked audio supply claim rejected'),
    ):
        path.write_text(value)
        check(False, description)
        path.write_text(baseline[path])
    (net / 'device').unlink()
    (net / 'device').symlink_to(replacement)
    check(False, 'changed USB device rejected')
    (net / 'device').unlink()
    (net / 'ifindex').unlink()
    check(False, 'removed USB device rejected')
