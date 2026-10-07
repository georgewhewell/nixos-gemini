#!/usr/bin/env python3
"""Pinned archive upload and independent readback for the existing rescue runner."""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import time
from typing import NamedTuple

BUNDLE=Path(__file__).resolve().parents[2]/'handoff/gemini-efi-boot-files-publish'
ARCHIVE_SHA='3acf483171660dc96b373966ed80e1c2e36286149bec3c3715f1ca14550b36d7'
ARCHIVE_SIZE=20449280


class FilesProfile(NamedTuple):
    bundle: Path
    sha: str
    size: int
    count: int = 5

def default_profile():
    return FilesProfile(BUNDLE,ARCHIVE_SHA,ARCHIVE_SIZE)

def payload(profile=None):
    p=profile or default_profile()
    archive=p.bundle/'boot-files.tar'
    with archive.open('rb') as src:
        digest=hashlib.file_digest(src,'sha256').hexdigest()
    if archive.stat().st_size!=p.size or digest!=p.sha:
        raise RuntimeError('Boot-file archive differs from the pinned artifact')
    manifest=json.loads((p.bundle/'manifest.json').read_text())
    if manifest['archive']!={'sha256':p.sha,'size':p.size} or len(manifest['files'])!=p.count:
        raise RuntimeError('Boot-file manifest differs from the pinned archive')
    found={}
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            if not member.isfile() or not re.fullmatch(r'[A-Za-z0-9._/-]+',member.name) or member.name.startswith('/') or any(p in ('.','..','') for p in member.name.split('/')) or member.name in found:
                raise RuntimeError('Archive contains an unsafe or duplicate member')
            data=tf.extractfile(member).read()
            found[member.name]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    if found!=manifest['files']:
        raise RuntimeError('Boot-file archive members differ from the manifest')
    return archive,manifest


def marker(state,profile=None):
    p=profile or default_profile()
    return f'efi-files={state} sha256={p.sha} size={p.size}'


def upload_command(before, boot_sha, profile=None):
    p=profile or default_profile()
    if not re.fullmatch(r'[0-9a-f-]{36}',before['boot_id']) or not all(
            re.fullmatch('[0-9a-f]{64}',v) for v in (boot_sha,before['gpt_sha256'],p.sha)):
        raise ValueError('Boot-file upload requires exact boot and GPT identities')
    return f'''set -eu
umask 077
test "$(cat /proc/sys/kernel/random/boot_id)" != '{before['boot_id']}'
test "$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)" = '{boot_sha}'
test "$(head -c 32768 /dev/mmcblk0 | sha256sum | cut -d' ' -f1)" = '{before['gpt_sha256']}'
test "$(cat /sys/firmware/efi/fw_platform_size)" = 64
test "$(tr -d '\\000' < /sys/firmware/devicetree/base/chosen/gemini,uefi-storage-result)" = passed
test "$(cat /run/efi-boot-files.required)" = '{marker('required',p)}'
opts=$(awk '$1 == "/dev/mmcblk0p29" && $2 == "/mnt/gemian" && $3 == "ext4" {{print $4}}' /proc/mounts)
case ",$opts," in *,ro,*) ;; *) exit 1 ;; esac
test ! -e /run/efi-boot-files.upload && test ! -L /run/efi-boot-files.upload
test ! -e /run/efi-boot-files.ready && test ! -L /run/efi-boot-files.ready
(set -C; cat > /run/efi-boot-files.upload)
test "$(stat -c %s /run/efi-boot-files.upload)" = '{p.size}'
test "$(stat -c %h /run/efi-boot-files.upload)" = 1
test "$(sha256sum /run/efi-boot-files.upload | cut -d' ' -f1)" = '{p.sha}'
printf '%s\\n' '{marker('ready',p)}' > /run/efi-boot-files.ready
printf '%s\\n' 'Boot files uploaded to RAM; Stage 1 owns checked publication'
'''


