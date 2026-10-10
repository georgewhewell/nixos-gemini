#!/usr/bin/env python3
"""Exercise built onboard playback PCMs with real ALSA and isolated channels.

Only the hardware/control-hook boundary is replaced by a file sink. Production
route, plug, and default PCM definitions are retained. No sound device is opened.
"""
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile


def definition(configuration, prefix, name):
    start = configuration.index(prefix + name + " {")
    brace = configuration.index("{", start)
    depth, end = 1, brace + 1
    quoted = escaped = False
    while depth:
        character = configuration[end]
        if escaped:
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted:
            depth += (character == "{") - (character == "}")
        end += 1
    return configuration[start:end]


def validate(configuration, ucm, previous=None):
    names = ("gemini_speakers", "gemini_headphones", "gemini_playback_ucm")
    for device in ("Speaker", "Headphones"):
        section = definition(ucm, 'SectionDevice.', '"' + device + '"')
        assert section.count('PlaybackPCM "gemini_playback_ucm"') == 1, device
        assert 'PlaybackChannels 2' in section, device
        assert 'PlaybackChannelPos' not in section, device
    for name in ("gemini_speakers_stereo", "gemini_headphones_stereo", "gemini_playback_ucm"):
        route = definition(configuration, 'pcm.', name)
        assert 'type route' in route and 'channels 2' in route, name
        assert re.findall(r'ttable\.([0-9]+)\.([0-9]+)\s+([0-9.]+)', route) == [('0', '1', '1'), ('1', '0', '1')], name
    assert '"hw:CARD=mt6797mt6351,DEV=0"' in definition(configuration, 'pcm.', 'gemini_playback_ucm')
    if previous is not None:
        for name in ('gemini_mic_routes', 'gemini_mic', 'gemini_headset_mic_routes',
                     'gemini_headset_mic', 'gemini_headset_mic_ucm'):
            assert definition(configuration, 'pcm.', name) == definition(previous, 'pcm.', name), ('capture changed', name)
        for device in ('Mic', 'Headset'):
            assert 'CapturePCM' in definition(ucm, 'SectionDevice.', '"' + device + '"')
    return names


def main():
    configuration = Path(sys.argv[1]).read_text()
    ucm = Path(sys.argv[2]).read_text()
    aplay = Path(sys.argv[3]).absolute()
    assert aplay.is_file()
    previous = Path(sys.argv[4]).read_text() if len(sys.argv) == 5 else None
    names = validate(configuration, ucm, previous)
    names += ('default',)
    parts = [definition(configuration, 'pcm.', name) for name in
             ('gemini_speakers', 'gemini_speakers_stereo', 'gemini_headphones',
              'gemini_headphones_stereo', 'gemini_playback_ucm', '!default')]
    source = '\n'.join(parts)
    assert source.count('"hw:CARD=mt6797mt6351,DEV=0"') == 1
    source = source.replace('"hw:CARD=mt6797mt6351,DEV=0"', '"fixture_sink"')
    source += '\npcm.gemini_speakers_routes { type plug slave.pcm "fixture_sink" }\n'
    source += 'pcm.gemini_headphones_routes { type plug slave.pcm "fixture_sink" }\n'
    # A full number of aplay periods avoids its zero padding at EOF.
    frames = 49152
    fixtures = {
        'left-only': [((n * 37 % 6001) - 3000, 0) for n in range(frames)],
        'right-only': [(0, (n * 53 % 4001) - 2000) for n in range(frames)],
        'distinct-stereo': [((n * 37 % 6001) - 3000, (n * 53 % 4001) - 2000) for n in range(frames)],
    }
    checks = 0
    with tempfile.TemporaryDirectory(prefix='gemini-playback-map-') as temporary:
        root = Path(temporary)
        output = root / 'captured.raw'
        config = root / 'alsa.conf'
        config.write_text('pcm.fixture_null { type null }\n'
                          'pcm.fixture_sink { type file slave.pcm "fixture_null" file '
                          + json.dumps(str(output)) + ' format "raw" }\n' + source)
        env = os.environ | {'ALSA_CONFIG_PATH': str(config)}
        for fixture, samples in fixtures.items():
            incoming = b''.join(struct.pack('<hh', left, right) for left, right in samples)
            swapped = b''.join(struct.pack('<hh', right, left) for left, right in samples)
            # Direct fixture bypass checks the recorder itself does not swap.
            for name in ('fixture_sink',) + names:
                output.unlink(missing_ok=True)
                result = subprocess.run([str(aplay), '-q', '-D', name, '-t', 'raw',
                                         '-f', 'S16_LE', '-r', '48000', '-c', '2',
                                         '--period-size=512', '--buffer-size=2048',
                                         '--samples=' + str(frames)],
                                        input=incoming, env=env, capture_output=True, timeout=5)
                assert result.returncode == 0 and not result.stderr, (name, fixture, result.stderr)
                actual = output.read_bytes()
                expected = incoming if name == 'fixture_sink' else swapped
                assert actual == expected, (name, fixture, len(actual), len(expected))
                checks += 1
                print(f'PASS real ALSA {name}: {fixture}, exact ' + ('identity' if name == 'fixture_sink' else 'single stereo swap'))
    print(f'PASS {checks} independent playback captures; onboard UCM binding and capture scope checked')


if __name__ == '__main__':
    main()
