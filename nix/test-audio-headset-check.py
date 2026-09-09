#!/usr/bin/env python3
"""Exercise the actual headset qualification shell and its process cleanup."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

script = Path(__file__).with_name('audio-headset-check.sh').resolve()
fake = r'''
import os
from pathlib import Path
import signal
import sys
import time
root = Path(os.environ['FIXTURE'])
mode = os.environ['MODE']
command = Path(sys.argv[0]).name

def reg(address, value, printed=None):
    with (root / 'pmic').open('r+b') as f:
        f.seek(address // 2 * 11)
        f.write(f'{address if printed is None else printed:04x}: {value:04x}\n'.encode())

def idle():
    if not (root / 'pmic').exists():
        (root / 'pmic').write_bytes((root / 'pmic-copy').read_bytes())
    reg(0xd08, 2)
    reg(0xd0a, 2)
    reg(0xd1c, 0x70 if mode == 'bias-leak' else 0xf0)
    (root / 'status').write_text('RUNNING\n' if mode == 'still-open' else 'closed\n')
    (root / 'controls').write_text('selected\n' if mode in ('hook-restore-failure', 'restore-failure', 'leaked-control') else 'baseline\n')
    (root / 'child-closed').touch()

if command == 'snapshot':
    if mode == 'snapshot-failure' and not (root / 'stored').exists():
        sys.exit(1)
    print((root / 'controls').read_text(), end='')
elif command == 'alsactl':
    if 'store' in sys.argv:
        if mode == 'store-failure':
            sys.exit(1)
        (root / 'stored').touch()
    else:
        assert 'restore' in sys.argv
        (root / 'restored').touch()
        if mode == 'restore-failure':
            sys.exit(1)
        (root / 'controls').write_text('leak\n' if mode == 'leaked-control' else 'baseline\n')
elif command == 'amixer':
    if mode == 'control-read-failure':
        sys.exit(1)
    print('mock named route control')
elif command == 'arecord':
    assert sys.argv[sys.argv.index('-D')+1] == 'gemini_headset_mic'
    assert sys.argv[sys.argv.index('-c')+1] == '1'
    assert sys.argv[-1] == '/dev/null'
    (root / 'child-pid').write_text(str(os.getpid()))
    stopped = False
    def stop(signum, frame):
        global stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if mode == 'early-exit':
            sys.exit(1)
        (root / 'controls').write_text('selected\n')
        reg(0xd08, 0x5123, 0xd06 if mode == 'wrong-address' else None)
        reg(0xd0a, 0x5113 if mode == 'right-active' else 2)
        reg(0xd1a, 1 if mode == 'internal-bias-active' else 0)
        reg(0xd1c, 0xf5 if mode == 'wrong-bias' else 0x75)
        if mode == 'read-failure':
            (root / 'pmic-copy').write_bytes((root / 'pmic').read_bytes())
            (root / 'pmic').unlink()
        (root / 'status').write_text('state: RUNNING\n')
        (root / 'child-started').touch()
        deadline = time.monotonic() + (30 if mode in ('timeout', 'signal') else 0.6)
        while not stopped and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        idle()
else:
    raise AssertionError(command)
'''

with tempfile.TemporaryDirectory(prefix='gemini-headset-check-') as temporary:
    base = Path(temporary)
    binary = base / 'bin'
    binary.mkdir()
    for command in ('snapshot', 'alsactl', 'amixer', 'arecord'):
        p = binary / command
        p.write_text('#!' + sys.executable + '\n' + fake)
        p.chmod(0o755)
    modes = ['normal', 'hook-restore-failure', 'right-active', 'internal-bias-active',
             'wrong-bias', 'wrong-address', 'read-failure', 'control-read-failure',
             'early-exit', 'bias-leak', 'still-open', 'restore-failure',
             'leaked-control', 'snapshot-failure', 'store-failure', 'busy', 'timeout', 'signal']
    for mode in modes:
        root = base / mode
        root.mkdir()
        (root / 'status').write_text('RUNNING\n' if mode == 'busy' else 'closed\n')
        (root / 'controls').write_text('baseline\n')
        registers = bytearray(b''.join(f'{n:04x}: 0000\n'.encode() for n in range(0, 65536, 2)))
        for address, value in ((0xd08, 2), (0xd0a, 2), (0xd1c, 0xf0)):
            registers[address//2*11:address//2*11+11] = f'{address:04x}: {value:04x}\n'.encode()
        (root / 'pmic').write_bytes(registers)
        env = os.environ | {'PATH': str(binary) + ':' + os.environ['PATH'],
                            'FIXTURE': str(root), 'MODE': mode,
                            'GEMINI_HEADSET_WORK': str(root / 'work'),
                            'GEMINI_HEADSET_PCM_STATUS': str(root / 'status'),
                            'GEMINI_HEADSET_PMIC_REGISTERS': str(root / 'pmic'),
                            'GEMINI_AUDIO_CONTROLS': str(binary / 'snapshot')}
        with subprocess.Popen(['bash', str(script)], env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as process:
            if mode == 'signal':
                deadline = time.monotonic() + 3
                while not (root / 'child-started').exists():
                    assert process.poll() is None
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                process.send_signal(signal.SIGTERM)
            out, err = process.communicate(timeout=12)
            expected = mode in ('normal', 'hook-restore-failure')
            assert (process.returncode == 0) == expected, (mode, process.returncode, out, err)
        assert (root / 'work/result').exists() == expected, mode
        if mode not in ('snapshot-failure', 'store-failure', 'busy'):
            assert (root / 'restored').exists(), mode
            assert (root / 'child-closed').exists(), mode
            pid = int((root / 'child-pid').read_text())
            assert not Path(f'/proc/{pid}').exists(), (mode, 'orphaned capture', pid)
        if mode not in ('still-open', 'busy'):
            assert (root / 'status').read_text() == 'closed\n', mode
        if mode not in ('restore-failure', 'leaked-control'):
            assert (root / 'controls').read_text() == 'baseline\n', mode
        print('PASS actual headset qualification:', mode)
