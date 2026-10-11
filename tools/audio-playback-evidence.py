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
    def position(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value.strip('[] ').replace(',', ' ').split()
        return value

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
        # The adapter's volume channelMap describes logical client channels.
        # ALSA exports the actual hardware order separately in Props.params.
        backend = [dict(zip(entry['params'][::2], entry['params'][1::2]))
                   for entry in info.get('params', {}).get('Props', [])
                   if isinstance(entry.get('params'), list)
                   and 'api.alsa.use-chmap' in entry['params']]
        sinks.append(dict(id=item['id'], state=info.get('state'),
                          pcm=props.get('api.alsa.path'),
                          channels=int(props.get('audio.channels', 0)),
                          position=position(props.get('audio.position')), channel_maps=maps,
                          hardware_positions=[position(entry.get('audio.position')) for entry in backend],
                          hardware_use_chmap=[entry.get('api.alsa.use-chmap') for entry in backend],
                          profile=props.get('device.profile.name')))
    print(json.dumps(dict(schema=1, sinks=sinks), sort_keys=True), flush=True)
    if not sinks:
        raise RuntimeError('No onboard playback sink is present')
    for sink in sinks:
        if (sink['pcm'] != 'hw:mt6797mt6351,0' or sink['channels'] != 2
                or sink['position'] != ['FR', 'FL']
                or not sink['channel_maps']
                or any(mapping != ['FL', 'FR'] for mapping in sink['channel_maps'])
                or sink['hardware_positions'] != [['FR', 'FL']]
                or sink['hardware_use_chmap'] != [False]
                or sink['profile'] not in ('HiFi: Speaker: sink', 'HiFi: Headphones: sink')):
            raise RuntimeError('Onboard playback transport or hardware channel order differs')


def audio_evidence(runner, ssh, state, directory, system):
    out = directory / 'audio-playback-routing'
    out.mkdir(mode=0o700)
    files = ('asound.conf', 'gemini/audio-ucm-hifi.conf',
             'systemd/user/wireplumber.service.d/overrides.conf')
    hashes = {}
    resolved = {}
    remote_paths = {}
    for relative in files:
        artifact = (Path(system) / 'etc' / relative).resolve(strict=True)
        hashes[relative] = hashlib.sha256(artifact.read_bytes()).hexdigest()
        resolved[relative] = str(artifact)
        remote_paths[relative] = '/etc/' + relative
    # NixOS supplies WirePlumber configuration through the unit's exact
    # XDG_DATA_DIRS, rather than /etc/wireplumber or the system profile.
    override = Path(resolved[files[-1]]).read_text()
    data_dirs = [value.removeprefix('XDG_DATA_DIRS=')
                 for line in override.splitlines() if line.startswith('Environment=')
                 for value in shlex.split(line.removeprefix('Environment='))
                 if value.startswith('XDG_DATA_DIRS=')]
    if len(data_dirs) != 1:
        raise RuntimeError('Candidate WirePlumber configuration search path is ambiguous')
    rules = [Path(path) / 'wireplumber/wireplumber.conf.d/51-gemini-playback-channels.conf'
             for path in data_dirs[0].split(':')]
    rules = [path.resolve(strict=True) for path in rules if path.is_file()]
    if len(rules) != 1:
        raise RuntimeError('Candidate onboard playback configuration is not unique')
    key = 'wireplumber-playback-rule'
    hashes[key] = hashlib.sha256(rules[0].read_bytes()).hexdigest()
    resolved[key] = remote_paths[key] = str(rules[0])
    script = 'set -eu\n'
    script += 'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + shlex.quote(state['boot_id']) + '\n'
    script += 'test "$(readlink /run/current-system)" = ' + shlex.quote(system) + '\n'
    for relative, digest in hashes.items():
        script += 'test "$(sha256sum ' + shlex.quote(remote_paths[relative]) + ' | cut -d\" \" -f1)" = ' + shlex.quote(digest) + '\n'
    script += '''uid=$(id -u gemini)
test -S /run/user/$uid/pipewire-0
python=$(systemctl show gemini-network-profiles.service -p ExecStart --value | sed -n 's/^{ path=\\([^ ;]*\\) ;.*$/\\1/p')
case "$python" in /nix/store/*/bin/python3) ;; *) exit 1 ;; esac
test -x "$python"
runuser -u gemini -- env XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus \\
 "$python" - --inspect <<'GEMINI_AUDIO_INSPECT_SOURCE'
'''
    script += Path(__file__).read_text() + '\nGEMINI_AUDIO_INSPECT_SOURCE\n'
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
    print('PASS: onboard PipeWire sink uses the native PCM with physical FR/FL mapping; audible orientation pending', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] != ['--inspect']:
        sys.exit('Expected --inspect; this helper performs read-only inspection only')
    inspect()
