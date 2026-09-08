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
        'regulators': 'vproc-little 0 0 0 0 1000mV\nvproc-big 0 0 0 0 1000mV\nvsram-big 0 0 0 0 1100mV\n',
        'clocks': 'mt6797_mp2 0 0 0 2250000000\nmt6797_mp2_armpll 0 0 0 2250000000\n',
        'log': ('DA9214 direct-address regulators registered\n'
                'voltage read/set ready; enable, status, and disable unsupported\n'
                'CPU8/9 resource-preflight-v2: offline=1 mode=cpu8-admission vproc=1000000uV vproc-enabled=0 sram=1100000uV sram-contract=voltage-only sram-selector=10 mp2=2250000000Hz pwrap-reset=0 spm-mp2=0x00000000 spm-buck-iso=0x00000003 transaction=ready\n'
                'cpu-on-gate-v3: CPU8-admission=ready CPU9=after-CPU8\n'),
    }
    for name, value in files.items():
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
    (root/'driver').mkdir(); (root/'device').mkdir()
    (root/'driver/a72-power').symlink_to(root/'device')
    env = dict(os.environ, CPU_ROOT=str(root/'cpu'), DT_ROOT=str(root/'dt'),
               DRIVER_ROOT=str(root/'driver'), REGULATOR_SUMMARY=str(root/'regulators'),
               CLOCK_SUMMARY=str(root/'clocks'), CMDLINE_PATH=str(root/'cmdline'),
               KERNEL_LOG=str(root/'log'), EXPECTED_CPU8_STATUS='okay', EXPECTED_CPU9_STATUS='okay')
    cases = [('pass', None, None), ('online-a72', 'cpu/online', '0-8\n'),
             ('wrong-cpu9', 'dt/cpus/cpu@201/status', 'disabled\0'),
             ('rail-mismatch', 'regulators', files['regulators'].replace('vproc-big 0 0 0 0 1000mV','vproc-big 0 0 0 0 900mV')),
             ('missing-gate', 'log', files['log'].split('cpu-on-gate-v3:')[0]),
             ('kernel-error', 'log', files['log']+'mt6797-a72: transaction error\n'),
             ('missing-clock', 'clocks', '')]
    for name, changed, value in cases:
        if changed: (root/changed).write_text(value)
        before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
        result = subprocess.run(['sh', str(helper)], env=env, capture_output=True, text=True)
        assert (result.returncode == 0) == (name == 'pass'), (name, result.stdout, result.stderr)
        if name == 'pass': assert 'cpu_on_requested=no\n' in result.stdout and 'result=pass\n' in result.stdout
        assert {path: path.read_bytes() for path in before} == before
        if changed: (root/changed).write_text(files[changed])
        print('PASS actual A72 preflight:', name)
