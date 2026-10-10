#!/usr/bin/env python3
"""Read-only onboard playback mapping gate for the supervised image trial.

The device entrypoint filters PipeWire data before emitting anything: no other
audio device or application identifiers are exported. This never opens a PCM,
changes profiles, changes volume, or plays sound.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


def inspect():
    objects = json.loads(subprocess.run(
        ['/run/current-system/sw/bin/pw-dump'], check=True, capture_output=True,
        text=True, timeout=8).stdout)
    sinks = []
    for item in objects:
        info = item.get('info', {})
        props = info.get('props', {})
        name = props.get('node.name', '')
        if (item.get('type') != 'PipeWire:Interface:Node'
                or props.get('media.class') != 'Audio/Sink'
                or not name.startswith('alsa_output.platform-sound.')):
            continue
        maps = [entry['channelMap'] for entry in info.get('params', {}).get('Props', [])
                if 'channelMap' in entry]
        position = props.get('audio.position')
        if isinstance(position, str):
            position = position.strip('[] ').replace(',', ' ').split()
        sinks.append(dict(id=item['id'], state=info.get('state'),
                          pcm=props.get('api.alsa.path'),
                          channels=int(props.get('audio.channels', 0)),
                          position=position, channel_maps=maps,
                          profile=props.get('device.profile.name')))
    if not sinks:
        raise RuntimeError('No onboard playback sink is present')
    for sink in sinks:
        if (sink['pcm'] != 'gemini_playback_ucm' or sink['channels'] != 2
                or sink['position'] != ['FL', 'FR']
                or not sink['channel_maps']
                or any(mapping != ['FL', 'FR'] for mapping in sink['channel_maps'])
                or sink['profile'] not in ('HiFi: Speaker: sink', 'HiFi: Headphones: sink')):
            raise RuntimeError('Onboard playback path or logical channel map differs')
    print(json.dumps(dict(schema=1, sinks=sinks), sort_keys=True))


def audio_evidence(runner, ssh, state, directory, system):
    out = directory / 'audio-playback-routing'
    out.mkdir(mode=0o700)
    files = ('asound.conf', 'gemini/audio-ucm-hifi.conf', 'gemini/audio-playback-inspect')
    hashes = {}
    resolved = {}
    for relative in files:
        artifact = (Path(system) / 'etc' / relative).resolve(strict=True)
        hashes[relative] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        resolved[relative] = str(artifact)
    script = 'set -eu\n'
    script += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
    script += 'test "$(readlink /run/current-system)" = ' + shlex.quote(system) + '\n'
    for relative, digest in hashes.items():
        script += 'test "$(sha256sum ' + shlex.quote('/etc/' + relative) + ' | cut -d\" \" -f1)" = ' + shlex.quote(digest) + '\n'
    script += '''uid=$(id -u gemini)
test -S /run/user/$uid/pipewire-0
env XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus \\
 runuser -u gemini -- /etc/gemini/audio-playback-inspect
'''
    raw = runner.persistence.run(ssh, script, out, 'mapping', timeout=20)
    observed = json.loads(raw)
    if observed.get('schema') != 1 or not observed.get('sinks'):
        raise RuntimeError('Incomplete onboard audio mapping evidence')
    record = dict(result='passed', scope='read-only effective onboard playback mapping',
                  boot_id=state['boot_id'], system=system,
                  candidate_configuration_sha256=hashes,
                  candidate_configuration_paths=resolved, observed=observed,
                  physical_orientation_qualified=False,
                  audible_playback_performed=False,
                  capture_and_other_devices_modified=False)
    runner.qualify.save(out, 'result.json', record)
    print('PASS: onboard PipeWire sink uses the corrected PCM with logical FL/FR; physical orientation pending', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] != ['--inspect']:
        sys.exit('Expected --inspect; this helper performs read-only inspection only')
    inspect()
