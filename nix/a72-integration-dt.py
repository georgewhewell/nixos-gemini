#!/usr/bin/env python3
"""Compose A72 admission on the integration DT, publishing only a checked delta."""
from pathlib import Path
import subprocess
import sys
import tempfile

source, *overlays = map(Path, sys.argv[1:])
assert len(overlays) == 3

def run(args):
    return subprocess.check_output(args, text=True).strip()

def get(tree, node, prop, kind='s'):
    return run(['fdtget', '-t', kind, str(tree), node, prop])

def snapshot(tree, node='/'):
    data = {node: {p: get(tree, node, p, 'bx')
                  for p in run(['fdtget', '-p', str(tree), node]).split()}}
    for child in run(['fdtget', '-l', str(tree), node]).split():
        data.update(snapshot(tree, node.rstrip('/') + '/' + child))
    return data

before = snapshot(source)
labels = {
    'cpuclk': '/clock-controller@1001a000',
    'cluster0_opp': '/opp-table-cluster0', 'cluster1_opp': '/opp-table-cluster1',
    'da9214': '/i2c@1100e000/regulator@68',
    'da9214_bucka': '/i2c@1100e000/regulator@68/regulators/BUCKA',
    'da9214_buckb': '/i2c@1100e000/regulator@68/regulators/BUCKB',
    'vsram_big': '/regulator-sram-big', 'a72_power': '/a72-power',
    'cpu8': '/cpus/cpu@200', 'cpu9': '/cpus/cpu@201',
}
for label, node in labels.items():
    assert get(source, '/__symbols__', label) == node, label
# CI9 CPU nodes omit status (default available), but maxcpus=8 keeps them
# offline. Provider statuses, not CPU status alone, identify this baseline.
for label in ('cpuclk', 'da9214', 'vsram_big', 'a72_power'):
    assert get(source, labels[label], 'status') == 'disabled', label
with tempfile.TemporaryDirectory() as directory:
    result = Path(directory) / 'result.dtb'
    run(['fdtoverlay', '-i', str(source), '-o', str(result), *map(str, overlays)])
    # Force-CMDLINE supplies maxcpus/regulator_ignore_unused. Preserve all
    # original /chosen properties rather than retaining overlay bootargs.
    if 'bootargs' in before['/chosen']:
        run(['fdtput', '-t', 'bx', str(result), '/chosen', 'bootargs',
             *before['/chosen']['bootargs'].split()])
    else:
        run(['fdtput', '-d', str(result), '/chosen', 'bootargs'])
    after = snapshot(result)
    assert set(before) == set(after), 'unexpected DT nodes'
    allowed = {(node, 'status'): 'disabled' if label.startswith('cluster') else 'okay'
               for label, node in labels.items()}
    for label in ('cpu8', 'cpu9'):
        allowed[(labels[label], 'enable-method')] = 'mediatek,mt6797-psci'
        assert 'operating-points-v2' not in after[labels[label]]
    for (node, prop), expected in allowed.items():
        assert get(result, node, prop) == expected, (node, prop)
    for node, props in before.items():
        for prop in set(props) | set(after[node]):
            if props.get(prop) != after[node].get(prop):
                assert (node, prop) in allowed, (node, prop)
    source.write_bytes(result.read_bytes())
print('PASS A72 integration DT: explicit admission statuses, original node set and all other properties preserved')
