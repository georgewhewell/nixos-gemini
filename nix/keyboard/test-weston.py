"""Read real Weston keymaps; no input injection and no device dependency."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

weston, probe, fixture, data = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='gemini-keyboard-') as temporary:
    root = Path(temporary)
    damaged = root / 'damaged'
    shutil.copytree(data, damaged, symlinks=True)
    symbols = damaged / 'symbols/planet_vndr/gemini'
    text = symbols.read_text()
    assert 'ISO_Level3_Shift' in text
    assert not symbols.parent.is_symlink()
    symbols.parent.chmod(0o755)
    symbols.unlink()
    symbols.write_text(text.replace('ISO_Level3_Shift', 'Super_L'))
    cases = [
        ('gemini', 'planet_vndr/gemini', 'us', data, True, True, 0, ''),
        ('generic-us', 'us', '', data, True, True, 1, 'layout-name'),
        ('wrong-fn', 'planet_vndr/gemini', 'us', str(damaged), True, True, 1, 'keysym-mismatch'),
        ('fixture-is-not-device', 'planet_vndr/gemini', 'us', data, True, False, 1, 'fixture-mode'),
        ('missing-seat', 'planet_vndr/gemini', 'us', data, False, True, 1, 'keyboard-keymap-missing'),
    ]
    for name, layout, variant, includes, seat, fixture_mode, expected, stage in cases:
        directory = root / name
        directory.mkdir(mode=0o700)
        config = directory / 'weston.ini'
        config.write_text('[core]\nidle-time=0\n[keyboard]\nkeymap_layout=' + layout +
                          '\nkeymap_variant=' + variant + '\n')
        env = dict(os.environ, HOME=str(directory), XDG_RUNTIME_DIR=str(directory),
                   WAYLAND_DISPLAY='wayland-test', XKB_CONFIG_ROOT=includes,
                   LANG='C.UTF-8', LC_CTYPE='C.UTF-8')
        env.pop('DISPLAY', None)
        env.pop('LC_ALL', None)
        command = [weston, '-Bheadless', '--renderer=pixman', '--idle-time=0',
                   '--socket=wayland-test', '--config=' + str(config)]
        if seat:
            command += ['--modules=' + fixture]
        with tempfile.TemporaryFile(mode='w+') as log:
            server = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if (directory / 'wayland-test').exists() or server.poll() is not None:
                        break
                    time.sleep(0.05)
                result = subprocess.run([probe] + (['--headless-fixture'] if fixture_mode else []),
                    env=env, capture_output=True, text=True, timeout=15)
                log.seek(0)
                assert result.returncode == expected, (name, result, log.read())
                if expected:
                    assert 'failed=' + stage in result.stderr, (name, result.stderr)
                    assert 'desktop-keyboard=passed' not in result.stdout
                else:
                    assert 'keymap=gemian-us-v1 combinations=416 modifiers=5 caps-toggle=passed' in result.stdout
                    assert 'desktop-keyboard=passed mode=headless-fixture' in result.stdout
                    assert 'compose=passed accents=8 locale=C.UTF-8' in result.stdout
                print(name + ': PASS', flush=True)
            finally:
                if server.poll() is None:
                    server.terminate()
                server.wait(timeout=10)
    directory = root / 'stalled'
    directory.mkdir(mode=0o700)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(directory / 'wayland-test'))
        server.listen(1)
        started = time.monotonic()
        result = subprocess.run([probe, '--headless-fixture'], capture_output=True, text=True,
            env=dict(os.environ, XDG_RUNTIME_DIR=str(directory), WAYLAND_DISPLAY='wayland-test'), timeout=15)
        assert result.returncode == -signal.SIGALRM and 9 <= time.monotonic() - started < 15, result
        assert 'desktop-keyboard=passed' not in result.stdout
        print('unresponsive compositor: bounded failure PASS')