def provision(ssh,before,boot_sha,directory,qualify,rescued,profile=None):
    p=profile or default_profile()
    archive,_=payload(p)
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        if rescued():
            raise RuntimeError('Automatic rescue ran before boot-file publication')
        try:
            state=qualify.run(ssh+['if test -s /run/efi-boot-files.verified; then cat /run/efi-boot-files.verified; '
                                  'elif test -s /run/efi-boot-files.required; then cat /run/efi-boot-files.required; fi']).strip()
        except subprocess.SubprocessError:
            time.sleep(3);continue
        if state==marker('verified',p):
            return
        if not state:
            time.sleep(3);continue
        if state!=marker('required',p):
            raise RuntimeError('Stage 1 requested different boot files: '+state)
        command=upload_command(before,boot_sha,p)
        (directory/'boot-files-upload.sh').write_text(command)
        print('Trusted Stage 1 requested the pinned boot files; uploading the archive to RAM',flush=True)
        with archive.open('rb') as src,(directory/'boot-files-upload.log').open('w') as log:
            subprocess.run(ssh+[command],stdin=src,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
        return
    raise RuntimeError('Stage 1 did not request the pinned boot files within 240s')


def evidence(ssh,boot_id,directory,qualify,require_verified=True,name='boot-files.json',profile=None,preserved=False):
    p=profile or default_profile()
    _,manifest=payload(p)
    command=['set -eu',"printf 'boot_id='; cat /proc/sys/kernel/random/boot_id",
             '''opts=$(awk '$1 == "/dev/mmcblk0p29" && $2 == "/gemian" && $3 == "ext4" {print $4}' /proc/mounts)''',
             '''case ",$opts," in *,ro,*) ;; *) exit 1 ;; esac''']
    if require_verified:
        if preserved:
            raise ValueError('Active publication must be verified at its original paths')
        command.append(f'test "$(cat /run/efi-boot-files.verified)" = {shlex.quote(marker("verified",p))}')
    for relative,info in manifest['files'].items():
        path=Path('/gemian')/relative
        for parent in reversed(path.parents):
            if str(parent)=='/':continue
            command.append(f'test -d {shlex.quote(str(parent))} && test ! -L {shlex.quote(str(parent))}')
        quoted=shlex.quote(str(path))
        command.append(f'file={quoted}')
        if preserved and relative in ('loader/loader.conf', 'EFI/systemd/systemd-bootaa64.efi'):
            backup=shlex.quote(str(path)+'.gemini-backup-'+info['sha256'])
            command.append(f'if test -f "$file" && test ! -L "$file" && '
                           f'test "$(sha256sum "$file" | cut -d\' \' -f1)" = {info["sha256"]}; '
                           f'then :; else file={backup}; fi')
        command += ['test -f "$file" && test ! -L "$file"',
                    f'test "$(stat -c %s "$file")" = {info["size"]}', 'sha256sum "$file"']
    rows=qualify.run(ssh+['\n'.join(command)]).splitlines()
    if not rows or rows[0]!='boot_id='+boot_id:
        raise RuntimeError('Boot-file evidence is not from the candidate boot')
    hashes={}
    locations={}
    for row in rows[1:]:
        sha,relative=row.split();relative=relative.removeprefix('/gemian/')
        original=relative
        if preserved and '.gemini-backup-' in relative:
            original,backup_sha=relative.rsplit('.gemini-backup-',1)
            if original not in ('loader/loader.conf','EFI/systemd/systemd-bootaa64.efi') or backup_sha != sha:
                raise RuntimeError('Unexpected boot-file backup')
        if original in hashes:
            raise RuntimeError('Duplicate boot-file evidence')
        hashes[original]=sha;locations[original]=relative
    if hashes!={name:info['sha256'] for name,info in manifest['files'].items()}:
        raise RuntimeError('Published boot files failed independent Linux readback')
    qualify.save(directory,name,dict(boot_id=boot_id,archive_sha256=p.sha,
                                                p29_read_only=True,files=manifest['files'],locations=locations))
