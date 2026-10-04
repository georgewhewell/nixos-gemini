#!/usr/bin/env python3
"""Qualify exact factory-GPT rewrites with unchanged layout and boot images.

Default is read-only preflight. --execute runs a durable user service, retaining
both flash locks through a bounded privileged DA session and healthy return.
This command does not provision p34, format storage, or change boot images.
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
import shutil
import subprocess
import sys
import time
import threading

ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT.parent
MTK='/nix/store/rj1a8wj8l9w7z7rfy6sw0ka2imlhrawy-mtkclient-gemini-gpt-2.1.4.1/bin/mtk'
SSH=['ssh','-F','/dev/null','-i','/home/grw/.ssh/gemini-stage1-ed25519',
     '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=5',
     '-o','ControlPath=none','-o','StrictHostKeyChecking=yes',
     '-o','HostKeyAlias=192.168.23.70','root@10.15.19.82']
TRIALS=('persistent-nix-01','efi-nix-provision-01','efi-nix-manager-01','efi-nix-provision-02',
        'efi-entry-dt-provision-01','efi-entry-dt-manager-01','efi-entry-dt-cross-manager-01',
        'efi-key-events-manager-02','desktop-keyboard-01','power-kernel-01')


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


r=module('recovery',ROOT/'tools/qualify-uboot-recovery.py')
g=module('gpt',ROOT/'nix/mtk-gpt-rewrite.py')


def snapshot():
    state=r.snapshot(SSH)
    lines=r.qualify.run(SSH+['''set -eu
dd if=/dev/mmcblk0 bs=512 skip=122142687 count=33 status=none | sha256sum
sha256sum /dev/mmcblk0p33
''']).splitlines()
    if len(lines)!=2 or lines[0].split()[0]!=g.BACKUP_SHA or state['gpt_sha256']!=g.PRIMARY_SHA:
        raise RuntimeError('Both GPT copies must match the qualified factory layout')
    state['backup_gpt_sha256']=lines[0].split()[0]
    state['flashinfo_sha256']=lines[1].split()[0]
    if not re.fullmatch('[0-9a-f]{64}',state['flashinfo_sha256']):
        raise RuntimeError('Missing flashinfo identity')
    return state


def preserved_files(boot_id,directory,name):
    r.efi_files.evidence(SSH,boot_id,directory,r.qualify,require_verified=False,
                        name=name+'-boot-files.json',profile=r.entry_dt.files_profile(r.efi_files))
    r.previous_files_evidence(SSH,boot_id,directory,'power-kernel',name+'-previous-files')


def preserved_outputs(boot_id,directory):
    out=directory/'all-nix-outputs';out.mkdir(mode=0o700)
    retained={}
    for trial in TRIALS:
        previous=json.loads((WORKSPACE/'handoff'/trial/'nix-candidate.json').read_text())
        r.persistent_nix.verify_retained(SSH,boot_id,out,r.qualify,r.persistence,previous,name=trial)
        retained[trial]=previous['output']
    r.persistent_nix.old_persistence(SSH,boot_id,directory,r.qualify,r.persistence,
                                  r.qualify.ACCEPTED_SYSTEM,'original-persistence')
    return retained


def stage(directory,before,execute):
    directory.mkdir(mode=0o700)
    r.qualify.save(directory,'before.json',before)
    prepared=WORKSPACE/'handoff/fixed-swap-plan-01/prepared'
    for name in ('primary-gpt-before.bin','backup-gpt-before.bin'):
        with (directory/name).open('xb') as output: output.write((prepared/name).read_bytes())
        (directory/name).chmod(0o400)
    for name in g.OUTPUTS: (directory/name).touch(exist_ok=False)
    g.load_inputs(directory)
    packaged=Path(MTK).parents[1]/'lib/python3.14/site-packages/mtkclient/Library/gemini_gpt_rewrite.py'
    if packaged.read_bytes()!=(ROOT/'nix/mtk-gpt-rewrite.py').read_bytes():
        raise RuntimeError('Host verifier and pinned GPT command differ')
    sources=directory/'executed-sources';sources.mkdir(mode=0o700)
    hashes={}
    for relative in ('tools/qualify-gpt-rewrite.py','nix/mtk-gpt-rewrite.py',
                     'tools/qualify-uboot-recovery.py','tools/qualify-mtkclient.py',
                     'research/p22-mtkclient-backend.py','research/trex-gadget-net-watcher.sh',
                     'tools/qualify-gemini-persistence.py','tools/qualify-persistent-nix.py',
                     'tools/qualify-efi-files.py','tools/qualify-efi-entry-dt.py'):
        raw=(ROOT/relative).read_bytes();(sources/Path(relative).name).write_bytes(raw)
        hashes[relative]=hashlib.sha256(raw).hexdigest()
    r.qualify.save(directory,'plan.json',dict(mtk=MTK,execute=execute,command='gemini-gpt-rewrite',
        changed_partition_layout=False,executed_sources_sha256=hashes,
        write_ranges=[dict(offset=g.BACKUP_OFFSET,size=33*512,sha256=g.BACKUP_SHA),
                      dict(offset=0,size=34*512,sha256=g.PRIMARY_WRITE_SHA)]))
    preserved_files(before['boot_id'],directory,'before')


def verify_evidence(directory,before,returncode,window):
    result=json.loads((directory/'gpt-result.json').read_text())
    events=[json.loads(line) for line in (directory/'gpt-events.jsonl').read_text().splitlines()]
    if (returncode!=0 or not window.complete or not window.acknowledged or
            result.get('schema')!='gemini-factory-gpt-rewrite-v1' or
            any(result.get(key) is not True for key in ('operation_qualified','original_layout_verified','reboot_acknowledged','write_attempted')) or
            result.get('rollback_attempted') is not False or result.get('events')!=events):
        raise RuntimeError('Complete acknowledged GPT writes, readbacks and reboot are not proven')
    expected=[('backup',g.BACKUP_OFFSET,33*512,g.BACKUP_SHA),
              ('primary',0,34*512,g.PRIMARY_WRITE_SHA)]
    def writes(kind):
        return [(e.get('name'),e.get('offset'),e.get('size'),e.get('sha256')) for e in events if e.get('event')==kind]
    if writes('write-intent')!=expected or writes('write-acknowledged')!=expected:
        raise RuntimeError('GPT write addresses, lengths, bytes or order differ')
    kinds=[e['event'] for e in events]
    if kinds.count('admitted')!=1 or kinds.index('admitted')>kinds.index('write-intent'):
        raise RuntimeError('GPT writes lack prior in-session admission')
    sequence=[(e['event'],e.get('name')) for e in events
              if e['event'] in ('write-intent','write-acknowledged') or
              (e['event']=='read-verified' and e.get('name','').endswith('-readback'))]
    wanted=[(event,name+suffix) for name in ('backup','primary')
            for event,suffix in (('write-intent',''),('write-acknowledged',''),('read-verified','-readback'))]
    if sequence!=wanted:raise RuntimeError('Each GPT write must pass readback before the next write')
    protected={name:digest for name,_,_,digest in g.PROTECTED}
    protected['flashinfo']=before['flashinfo_sha256']
    if result.get('protected_before')!=protected or result.get('protected_after')!=protected:
        raise RuntimeError('Protected boot images or flashinfo changed')
    expected_reads=[('primary-before',0,32768,g.PRIMARY_SHA),
                    ('backup-before',g.BACKUP_OFFSET,33*512,g.BACKUP_SHA)]
    protected_reads=[(name,offset,size,protected[name]) for name,offset,size,_ in g.PROTECTED]
    chronology=[('read-verified',name) for name,_,_,_ in expected_reads+protected_reads]
    chronology += [('admitted',None)] + wanted
    chronology += [('read-verified','primary-after'),('read-verified','backup-after')]
    chronology += [('read-verified',name) for name,_,_,_ in protected_reads]
    chronology += [('reboot',None)]
    if [(e.get('event'),e.get('name')) for e in events]!=chronology:
        raise RuntimeError('The complete admission/write/readback/reboot chronology is missing')
    read_specs={name:(offset,size,digest) for name,offset,size,digest in expected_reads+protected_reads}
    read_specs.update({'primary-after':(0,32768,g.PRIMARY_SHA),
                       'backup-after':(g.BACKUP_OFFSET,33*512,g.BACKUP_SHA),
                       'primary-readback':(0,34*512,g.PRIMARY_WRITE_SHA),
                       'backup-readback':(g.BACKUP_OFFSET,33*512,g.BACKUP_SHA)})
    for event in events:
        if event['event']=='read-verified' and tuple(event.get(k) for k in ('offset','size','sha256'))!=read_specs[event['name']]:
            raise RuntimeError('An in-session read has incorrect bounds or bytes')
    admission=events[6]
    if admission.get('primary_sha256')!=g.PRIMARY_SHA or admission.get('backup_sha256')!=g.BACKUP_SHA or events[-1].get('acknowledged') is not True:
        raise RuntimeError('Admission or reboot acknowledgement differs')
    for prefix,size,digest in (('primary',32768,g.PRIMARY_SHA),('backup',33*512,g.BACKUP_SHA)):
        for suffix in ('before','after'):
            raw=(directory/(prefix+'-'+suffix+'.bin')).read_bytes()
            if len(raw)!=size or g.sha(raw)!=digest:
                raise RuntimeError('Host GPT readback disagrees: '+prefix+'-'+suffix)
    return result


def da_trial(directory,before,writer_lock):
    logpath=directory/'mtk.log'
    window=r.backend.BootWindow();window.observe(r.backend.usb_snapshot('3-2'),time.monotonic())
    command=['sudo','-n','env','PYTHONUNBUFFERED=1','timeout','--foreground',
             '--kill-after=5s','180s',MTK,'gemini-gpt-rewrite',str(directory)]
    r.qualify.save(directory,'command.json',command)
    error=None;rebooted=False
    stopped=threading.Event();monitor_errors=[]
    def observe():
        try:
            while not stopped.is_set():
                text=logpath.read_text(errors='replace')
                window.acknowledged |= r.backend.ACK in text
                window.observe(r.backend.usb_snapshot('3-2'),time.monotonic())
                stopped.wait(0.02)
        except Exception as caught:monitor_errors.append(caught)
    with logpath.open('w') as log:
        # The root timeout retains the writer flock through fd 0 even if the
        # observer dies; sudo closes other inherited non-standard descriptors.
        child=subprocess.Popen(command,cwd=directory,stdout=log,stderr=subprocess.STDOUT,
                               stdin=writer_lock.fileno())
        monitor=threading.Thread(target=observe,daemon=True);monitor.start()
        try:
            ready_deadline=time.monotonic()+20
            while child.poll() is None:
                if monitor_errors:raise monitor_errors[0]
                text=logpath.read_text(errors='replace')
                if not rebooted:
                    if 'Waiting for PreLoader' in text:
                        if snapshot()!=before:raise RuntimeError('Device changed before the DA trial')
                        print('GPT writer is ready; rebooting healthy M69 once',flush=True)
                        rebooted=True
                        r.reboot(SSH,directory,'reboot-request.json')
                    elif time.monotonic()>ready_deadline:
                        raise RuntimeError('DA did not become ready; Linux was not rebooted')
                time.sleep(0.05)
        except Exception as caught:
            error=caught
        finally:
            try:
                child.wait(timeout=190)
                deadline=time.monotonic()+30
                while rebooted and not window.complete and not monitor_errors and time.monotonic()<deadline:
                    time.sleep(0.05)
            finally:
                stopped.set();monitor.join(timeout=2)
    r.qualify.save(directory,'usb-events.json',window.events)
    r.qualify.save(directory,'mtk-exit.json',dict(returncode=child.returncode,reboot_requested=rebooted))
    error=error or (monitor_errors[0] if monitor_errors else None)
    if error:(directory/'da-observer-error.txt').write_text(str(error)+'\n')
    if not rebooted:raise error or RuntimeError('DA exited before a device trial')
    return child.returncode,window,error


def work(directory,execute):
    os.umask(0o077)
    with ExitStack() as locks:
        for name in ('.p22-transaction.lock','.p22-flash-writer.lock'):
            handle=locks.enter_context((r.LOCKS/name).open('a'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        r.qualify.check_host_idle()
        before=snapshot()
        usb=r.backend.usb_snapshot('3-2')
        if usb is None or usb[:2]!=('0525','a4a2'):
            raise RuntimeError('Gemini is not on the qualified USB port')
        r.qualify.run(['sudo','-n','true'])
        r.qualify.run([MTK,'gemini-gpt-rewrite','--help'])
        stage(directory,before,execute)
        if not execute:
            print('Preflight passed; no reboot or DA access: '+str(directory));return
        net='gpt-qual-net-'+str(os.getpid())
        r.qualify.save(directory,'units.json',dict(worker=os.environ.get('GEMINI_GPT_UNIT'),network=net))
        r.unit(net,850,[shutil.which('sh'),directory/'executed-sources/trex-gadget-net-watcher.sh',
                       directory/'host-net.log',directory/'host-net.state'])
        try:
            rc,window,observer_error=da_trial(directory,before,handle)
            print('DA session ended; checking fresh healthy M69 and data retention',flush=True)
            # Observe health before interpreting a failure; never hide a
            # successful automatic recovery behind a verifier exception.
            deadline=time.monotonic()+360
            while time.monotonic()<deadline:
                try:
                    after=snapshot();r.qualify.verify_return(before,after)
                    for key in ('p30_sha256','p31_sha256','backup_gpt_sha256','flashinfo_sha256'):
                        if after[key]!=before[key]:raise RuntimeError('Changed protected identity: '+key)
                    break
                except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:
                    (directory/'last-health-error.txt').write_text(str(error)+'\n');time.sleep(3)
            else:raise RuntimeError('Fresh healthy M69 did not return within 360 seconds')
            r.qualify.save(directory,'after.json',after)
            r.qualify.run(['systemctl','--user','stop',net])
            preserved_files(after['boot_id'],directory,'after')
            retained=preserved_outputs(after['boot_id'],directory)
            if observer_error:raise observer_error
            verify_evidence(directory,before,rc,window)
            r.qualify.check_host_idle()
            if snapshot()!=after:raise RuntimeError('State changed during final retention audit')
            r.qualify.save(directory,'result.json',dict(result='passed',gpt_rewrite_qualified=True,
                partition_layout_changed=False,swap_provisioned=False,healthy_boot=after['boot_id'],
                ordinary_outputs_retained=retained,locks_exclusively_held=True,no_writer=True))
            print('PASS: both factory GPT copies rewritten and independently verified; fresh healthy M69; all ten Nix outputs retained',flush=True)
        except Exception as error:
            r.qualify.save(directory,'result.json',dict(result='failed',error=str(error),
                gpt_rewrite_qualified=False,note='Inspect the terminal DA result and health evidence before any next transaction'))
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();directory=args.out.resolve()
    if args.worker:
        unit=os.environ.get('GEMINI_GPT_UNIT','')
        if not re.fullmatch('gpt-rewrite-[0-9]+-[0-9]+',unit) or not os.environ.get('INVOCATION_ID'):
            raise RuntimeError('Execution requires its durable host service')
        pid=r.qualify.run(['systemctl','--user','show',unit,'-p','MainPID','--value']).strip()
        if pid!=str(os.getpid()):raise RuntimeError('Host service does not own this process')
        work(directory,True)
    elif args.execute:
        unit='gpt-rewrite-'+str(int(time.time()))+'-'+str(os.getpid())
        print('Starting durable GPT qualification service '+unit,flush=True)
        subprocess.run(['systemd-run','--user','--collect','--wait','--pipe','--quiet','--unit='+unit,
            '--property=RuntimeMaxSec=900','--setenv=PATH='+os.environ['PATH'],
            '--setenv=GEMINI_GPT_UNIT='+unit,sys.executable,str(Path(__file__).resolve()),
            '--worker','--out',str(directory)],check=True)
    else:work(directory,False)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:sys.exit(str(error))
