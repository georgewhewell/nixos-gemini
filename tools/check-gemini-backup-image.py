#!/usr/bin/env python3
"""Replay an offline ext4 journal in a private host copy, preserving raw bytes."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

E2FSCK = '/nix/store/wjvj88kk8gv0742k1lwazpxr7lnzgi1a-e2fsprogs-1.47.4-bin/bin/e2fsck'


def verify_files(directory, expected):
    """Read known persistence proofs from the recovered image without mounting it."""
    directory = Path(directory)
    if any(not re.fullmatch(r'/[A-Za-z0-9_./-]+', name) or
           not re.fullmatch('[0-9a-f]{64}', digest) for name, digest in expected.items()):
        raise ValueError('Invalid image proof path or digest')
    observed = {}
    for name, digest in expected.items():
        result = subprocess.run([str(Path(E2FSCK).with_name('debugfs')), '-R', 'cat ' + name,
                                 str(directory / 'data-recovered.ext4')],
                                capture_output=True, timeout=20, check=True)
        if len(result.stdout) > 4096 or hashlib.sha256(result.stdout).hexdigest() != digest:
            raise RuntimeError('Recovered image lacks expected proof bytes: ' + name)
        observed[name] = digest
    (directory / 'image-file-proofs.json').write_text(json.dumps(observed, indent=2) + '\n')
    return observed


def check(directory, expected, extent):
    directory = Path(directory)
    raw = directory / 'data.ext4'
    recovered = directory / 'data-recovered.ext4'
    source_fd = os.open(raw, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(source_fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != expected['filesystem']['size']:
            raise RuntimeError('Offline image is not the complete private regular file')
        source.seek(1024); original_extent = extent(source.read(1024)); source.seek(0)
        if original_extent != expected['filesystem']:
            raise RuntimeError('Raw filesystem identity changed before host recovery')
        fd = os.open(recovered, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        digest = hashlib.sha256()
        with os.fdopen(fd, 'wb') as destination:
            while chunk := source.read(16 * 1024 * 1024):
                destination.write(chunk); digest.update(chunk)
            destination.flush(); os.fsync(destination.fileno())
        if digest.hexdigest() != expected['data_sha256']:
            raise RuntimeError('Raw offline image changed before host recovery')
        os.fchmod(source.fileno(), 0o400)
    commands = [
        [E2FSCK, '-p', '-E', 'journal_only', str(recovered)],
        [E2FSCK, '-f', '-n', str(recovered)],
    ]
    codes = []
    (directory / 'fsck-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    for index, command in enumerate(commands):
        with (directory / ('fsck-' + str(index) + '.log')).open('w') as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        codes.append(completed.returncode)
        (directory / 'fsck-status.json').write_text(json.dumps(dict(returncodes=codes)) + '\n')
        if completed.returncode not in ((0, 1) if index == 0 else (0,)):
            raise RuntimeError('Host journal replay or read-only filesystem check failed; retain both images')
    with raw.open('rb') as source:
        raw_sha = hashlib.file_digest(source, 'sha256').hexdigest()
    with recovered.open('rb') as source:
        source.seek(1024); recovered_extent = extent(source.read(1024)); source.seek(0)
        recovered_sha = hashlib.file_digest(source, 'sha256').hexdigest()
    if raw_sha != expected['data_sha256']:
        raise RuntimeError('Original offline bytes changed during host recovery')
    if (not recovered_extent['clean'] or recovered_extent['needs_recovery'] or
            any(recovered_extent[k] != original_extent[k] for k in ('uuid', 'block_count', 'block_size', 'size'))):
        raise RuntimeError('Recovered filesystem identity or clean state differs')
    recovered.chmod(0o400)
    result = dict(raw_sha256=raw_sha, recovered_sha256=recovered_sha,
                  raw_preserved=True, journal_replayed_in_host_copy_only=True,
                  readonly_fsck_passed=True, recovered_filesystem=recovered_extent,
                  fsck_returncodes=codes)
    (directory / 'fsck-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
