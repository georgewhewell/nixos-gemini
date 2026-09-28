#!/usr/bin/env python3
"""Enable the CONSYS Bluetooth child on an already connectivity-enabled DT."""
from pathlib import Path
import subprocess, sys, tempfile

source, overlay, output = map(Path, sys.argv[1:])


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def get(tree, node, prop, kind='bx'):
    return run('fdtget', '-t', kind, tree, node, prop)


def snapshot(tree, node='/'):
    data = {node: {p: get(tree, node, p) for p in run('fdtget', '-p', tree, node).split()}}
    for child in run('fdtget', '-l', tree, node).split():
        data.update(snapshot(tree, node.rstrip('/') + '/' + child))
    return data


bluetooth = get(source, '/__symbols__', 'bluetooth', 's')
assert bluetooth == '/consys@18070000/bluetooth', bluetooth
assert get(source, bluetooth, 'compatible', 's') == 'mediatek,mt6797-bluetooth'
assert get(source, bluetooth, 'status', 's') == 'disabled'
# The Wi-Fi activation step must already own the aggregate and its suppliers.
for label in ['consys_emi_mpu', 'btif', 'consys', 'wifi']:
    node = get(source, '/__symbols__', label, 's')
    assert get(source, node, 'status', 's') == 'okay', node

before = snapshot(source)
with tempfile.TemporaryDirectory() as d:
    result = Path(d) / 'bluetooth.dtb'
    run('fdtoverlay', '-i', source, '-o', result, overlay)
    after = snapshot(result)
    assert before.keys() == after.keys(), 'unexpected nodes'
    for node, props in before.items():
        for prop in props.keys() | after[node].keys():
            if props.get(prop) != after[node].get(prop):
                assert node == bluetooth and prop == 'status', (node, prop)
    assert get(result, bluetooth, 'status', 's') == 'okay'
    with output.open('xb') as f:
        f.write(result.read_bytes())
print('PASS bluetooth DT: only the CONSYS Bluetooth child status changed')
