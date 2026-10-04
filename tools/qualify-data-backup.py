#!/usr/bin/env python3
"""Capture offline p32 data, verify its bytes/filesystem, and retain healthy M69.

Default is read-only preflight. --execute owns one bounded read-only DA session
in a durable host service. It never writes GPT, filesystem or boot partitions.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gpt_qualification', ROOT / 'tools/qualify-gpt-rewrite.py')
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
PACKAGE = Path('/nix/store/y65zyaa56fv5m08ra7hnjdj35g35a3kf-mtkclient-gemini-backup-2.1.4.1')
MTK = PACKAGE / 'bin/mtk'
LIB = PACKAGE / 'lib/python3.14/site-packages'
sys.path.insert(0, str(LIB))
b = q.module('data_backup', ROOT / 'nix/mtk-data-backup.py')
image_check = q.module('image_check', ROOT / 'tools/check-gemini-backup-image.py')
E2FSCK = image_check.E2FSCK
DA_TIMEOUT = 1500


def stage(directory, before, execute):
    directory.mkdir(mode=0o700)
    q.r.qualify.save(directory, 'before.json', before)
    for name in b.OUTPUTS: (directory / name).touch(exist_ok=False)
    for name, installed in (('mtk-data-backup.py', 'gemini_data_backup.py'),
                             ('mtk-gpt-rewrite.py', 'gemini_gpt_rewrite.py')):
        if (ROOT / 'nix' / name).read_bytes() != (LIB / 'mtkclient/Library' / installed).read_bytes():
            raise RuntimeError('Host and pinned DA module differ: ' + name)
    sources = directory / 'executed-sources'; sources.mkdir(mode=0o700)
    # Include all helper sources inherited from the qualified GPT observer.
    previous = json.loads((q.WORKSPACE / 'handoff/gpt-rewrite-01/plan.json').read_text())
    names = tuple(previous['executed_sources_sha256']) + ('tools/qualify-data-backup.py', 'nix/mtk-data-backup.py',
                                                         'tools/check-gemini-backup-image.py')
    hashes = {}
    for relative in names:
        raw = (ROOT / relative).read_bytes(); (sources / Path(relative).name).write_bytes(raw)
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    q.r.qualify.save(directory, 'plan.json', dict(mtk=str(MTK), execute=execute,
        device_writes_performed=False, filesystem_offset=b.DATA_OFFSET,
        filesystem_size=b.DATA_SIZE, da_timeout=DA_TIMEOUT, e2fsck=E2FSCK,
        executed_sources_sha256=hashes))
    q.preserved_files(before['boot_id'], directory, 'before')


def run_da(directory, before, writer_lock):
    logpath = directory / 'mtk.log'
    window = q.r.backend.BootWindow()
    window.observe(q.r.backend.usb_snapshot('3-2'), time.monotonic())
    command = ['sudo', '-n', 'env', 'PYTHONUNBUFFERED=1', 'timeout', '--foreground',
               '--kill-after=5s', str(DA_TIMEOUT) + 's', str(MTK), 'gemini-data-backup', str(directory)]
    q.r.qualify.save(directory, 'command.json', command)
    stopped = threading.Event(); monitor_errors = []
    error = None; rebooted = False
    def observe():
        try:
            while not stopped.is_set():
                window.acknowledged |= q.r.backend.ACK in logpath.read_text(errors='replace')
                window.observe(q.r.backend.usb_snapshot('3-2'), time.monotonic())
                stopped.wait(0.02)
        except Exception as caught: monitor_errors.append(caught)
    with logpath.open('w') as log:
        child = subprocess.Popen(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=writer_lock.fileno())
        monitor = threading.Thread(target=observe, daemon=True); monitor.start()
        try:
            ready_deadline = time.monotonic() + 20
            while child.poll() is None:
                if monitor_errors: raise monitor_errors[0]
                if not rebooted:
                    if 'Waiting for PreLoader' in logpath.read_text(errors='replace'):
                        if q.snapshot() != before: raise RuntimeError('Device changed before offline capture')
                        print('Read-only DA is ready; rebooting healthy M69 once', flush=True)
                        rebooted = True
                        q.r.reboot(q.SSH, directory, 'reboot-request.json')
                    elif time.monotonic() > ready_deadline:
                        raise RuntimeError('DA was not ready; Linux was not rebooted')
                time.sleep(0.05)
        except Exception as caught: error = caught
        finally:
            try:
                child.wait(timeout=DA_TIMEOUT + 10)
                deadline = time.monotonic() + 30
                while rebooted and not window.complete and not monitor_errors and time.monotonic() < deadline:
                    time.sleep(0.05)
            finally:
                stopped.set(); monitor.join(timeout=2)
    q.r.qualify.save(directory, 'usb-events.json', window.events)
    q.r.qualify.save(directory, 'mtk-exit.json', dict(returncode=child.returncode, reboot_requested=rebooted))
    error = error or (monitor_errors[0] if monitor_errors else None)
    if error: (directory / 'da-observer-error.txt').write_text(str(error) + '\n')
    if not rebooted: raise error or RuntimeError('DA exited before device access')
    return child.returncode, window, error


def verify_capture(directory, before, rc, window):
    result = json.loads((directory / 'backup-result.json').read_text())
    events = [json.loads(row) for row in (directory / 'backup-events.jsonl').read_text().splitlines()]
    if (rc != 0 or not window.complete or not window.acknowledged or
            result.get('schema') != 'gemini-offline-data-backup-v1' or
            any(result.get(key) is not True for key in ('qualified', 'capture_complete', 'original_layout_verified', 'reboot_acknowledged')) or
            result.get('device_writes_performed') is not False or result.get('events') != events):
        raise RuntimeError('Incomplete offline capture or reboot evidence')
    protected = {name: digest for name, _, _, digest in b.g.PROTECTED}
    protected['flashinfo'] = before['flashinfo_sha256']
    if result.get('protected_before') != protected or result.get('protected_after') != protected:
        raise RuntimeError('Protected boot images or flashinfo changed')
    guards = [('gpt-verified', 'primary'), ('gpt-verified', 'backup')]
    guards += [('protected-verified', name) for name, _, _, _ in b.g.PROTECTED]
    chunks = (b.DATA_SIZE + b.CHUNK - 1) // b.CHUNK
    chronology = guards + [('filesystem-admitted', None)] + [('chunk-captured', None)] * chunks
    chronology += [('capture-complete', None)] + guards + [('reboot', None)]
    if [(e.get('event'), e.get('name')) for e in events] != chronology or events[-1].get('acknowledged') is not True:
        raise RuntimeError('Offline capture chronology differs')
    expected = {'primary': (0, 32768, b.g.PRIMARY_SHA),
                'backup': (b.g.BACKUP_OFFSET, 33 * 512, b.g.BACKUP_SHA)}
    expected.update({name: (offset, size, protected[name]) for name, offset, size, _ in b.g.PROTECTED})
    for phase, group in (('before', events[:6]), ('after', events[-7:-1])):
        for e in group:
            if e.get('phase') != phase or tuple(e.get(k) for k in ('offset', 'size', 'sha256')) != expected[e['name']]:
                raise RuntimeError('Incorrect admission/return read evidence')
        for name in ('primary', 'backup'):
            raw = (directory / (name + '-' + phase + '.bin')).read_bytes()
            if len(raw) != expected[name][1] or b.g.sha(raw) != expected[name][2]:
                raise RuntimeError('Host GPT readback mismatch')
    digest = hashlib.sha256()
    with b.g.private_file(directory / 'data.ext4') as stream:
        if os.fstat(stream.fileno()).st_size != b.DATA_SIZE:
            raise RuntimeError('Incomplete offline filesystem image')
        stream.seek(1024); superblock = stream.read(1024); fs = b.extent(superblock); stream.seek(0)
        if (result.get('filesystem') != fs or events[6].get('superblock_sha256') != b.g.sha(superblock)
                or any(events[6].get(key) != value for key, value in fs.items())):
            raise RuntimeError('Filesystem extent or admission bytes differ')
        for e, offset in zip(events[7:7 + chunks], range(0, b.DATA_SIZE, b.CHUNK), strict=True):
            size = min(b.CHUNK, b.DATA_SIZE - offset); raw = stream.read(size)
            if e.get('offset') != offset or e.get('size') != size or len(raw) != size or e.get('sha256') != b.g.sha(raw):
                raise RuntimeError('Backup has a missing, reordered or changed chunk')
            digest.update(raw)
    if result.get('data_size') != b.DATA_SIZE or result.get('data_sha256') != digest.hexdigest():
        raise RuntimeError('Complete host filesystem digest differs')
    complete = events[7 + chunks]
    if complete.get('size') != b.DATA_SIZE or complete.get('sha256') != digest.hexdigest():
        raise RuntimeError('Capture completion differs from host image')
    tail = (directory / 'swap-header-before.bin').read_bytes()
    if len(tail) != 4096 or b.g.sha(tail) != result.get('swap_header_sha256'):
        raise RuntimeError('Original bytes at proposed swap start are incomplete')
    return dict(data_sha256=digest.hexdigest(), filesystem=fs, captured_chunks=chunks,
                swap_header_sha256=b.g.sha(tail))


def work(directory, execute):
    os.umask(0o077)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock', '.p22-flash-writer.lock'):
            handle = locks.enter_context((q.r.LOCKS / name).open('a')); fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        q.r.qualify.check_host_idle(); before = q.snapshot()
        usb = q.r.backend.usb_snapshot('3-2')
        if usb is None or usb[:2] != ('0525', 'a4a2'): raise RuntimeError('Wrong Gemini USB port')
        if shutil.disk_usage(directory.parent).free < 2 * b.DATA_SIZE + 1024**3:
            raise RuntimeError('Insufficient host space for raw and recovered offline copies')
        q.r.qualify.run(['sudo', '-n', 'true'])
        q.r.qualify.run([str(MTK), 'gemini-data-backup', '--help'])
        q.r.qualify.run([E2FSCK, '-V'])
        stage(directory, before, execute)
        if not execute:
            print('Backup preflight passed; no reboot or DA access: ' + str(directory)); return
        net = 'data-backup-net-' + str(os.getpid())
        q.r.qualify.save(directory, 'units.json', dict(worker=os.environ.get('GEMINI_BACKUP_UNIT'), network=net))
        q.r.unit(net, 2650, [shutil.which('sh'), directory / 'executed-sources/trex-gadget-net-watcher.sh',
                            directory / 'host-net.log', directory / 'host-net.state'])
        try:
            rc, window, error = run_da(directory, before, handle)
            print('DA session ended; checking automatic Linux return', flush=True)
            deadline = time.monotonic() + 360
            while time.monotonic() < deadline:
                try:
                    after = q.snapshot(); q.r.qualify.verify_return(before, after)
                    for key in ('p30_sha256', 'p31_sha256', 'backup_gpt_sha256', 'flashinfo_sha256'):
                        if after[key] != before[key]: raise RuntimeError('Protected data changed: ' + key)
                    break
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as caught:
                    (directory / 'last-health-error.txt').write_text(str(caught) + '\n'); time.sleep(3)
            else: raise RuntimeError('Healthy M69 did not return within 360 seconds')
            q.r.qualify.save(directory, 'after.json', after)
            q.r.qualify.run(['systemctl', '--user', 'stop', net])
            q.preserved_files(after['boot_id'], directory, 'after')
            retained = q.preserved_outputs(after['boot_id'], directory)
            if error: raise error
            print('Linux and retained data passed; checking the complete host image', flush=True)
            proof = verify_capture(directory, before, rc, window)
            recovered = image_check.check(directory, proof, b.extent)
            original = json.loads((q.WORKSPACE / 'handoff/data-persistence-02/persistence-before.json').read_text())
            files = {original['home']: original['content_sha256'],
                     '/nix/upper/' + Path(original['output']).name: original['content_sha256']}
            for trial in q.TRIALS:
                old = json.loads((q.WORKSPACE / 'handoff' / trial / 'nix-candidate.json').read_text())
                files['/nix/upper/' + Path(old['output']).name + '/proof'] = old['proof_sha256']
            recovered_files = image_check.verify_files(directory, files)
            q.r.qualify.check_host_idle()
            if q.snapshot() != after: raise RuntimeError('Device changed during final backup audit')
            q.r.qualify.save(directory, 'result.json', dict(result='passed', offline_backup_qualified=True,
                device_writes_performed=False, layout_changed=False, healthy_boot=after['boot_id'],
                ordinary_outputs_retained=retained, fsck_passed=True, locks_exclusively_held=True, no_writer=True,
                recovered_image=recovered, recovered_file_proofs=recovered_files, **proof))
            print('PASS: complete offline data backup, read-only fsck, fresh healthy M69 and all ten Nix outputs retained', flush=True)
        except Exception as error:
            q.r.qualify.save(directory, 'result.json', dict(result='failed', error=str(error), offline_backup_qualified=False))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(); directory = args.out.resolve()
    if args.worker:
        unit = os.environ.get('GEMINI_BACKUP_UNIT', '')
        if not re.fullmatch('data-backup-[0-9]+-[0-9]+', unit) or not os.environ.get('INVOCATION_ID'):
            raise RuntimeError('Backup execution requires its durable host service')
        if q.r.qualify.run(['systemctl', '--user', 'show', unit, '-p', 'MainPID', '--value']).strip() != str(os.getpid()):
            raise RuntimeError('Host service does not own the backup process')
        work(directory, True)
    elif args.execute:
        unit = 'data-backup-' + str(int(time.time())) + '-' + str(os.getpid())
        print('Starting durable offline-backup service ' + unit, flush=True)
        subprocess.run(['systemd-run', '--user', '--collect', '--wait', '--pipe', '--quiet', '--unit=' + unit,
            '--property=RuntimeMaxSec=2700', '--setenv=PATH=' + os.environ['PATH'],
            '--setenv=GEMINI_BACKUP_UNIT=' + unit, sys.executable, str(Path(__file__).resolve()),
            '--worker', '--out', str(directory)], check=True)
    else: work(directory, False)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: sys.exit(str(error))
