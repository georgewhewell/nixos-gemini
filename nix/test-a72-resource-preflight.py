#!/usr/bin/env python3
"""Execute the read-only helper against a synthetic provider snapshot."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

helper = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    files = {
        'cpu/online': '0-7\n',
        'dt/cpus/cpu@200/status': 'okay\0',
        'dt/cpus/cpu@201/status': 'okay\0',
        'cmdline': 'maxcpus=8 regulator_ignore_unused\n',
        'regulators': 'vproc-little 0 0 0 0 1000mV\nvproc-big 0 0 0 0 1000mV\nvsram-big 0 0 0 0 1050mV\n',
        'clocks': 'mt6797_mp2 0 0 0 26000000\nmt6797_mp2_armpll 0 0 0 0\n',
        'log': ('DA9214 direct-address regulators registered\n'
                'voltage read/set ready; enable, status, and disable unsupported\n'
                'CPU8/9 resource-preflight-v2: offline=1 mode=cpu8-admission vproc=1000000uV vproc-enabled=0 sram=1050000uV sram-contract=one-shot-first-cpu8-v1 sram-selector=0 sram-control=0x00000000 sram-calibration=0x00000000 mp2-clock-contract=cold-clk26m-v1 mp2=26000000Hz pwrap-reset=0 spm-mp2=0x00000000 spm-buck-iso=0x00000003 transaction=ready\n'
                'cpu-on-gate-v3: CPU8-admission=ready CPU9=after-CPU8\n'),
    }
    nodes = ['i2c@1100e000/regulator@68/regulators/BUCKA',
             'i2c@1100e000/regulator@68/regulators/BUCKB', 'regulator-sram-big']
    names = ['vproc-little', 'vproc-big', 'vsram-big']
    for i, (node, name) in enumerate(zip(nodes, names)):
        files[f'dt/{node}/phandle'] = '\0\0\0' + chr(i+1)
        files[f'regulator-class/regulator.{i}/name'] = name + '\n'
    files['dt/a72-power/vproc-big-supply'] = '\0\0\0\2'
    files['dt/a72-power/sram-big-supply'] = '\0\0\0\3'
    for name, value in files.items():
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
    for i, node in enumerate(nodes):
        (root/f'regulator-class/regulator.{i}/of_node').symlink_to(root/'dt'/node)
    (root/'driver').mkdir(); (root/'device').mkdir()
    (root/'driver/a72-power').symlink_to(root/'device')
    env = dict(os.environ, CPU_ROOT=str(root/'cpu'), DT_ROOT=str(root/'dt'),
               DRIVER_ROOT=str(root/'driver'), REGULATOR_SUMMARY=str(root/'regulators'), REGULATOR_ROOT=str(root/'regulator-class'),
               CLOCK_SUMMARY=str(root/'clocks'), CMDLINE_PATH=str(root/'cmdline'),
               KERNEL_LOG=str(root/'log'), EXPECTED_CPU8_STATUS='okay', EXPECTED_CPU9_STATUS='okay')
    cases = [('pass', None, None), ('online-a72', 'cpu/online', '0-8\n'),
             ('wrong-cpu9', 'dt/cpus/cpu@201/status', 'disabled\0'),
             ('rail-mismatch', 'regulators', files['regulators'].replace('vproc-big 0 0 0 0 1000mV','vproc-big 0 0 0 0 900mV')),
             ('missing-gate', 'log', files['log'].split('cpu-on-gate-v3:')[0]),
             ('kernel-error', 'log', files['log']+'mt6797-a72: transaction error\n'),
             ('missing-clock', 'clocks', ''),
             ('wrong-supply', 'dt/a72-power/vproc-big-supply', '\0\0\0\1'),
             ('short-supply', 'dt/a72-power/sram-big-supply', '\0\3'),
             ('wrong-published-name', 'regulator-class/regulator.1/name', 'vproc-little\n'),
             ('missing-contract', 'log', files['log'].replace('mp2-clock-contract=cold-clk26m-v1 ', '')),
             ('duplicate-contract', 'log', files['log'].replace('mp2-clock-contract=cold-clk26m-v1', 'mp2-clock-contract=cold-clk26m-v1 mp2-clock-contract=cold-clk26m-v1')),
             ('wrong-contract', 'log', files['log'].replace('cold-clk26m-v1', 'running')),
             ('wrong-rate', 'log', files['log'].replace('mp2=26000000Hz', 'mp2=25000000Hz')),
             ('programmed-pll', 'clocks', files['clocks'].replace('mt6797_mp2_armpll 0 0 0 0', 'mt6797_mp2_armpll 0 0 0 750000000')),
             ('duplicate-summary', 'regulators', files['regulators']+'vproc-big 0 0 0 0 1000mV\n')]
    for name, changed, value in cases:
        if changed: (root/changed).write_text(value)
        before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
        result = subprocess.run(['sh', str(helper)], env=env, capture_output=True, text=True)
        assert (result.returncode == 0) == (name == 'pass'), (name, result.stdout, result.stderr)
        if name == 'pass': assert 'cpu_on_requested=no\n' in result.stdout and 'result=pass\n' in result.stdout
        assert {path: path.read_bytes() for path in before} == before
        if changed: (root/changed).write_text(files[changed])
        print('PASS actual A72 preflight:', name)

    # An exact published-name name under the wrong DT node is not the right rail.
    link = root/'regulator-class/regulator.1/of_node'
    link.unlink(); link.symlink_to(root/'dt'/nodes[0])
    result = subprocess.run(['sh', str(helper)], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'provider identity mismatch' in result.stderr
    link.unlink(); link.symlink_to(root/'dt'/nodes[1])
    duplicate = root/'regulator-class/regulator.3'
    duplicate.mkdir(); (duplicate/'name').write_text(names[1]+'\n')
    (duplicate/'of_node').symlink_to(root/'dt'/nodes[1])
    result = subprocess.run(['sh', str(helper)], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'provider identity mismatch' in result.stderr
    print('PASS wrong-node and duplicate-provider refusal')
