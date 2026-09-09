#!/usr/bin/env python3
"""Test built PCM definitions with real ALSA and distinguishable source channels.

Only the hardware/ctl-hook boundary is replaced with a synthetic capture source.
The production route/plug definitions, format and channel constraints are kept.
"""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

configuration = Path(sys.argv[1]).read_text()
# arecord is an aplay symlink; preserving argv[0] selects capture mode.
arecord = Path(sys.argv[2]).absolute()
assert arecord.is_file()
alsa_dev = Path(sys.argv[3]).resolve(strict=True)
libdir = next(line.split('=', 1)[1] for line in (alsa_dev / 'lib/pkgconfig/alsa.pc').read_text().splitlines() if line.startswith('libdir='))
names = ('gemini_headset_mic', 'gemini_headset_mic_ucm')

def pcm_definition(name):
    start = configuration.index('pcm.' + name + ' {')
    brace = configuration.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (configuration[end] == '{') - (configuration[end] == '}')
        end += 1
    return configuration[start:end]

source = '\n'.join(pcm_definition(name) for name in names)
assert source.count('"gemini_headset_mic_routes"') == 1
assert source.count('"hw:CARD=mt6797mt6351,DEV=3"') == 1
source = source.replace('"gemini_headset_mic_routes"', '"fixture"')
source = source.replace('"hw:CARD=mt6797mt6351,DEV=3"', '"fixture"')
with tempfile.TemporaryDirectory(prefix='gemini-headset-mono-') as temporary:
    root = Path(temporary)
    module = root / 'libasound_module_pcm_gemini_test_source.so'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-DPIC', '-fPIC', '-shared', '-O2', '-I' + str(alsa_dev / 'include'),
                    str(Path(__file__).with_name('test-audio-source.c')), '-L' + libdir,
                    '-Wl,-rpath,' + libdir, '-lasound', '-o', str(module)], check=True)
    # Neither channel is constant or zero; a swap, mix or divide is observable.
    left = [(n * 37 % 6001) - 3000 for n in range(48000)]
    config = root / 'alsa.conf'
    config.write_text(f'pcm_type.gemini_test_source {{ lib "{module}" }}\n'
                      'pcm.fixture { type gemini_test_source slave.pcm { type null } }\n' + source)
    env = os.environ | {'ALSA_CONFIG_PATH': str(config)}
    for name in names:
        for channels in (1, 2):
            for period in (257, 512, 6000):
                output = root / f'{name}-{channels}-{period}.raw'
                result = subprocess.run([str(arecord), '-q', '-D', name, '-t', 'raw',
                                         '-f', 'S16_LE', '-r', '48000', '-c', str(channels),
                                         '--period-size=' + str(period), '--buffer-size=' + str(period*4),
                                         '-d', '1', str(output)], env=env, capture_output=True,
                                        text=True, timeout=5)
                assert result.returncode == 0 and not result.stderr, (name, channels, result.stderr)
                actual = output.read_bytes()
                expected = b''.join(struct.pack('<' + 'h' * channels, *([l] * channels)) for l in left)
                assert actual == expected, (name, channels, period, len(actual), len(expected))
                print(f'PASS real ALSA {name}: {channels}-channel client, period {period}, exact left-only samples')
