#!/usr/bin/env python3
"""Exercise the actual transformer on an integration DT and mutated providers."""
from pathlib import Path
import subprocess
import sys
import tempfile

base, overlay = map(Path, sys.argv[1:3])
script = Path(sys.argv[3]) if len(sys.argv) == 4 else Path(__file__).with_name('cellular-integration-dt.py')
with tempfile.TemporaryDirectory() as directory:
    tree = Path(directory) / 'test.dtb'
    tree.write_bytes(base.read_bytes())
    subprocess.run([sys.executable, str(script), str(tree), str(overlay)], check=True)
    before = tree.read_bytes()
    result = subprocess.run([sys.executable, str(script), str(tree), str(overlay)], capture_output=True)
    assert result.returncode != 0 and tree.read_bytes() == before
    for name, kind, node, prop, values in (
        ('wrong-provider', 's', '/watchdog@10007000', 'compatible', ['wrong']),
        ('wrong-reset', 'x', '/pwrap@1000d000', 'resets', ['3','40']),
        ('missing-symbol', None, '/__symbols__', 'pmic', []),
    ):
        tree.write_bytes(base.read_bytes())
        command = ['fdtput'] + (['-t', kind] if kind else ['-d'])
        subprocess.run(command + [str(tree), node, prop] + values, check=True)
        before = tree.read_bytes()
        result = subprocess.run([sys.executable, str(script), str(tree), str(overlay)], capture_output=True)
        assert result.returncode != 0 and tree.read_bytes() == before, name
        print('PASS refusal without mutation:', name)
    bad_overlay = Path(directory) / 'bad.dtbo'
    for prop, values in (
        ('mediatek,configuration', ['0','0','0','0']),
        ('mediatek,driving', ['2','2','2','2']),
        ('mediatek,driving', ['1','1','1']),
        ('unexpected-clock-policy', ['1']),
    ):
        tree.write_bytes(base.read_bytes())
        bad_overlay.write_bytes(overlay.read_bytes())
        subprocess.run(['fdtput', '-t', 'x', str(bad_overlay),
                        '/fragment@0/__overlay__/modem@10014000/rf-clock',
                        prop] + values, check=True)
        before = tree.read_bytes()
        result = subprocess.run([sys.executable, str(script), str(tree), str(bad_overlay)], capture_output=True)
        assert result.returncode != 0 and tree.read_bytes() == before, (prop, values)
        print('PASS refusal without mutation: RF policy', prop, values)
print('PASS real transformer and duplicate-application refusal')
