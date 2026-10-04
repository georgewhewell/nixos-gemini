#!/usr/bin/env python3
"""Pinned daemon/sandbox trial; the shared p22 supervisor owns every reboot."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import uuid

WORKSPACE=Path(__file__).resolve().parents[2]
BUNDLE=WORKSPACE/'handoff/persistent-nix-candidate'
SYSTEM='/nix/store/hqkwklfldn7sfw1bj7xxbdhq5c2namif-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade'
KERNEL=Path('/nix/store/j0h3y2s1yal2sc7v1026c5hp0vn45xry-gemini-mainline-efi-nix-kernel-7.1.3')
BOOT_SHA='0cd222881c2dcc56d8da25f54903f70cf4d93475bc591175251403ba971be50e'
STORE_SHA='a55afc6b3ad2816a04b92659755982314195093707714ebc169e0bc8ce597d9d'
STORE_SIZE=426987520
OLD_PROOF=WORKSPACE/'handoff/data-persistence-02/persistence-before.json'
OLD_CONTENT='f6060daac54edc95a47230072c20e6752f6b09306f3ddf8959a3fc917c9effdd'
SYSTEMD='/nix/store/wmxjss8gx93bnz0bcj3si4gqrxl25p72-systemd-minimal-aarch64-unknown-linux-gnu-253.6/bin'


EFI_ENTRY='gemini-9c1bfbbbb260cf5830de42c587ea599cfbad29749ee66c61c65d2caf6caff999.conf'
OLD_LOADER_SHA='9547db8cf45f9d032c9792411c7f06bbde375e7b9f620deea6c09740b4d34266'

def store_profile(provisioner,require_efi=False):
    return provisioner.StoreProfile(BUNDLE,SYSTEM,STORE_SHA,STORE_SIZE,require_efi)

def files_profile(files):
    return files.FilesProfile(WORKSPACE/'handoff/nix-efi-candidates',
        '4d98df6ccc325f7f1354ca85a66bb6d8f02dad94b586c64301bce4e7a0f1bc0f',20449280)

def activation_evidence(ssh,boot_id,directory,qualify,persistence,name='previous-efi-files',previous_files=None,previous_sha=OLD_LOADER_SHA):
    # Retain the previous manager entry/payload and its checked default backup.
    p=WORKSPACE/'handoff/gemini-efi-boot-files-publish/manifest.json'
    old=previous_files if previous_files is not None else json.loads(p.read_text())['files']
    if not re.fullmatch('[0-9a-f]{64}',previous_sha) or old['loader/loader.conf']['sha256']!=previous_sha:
        raise ValueError('Previous loader configuration is not pinned')
    commands=['set -eu',f'test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}']
    for relative,info in old.items():
        if relative=='loader/loader.conf':relative+='.gemini-backup-'+previous_sha
        path='/gemian/'+relative
        for parent in reversed(Path(path).parents):
            if str(parent)!='/':commands.append(f'test -d {parent} && test ! -L {parent}')
        commands += [f'test -f {path} && test ! -L {path}',
                     f'test "$(stat -c %s {path})" = {info["size"]}',
                     f'test "$(sha256sum {path} | cut -d\' \' -f1)" = {info["sha256"]}']
    persistence.run(ssh,'\n'.join(commands),directory,name)
    qualify.save(directory,name+'.json',dict(boot_id=boot_id,old_entry_and_payload_retained=True,
                                                        previous_default_backup_sha256=previous_sha))


def old_persistence(ssh, boot_id, directory, qualify, persistence, system, name):
    old=json.loads(OLD_PROOF.read_text())
    if old['content_sha256']!=OLD_CONTENT or old['build_type']!='fixed-output':
        raise RuntimeError('Original M69 persistence evidence changed')
    target=directory/name;target.mkdir(mode=0o700)
    return persistence.evidence(ssh,boot_id,target,qualify,previous=old,system=system)


def verify_builder(evidence, token, host_net, daemon_net):
    if evidence.get('token')!=token or evidence.get('outside_home')!='absent':
        raise RuntimeError('Build token or filesystem sandbox differs')
    if not evidence.get('uid','').isdecimal() or int(evidence['uid'])==0:
        raise RuntimeError('Builder did not run as a non-root identity')
    net=evidence.get('net','')
    if not re.fullmatch(r'net:\[\d+\]',net) or net in (host_net,daemon_net):
        raise RuntimeError('Builder did not receive its own network namespace')


def evidence(ssh, boot_id, directory, qualify, persistence, require_efi=False):
    old_persistence(ssh,boot_id,directory,qualify,persistence,SYSTEM,'candidate-old-persistence')
    config_sha=hashlib.sha256((KERNEL/'kernel.config').read_bytes()).hexdigest()
    efi_guard='test "$(cat /sys/firmware/efi/fw_platform_size)" = 64' if require_efi else 'test ! -e /sys/firmware/efi'
    raw=persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(readlink /run/current-system)" = {SYSTEM}
test "$(zcat /proc/config.gz | sha256sum | cut -d' ' -f1)" = {config_sha}
{efi_guard}
test "$(cat /sys/devices/system/cpu/cpu8/online)" = 1
test "$(cat /sys/devices/system/cpu/cpu9/online)" = 1
dmesg | grep -F 'arm64-late-cpu-profile: verified the pre-finalization runtime identity binding' >/dev/null
dmesg | grep -F 'arm64-late-cpu-profile: mt6797-a53-a72-a41-v7 ready' >/dev/null
grep -qx 'sandbox = true' /etc/nix/nix.conf
grep -qx 'sandbox-fallback = false' /etc/nix/nix.conf
systemctl is-active nix-daemon.socket gemini-nix-db-seed >/dev/null
systemctl start nix-daemon.service
systemctl is-active nix-daemon.service >/dev/null
pid=$(systemctl show nix-daemon.service -p MainPID --value)
test "$pid" -gt 1
printf 'daemon_pid=%s\\n' "$pid"
printf 'host_net='; readlink /proc/1/ns/net
printf 'daemon_net='; readlink /proc/"$pid"/ns/net
printf 'client_uid='; id -u gemini
''',directory,'nix-candidate-state')
    state=dict(line.split('=',1) for line in raw.splitlines())
    if not state['client_uid'].isdecimal() or int(state['client_uid'])==0:
        raise RuntimeError('Gemini client is not an unprivileged account')
    token=uuid.uuid4().hex
    home='/home/gemini/.gemini-daemon-build-'+token
    output_link=home+'/result'
    script=f'''set -eu
export PATH={persistence.BUSYBOX}/bin
test "$(id -u)" != 0
test ! -e /home/gemini
net=$(readlink /proc/self/ns/net)
test "$net" != {shlex.quote(state['host_net'])}
test "$net" != {shlex.quote(state['daemon_net'])}
mkdir "$out"
printf 'token=%s\\nuid=%s\\nnet=%s\\noutside_home=absent\\n' {token} "$(id -u)" "$net" > "$out/proof"
'''
    expr=('builtins.derivation { name = "gemini-daemon-'+token+'"; system = "aarch64-linux"; '
          'builder = (builtins.storePath '+json.dumps(persistence.BUSYBOX)+') + "/bin/sh"; '
          'args = [ "-c" '+json.dumps(script)+' ]; }')
    client=f'''set -eu
test "$(id -un)" = gemini
mkdir -m 0700 {home}
{persistence.NIX}/nix-build --store daemon --out-link {output_link} --option substituters '' --option builders '' --expr {shlex.quote(expr)}
'''
    command=f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
{SYSTEMD}/systemd-run --quiet --wait --pipe --collect --unit=gemini-nix-build-{token} --uid=gemini --gid=users --property=WorkingDirectory=/home/gemini --setenv=HOME=/home/gemini --setenv=PATH={persistence.BUSYBOX}/bin:{persistence.NIX} {persistence.BUSYBOX}/bin/sh -c {shlex.quote(client)}
'''
    output=persistence.run(ssh,command,directory,'nix-unprivileged-build').strip()
    if not re.fullmatch('/nix/store/[0-9a-z]{32}-gemini-daemon-'+token,output):
        raise RuntimeError('Unexpected daemon build output')
    raw=persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(readlink {output_link})" = {output}
test "$(stat -c %U:%G {home})" = gemini:users
cat {output}/proof
''',directory,'nix-builder-proof')
    builder=dict(line.split('=',1) for line in raw.splitlines())
    verify_builder(builder,token,state['host_net'],state['daemon_net'])
    result=dict(boot_id=boot_id,token=token,output=output,output_link=output_link,
                builder=builder,state=state,proof_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                ordinary_daemon_build_qualified=True,unprivileged_client=True)
    verify_retained(ssh,boot_id,directory,qualify,persistence,result,name='nix-build-before')
    qualify.save(directory,'nix-candidate.json',result)
    return result


def verify_retained(ssh, boot_id, directory, qualify, persistence, previous, name='nix-build-after'):
    raw=persistence.run(ssh,f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
test "$(readlink {previous['output_link']})" = {previous['output']}
{persistence.NIX}/nix-store --check-validity {previous['output']}
printf 'proof_sha256='; sha256sum {previous['output']}/proof | cut -d' ' -f1
printf 'nix_hash='; {persistence.NIX}/nix-store --query --hash {previous['output']}
printf 'deriver='; {persistence.NIX}/nix-store --query --deriver {previous['output']}
sync
''',directory,name)
    observed=dict(line.split('=',1) for line in raw.splitlines())
    if observed['proof_sha256']!=previous['proof_sha256']:
        raise RuntimeError('Ordinary build output changed')
    if not re.fullmatch(r'/nix/store/[0-9a-z]{32}-gemini-daemon-'+previous['token']+r'\.drv',observed['deriver']):
        raise RuntimeError('Ordinary build derivation not registered')
    if 'registered' in previous and observed!=previous['registered']:
        raise RuntimeError('Ordinary build database records changed')
    previous['registered']=observed
    qualify.save(directory,name+'.json',dict(boot_id=boot_id,**observed))


def after_recovery(ssh, boot_id, directory, qualify, persistence):
    old_persistence(ssh,boot_id,directory,qualify,persistence,qualify.ACCEPTED_SYSTEM,'recovered-old-persistence')
    before=json.loads((directory/'nix-candidate.json').read_text())
    if boot_id==before['boot_id']:raise RuntimeError('Ordinary build checked without a fresh rescue boot')
    verify_retained(ssh,boot_id,directory,qualify,persistence,before)
    qualify.save(directory,'nix-recovered.json',dict(boot_id=boot_id,ordinary_output_retained=True,
                                                   original_persistence_retained=True))
