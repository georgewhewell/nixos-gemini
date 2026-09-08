#!/usr/bin/env python3
"""Exercise the actual service regex against healthy and failed kernel logs."""
from pathlib import Path
import re
import subprocess

source = (Path(__file__).resolve().parents[1] / 'nixos/connectivity.nix').read_text()
patterns = re.findall(r"if grep -Ei '([^']+)' /run/gemini-connectivity/kernel-steady.txt; then", source)
assert len(patterns) == 1
healthy = [
    '[ 246.653666] mt6797-wifi 180f0000.wifi: WLAN 0x6797 fw 0x0403 HIF_EVENT_PUMP_READY irq=238 budget=32 timeout_ms=100',
    'mt6797-wifi 180f0000.wifi: HIF startup result=0 status=0x3 rx=2 events=2',
    'mt6797-consys 18070000.consys: CONSYS powered; chip 0x279 and firmware patched; radios disabled',
    'unrelated-device: timeout waiting for optional hardware',
]
failed = [
    'mt6797-wifi 180f0000.wifi: timeout',
    'mt6797-wifi 180f0000.wifi: timeout waiting for reply',
    'mt6797-wifi 180f0000.wifi: fault=0x1',
    'mt6797-wifi 180f0000.wifi: fatal: invalid state',
    'mt6797-consys 18070000.consys: firmware failed (-5)',
    'mt6797-btif 1100c000.serial: transfer timed out',
    'mt6797-wifi 180f0000.wifi: HIF fenced: -71',
    healthy[0] + ' failed later',
    'mt6797-wifi 180f0000.wifi: TIMEOUT',
]
for line in healthy + failed:
    result = subprocess.run(['grep', '-Ei', patterns[0]], input=line+'\n', text=True, capture_output=True)
    assert result.returncode == (1 if line in healthy else 0), (line, result)
print(f'PASS: {len(healthy)} healthy and {len(failed)} failure log cases')
