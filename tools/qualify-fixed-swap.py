#!/usr/bin/env python3
"""Install fixed swap with verified factory restoration and reboot persistence.

Default is read-only preflight. --execute uses independent durable worker and
rescue services. The rescue service restores the factory layout if the worker
exits without a fully verified commit, including unexpected worker death.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gpt', ROOT / 'tools/qualify-gpt-rewrite.py')
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)
PACKAGE = Path('/nix/store/n4p7mz68zms2m6pawpwfbrs1sbdjq4vs-mtkclient-gemini-swap-2.1.4.1')
LIB = PACKAGE / 'lib/python3.14/site-packages'; MTK = PACKAGE / 'bin/mtk'
sys.path.insert(0, str(LIB))
from mtkclient.Library import gemini_fixed_swap as s

PARTUUID = '5e0f3a1c-9b2d-4c8e-a7f6-2d1b0c9e8a71'
SWAP_UUID = '85ae0e4c-91cb-4b97-a960-fc6780f42361'
BACKUP = q.WORKSPACE / 'handoff/data-backup-02'
RESTORE_PROOF = q.WORKSPACE / 'handoff/fixed-swap-01'
OLD_GUARD = 'test "$(cat /sys/class/block/mmcblk0p32/size)" = 32737247\ntest ! -e /sys/class/block/mmcblk0p34'
GEOMETRY = {
    'factory': (s.g.PRIMARY_SHA, s.g.BACKUP_SHA, s.OLD_HEADER_SHA, 32737247),
    'swap': (s.SWAP_PRIMARY_SHA, s.SWAP_BACKUP_SHA, s.SWAP_HEADER_SHA, 22249472),
}


def script(layout, healthy=True):
    if layout not in GEOMETRY: raise ValueError('Unidentified storage layout')
    base = q.r.qualify.SNAPSHOT
    if base.count(OLD_GUARD) != 1: raise RuntimeError('Legacy snapshot geometry changed; review the adapter')
    geometry = f'test "$(cat /sys/class/block/mmcblk0p32/size)" = {GEOMETRY[layout][3]}\n'
    if layout == 'swap':
        geometry += f'''test "$(cat /sys/class/block/mmcblk0p34/start)" = 111622144
test "$(cat /sys/class/block/mmcblk0p34/size)" = 10485760
test "$(readlink -f /dev/disk/by-partuuid/{PARTUUID})" = /dev/mmcblk0p34
'''
    else: geometry += 'test ! -e /sys/class/block/mmcblk0p34\n'
    base = base.replace(OLD_GUARD, geometry)
    if not healthy:
        for line in ("grep -qx 'unattended_recovery=healthy' /run/unattended-recovery.accepted",
                     'systemctl is-active gemini-desktop gemini-jpeg gemini-gpu gemini-wifi gemini-audio >/dev/null',
                     'test -z "$(systemctl --failed --no-legend --plain)"'):
            base = base.replace(line, ':')
        base = base.replace("printf 'healthy=yes\\n'", "printf 'healthy=unchecked\\n'")
    return base + f'''
test "$(cat /sys/class/block/mmcblk0p32/start)" = 89372672
test "$(cat /sys/class/block/mmcblk0p33/start)" = 122109919
test "$(cat /sys/class/block/mmcblk0p33/size)" = 32768
test "$(sed -n 's/^AllowHibernation=//p' /etc/systemd/sleep.conf)" = false
test "$(sed -n 's/^AllowSuspendThenHibernate=//p' /etc/systemd/sleep.conf)" = false
printf 'backup_gpt_sha256='; dd if=/dev/mmcblk0 bs=512 skip=122142687 count=33 status=none | sha256sum | cut -d' ' -f1
printf 'swap_header_sha256='; dd if=/dev/mmcblk0 bs=512 skip=111622144 count=8 status=none | sha256sum | cut -d' ' -f1
printf 'p30_sha256='; sha256sum /dev/mmcblk0p30 | cut -d' ' -f1
printf 'p31_sha256='; sha256sum /dev/mmcblk0p31 | cut -d' ' -f1
printf 'flashinfo_sha256='; sha256sum /dev/mmcblk0p33 | cut -d' ' -f1
'''


def snapshot(layout, healthy=True):
    state = dict(row.split('=', 1) for row in q.r.qualify.run(q.SSH + [script(layout, healthy)]).splitlines())
    expected = dict(system=q.r.qualify.ACCEPTED_SYSTEM, boot_sha256=q.r.qualify.ACCEPTED_BOOT,
                    gpt_sha256=GEOMETRY[layout][0], backup_gpt_sha256=GEOMETRY[layout][1],
                    swap_header_sha256=GEOMETRY[layout][2], p30_sha256=q.r.P30_SHA, p31_sha256=q.r.P31_SHA,
                    healthy='yes' if healthy else 'unchecked')
    if any(state.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Linux does not match the exact requested layout and M69 identity')
    if not re.fullmatch('[0-9a-f-]{36}', state.get('boot_id', '')) or not re.fullmatch('[0-9a-f]{64}', state.get('flashinfo_sha256', '')):
        raise RuntimeError('Missing boot or flashinfo identity')
    return dict(state, layout=layout)


def healthy_return(directory, layout, previous):
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        try:
            after = snapshot(layout)
            if after['boot_id'] == previous['boot_id']: raise RuntimeError('Original boot still running')
            if after['flashinfo_sha256'] != previous['flashinfo_sha256']: raise RuntimeError('Flashinfo changed')
            q.r.qualify.save(directory, 'after.json', after); return after
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            (directory / 'last-health-error.txt').write_text(str(error) + '\n'); time.sleep(3)
    raise RuntimeError('Fresh healthy M69 did not return with layout ' + layout)


def swap_evidence(directory, state):
    raw = q.r.persistence.run(q.SSH, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
printf 'blkid='; blkid /dev/mmcblk0p34
printf 'page_kib='; awk '/^KernelPageSize:/ {{print $2; exit}}' /proc/1/smaps
cat /proc/swaps
''', directory, 'swap-state')
    lines = raw.splitlines()
    if len(lines) != 4 or lines[1] != 'page_kib=4' or not lines[0].startswith('blkid='):
        raise RuntimeError('Unexpected swap count or kernel page size')
    identity = shlex.split(lines[0].removeprefix('blkid='))
    metadata = dict(row.split('=',1) for row in identity[1:])
    if identity[:1] != ['/dev/mmcblk0p34:'] or any(metadata.get(k) != v for k,v in {'UUID':SWAP_UUID,'TYPE':'swap','LABEL':'gemini-swap'}.items()):
        raise RuntimeError('Swap filesystem identity differs')
    fields = lines[3].split()
    if len(fields) != 5 or fields[:3] != ['/dev/mmcblk0p34', 'partition', '5242876'] or not fields[3].isdigit():
        raise RuntimeError('Fixed swap is not active with the exact usable size')
    result = dict(boot_id=state['boot_id'], active=True, device=fields[0], usable_kib=int(fields[2]),
                  used_kib=int(fields[3]), page_size=4096, uuid=SWAP_UUID, partuuid=PARTUUID)
    q.r.qualify.save(directory, 'swap-active.json', result); return result


def retained(directory, state):
    q.preserved_files(state['boot_id'], directory, 'after')
    outputs = q.preserved_outputs(state['boot_id'], directory)
    if snapshot(state['layout']) != state: raise RuntimeError('Device changed during data-retention checks')
    return outputs


def copy_inputs(directory):
    directory.mkdir(mode=0o700)
    sources = {
        'primary-factory.bin': BACKUP / 'primary-before.bin',
        'backup-factory.bin': BACKUP / 'backup-before.bin',
        'primary-swap.bin': q.WORKSPACE / 'handoff/fixed-swap-plan-01/prepared/primary-gpt.bin',
        'backup-swap.bin': q.WORKSPACE / 'handoff/fixed-swap-plan-01/prepared/backup-gpt.bin',
        'header-factory.bin': BACKUP / 'swap-header-before.bin',
        'header-swap.bin': q.WORKSPACE / 'handoff/fixed-swap-header-01/swap-header.bin',
    }
    for name, source in sources.items():
        with (directory / name).open('xb') as output: output.write(source.read_bytes())
        (directory / name).chmod(0o400)
    for name in s.OUTPUTS: (directory / name).touch(exist_ok=False)
    s.inputs(directory)


def prior_restoration():
    """Reuse the completed independent rescue, not the rejected install profile."""
    result=json.loads((RESTORE_PROOF/'rescue-result.json').read_text())
    after=json.loads((RESTORE_PROOF/'emergency-restore/after.json').read_text())
    before=json.loads((RESTORE_PROOF/'before.json').read_text())
    if (result.get('result')!='restored' or result.get('factory_restored') is not True or
            set(result.get('ordinary_outputs_retained',{}))!=set(q.TRIALS) or
            result.get('healthy_boot')!=after.get('boot_id') or after.get('healthy')!='yes' or
            after.get('layout')!='factory' or after.get('boot_id')==before.get('boot_id')):
        raise RuntimeError('Prior complete hardware restoration evidence is missing')
    required=dict(system=q.r.qualify.ACCEPTED_SYSTEM,boot_sha256=q.r.qualify.ACCEPTED_BOOT,
                  gpt_sha256=GEOMETRY['factory'][0],backup_gpt_sha256=GEOMETRY['factory'][1],
                  swap_header_sha256=GEOMETRY['factory'][2],p30_sha256=q.r.P30_SHA,p31_sha256=q.r.P31_SHA,
                  flashinfo_sha256=before['flashinfo_sha256'])
    if any(after.get(key)!=value for key,value in required.items()):
        raise RuntimeError('Prior rescue did not restore the exact factory identity')
    out=RESTORE_PROOF/'emergency-restore'
    window=q.r.backend.BootWindow()
    window.acknowledged=q.r.backend.ACK in (out/'mtk.log').read_text(errors='replace')
    for event in json.loads((out/'usb-events.json').read_text()):
        window.observe(tuple(event['usb']) if event['usb'] is not None else None,event['monotonic'])
    da=verify_da(out,before,'factory',json.loads((out/'mtk-exit.json').read_text())['returncode'],window)
    if da.get('initial_state')!={'primary':'swap','backup':'swap','header':'swap'}:
        raise RuntimeError('Prior rescue did not start from the installed swap layout')
    plan=json.loads((RESTORE_PROOF/'plan.json').read_text())
    for relative,digest in plan['executed_sources_sha256'].items():
        if hashlib.sha256((RESTORE_PROOF/'executed-sources'/Path(relative).name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Prior rescue execution archive changed')
    return dict(directory=str(RESTORE_PROOF),restored_boot=after['boot_id'],complete_restore_verified=True,
                result_sha256=hashlib.sha256((RESTORE_PROOF/'rescue-result.json').read_bytes()).hexdigest())


def stage(directory, before, execute):
    directory.mkdir(mode=0o700); q.r.qualify.save(directory, 'before.json', before)
    restoration=prior_restoration()
    q.r.qualify.save(directory,'prior-restoration.json',restoration)
    for phase in ('install-01', 'emergency-restore'): copy_inputs(directory / phase)
    (directory / 'reboot-check').mkdir(mode=0o700)
    previous = json.loads((BACKUP / 'result.json').read_text())
    if (previous.get('result') != 'passed' or previous.get('offline_backup_qualified') is not True or
            previous.get('fsck_passed') is not True or len(previous.get('recovered_file_proofs', {})) != 12):
        raise RuntimeError('Verified offline data backup is missing')
    for name, digest in (('data.ext4', previous['data_sha256']),
                         ('data-recovered.ext4', previous['recovered_image']['recovered_sha256'])):
        with s.g.private_file(BACKUP / name) as image:
            if os.fstat(image.fileno()).st_size != s.b.DATA_SIZE or hashlib.file_digest(image, 'sha256').hexdigest() != digest:
                raise RuntimeError('Offline backup changed: ' + name)
    for local, packaged in (('mtk-fixed-swap.py', 'gemini_fixed_swap.py'),
                            ('mtk-data-backup.py', 'gemini_data_backup.py'), ('mtk-gpt-rewrite.py', 'gemini_gpt_rewrite.py')):
        if (ROOT / 'nix' / local).read_bytes() != (LIB / 'mtkclient/Library' / packaged).read_bytes():
            raise RuntimeError('Pinned transition package differs from reviewed source')
    sources = directory / 'executed-sources'; sources.mkdir(mode=0o700)
    base = json.loads((q.WORKSPACE / 'handoff/gpt-rewrite-01/plan.json').read_text())
    names = tuple(base['executed_sources_sha256']) + ('tools/qualify-fixed-swap.py', 'nix/mtk-fixed-swap.py', 'nix/mtk-data-backup.py')
    hashes = {}
    for name in names:
        raw = (ROOT / name).read_bytes(); (sources / Path(name).name).write_bytes(raw); hashes[name] = hashlib.sha256(raw).hexdigest()
    q.r.qualify.save(directory, 'plan.json', dict(mtk=str(MTK), execute=execute,
        sequence=['install', 'normal-reboot'],qualified_prior_restoration=restoration,
        original_backup=str(BACKUP), raw_backup_sha256=previous['data_sha256'],
        executed_sources_sha256=hashes, automatic_failure_action='restore-factory-gpt-and-header'))
    q.preserved_files(before['boot_id'], directory, 'before')


def run_da(directory, writer_lock, before=None, restore=False):
    timeout = 900 if before is None else 180
    command = ['sudo', '-n', 'env', 'PYTHONUNBUFFERED=1', 'timeout', '--foreground', '--kill-after=5s',
               str(timeout) + 's', str(MTK), 'gemini-fixed-swap', str(directory)]
    if restore: command.append('--restore')
    q.r.qualify.save(directory, 'command.json', command)
    logpath = directory / 'mtk.log'; stopped = threading.Event(); monitor_errors = []
    window = q.r.backend.BootWindow(); window.observe(q.r.backend.usb_snapshot('3-2'), time.monotonic())
    error = None; ready = False; rebooted = False
    def monitor():
        try:
            while not stopped.is_set():
                window.acknowledged |= q.r.backend.ACK in logpath.read_text(errors='replace')
                window.observe(q.r.backend.usb_snapshot('3-2'), time.monotonic()); stopped.wait(0.02)
        except Exception as caught: monitor_errors.append(caught)
    with logpath.open('w') as log:
        child = subprocess.Popen(command, cwd=directory, stdin=writer_lock.fileno(), stdout=log, stderr=subprocess.STDOUT)
        thread = threading.Thread(target=monitor, daemon=True); thread.start()
        try:
            deadline = time.monotonic() + 20
            while child.poll() is None:
                if monitor_errors: raise monitor_errors[0]
                if not ready:
                    if 'Waiting for PreLoader' in logpath.read_text(errors='replace'):
                        ready = True
                        if before is not None:
                            if snapshot(before['layout']) != before: raise RuntimeError('Device changed before transition')
                            rebooted = True; q.r.reboot(q.SSH, directory, 'reboot-request.json')
                        else:
                            # Rescue may start during an existing watchdog boot
                            # window. Reboot only an identified M69 instance.
                            try:
                                identity = q.r.qualify.run(q.SSH + ['readlink /run/current-system; sha256sum /dev/mmcblk0p22']).splitlines()
                                if len(identity) == 2 and identity[0] == q.r.qualify.ACCEPTED_SYSTEM and identity[1].split()[0] == q.r.qualify.ACCEPTED_BOOT:
                                    rebooted = True; q.r.reboot(q.SSH, directory, 'reboot-request.json')
                            except subprocess.SubprocessError: pass
                    elif time.monotonic() > deadline: raise RuntimeError('DA did not become ready')
                time.sleep(0.05)
        except Exception as caught: error = caught
        finally:
            try:
                child.wait(timeout=timeout + 10)
                deadline = time.monotonic() + 30
                while not window.complete and not monitor_errors and time.monotonic() < deadline: time.sleep(0.05)
            finally: stopped.set(); thread.join(timeout=2)
    q.r.qualify.save(directory, 'usb-events.json', window.events)
    q.r.qualify.save(directory, 'mtk-exit.json', dict(returncode=child.returncode, reboot_requested=rebooted))
    error = error or (monitor_errors[0] if monitor_errors else None)
    if error: (directory / 'observer-error.txt').write_text(str(error) + '\n')
    return child.returncode, window, error


def verify_da(directory, before, target, rc, window):
    result = json.loads((directory / 'swap-result.json').read_text())
    events = [json.loads(row) for row in (directory / 'swap-events.jsonl').read_text().splitlines()]
    if (rc != 0 or not window.complete or not window.acknowledged or
            result.get('schema') != 'gemini-fixed-swap-v1' or result.get('target') != target or
            result.get('final_layout') != target or result.get('events') != events or
            any(result.get(k) is not True for k in ('operation_qualified', 'write_attempted', 'reboot_acknowledged')) or
            result.get('rollback_attempted') is not False):
        raise RuntimeError('Transition lacks complete acknowledged writes and reboot')
    files = {name: (directory / name).read_bytes() for name, _, _ in s.INPUTS}
    if any(len(files[name]) != size or s.g.sha(files[name]) != digest for name,size,digest in s.INPUTS):
        raise RuntimeError('Transition input artifacts no longer match the reviewed bytes')
    files['primary-swap.bin'] += files['primary-factory.bin'][34*512:]
    protected = {name: digest for name, _, _, digest in s.g.PROTECTED}; protected['flashinfo'] = before['flashinfo_sha256']
    if result.get('protected_before') != protected or result.get('protected_after') != protected:
        raise RuntimeError('Protected images changed')
    sb = (directory / 'superblock-before.bin').read_bytes()
    if s.b.extent(sb) != result.get('filesystem') or (directory / 'superblock-after.bin').read_bytes() != sb:
        raise RuntimeError('Persistent filesystem extent or superblock changed')
    initial = result.get('initial_state', {})
    for name in ('primary', 'backup', 'header'):
        raw = (directory / (name + '-before.bin')).read_bytes()
        if s.classify(raw, files[name+'-factory.bin'], files[name+'-swap.bin']) != initial.get(name):
            raise RuntimeError('Initial layout evidence differs')
        if target == 'swap' and initial.get(name) != 'factory': raise RuntimeError('Installation was not admitted from factory bytes')
        if (directory / (name + '-after.bin')).read_bytes() != files[name+'-'+target+'.bin']:
            raise RuntimeError('Host final readback differs: ' + name)
    reads = [(name+'-before', offset, len(files[name+'-factory.bin']), s.g.sha((directory/(name+'-before.bin')).read_bytes()))
             for name, offset in (('primary', 0), ('backup', s.g.BACKUP_OFFSET), ('header', s.b.SWAP_OFFSET))]
    protected_reads = [(name, offset, size, protected[name]) for name, offset, size, _ in s.g.PROTECTED]
    sequence = [('read-verified', name, offset, size, digest) for name, offset, size, digest in reads + protected_reads]
    sequence += [('read-verified', 'superblock-before', s.b.DATA_OFFSET+1024, 1024, s.g.sha(sb)), ('admitted', None, None, None, None)]
    order = ('header', 'backup', 'primary') if target == 'swap' else ('backup', 'primary', 'header')
    offsets = {'primary':0, 'backup':s.g.BACKUP_OFFSET, 'header':s.b.SWAP_OFFSET}
    for name in order:
        raw = files[name+'-'+target+'.bin']; raw = raw[:34*512] if name == 'primary' else raw
        sequence += [(event, name+suffix, offsets[name], len(raw), s.g.sha(raw)) for event, suffix in
                     (('write-intent',''),('write-acknowledged',''),('read-verified','-readback'))]
    sequence += [('read-verified', name+'-after', offsets[name], len(files[name+'-'+target+'.bin']), s.g.sha(files[name+'-'+target+'.bin'])) for name in ('primary','backup','header')]
    sequence += [('read-verified','superblock-after',s.b.DATA_OFFSET+1024,1024,s.g.sha(sb))]
    sequence += [('read-verified',name,offset,size,digest) for name,offset,size,digest in protected_reads]
    sequence += [('layout-verified',None,None,None,None),('reboot',None,None,None,None)]
    actual = [tuple(e.get(k) for k in ('event','name','offset','size','sha256')) for e in events]
    if actual != sequence or events[-1].get('acknowledged') is not True or events[-2].get('layout') != target:
        raise RuntimeError('Complete transition read/write chronology differs')
    if any(e.get('layout') != target for e in events if e['event'].startswith('write-')):
        raise RuntimeError('Writes did not target the requested layout')
    if events[8].get('target') != target or events[8].get('initial_state') != initial or events[8].get('filesystem') != result['filesystem']:
        raise RuntimeError('Admission record differs')
    return result


def owner_alive(unit):
    state = q.r.qualify.run(['systemctl','--user','show',unit,'-p','ActiveState','--value']).strip()
    if state not in ('active','activating','deactivating','inactive','failed'): raise RuntimeError('Unknown owner service state')
    return state in ('active','activating','deactivating')


def committed(directory):
    try: result = json.loads((directory / 'commit.json').read_text())
    except (OSError, ValueError): return False
    return (result.get('result') == 'passed' and result.get('factory_restore_qualified') is True
            and result.get('swap_active') is True and result.get('reboot_persistence_qualified') is True)


def rescue(directory):
    units = json.loads((directory / 'units.json').read_text())
    (directory / 'rescue.ready').write_text(str(os.getpid()) + '\n')
    deadline = time.monotonic() + 1750
    while time.monotonic() < deadline:
        if committed(directory):
            q.r.qualify.save(directory,'rescue-result.json',dict(result='committed',factory_restored=False));return
        try:
            if not owner_alive(units['worker']): break
        except (OSError,RuntimeError,subprocess.SubprocessError) as error:
            (directory/'rescue-owner-observer-error.txt').write_text(str(error)+'\n')
        time.sleep(0.5)
    else: raise RuntimeError('Worker did not finish before its service deadline')
    with ExitStack() as locks:
        deadline = time.monotonic() + 30
        for name in ('.p22-transaction.lock','.p22-flash-writer.lock'):
            handle = locks.enter_context((q.r.LOCKS/name).open('a'))
            while True:
                try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>deadline:raise RuntimeError('Previous transaction still owns a flash lock')
                    time.sleep(0.2)
        if committed(directory):
            q.r.qualify.save(directory,'rescue-result.json',dict(result='committed',factory_restored=False));return
        before = json.loads((directory/'before.json').read_text()); out = directory/'emergency-restore'
        factory = None
        try: factory = snapshot('factory',healthy=False)
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):pass
        if factory is None:
            print('Rescue owns both locks; restoring original GPT and header',flush=True)
            rc,window,error = run_da(out,handle,restore=True)
            after = healthy_return(out,'factory',before)
            if error:raise error
            verify_da(out,before,'factory',rc,window)
        else:
            # An in-session rollback may already have restored the factory.
            deadline = time.monotonic()+360
            while time.monotonic()<deadline:
                try:after=snapshot('factory');break
                except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):time.sleep(3)
            else:raise RuntimeError('Factory Linux did not become healthy')
            if after['flashinfo_sha256']!=before['flashinfo_sha256']:raise RuntimeError('Rescue flashinfo changed')
            q.r.qualify.save(out,'after.json',after)
        outputs=retained(out,after);q.r.qualify.check_host_idle()
        q.r.qualify.save(directory,'rescue-result.json',dict(result='restored',factory_restored=True,
            healthy_boot=after['boot_id'],ordinary_outputs_retained=outputs))


def work(directory, execute):
    os.umask(0o077)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock','.p22-flash-writer.lock'):
            handle=locks.enter_context((q.r.LOCKS/name).open('a'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        q.r.qualify.check_host_idle();before=snapshot('factory')
        usb=q.r.backend.usb_snapshot('3-2')
        if usb is None or usb[:2]!=('0525','a4a2'):raise RuntimeError('Wrong Gemini USB port')
        q.r.qualify.run(['sudo','-n','true']);q.r.qualify.run([str(MTK),'gemini-fixed-swap','--help'])
        stage(directory,before,execute)
        if not execute:print('Fixed-swap preflight passed; no reboot or device writes: '+str(directory));return
        worker=os.environ['GEMINI_SWAP_UNIT'];rescue_unit=worker+'-rescue';net=worker+'-net'
        q.r.qualify.save(directory,'units.json',dict(worker=worker,rescue=rescue_unit,network=net))
        q.r.unit(net,3400,[shutil.which('sh'),directory/'executed-sources/trex-gadget-net-watcher.sh',directory/'host-net.log',directory/'host-net.state'])
        q.r.unit(rescue_unit,3300,[sys.executable,str(Path(__file__).resolve()),'--rescue-worker','--out',directory])
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if (directory/'rescue.ready').exists() and owner_alive(rescue_unit):break
            time.sleep(0.1)
        else:raise RuntimeError('Independent rescue did not become ready')
        try:
            previous=before;outputs=None
            for phase,target in (('install-01','swap'),):
                out=directory/phase
                if not owner_alive(rescue_unit):raise RuntimeError('Independent rescue stopped before transition')
                print('Starting '+phase+'; independent factory rescue is armed',flush=True)
                rc,window,error=run_da(out,handle,previous,restore=target=='factory')
                if error:raise error
                verify_da(out,previous,target,rc,window)
                after=healthy_return(out,target,previous)
                if target=='swap':swap_evidence(out,after)
                outputs=retained(out,after);previous=after
                print(phase+' passed with fresh healthy M69 and retained data',flush=True)
            if not owner_alive(rescue_unit):raise RuntimeError('Independent rescue stopped before reboot check')
            out=directory/'reboot-check';q.r.reboot(q.SSH,out,'reboot-request.json')
            after=healthy_return(out,'swap',previous);swap_evidence(out,after);outputs=retained(out,after)
            q.r.qualify.check_host_idle()
            result=dict(result='passed',swap_active=True,factory_restore_qualified=True,
                        reboot_persistence_qualified=True,healthy_boot=after['boot_id'],
                        factory_restore_evidence=str(RESTORE_PROOF),
                        ordinary_outputs_retained=outputs,layout='swap',no_writer=True,
                        swap_io_under_pressure_qualified=False,hibernation_qualified=False)
            q.r.qualify.save(directory,'result.json',result)
            with (directory/'commit.tmp').open('x') as file:
                json.dump(result,file);file.flush();os.fsync(file.fileno())
            (directory/'commit.tmp').rename(directory/'commit.json')
            print('PASS: fixed swap active; factory restoration and reboot persistence proven',flush=True)
        except Exception as error:
            q.r.qualify.save(directory,'result.json',dict(result='failed',error=str(error),swap_active=False))
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--rescue-worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();directory=args.out.resolve()
    if args.rescue_worker:
        units=json.loads((directory/'units.json').read_text())
        if not os.environ.get('INVOCATION_ID') or q.r.qualify.run(['systemctl','--user','show',units['rescue'],'-p','MainPID','--value']).strip()!=str(os.getpid()):
            raise RuntimeError('Rescue lacks its independent service owner')
        try:rescue(directory)
        except Exception as error:
            q.r.qualify.save(directory,'rescue-result.json',dict(result='failed',error=str(error)));raise
        finally:q.r.qualify.run(['systemctl','--user','stop',units['network']])
    elif args.worker:
        unit=os.environ.get('GEMINI_SWAP_UNIT','')
        if not re.fullmatch('fixed-swap-[0-9]+-[0-9]+',unit) or not os.environ.get('INVOCATION_ID'):
            raise RuntimeError('Execution requires a durable service')
        if q.r.qualify.run(['systemctl','--user','show',unit,'-p','MainPID','--value']).strip()!=str(os.getpid()):raise RuntimeError('Worker service ownership differs')
        work(directory,True)
    elif args.execute:
        unit='fixed-swap-'+str(int(time.time()))+'-'+str(os.getpid())
        print('Starting durable fixed-swap worker '+unit,flush=True)
        child=subprocess.run(['systemd-run','--user','--collect','--wait','--pipe','--quiet','--unit='+unit,
            '--property=RuntimeMaxSec=1650','--setenv=PATH='+os.environ['PATH'],'--setenv=GEMINI_SWAP_UNIT='+unit,
            sys.executable,str(Path(__file__).resolve()),'--worker','--out',str(directory)])
        units_file=directory/'units.json'
        if units_file.exists():
            units=json.loads(units_file.read_text());deadline=time.monotonic()+1500
            while owner_alive(units['rescue']):
                if time.monotonic()>deadline:raise RuntimeError('Rescue service is still running; inspect the same unit')
                time.sleep(1)
            status=json.loads((directory/'rescue-result.json').read_text())
            print('Independent rescue result: '+status['result'],flush=True)
            if status['result'] not in ('committed','restored'):raise RuntimeError('Factory recovery failed')
        if child.returncode:raise RuntimeError('Fixed-swap trial failed; inspect retained worker and rescue evidence')
    else:work(directory,False)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:sys.exit(str(error))
