#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual request-test CLI and IRQ acceptance predicate without devices."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
GREY_SHA256 = '855a5ef2c41f93be0348d94136d49a78fba4c22829670cd2e6526ca09fc111e7'


def check_cli(source):
    match = re.search(r'^int main\(int argc, char \*\*argv\)\n\{.*\Z', source.read_text(), re.M | re.S)
    assert match, 'Production main not found'
    code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
typedef uint8_t u8;
'''
    code += '#include ' + json.dumps(str(REPO/'research/mt6797-vdec/pcm64-fixture.h')) + '\n'
    code += r'''
struct stream { int live; };
static const char *status_path, *fixture_directory;
static unsigned width = 64, height = 64, storage_height = 64;
static int export_buffers, buffers_only, live;
static void test_native_gpu(const char *video, const char *media, const char *render,
                            const char *helper, const char *out)
{
    assert(!live && !strcmp(video, "video") && !strcmp(media, "media"));
    assert(!strcmp(render, "render") && !strcmp(helper, "helper") && !strcmp(out, "output"));
    assert(width == 80 && height == 64 && storage_height == 64 && !buffers_only);
    puts("{\"op\":\"gpu\"}");
}
static void test_create_buffers(const char *video, const char *media)
{
    assert(!live && !strcmp(video, "video") && !strcmp(media, "media"));
    assert(width == 80 && height == 64 && storage_height == 64 && buffers_only);
    puts("{\"op\":\"create\"}");
}
static void test_native_buffers(struct stream *s, const char *video, const char *media,
                                const char *render)
{
    assert(!live && !strcmp(video, "video") && !strcmp(media, "media"));
    assert(!strcmp(render, "render") && !fixture_directory);
    assert(width == 80 && height == 64 && storage_height == 64 && buffers_only);
    (void)s;
    puts("{\"op\":\"buffers\"}");
}
static void open_stream(struct stream *s, const char *video, const char *media)
{
    assert(!live && !strcmp(video, "video") && !strcmp(media, "media"));
    assert(!strcmp(status_path, "status") && !fixture_directory);
    assert(width == 64 && height == 64 && storage_height == 64 && !export_buffers);
    s->live = live = 1;
    puts("{\"op\":\"open\"}");
}
static void decode(struct stream *s, const char *out, const char *name,
                   const u8 *nal, size_t bytes, int predicted, int patterned,
                   int expect_error, unsigned timestamp, unsigned sequence)
{
    assert(live && s->live && !strcmp(out, "output"));
    printf("{\"op\":\"decode\",\"name\":\"%s\",\"bytes\":%zu,"
           "\"controls\":[%d,%d,%d,%u,%u],\"grey_hex\":\"",
           name, bytes, predicted, patterned, expect_error, timestamp, sequence);
    if (!strcmp(name, "grey64"))
        for (size_t i = 0; i < bytes; i++) printf("%02x", nal[i]);
    puts("\"}");
}
static void close_stream(struct stream *s)
{
    assert(live && s->live);
    s->live = live = 0;
    puts("{\"op\":\"close\"}");
}
'''
    code += match.group(0)
    with tempfile.TemporaryDirectory(prefix='vdec-irq-case-host-') as tmp:
        path = Path(tmp)
        (path/'main.c').write_text(code)
        compiler = shlex.split(os.environ.get('HOSTCC', os.environ.get('CC', 'cc')))
        flags = shlex.split(os.environ.get('CFLAGS', ''))
        subprocess.run(compiler + ['-std=gnu11', '-Wall', '-Wextra', '-Werror'] + flags +
                       [str(path/'main.c'), '-o', str(path/'main')], check=True)

        def run(extra, expected=0, base=True):
            args = ['video', 'media', 'output', 'status'] if base else []
            result = subprocess.run([str(path/'main')] + args + extra, capture_output=True, text=True)
            assert result.returncode == expected, (extra, result.returncode, result.stderr)
            return [json.loads(line) for line in result.stdout.splitlines()]

        single = run(['--single', 'grey64'])
        assert [r.get('op') for r in single] == ['open', 'decode', 'close', None], single
        grey = single[1]
        assert grey['name'] == 'grey64' and grey['bytes'] == 20 and grey['controls'] == [0, 0, 0, 1, 0]
        assert hashlib.sha256(bytes.fromhex(grey['grey_hex'])).hexdigest() == GREY_SHA256
        assert single[-1] == dict(public_api_test_passed=True, scope='single-grey64')
        assert run(['--buffers-only', 'render']) == [dict(op='create'), dict(op='buffers')]
        assert run(['--native-gpu', 'render', 'helper']) == [dict(op='gpu')]
        for extra in (['--single'], ['--single', 'pcm64'], ['--other', 'grey64'],
                      ['--single', 'grey64', 'extra'], ['--single', 'grey64', '64', 'mmap'],
                      ['--buffers-only'], ['--buffers-only', 'render', 'extra'],
                      ['--native-gpu'], ['--native-gpu', 'render'],
                      ['--native-gpu', 'render', 'helper', 'extra']):
            assert run(extra, expected=2) == [], extra
        assert run([], expected=2, base=False) == []
        legacy = run([])
        assert [r.get('op') for r in legacy] == [
            'open', 'decode', 'decode', 'close', 'open', 'decode', 'decode', 'close',
            'open', 'decode', 'close', None]
        assert [r['name'] for r in legacy if r.get('op') == 'decode'] == [
            'pcm64', 'pcm64-p', 'grey64', 'pattern64', 'missing-reference']
        assert legacy[-1] == dict(public_api_test_passed=True)
    print('Actual C main: grey-only dispatch/bytes/controls/close, invalid selectors, legacy sequence: PASS')


def check_qualification(path):
    spec = importlib.util.spec_from_file_location('vdec_irq_case', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='vdec-gpu-launcher-') as tmp:
        root = Path(tmp)
        helper, elf, interpreter = (root/name for name in ('launcher', 'program', 'shell'))
        arm64 = bytearray(64)
        arm64[:7] = b'\x7fELF\x02\x01\x01'
        arm64[16:20] = (2).to_bytes(2, 'little')+(183).to_bytes(2, 'little')
        elf.write_bytes(arm64); interpreter.write_bytes(arm64)
        helper.write_text('#! '+str(interpreter)+' -e\nexec '+str(elf)+' "$@"\n')
        module.check_gpu_launcher(helper, elf, interpreter)
        for dependency in (elf, interpreter):
            for change in ('absent', 'host', 'relocatable', 'endian', 'truncated'):
                bad = bytearray(arm64)
                if change == 'absent': dependency.unlink()
                else:
                    if change == 'host': bad[18:20] = (62).to_bytes(2, 'little')
                    if change == 'relocatable': bad[16:18] = (1).to_bytes(2, 'little')
                    if change == 'endian': bad[5] = 2
                    dependency.write_bytes(bad[:32] if change == 'truncated' else bad)
                try:
                    module.check_gpu_launcher(helper, elf, interpreter)
                except (RuntimeError, FileNotFoundError):
                    pass
                else:
                    raise AssertionError('Invalid GPU execution dependency admitted: '+change)
                dependency.write_bytes(arm64)
        for text in ('', '#!/bin/sh\n', '#! '+str(interpreter)+'\n'):
            helper.write_text(text)
            try:
                module.check_gpu_launcher(helper, elf, interpreter)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Absent/foreign GPU launcher shebang admitted')
    # Optional immutable trial input supplements portable fixtures without
    # making ordinary host checks depend on this machine's retained store.
    retained = os.environ.get('VDEC_REJECTED_GPU_ADMISSION')
    if retained:
        gpu = json.loads(Path(retained).read_text())['gpu_helper']
        helper, elf = Path(gpu['path']), Path(gpu['elf_path'])
        interpreter = Path(helper.read_text().splitlines()[0].removeprefix('#! ').removesuffix(' -e'))
        assert hashlib.sha256(helper.read_bytes()).hexdigest() == gpu['sha256']
        assert hashlib.sha256(elf.read_bytes()).hexdigest() == gpu['elf_sha256']
        try:
            module.check_gpu_launcher(helper, elf, interpreter)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Retained host-shell GPU launcher admitted')
    print('Actual GPU launcher admission: ARM64 program/interpreter accepted; absent/host/relocatable/endian/truncated dependencies and foreign shebangs rejected: PASS')
    with tempfile.TemporaryDirectory(prefix='vdec-kernel-revision-') as tmp:
        kernel = Path(tmp)
        revision = '01222a4b2074555955a85715587bebf0933fb0eb'
        manifest = kernel/'BUILD-MANIFEST'
        manifest.write_text('source-revision='+revision+'\nkernel-release=same-ABI\n')
        module.check_kernel_revision(kernel, revision)
        for text, expected in (
                ('kernel-release=same-ABI\n', revision),
                ('source-revision='+'0'*40+'\n', revision),
                ('source-revision='+revision+'\nsource-revision='+revision+'\n', revision),
                ('source-revision='+revision+'\n', 'invalid')):
            manifest.write_text(text)
            try:
                module.check_kernel_revision(kernel, expected)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Missing/foreign/ambiguous kernel source admitted')
    status = dict(result=0, fetched=1, submitted=1, quiesced=1, guards=1, error=0,
                  message=0, reset=0, irq_events=1, irq_unexpected=0, jobs=1,
                  fetch_commands=1, frame_commands=1, nal_bytes=20, header_bits=28,
                  irq_clock_result=0, state=0x80000001, irq_status=0x13001,
                  irq_command=1, irq_received_command=1, irq_clock_trace_valid=0x1f,
                  irq_clock_submit=0x101, irq_clock_guard=0x101, irq_complete=1)
    status['break'] = 0
    before = dict(irq=77, counts=[0]*10, total=0)
    # CPU8 may have parked after the event; its possible-CPU counter remains.
    after = dict(irq=77, counts=[0]*8+[1, 0], total=1)
    good = dict(statuses={'grey64': status}, comparisons={'grey64': {'passed': True}},
                start=before, finish=after, returncode=0, safe=True,
                program_complete=True, single='grey64')
    assert module.completion_qualified(**good), 'Actual five-phase accepted evidence rejected'
    rejected = 0

    def reject(value, label):
        nonlocal rejected
        assert not module.completion_qualified(**value), label
        rejected += 1

    bad_fields = dict(result=-110, fetched=0, submitted=0, quiesced=0, guards=0,
                      error=1, message=1, reset=1, irq_events=0, irq_unexpected=1,
                      jobs=2, fetch_commands=2, frame_commands=2, nal_bytes=6180,
                      header_bits=38, irq_clock_result=-5, state=1, irq_status=0x3001,
                      irq_command=0, irq_received_command=2, irq_clock_trace_valid=0x3f,
                      irq_clock_submit=0x111, irq_clock_guard=0x111, irq_complete=0)
    bad_fields['break'] = 1
    for field, value in bad_fields.items():
        changed = copy.deepcopy(good)
        changed['statuses']['grey64'][field] = value
        reject(changed, field)
    for field in ('irq_status', 'irq_command', 'irq_received_command', 'irq_clock_result',
                  'irq_clock_trace_valid', 'irq_clock_submit', 'irq_clock_guard', 'irq_complete'):
        changed = copy.deepcopy(good)
        del changed['statuses']['grey64'][field]
        reject(changed, 'absent ' + field)
    for field, value in (('returncode', 1), ('safe', False), ('program_complete', False),
                         ('statuses', {}), ('comparisons', {}),
                         ('comparisons', {'grey64': {'passed': False}})):
        changed = copy.deepcopy(good)
        changed[field] = value
        reject(changed, field)
    for field in ('statuses', 'comparisons'):
        changed = copy.deepcopy(good)
        changed[field]['pcm64'] = copy.deepcopy(changed[field]['grey64'])
        reject(changed, 'extra ' + field)
    for finish in (dict(irq=78, counts=after['counts'], total=1),
                   dict(irq=77, counts=[1], total=1),
                   dict(irq=77, counts=[0]*10, total=0),
                   dict(irq=77, counts=[0]*8+[2, 0], total=2)):
        changed = copy.deepcopy(good)
        changed['finish'] = finish
        reject(changed, 'IRQ identity/counts/delta')
    changed = copy.deepcopy(good)
    changed['start'] = dict(irq=77, counts=[1]+[0]*9, total=1)
    changed['finish'] = dict(irq=77, counts=[0]*8+[2, 0], total=2)
    reject(changed, 'One counter regressed despite a net delta of one')
    full = copy.deepcopy(good)
    full['single'] = None
    full['statuses'] = {}
    full['comparisons'] = {}
    for command, name in enumerate(('pcm64', 'pcm64-p', 'grey64', 'pattern64'), 1):
        full['statuses'][name] = dict(status, irq_command=command, irq_received_command=command)
        full['comparisons'][name] = {'passed': True}
    full['statuses']['missing-reference'] = dict(result=-2, fetched=0, submitted=0)
    full['finish'] = dict(irq=77, counts=[0]*8+[4, 0], total=4)
    assert module.completion_qualified(**full), 'Legacy four-picture predicate changed'
    full['statuses']['pattern64']['irq_command'] = full['statuses']['pattern64']['irq_received_command'] = 1
    reject(full, 'Reused command attribution across legacy pictures')
    changed = copy.deepcopy(good)
    changed['statuses']['grey64']['irq_complete'] = 0x20
    assert module.completion_qualified(**changed), 'Raw nonzero single-core finish word rejected'
    print(f'Actual qualifier: grey-only and legacy acceptance, {rejected} missing/unsafe/foreign evidence cases rejected: PASS')

    report = dict(native_buffers_test_passed=True, scope='native-buffers', width=80, height=64,
                  capture_buffers=17, planes_per_buffer=2, sizeimage=[5120, 7680],
                  plane_lengths=[196608, 196608], data_offsets=[0, 5120],
                  exported_fds=34, prime_handles=17, prime_aliases_same_handle=True,
                  prime_gpu_va_verified=True, mmap_export_aliases_verified=True,
                  queue_cache_cycle_verified=True, video_close_lifetime_verified=True,
                  closed_fd_aliases_verified=True, prime_release_lifetime_verified=True,
                  all_user_refs_released=True, codec_submissions=0, gpu_submissions=0,
                  create_bufs_cases=9, create_bufs_lengths_preserved=True,
                  create_bufs_full_backing_verified=True, create_bufs_queue_prepare_verified=True,
                  decode_qualified=False, gpu_rendering_qualified=False)
    idle = dict.fromkeys(('jobs', 'failures', 'fetch_commands', 'frame_commands',
                         'fetched', 'submitted', 'irq_events', 'irq_unexpected',
                         'result', 'engine_result'), 0)
    buffers = dict(reports=[report], cached={name: idle.copy() for name in
                   ('last-job', 'engine-failure', 'context-failure')}, start=before,
                   finish=before.copy(), returncode=0, safe=True, statuses={})
    assert module.buffers_qualified(**buffers)
    rejected = 0

    def reject_buffer(changed, label):
        nonlocal rejected
        assert not module.buffers_qualified(**changed), label
        rejected += 1

    for key, value in report.items():
        changed = copy.deepcopy(buffers)
        del changed['reports'][0][key]
        reject_buffer(changed, 'missing ' + key)
        changed = copy.deepcopy(buffers)
        changed['reports'][0][key] = (not value if type(value) is bool else
                                    value + 1 if type(value) is int else
                                    [value[0] + 1, *value[1:]] if type(value) is list else 'foreign')
        reject_buffer(changed, 'invalid ' + key)
    for name in buffers['cached']:
        for key in idle:
            changed = copy.deepcopy(buffers)
            changed['cached'][name][key] = 1
            reject_buffer(changed, 'command/failure ' + name + '/' + key)
            del changed['cached'][name][key]
            reject_buffer(changed, 'missing ' + name + '/' + key)
    for key, value in (('reports', []), ('reports', [report, report]),
                       ('reports', [True]), ('cached', {}), ('safe', False),
                       ('returncode', 1), ('statuses', {'grey64': status}),
                       ('finish', after), ('finish', dict(before, irq=78))):
        changed = copy.deepcopy(buffers); changed[key] = value
        reject_buffer(changed, key)
    for key, value in (('native_buffers_test_passed', 1), ('codec_submissions', False),
                       ('data_offsets', [False, 5120]), ('extra', True)):
        changed = copy.deepcopy(buffers); changed['reports'][0][key] = value
        reject_buffer(changed, 'foreign type/key ' + key)
    print(f'Actual native-buffer predicate: exact scope and zero-command evidence; {rejected} incomplete/foreign cases rejected: PASS')

    gpu_report = dict(native_gpu_test_passed=True, scope='synthetic-native-mm21-gpu',
                      width=80, height=64, pixels=5120, rgb_tolerance=2, exported_fds=2,
                      export_capacity=196608, api_draws=1, parent_refs_released=True,
                      codec_submissions=0, decode_qualified=False)
    marker = ('GPU_NATIVE_MM21_PASS width=80 height=64 pixels=5120 '
              'rgb_tolerance=2 imported_fds_closed=1')
    gpu_before = {kind: dict(irq=80+index, counts=[0]*10, total=0,
                            actions='panfrost-'+kind, counter='sysfs-all-possible-cpus')
                  for index, kind in enumerate(('job', 'mmu', 'gpu'))}
    gpu_after = copy.deepcopy(gpu_before)
    gpu_after['job'].update(counts=[0]*8+[3, 0], total=3)
    gpu = dict(reports=[gpu_report], helper_log='renderer=Mali-T880\n'+marker+'\n',
               cached=copy.deepcopy(buffers['cached']), start=before, finish=before.copy(),
               gpu_before=gpu_before, gpu_after=gpu_after,
               kernel_health=dict(scoped_gpu_error_lines=0, kernel_failure_lines=0),
               returncode=0, safe=True, statuses={})
    assert module.native_gpu_qualified(**gpu)
    rejected = 0

    def reject_gpu(changed, label):
        nonlocal rejected
        assert not module.native_gpu_qualified(**changed), label
        rejected += 1

    for key, value in gpu_report.items():
        changed = copy.deepcopy(gpu); del changed['reports'][0][key]
        reject_gpu(changed, 'missing GPU field '+key)
        changed = copy.deepcopy(gpu)
        changed['reports'][0][key] = (not value if type(value) is bool else
                                    value+1 if type(value) is int else 'foreign')
        reject_gpu(changed, 'bad GPU field '+key)
    for key, value in (('reports', []), ('reports', [gpu_report, gpu_report]),
                       ('reports', [True]), ('cached', {}), ('safe', False), ('returncode', 1),
                       ('statuses', {'grey64': status}), ('finish', after),
                       ('gpu_before', {}), ('gpu_after', {})):
        changed = copy.deepcopy(gpu); changed[key] = value
        reject_gpu(changed, key)
    for text in ('', marker+'\nlate output\n', marker+'\n'+marker+'\n',
                 'GPU_RENDER_FAIL: error\n'+marker, marker.replace('pixels=5120', 'pixels=5119')):
        changed = copy.deepcopy(gpu); changed['helper_log'] = text
        reject_gpu(changed, 'incomplete/failed/helper marker')
    for name in gpu['cached']:
        for key in idle:
            changed = copy.deepcopy(gpu); changed['cached'][name][key] = 1
            reject_gpu(changed, name+'/'+key)
            del changed['cached'][name][key]
            reject_gpu(changed, 'missing '+name+'/'+key)
    for kind in gpu_before:
        for key, value in (('irq', 900), ('counts', [0]), ('total', 123),
                           ('counts', [False]*10), ('counts', [-1]+[0]*9),
                           ('actions', 'foreign'), ('counter', 'online-cpus')):
            changed = copy.deepcopy(gpu); changed['gpu_after'][kind][key] = value
            reject_gpu(changed, kind+'/'+key)
        changed = copy.deepcopy(gpu)
        changed['gpu_before'][kind].update(counts=[4]+[0]*9, total=4)
        changed['gpu_after'][kind].update(counts=[0, 5]+[0]*8, total=5)
        reject_gpu(changed, 'counter regression '+kind)
    for kind in ('mmu', 'gpu'):
        changed = copy.deepcopy(gpu)
        changed['gpu_after'][kind].update(counts=[1]+[0]*9, total=1)
        assert module.native_gpu_qualified(**changed), 'Benign/recoverable IRQ rejected '+kind
    for health in ({}, dict(scoped_gpu_error_lines=1, kernel_failure_lines=0),
                   dict(scoped_gpu_error_lines=0, kernel_failure_lines=1),
                   dict(scoped_gpu_error_lines=False, kernel_failure_lines=0),
                   dict(scoped_gpu_error_lines=0, kernel_failure_lines=0, extra=0)):
        changed = copy.deepcopy(gpu); changed['kernel_health'] = health
        reject_gpu(changed, 'absent/fault/foreign kernel health')
    changed = copy.deepcopy(gpu); changed['gpu_after']['job'] = copy.deepcopy(gpu_before['job'])
    reject_gpu(changed, 'no GPU jobs')
    for key, value in (('native_gpu_test_passed', 1), ('codec_submissions', False), ('extra', True)):
        changed = copy.deepcopy(gpu); changed['reports'][0][key] = value
        reject_gpu(changed, 'foreign type/key '+key)
    for action in ('16020000.video-codec', 'panfrost-job', 'panfrost-mmu', 'panfrost-gpu'):
        text = 'irq=77\nactions='+action+'\ncounts='+','.join(['0']*10)+'\n'
        assert module.irq_counter(text, action)['actions'] == action
        assert '"'+action+'"' in module.irq_snapshot_script(action)
        for changed in (text.replace(action, 'foreign'), text+'extra=0\n', text.replace('counts=0', 'counts=-1', 1)):
            try:
                module.irq_counter(changed, action)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Foreign/malformed IRQ snapshot accepted')
    for message, gpu_errors, kernel_errors in (
            ('',0,0), ('panfrost 13040000.gpu: GPU Fault 0x123',1,0),
            ('panfrost 13040000.gpu: Unhandled Page fault in AS0',1,0),
            ('panfrost 13040000.gpu: js fault, status=DATA_INVALID_FAULT',1,0),
            ('panfrost 13040000.gpu: AS_ACTIVE bit stuck',1,0),
            ('rt5735: vgpu regulator failed',1,0), ('Oops: kernel error',0,1),
            ('Failed to power on domain mfg_async',1,0), ('WARNING: kernel ownership',0,1),
            ('BUG: generic error',0,1), ('rcu: detected stalls',0,1),
            ('panfrost 13040000.gpu: idle status=1',0,0),
            ('wifi: unrelated private failure omitted',0,0)):
        filtered = subprocess.run(['sh', '-c', module.gpu_fault_filter_script()],
                                  input=message+'\n',capture_output=True,text=True,check=True)
        assert json.loads(filtered.stdout)==dict(scoped_gpu_error_lines=gpu_errors,kernel_failure_lines=kernel_errors)
        assert not filtered.stderr
        if message:
            assert message not in filtered.stdout
    print(f'Actual native-GPU predicate: full pixel marker, CPU release, zero codec work, real GPU jobs and scalar kernel health; {rejected} incomplete/unsafe cases rejected: PASS')


def check_native_gpu(source):
    """Run the production ioctl/tiling/fork/exec path with real file aliases."""
    code = ('#define ioctl fake_ioctl\n#define main request_program_main\n'
            '#define close fake_close\n#define read fake_read\n#define write fake_write\n'
            '#define waitpid fake_waitpid\n')
    code += '#include '+json.dumps(str(source.resolve()))+'\n'
    code += r'''
#undef main
#undef close
#undef read
#undef write
#undef waitpid
extern int close(int);
extern ssize_t read(int, void *, size_t);
extern ssize_t write(int, const void *, size_t);
extern pid_t waitpid(pid_t, int *, int);
#include <assert.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdarg.h>
static unsigned fault, exports, syncs;
static int backing, video_fd, media_fd, export_fds[2];
static pid_t parent;
static _Atomic unsigned *events;
int fake_close(int fd)
{
    int owner=exports==2 && syncs==2 && getpid()==parent &&
              (fd==video_fd || fd==media_fd || fd==export_fds[0] || fd==export_fds[1]);
    if (owner && fd==media_fd) {
        /* Force exec to race this live parent owner unless the actual child
         * enters its gate read. An ungated helper snapshots once, then signals.
         */
        for (unsigned attempt=0; !atomic_load(events) && !atomic_load(events+1); attempt++) {
            assert(attempt<1000);
            struct timespec pause={.tv_nsec=1000000}; nanosleep(&pause,NULL);
        }
    }
    int result=close(fd);
    if (owner) {
        atomic_fetch_add(events+2,1);
        if (fd==media_fd && (fault==10 || fault==11)) {
            assert(!result); errno=fault==10 ? EIO : EINTR; return -1;
        }
    }
    return result;
}
ssize_t fake_read(int fd, void *buffer, size_t bytes)
{
    if (getpid()!=parent) {
        assert(bytes==1);
        unsigned reads=atomic_fetch_add(events,1);
        if (fault==13 && !reads) { errno=EINTR; return -1; }
    }
    return read(fd,buffer,bytes);
}
ssize_t fake_write(int fd, const void *buffer, size_t bytes)
{
    static unsigned writes;
    assert(getpid()==parent && bytes==1);
    if (fault==12 && !writes++) { errno=EINTR; return -1; }
    if (fault==14) { assert(!raise(SIGPIPE)); errno=EPIPE; return -1; }
    return write(fd,buffer,bytes);
}
pid_t fake_waitpid(pid_t child, int *status, int options)
{
    static unsigned waits;
    if (fault==15 && !waits++) { errno=EINTR; return -1; }
    pid_t result=waitpid(child,status,options);
    if (result==child) atomic_store(events+3,1);
    return result;
}
int fake_ioctl(int fd, unsigned long command, ...)
{
    va_list args; va_start(args, command); void *arg = va_arg(args, void *); va_end(args);
    if (command == VIDIOC_QUERYCAP) {
        strcpy((char *)((struct v4l2_capability *)arg)->driver, fault==1 ? "foreign" : "mt6797-vdec");
        char value[32]; snprintf(value, sizeof(value), "%d", fd);
        assert(!setenv("TEST_VIDEO_FD", value, 1));
        /* open_device opens media immediately after video. */
        snprintf(value, sizeof(value), "%d", fd+1); assert(!setenv("TEST_MEDIA_FD", value, 1));
        video_fd=fd; media_fd=fd+1;
    } else if (command == VIDIOC_S_FMT) {
        struct v4l2_format *f=arg;
        assert(f->type==V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE && f->fmt.pix_mp.width==80 && f->fmt.pix_mp.height==64);
    } else if (command == VIDIOC_G_FMT) {
        struct v4l2_format *f=arg;
        assert(f->type==V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE);
        f->fmt.pix_mp.width=80; f->fmt.pix_mp.height=64; f->fmt.pix_mp.num_planes=2;
        f->fmt.pix_mp.pixelformat=fault==2 ? V4L2_PIX_FMT_NV12 : V4L2_PIX_FMT_MM21;
        f->fmt.pix_mp.plane_fmt[0].sizeimage=5120; f->fmt.pix_mp.plane_fmt[1].sizeimage=7680;
        if (fault==3) f->fmt.pix_mp.plane_fmt[1].sizeimage=2560;
    } else if (command == VIDIOC_CREATE_BUFS) {
        struct v4l2_create_buffers *c=arg;
        assert(c->count==1 && c->memory==V4L2_MEMORY_MMAP && c->format.fmt.pix_mp.plane_fmt[1].sizeimage==7680);
        c->index=fault==4; if (fault==5) c->count=2;
    } else if (command == VIDIOC_QUERYBUF) {
        struct v4l2_buffer *b=arg;
        assert(b->index==0 && b->length==2 && b->memory==V4L2_MEMORY_MMAP);
        b->m.planes[0].length=5120; b->m.planes[1].length=7680;
        b->m.planes[1].bytesused=b->m.planes[1].data_offset=5120;
        if (fault==6) b->m.planes[0].length--;
        if (fault==7) b->m.planes[1].data_offset=0;
        if (fault==8) b->m.planes[1].bytesused++;
    } else if (command == VIDIOC_EXPBUF) {
        struct v4l2_exportbuffer *e=arg;
        assert(e->type==V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE && e->index==0);
        assert(e->plane==exports && e->flags==(O_RDWR|O_CLOEXEC));
        e->fd=fcntl(backing, F_DUPFD_CLOEXEC, 3); assert(e->fd>=3);
        export_fds[exports]=e->fd;
        if (++exports==2) { assert(!close(backing)); backing=-1; }
    } else if (command == DMA_BUF_IOCTL_SYNC) {
        struct dma_buf_sync *s=arg; assert(exports==2 && syncs<2);
        assert(s->flags==(syncs ? DMA_BUF_SYNC_END|DMA_BUF_SYNC_WRITE : DMA_BUF_SYNC_START|DMA_BUF_SYNC_WRITE));
        syncs++;
    } else assert(!"Unexpected ioctl in native GPU input path");
    return 0;
}
int main(int argc, char **argv)
{
    assert(argc==4); fault=strtoul(argv[2], NULL, 10);
    char path[1024], video[1024], media[1024];
    parent=getpid();
    int event_fd=open(getenv("TEST_EVENT_PATH"),O_RDWR|O_CREAT|O_EXCL|O_CLOEXEC,0600);
    assert(event_fd>=3 && !ftruncate(event_fd,4*sizeof(*events)));
    events=mmap(NULL,4*sizeof(*events),PROT_READ|PROT_WRITE,MAP_SHARED,event_fd,0);
    assert(events!=MAP_FAILED && !close(event_fd));
    for (unsigned i=0;i<4;i++) atomic_init(events+i,0);
    snprintf(path,sizeof(path),"%s/backing",argv[1]);
    backing=open(path,O_RDWR|O_CREAT|O_EXCL|O_CLOEXEC,0600); assert(backing>=3); assert(!unlink(path));
    size_t capacity=fault==9 ? 131072 : 196608;
    assert(!ftruncate(backing,capacity));
    void *data=mmap(NULL,capacity,PROT_READ|PROT_WRITE,MAP_SHARED,backing,0); assert(data!=MAP_FAILED);
    memset(data,0xa5,capacity); assert(!munmap(data,capacity));
    snprintf(video,sizeof(video),"%s/video",argv[1]); snprintf(media,sizeof(media),"%s/media",argv[1]);
    int fd=open(video,O_WRONLY|O_CREAT|O_EXCL,0600); assert(fd>=0); assert(!close(fd));
    fd=open(media,O_WRONLY|O_CREAT|O_EXCL,0600); assert(fd>=0); assert(!close(fd));
    width=80; height=storage_height=64;
    struct sigaction before,after;
    assert(!sigaction(SIGPIPE,NULL,&before));
    test_native_gpu(video,media,"render",argv[3],argv[1]);
    assert(exports==2 && syncs==2 && backing==-1);
    assert(atomic_load(events)>=1 && atomic_load(events+1)==1 &&
           atomic_load(events+2)==4 && atomic_load(events+3)==1);
    assert(!sigaction(SIGPIPE,NULL,&after) && before.sa_handler==after.sa_handler);
    return 0;
}
'''
    helper = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
int main(int argc,char **argv)
{
    assert(argc==5 && !strcmp(argv[1],"render") && !strcmp(argv[2],"--native-mm21"));
    int fd[2]={atoi(argv[3]),atoi(argv[4])}; assert(fd[0]>=3 && fd[1]>=3 && fd[0]!=fd[1]);
    int video=atoi(getenv("TEST_VIDEO_FD")),media=atoi(getenv("TEST_MEDIA_FD"));
    assert(fcntl(video,F_GETFD)==-1 && errno==EBADF);
    assert(fcntl(media,F_GETFD)==-1 && errno==EBADF);
    assert(fcntl(fd[0],F_GETFD)==0 && fcntl(fd[1],F_GETFD)==0);
    struct stat a,b; assert(!fstat(fd[0],&a) && !fstat(fd[1],&b));
    assert(a.st_dev==b.st_dev && a.st_ino==b.st_ino && a.st_size==196608);
    /* Observe once at helper entry; waiting for the parent would mask the race. */
    int owners[]={video,media,fd[0],fd[1]};
    unsigned live=0;
    for (unsigned i=0;i<4;i++) {
        char p[128]; snprintf(p,sizeof(p),"/proc/%d/fd/%d",(int)getppid(),owners[i]);
        if (!access(p,F_OK)) live++;
    }
    int event_fd=open(getenv("TEST_EVENT_PATH"),O_RDWR|O_CLOEXEC); assert(event_fd>=3);
    _Atomic unsigned *events=mmap(NULL,4*sizeof(*events),PROT_READ|PROT_WRITE,MAP_SHARED,event_fd,0);
    assert(events!=MAP_FAILED && !close(event_fd));
    atomic_fetch_add(events+1,1);
    assert(!live && "Helper entered before parent owner release");
    uint8_t *data=mmap(NULL,196608,PROT_READ,MAP_SHARED,fd[1],0); assert(data!=MAP_FAILED);
    static const uint8_t colors[][3]={{81,90,240},{145,54,34},{41,240,110},{128,128,128}};
    /* Inverse byte-to-pixel oracle is independent of the production addressing loops. */
    for (size_t i=0;i<5120;i++) {
        unsigned tile=i/512, local=i%512;
        unsigned x=16*(tile%5)+local%16, y=32*(tile/5)+local/16;
        assert(data[i]==colors[(x/8+3*(y/8))%4][0]);
    }
    for (size_t i=0;i<2560;i++) {
        unsigned tile=i/256, local=i%256;
        unsigned x=8*(tile%5)+(local%16)/2,y=16*(tile/5)+local/16;
        assert(data[5120+i]==colors[(x/4+3*(y/4))%4][1+i%2]);
    }
    for (size_t i=7680;i<196608;i++) assert(data[i]==0xa5);
    assert(!munmap(data,196608)); assert(!close(fd[0]) && !close(fd[1]));
    const char *failure=getenv("TEST_HELPER_FAIL");
    return failure ? atoi(failure) : 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='vdec-native-gpu-host-') as tmp:
        path = Path(tmp)
        compiler = shlex.split(os.environ.get('HOSTCC', os.environ.get('CC', 'cc')))
        flags = shlex.split(os.environ.get('CFLAGS', ''))
        for name, text in (('input', code), ('helper', helper)):
            (path/(name+'.c')).write_text(text)
            subprocess.run(compiler+['-std=gnu11', '-Wall', '-Wextra', '-Werror']+flags+
                           [str(path/(name+'.c')), '-o', str(path/name)], check=True)
        print('Compiled actual native-GPU parent and single-shot ownership helper: PASS', flush=True)
        def run(name, fault=0, executable=None, failure=None):
            out=path/name; out.mkdir()
            env=os.environ.copy()
            env['TEST_EVENT_PATH']=str(out/'host-events')
            if failure is not None: env['TEST_HELPER_FAIL']=str(failure)
            return subprocess.run([str(path/'input'), str(out), str(fault),
                                   str(executable or path/'helper')], env=env,
                                  capture_output=True, text=True, timeout=8)
        good=run('good')
        helper_log=path/'good/native-gpu.txt'
        assert good.returncode==0, good.stderr+(helper_log.read_text() if helper_log.exists() else '')
        record=json.loads(good.stdout)
        assert record['parent_refs_released'] is True and record['pixels']==5120 and record['codec_submissions']==0
        for fault in (12,13,15):
            retried=run('retry-'+str(fault),fault)
            assert retried.returncode==0, (fault,retried.stderr)
        for fault in range(1,10):
            bad=run('fault-'+str(fault),fault)
            assert bad.returncode==1 and not bad.stdout, (fault,bad)
        for name, executable, failure in (('nonzero',None,7),('missing',path/'absent',None)):
            bad=run(name,executable=executable,failure=failure)
            assert bad.returncode==1 and not bad.stdout and 'retain module' in bad.stderr, bad
        for fault in (10,11,14):
            name='release-'+str(fault); bad=run(name,fault)
            assert bad.returncode==1 and not bad.stdout and 'GPU parent release' in bad.stderr, (fault,bad)
            event=(path/name/'host-events').read_bytes()
            assert len(event)==16
            values=[int.from_bytes(event[i:i+4],byteorder='little') for i in range(0,16,4)]
            assert values[0]>=1 and values[1:]==[0,4,1], (fault,values)
    print('Actual native-GPU input: typed layout/tiling, deterministic parent-release gate and single-shot helper ownership, EINTR/SIGPIPE handling and reaped no-exec failures; 14 invalid/device/helper/release cases rejected: PASS')


def check_capture(source):
    """Run actual buffer selection, pixel access, sync and DQBUF validation."""
    code = '#define ioctl fake_ioctl\n#define main request_program_main\n'
    code += '#include ' + json.dumps(str(source.resolve())) + '\n'
    code += r'''
#undef main
#include <assert.h>
#include <stdarg.h>
static unsigned calls, retries, fault;
static uint64_t sync_flags[16];
static struct stream *current;
int fake_ioctl(int fd, unsigned long command, ...)
{
    va_list args;
    va_start(args, command);
    void *arg = va_arg(args, void *);
    va_end(args);
    if (command == DMA_BUF_IOCTL_SYNC) {
        assert(fd == 10 || fd == 11);
        if (retries) {
            errno = --retries ? EINTR : EAGAIN;
            return -1;
        }
        assert(calls < 16);
        sync_flags[calls++] = ((struct dma_buf_sync *)arg)->flags;
        return 0;
    }
    assert(command == VIDIOC_DQBUF);
    struct v4l2_buffer *b = arg;
    size_t luma = width * storage_height;
    b->index = current->capture_index;
    b->timestamp.tv_sec = 2;
    b->sequence = 7;
    for (unsigned i = 0; i < 2; i++) {
        b->m.planes[i].length = current->capture[i].bytes;
        b->m.planes[i].data_offset = current->capture[i].data_offset;
        b->m.planes[i].bytesused = b->m.planes[i].data_offset + luma / (i ? 2 : 1);
    }
    switch (fault) {
    case 1: b->m.planes[1].bytesused = luma / 2; break;
    case 2: b->m.planes[1].data_offset = b->m.planes[1].length + 1; break;
    case 3: b->m.planes[0].bytesused = b->m.planes[0].length + 1; break;
    case 4: b->timestamp.tv_sec++; break;
    case 5: b->index = CAPTURE_COUNT; break;
    case 6: case 7: case 8:
        b->flags |= V4L2_BUF_FLAG_ERROR;
        b->m.planes[0].bytesused = fault == 7;
        b->m.planes[1].bytesused = fault == 8 ? 0 : b->m.planes[1].data_offset;
        break;
    }
    return 0;
}
int main(void)
{
    const char *safe[] = {
        "fetched=0 submitted=0 quiesced=0 guards=0 break=0 reset=0",
        "jobs=1 fetched=1 submitted=1 quiesced=1 guards=1 break=0 reset=0 result=0",
        "fetched=1 submitted=0 quiesced=1 guards=1 break=-110 reset=0\n",
    };
    const char *unsafe[] = {
        "", "fetched=0 submitted=0 quiesced=0",
        "fetched=1 submitted=1 quiesced=0 guards=1",
        "fetched=1 submitted=1 quiesced=1 guards=0",
        "fetched=1 submitted=0 quiesced=0 guards=1",
        "fetched=0 submitted=1 quiesced=0 guards=1",
        "fetched=0 submitted=0 quiesced=0 guards=0 fetched=0",
        "fetched=2 submitted=0 quiesced=1 guards=1",
        "fetched=0x0 submitted=0 quiesced=0 guards=0",
        "fetched=0 submitted=0 quiesced=0 guards=bad",
        "xfetched=0 submitted=0 quiesced=0 guards=0",
        "fetched=0 submitted=0 quiesced=0 guards=0 break=0 reset=-110",
        "fetched=0 submitted=0 quiesced=0 guards=0 break=-110 reset=0",
        "fetched=0 submitted=0 quiesced=0 guards=0 reset=0",
        "fetched=0 submitted=0 quiesced=0 guards=0 break=0",
        "fetched=0 submitted=0 quiesced=0 guards=0 break=0 reset=0 reset=0",
        "fetched=0 submitted=0 quiesced=0 guards=0 break=0 reset=0x0",
    };
    for (unsigned i = 0; i < sizeof(safe)/sizeof(safe[0]); i++)
        assert(cached_cpu_access_safe(safe[i]));
    for (unsigned i = 0; i < sizeof(unsafe)/sizeof(unsafe[0]); i++)
        assert(!cached_cpu_access_safe(unsafe[i]));
    struct stream stream = { .capture_count = CAPTURE_COUNT };
    struct v4l2_ctrl_h264_decode_params params = { 0 };
    for (unsigned i = 0; i < V4L2_H264_NUM_DPB_ENTRIES; i++) {
        stream.timestamps[i] = (i + 1) * 1000000000ULL;
        params.dpb[i].reference_ts = stream.timestamps[i];
        params.dpb[i].flags = V4L2_H264_DPB_ENTRY_FLAG_VALID | V4L2_H264_DPB_ENTRY_FLAG_ACTIVE;
    }
    select_capture(&stream, &params);
    assert(stream.capture_index == V4L2_H264_NUM_DPB_ENTRIES);
    assert(stream.capture == stream.storage[V4L2_H264_NUM_DPB_ENTRIES]);
    for (unsigned i = 0; i < V4L2_H264_NUM_DPB_ENTRIES; i++)
        assert(stream.timestamps[i] == (i + 1) * 1000000000ULL);
    params.dpb[3].flags &= ~V4L2_H264_DPB_ENTRY_FLAG_ACTIVE;
    select_capture(&stream, &params);
    assert(stream.capture_index == 3 && !stream.timestamps[3]);
    width = 80;
    storage_height = 64; /* Non-page-aligned chroma offset. */
    size_t luma = width * storage_height, backing = 3 * 65536;
    u8 *pixels = malloc(backing);
    assert(pixels);
    memset(pixels, 0xa5, backing);
    for (unsigned i = 0; i < 2; i++)
        stream.capture[i] = (struct mapping) {
            .address = pixels, .bytes = backing, .data_offset = i ? luma : 0, .fd = 10 + i,
        };
    retries = 2;
    fill_capture(&stream);
    assert(!retries && calls == 4);
    assert(sync_flags[0] == (DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE));
    assert(sync_flags[1] == sync_flags[0]);
    assert(sync_flags[2] == (DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE));
    assert(sync_flags[3] == sync_flags[2]);
    for (size_t i = 0; i < backing; i++) assert(pixels[i] == (i < luma * 3 / 2 ? 0x79 : 0xa5));
    calls = 0;
    capture_untouched(&stream);
    assert(calls == 4 && sync_flags[0] == DMA_BUF_SYNC_READ &&
           sync_flags[2] == (DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ));
    current = &stream;
    assert(!dequeue(&stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, 0, 2, 7));
    assert(stream.timestamps[3] == 2000000000ULL);
    for (fault = 1; fault <= 5; fault++)
        assert(dequeue(&stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, 0, 2, 7));
    fault = 6;
    assert(!dequeue(&stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, 1, 2, 7));
    assert(dequeue(&stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, 0, 2, 7));
    fault = 7;
    assert(dequeue(&stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, 1, 2, 7));
    fault = 8;
    assert(dequeue(&stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, 1, 2, 7));
    calls = 0;
    stream.capture[0].fd = stream.capture[1].fd = -1;
    fill_capture(&stream);
    assert(!calls);
    free(pixels);
    puts("Actual capture: active DPB lifetime, aliased plane offsets, cache sync/retries and metadata rejection: PASS");
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='vdec-capture-host-') as tmp:
        path = Path(tmp)
        (path/'capture.c').write_text(code)
        compiler = shlex.split(os.environ.get('HOSTCC', os.environ.get('CC', 'cc')))
        flags = shlex.split(os.environ.get('CFLAGS', ''))
        subprocess.run(compiler + ['-std=gnu11', '-Wall', '-Wextra', '-Werror'] + flags +
                       [str(path/'capture.c'), '-o', str(path/'capture')], check=True)
        subprocess.run([str(path/'capture')], check=True)


def check_native_buffers(source):
    """Run the actual zero-command mode with instrumented public ioctls."""
    code = r'''
#define ioctl native_ioctl
#define open native_open
#define close native_close
#define mmap native_mmap
#define munmap native_munmap
#define main request_program_main
'''
    code += '#include ' + json.dumps(str(source.resolve())) + '\n'
    code += r'''
#undef main
#include <assert.h>
#include <stdarg.h>
static u8 *data[CAPTURE_COUNT];
static unsigned maps[CAPTURE_COUNT], cpu[CAPTURE_COUNT], queued[CAPTURE_COUNT];
static unsigned fd_live[CAPTURE_COUNT][2], gem_live[CAPTURE_COUNT];
static unsigned video_live, media_live, gpu_live, fault, qbufs, imports, releases;
static const size_t backing = 196608;
int native_open(const char *path, int flags, ...)
{
    assert(flags & O_CLOEXEC);
    if (!strcmp(path, "video")) { video_live = 1; return 1; }
    if (!strcmp(path, "media")) { media_live = 1; return 2; }
    assert(!strcmp(path, "render")); gpu_live = 1; return 3;
}
int native_close(int fd)
{
    if (fd == 1) {
        assert(video_live && !media_live && qbufs == CAPTURE_COUNT);
        for (unsigned i = 0; i < CAPTURE_COUNT; i++) {
            assert(queued[i] && maps[i] == 2 && !cpu[i]);
            queued[i] = 0;
        }
        if (fault == 7) data[0][0] ^= 1;
        video_live = 0;
    } else if (fd == 2) { assert(media_live); media_live = 0; }
    else if (fd == 3) {
        assert(gpu_live && releases == CAPTURE_COUNT); gpu_live = 0;
    } else {
        unsigned index = (fd - 10) / 2, plane = (fd - 10) % 2;
        assert(index < CAPTURE_COUNT && fd_live[index][plane] && !cpu[index]);
        fd_live[index][plane] = 0;
    }
    return 0;
}
void *native_mmap(void *address, size_t length, int prot, int flags, int fd, off_t offset)
{
    (void)address;
    assert(length == backing && prot == (PROT_READ|PROT_WRITE) && flags == MAP_SHARED);
    unsigned index;
    if (fd == 1) {
        assert(video_live && offset >= (off_t)backing && offset % backing == 0);
        index = (offset / backing - 1) / 2;
    } else {
        index = (fd - 10) / 2;
        assert(index < CAPTURE_COUNT && fd_live[index][(fd - 10) % 2] && !offset);
    }
    assert(index < CAPTURE_COUNT);
    maps[index]++;
    return data[index];
}
int native_munmap(void *address, size_t length)
{
    assert(length == backing);
    for (unsigned i = 0; i < CAPTURE_COUNT; i++) if (address == data[i]) {
        assert(maps[i]); maps[i]--; return 0;
    }
    abort();
}
int native_ioctl(int fd, unsigned long command, ...)
{
    va_list args; va_start(args, command); void *arg = va_arg(args, void *); va_end(args);
    if (command == VIDIOC_QUERYCAP) {
        assert(fd == 1 && video_live);
        strcpy((char *)((struct v4l2_capability *)arg)->driver, "mt6797-vdec");
    } else if (command == VIDIOC_G_FMT || command == VIDIOC_TRY_FMT || command == VIDIOC_S_FMT) {
        struct v4l2_format *f = arg;
        assert(fd == 1 && video_live);
        f->fmt.pix_mp.width = 80; f->fmt.pix_mp.height = 64;
        f->fmt.pix_mp.pixelformat = f->type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE ?
            V4L2_PIX_FMT_MM21 : V4L2_PIX_FMT_H264_SLICE;
        f->fmt.pix_mp.num_planes = 2;
        f->fmt.pix_mp.plane_fmt[0].sizeimage = 5120;
        f->fmt.pix_mp.plane_fmt[1].sizeimage = 7680;
    } else if (command == VIDIOC_REQBUFS) {
        struct v4l2_requestbuffers *b = arg;
        assert(fd == 1 && b->type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE &&
               b->memory == V4L2_MEMORY_MMAP && b->count == CAPTURE_COUNT);
        if (fault == 1) b->count--;
    } else if (command == VIDIOC_QUERYBUF) {
        struct v4l2_buffer *b = arg;
        assert(fd == 1 && b->index < CAPTURE_COUNT && b->length == 2);
        for (unsigned p = 0; p < 2; p++) {
            b->m.planes[p].length = backing;
            b->m.planes[p].data_offset = b->m.planes[p].bytesused = p ? 5120 : 0;
            b->m.planes[p].m.mem_offset = (b->index * 2 + p + 1) * backing;
        }
        if (fault == 2) b->m.planes[1].bytesused = 0;
    } else if (command == VIDIOC_EXPBUF) {
        struct v4l2_exportbuffer *b = arg;
        assert(fd == 1 && b->index < CAPTURE_COUNT && b->plane < 2 &&
               b->flags == (O_RDWR|O_CLOEXEC));
        assert(!fd_live[b->index][b->plane]);
        fd_live[b->index][b->plane] = 1;
        b->fd = 10 + b->index * 2 + b->plane;
    } else if (command == DRM_IOCTL_VERSION) {
        struct drm_version *v = arg;
        assert(fd == 3 && gpu_live && v->name_len >= 8);
        strcpy(v->name, fault == 3 ? "foreign" : "panfrost"); v->name_len = strlen(v->name);
    } else if (command == DRM_IOCTL_PRIME_FD_TO_HANDLE) {
        struct drm_prime_handle *p = arg;
        unsigned i = (p->fd - 10) / 2, plane = (p->fd - 10) % 2;
        assert(fd == 3 && gpu_live && i < CAPTURE_COUNT && fd_live[i][plane]);
        p->handle = i + 1;
        if (fault == 4 && plane) p->handle += CAPTURE_COUNT;
        if (fault == 5) p->handle = 1;
        gem_live[i] = 1; imports++;
    } else if (command == DRM_IOCTL_PANFROST_GET_BO_OFFSET) {
        struct drm_panfrost_get_bo_offset *p = arg;
        assert(fd == 3 && gpu_live && p->handle && p->handle <= CAPTURE_COUNT);
        assert(gem_live[p->handle - 1]);
        p->offset = fault == 6 ? 0 : p->handle * 0x100000;
    } else if (command == DMA_BUF_IOCTL_SYNC) {
        struct dma_buf_sync *s = arg;
        unsigned i = (fd - 10) / 2, plane = (fd - 10) % 2;
        assert(i < CAPTURE_COUNT && fd_live[i][plane]);
        assert((s->flags & DMA_BUF_SYNC_RW) == DMA_BUF_SYNC_RW ||
               (s->flags & DMA_BUF_SYNC_RW) == DMA_BUF_SYNC_READ);
        if (s->flags & DMA_BUF_SYNC_END) { assert(cpu[i]); cpu[i]--; }
        else {
            if (fault == 8 && cpu[i] && data[i][0]) memset(data[i], 0, backing);
            cpu[i]++;
        }
    } else if (command == VIDIOC_QBUF) {
        struct v4l2_buffer *b = arg;
        assert(fd == 1 && video_live && b->type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE &&
               b->index < CAPTURE_COUNT && b->length == 2 && !cpu[b->index]);
        assert(!queued[b->index]); queued[b->index] = 1; qbufs++;
    } else if (command == DRM_IOCTL_GEM_CLOSE) {
        struct drm_gem_close *b = arg;
        assert(fd == 3 && gpu_live && b->handle && b->handle <= CAPTURE_COUNT);
        assert(gem_live[b->handle - 1]); gem_live[b->handle - 1] = 0; releases++;
    } else {
        /* No STREAMON, Request, source QBUF, GPU submit or decoder command. */
        fprintf(stderr, "Unexpected ioctl %lu\n", command); abort();
    }
    return 0;
}
int main(int argc, char **argv)
{
    assert(argc == 2); fault = strtoul(argv[1], NULL, 10);
    for (unsigned i = 0; i < CAPTURE_COUNT; i++) { data[i] = calloc(1, backing); assert(data[i]); }
    struct stream stream;
    width = 80; height = storage_height = 64; buffers_only = create_buffers_checked = 1;
    test_native_buffers(&stream, "video", "media", "render");
    assert(imports == CAPTURE_COUNT * 2 && releases == CAPTURE_COUNT && qbufs == CAPTURE_COUNT);
    assert(!video_live && !media_live && !gpu_live);
    for (unsigned i = 0; i < CAPTURE_COUNT; i++) {
        assert(!maps[i] && !cpu[i] && !fd_live[i][0] && !fd_live[i][1] && !gem_live[i]);
        free(data[i]);
    }
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='vdec-native-buffers-host-') as tmp:
        path = Path(tmp); (path/'buffers.c').write_text(code)
        compiler = shlex.split(os.environ.get('HOSTCC', os.environ.get('CC', 'cc')))
        flags = shlex.split(os.environ.get('CFLAGS', ''))
        subprocess.run(compiler + ['-std=gnu11', '-Wall', '-Wextra', '-Werror'] + flags +
                       [str(path/'buffers.c'), '-o', str(path/'buffers')], check=True)
        result = subprocess.run([str(path/'buffers'), '0'], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['native_buffers_test_passed'] and report['scope'] == 'native-buffers'
        assert report['codec_submissions'] == report['gpu_submissions'] == 0
        for fault, message in ((1, 'Queue does not support'), (2, 'Unexpected queried'),
                               (3, 'Unexpected render driver'), (4, 'different GEM handles'),
                               (5, 'Distinct capture'), (6, 'Invalid native GPU'),
                               (7, 'Native capture alias contents differ'),
                               (8, 'Native capture alias contents differ')):
            result = subprocess.run([str(path/'buffers'), str(fault)], capture_output=True, text=True)
            assert result.returncode != 0 and message in result.stderr, (fault, result.stderr)
    print('Actual native mode: layouts, 17 aliased PRIME imports, nested CPU access, queue/close lifetimes and release; eight faulty-device cases rejected: PASS')


def check_create_buffers(source):
    """Run the actual CREATE_BUFS exerciser against a bounded ioctl device."""
    code = r'''
#define ioctl create_ioctl
#define open create_open
#define close create_close
#define mmap create_mmap
#define munmap create_munmap
#define lseek create_lseek
#define main request_program_main
'''
    code += '#include ' + json.dumps(str(source.resolve())) + '\n'
    code += r'''
#undef main
#include <assert.h>
#include <stdarg.h>
static const unsigned lengths[4][2] = {
    {5120,7680}, {196609,204801}, {208897,196611}, {196608,196608}
};
static const size_t capacities[4] = {196608,208896,212992,196608};
static const size_t mmap_lengths[4][2] = {
    {8192,8192}, {200704,208896}, {212992,200704}, {196608,196608}
};
static u8 *data[4], *foreign;
static unsigned allocated, invalid, queries, exported, qbufs, map_count[4], cpu[4];
static unsigned fd_live[4][2], queued[4], video_live, media_live, released, fault;
int create_open(const char *path, int flags, ...) {
    assert(flags & O_CLOEXEC);
    if (!strcmp(path,"video")) { assert(!video_live); video_live=1; return 1; }
    assert(!strcmp(path,"media") && !media_live); media_live=1; return 2;
}
int create_close(int fd) {
    if (fd == 1) { assert(video_live && !media_live && released); video_live=0; }
    else if (fd == 2) { assert(media_live && released); media_live=0; }
    else {
        unsigned i=(fd-10)/2, p=(fd-10)%2;
        assert(i<4 && fd_live[i][p] && !cpu[i]); fd_live[i][p]=0;
    }
    return 0;
}
off_t create_lseek(int fd, off_t offset, int whence) {
    unsigned i=(fd-10)/2, p=(fd-10)%2;
    assert(i<4 && fd_live[i][p] && !offset && whence==SEEK_END);
    return capacities[i] + (fault==5 ? 4096 : 0);
}
void *create_mmap(void *address, size_t length, int prot, int flags, int fd, off_t offset) {
    (void)address;
    assert(prot==(PROT_READ|PROT_WRITE) && flags==MAP_SHARED);
    unsigned i,p;
    if (fd==1) {
        assert(video_live && offset>=0x100000 && offset%0x100000==0);
        i=(offset/0x100000-1)/2; p=(offset/0x100000-1)%2;
        assert(i<4 && length==mmap_lengths[i][p]);
    } else {
        i=(fd-10)/2; p=(fd-10)%2;
        assert(i<4 && fd_live[i][p] && !offset && length==capacities[i]);
    }
    map_count[i]++;
    return fault==7 && i==0 && fd!=1 && p ? foreign : data[i];
}
int create_munmap(void *address, size_t length) {
    for (unsigned i=0;i<4;i++) if (address==data[i] || (i==0 && address==foreign)) {
        assert(map_count[i] && length<=capacities[i]); map_count[i]--; return 0;
    }
    abort();
}
int create_ioctl(int fd, unsigned long command, ...) {
    va_list args; va_start(args,command); void *arg=va_arg(args,void*); va_end(args);
    if (command==VIDIOC_QUERYCAP) {
        assert(fd==1 && video_live);
        strcpy((char*)((struct v4l2_capability*)arg)->driver,"mt6797-vdec");
    } else if (command==VIDIOC_S_FMT || command==VIDIOC_G_FMT) {
        struct v4l2_format *f=arg;
        assert(fd==1 && video_live);
        f->fmt.pix_mp.width=80; f->fmt.pix_mp.height=64;
        f->fmt.pix_mp.pixelformat=f->type==V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE ?
            V4L2_PIX_FMT_MM21 : V4L2_PIX_FMT_H264_SLICE;
        f->fmt.pix_mp.num_planes=2;
        f->fmt.pix_mp.plane_fmt[0].sizeimage=5120;
        f->fmt.pix_mp.plane_fmt[1].sizeimage=7680;
    } else if (command==VIDIOC_CREATE_BUFS) {
        struct v4l2_create_buffers *c=arg;
        assert(fd==1 && video_live && c->count==1 && c->memory==V4L2_MEMORY_MMAP &&
               c->format.type==V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE && c->format.fmt.pix_mp.num_planes==2);
        if (invalid<5) {
            static const unsigned bad[5][2]={{5120,2560},{5119,7680},{196608,7679},
                                             {UINT32_MAX,196608},{196608,UINT32_MAX}};
            assert(c->format.fmt.pix_mp.plane_fmt[0].sizeimage==bad[invalid][0] &&
                   c->format.fmt.pix_mp.plane_fmt[1].sizeimage==bad[invalid][1]);
            invalid++;
            if (fault==1) return 0;
            errno=fault==2 ? ENOMEM : EINVAL; return -1;
        }
        assert(allocated<4);
        for (unsigned p=0;p<2;p++)
            assert(c->format.fmt.pix_mp.plane_fmt[p].sizeimage==lengths[allocated][p]);
        c->index=allocated++; if (fault==3) c->format.fmt.pix_mp.plane_fmt[0].sizeimage++;
    } else if (command==VIDIOC_QUERYBUF) {
        struct v4l2_buffer *b=arg;
        assert(fd==1 && allocated==4 && b->index<4 && b->length==2); queries++;
        for (unsigned p=0;p<2;p++) {
            b->m.planes[p].length=lengths[b->index][p];
            b->m.planes[p].data_offset=b->m.planes[p].bytesused=p ? 5120 : 0;
            b->m.planes[p].m.mem_offset=(b->index*2+p+1)*0x100000;
        }
        if (fault==4) b->m.planes[0].length++;
    } else if (command==VIDIOC_EXPBUF) {
        struct v4l2_exportbuffer *e=arg;
        assert(fd==1 && e->index<4 && e->plane<2 && e->flags==(O_RDWR|O_CLOEXEC));
        assert(!fd_live[e->index][e->plane]); fd_live[e->index][e->plane]=1;
        exported++; e->fd=10+e->index*2+e->plane;
    } else if (command==DMA_BUF_IOCTL_SYNC) {
        unsigned i=(fd-10)/2,p=(fd-10)%2; struct dma_buf_sync *s=arg;
        assert(i<4 && fd_live[i][p]);
        if (s->flags&DMA_BUF_SYNC_END) { assert(cpu[i]); cpu[i]--; }
        else { if (fault==8 && cpu[i]) memset(data[i],0,capacities[i]); cpu[i]++; }
    } else if (command==VIDIOC_QBUF) {
        struct v4l2_buffer *b=arg;
        assert(fd==1 && b->index<4 && !cpu[b->index] && !queued[b->index]);
        assert(b->m.planes[0].length==lengths[b->index][0] &&
               b->m.planes[1].length==lengths[b->index][1]);
        if (fault==9) { errno=EINVAL; return -1; }
        queued[b->index]=1; qbufs++;
    } else if (command==VIDIOC_REQBUFS) {
        struct v4l2_requestbuffers *r=arg;
        assert(fd==1 && r->type==V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE &&
               r->memory==V4L2_MEMORY_MMAP && !r->count && qbufs==4);
        for (unsigned i=0;i<4;i++) {
            assert(queued[i] && !map_count[i] && !cpu[i] && !fd_live[i][0] && !fd_live[i][1]);
            queued[i]=0;
        }
        released=1;
    } else { fprintf(stderr,"Unexpected CREATE_BUFS ioctl %lu\n",command); abort(); }
    return 0;
}
int main(int argc,char **argv) {
    assert(argc==2); fault=strtoul(argv[1],NULL,10);
    for (unsigned i=0;i<4;i++) { data[i]=calloc(1,capacities[i]); assert(data[i]); }
    foreign=calloc(1,capacities[0]); assert(foreign);
    if (fault==6) data[0][capacities[0]-1]=1;
    width=80; height=storage_height=64;
    test_create_buffers("video","media");
    assert(create_buffers_checked && allocated==4 && invalid==5 && queries==4 && exported==8);
    assert(qbufs==4 && released && !video_live && !media_live);
    for (unsigned i=0;i<4;i++) free(data[i]);
    free(foreign); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='vdec-create-buffers-host-') as tmp:
        path = Path(tmp); (path/'create.c').write_text(code)
        compiler = shlex.split(os.environ.get('HOSTCC', os.environ.get('CC', 'cc')))
        flags = shlex.split(os.environ.get('CFLAGS', ''))
        subprocess.run(compiler + ['-std=gnu11', '-Wall', '-Wextra', '-Werror'] + flags +
                       [str(path/'create.c'), '-o', str(path/'create')], check=True)
        result = subprocess.run([str(path/'create'), '0'], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        for fault, message in ((1, 'Invalid CREATE_BUFS'), (2, 'Invalid CREATE_BUFS'),
                               (3, 'changed requested'), (4, 'queried lengths'),
                               (5, 'export capacity'), (6, 'not zeroed'),
                               (7, 'aliases differ'), (8, 'nested access lost'),
                               (9, 'QBUF created capture only')):
            result = subprocess.run([str(path/'create'), str(fault)], capture_output=True, text=True)
            assert result.returncode != 0 and message in result.stderr, (fault, result.stderr)
    print('Actual CREATE_BUFS mode: four mixed layouts, five invalid extents, full zeroed exports, nested aliases and prepare; nine faulty-device cases rejected: PASS')


def check_surface_jobs(source):
    """Exercise actual owner callbacks with instrumented kernel primitives."""
    original = source.read_text()
    def function(name):
        match = re.search(r'(?m)^(?:static )?(?:struct \w+ \*|void \*|void |int |long |bool |size_t |unsigned int )' +
                          re.escape(name) + r'\([^;]*?\)\n\{', original)
        assert match, name
        start = match.end() - 1
        depth, end = 1, start + 1
        while depth:
            depth += (original[end] == '{') - (original[end] == '}')
            end += 1
        return original[match.start():end] + '\n'
    structs = original[original.index('struct capture_surface {'):original.index('size_t mt6797_picture_bytes')]
    code = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint64_t dma_addr_t;
typedef int spinlock_t;
typedef unsigned refcount_t;
struct mutex { bool locked; };
struct device { int unused; };
struct sg_table { int unused; };
struct list_head { struct list_head *next, *prev; };
enum dma_data_direction { DMA_BIDIRECTIONAL, DMA_TO_DEVICE, DMA_FROM_DEVICE };
struct dma_fence { unsigned refs; bool signalled; int error; };
struct dma_resv { int id; bool locked; unsigned usage; struct dma_fence *fence; };
struct dma_buf { unsigned refs; size_t size; void *priv; struct dma_resv *resv; };
struct vb2_vmarea_handler { refcount_t *refcount; void (*put)(void *); void *arg; };
struct vb2_buffer { unsigned num_planes; struct { void *mem_priv; unsigned length; } planes[2]; };
struct ww_acquire_ctx { int unused; };
struct mt6797_picture { struct dma_buf *buffer; u8 *cpu; dma_addr_t dma; size_t bytes; };
#define SURFACE_LIMIT 17U
#define DEPENDENCY_TIMEOUT 1000U
#define GFP_KERNEL 0
#define SZ_64K ((size_t)65536)
#define SZ_128K ((size_t)131072)
#define PAGE_ALIGN(x) (((x) + 4095) & ~(size_t)4095)
#define DMA_BIT_MASK(n) ((1ULL << (n)) - 1)
#define max(a,b) ((a) > (b) ? (a) : (b))
#define round_down(x,y) ((x) & ~((__typeof__(x))(y) - 1))
#define check_mul_overflow(a,b,p) __builtin_mul_overflow((a),(b),(p))
#define check_add_overflow(a,b,p) __builtin_add_overflow((a),(b),(p))
#define DMA_RESV_USAGE_WRITE 1U
#define DMA_RESV_USAGE_READ 2U
#define READ_ONCE(x) (x)
#define WARN_ON(x) ({ bool bad = (x); assert(!bad); bad; })
#define dma_resv_usage_rw(write) ((write) ? DMA_RESV_USAGE_READ : DMA_RESV_USAGE_WRITE)
#define ERR_PTR(x) ((void *)(intptr_t)(x))
#define IS_ERR(x) ((uintptr_t)(x) >= (uintptr_t)-4095)
#define PTR_ERR(x) ((int)(intptr_t)(x))
#define kzalloc(n, flags) calloc(1, (n))
#define kfree free
#define time_after_eq(a, b) ((a) >= (b))
static unsigned long jiffies;
static int reservation_ww_class, fail_lock = -1, fail_reserve = -1, fail_wait = -1;
static int lock_error, fence_failure, allocated, released, fence_count, cpu_syncs, device_syncs;
static int wait_error, waits;
static struct mutex capture_lock;
static size_t mt6797_capture_luma(struct vb2_buffer *vb) { (void)vb; return 5120; }
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define list_for_each_entry(pos, head, member) \
    for (struct list_head *node = (head)->next; node != (head) && \
         ((pos) = container_of(node, __typeof__(*(pos)), member), 1); node = node->next)
static void INIT_LIST_HEAD(struct list_head *head) { head->next = head->prev = head; }
static void list_add_tail(struct list_head *node, struct list_head *head) {
    node->prev = head->prev; node->next = head; head->prev->next = node; head->prev = node;
}
static void mutex_lock(struct mutex *m) { assert(!m->locked); m->locked = true; }
static void mutex_unlock(struct mutex *m) { assert(m->locked); m->locked = false; }
static void refcount_set(refcount_t *r, unsigned n) { *r = n; }
static bool refcount_dec_and_test(refcount_t *r) { assert(*r); return --*r == 0; }
static unsigned refcount_read(refcount_t *r) { return *r; }
static struct dma_fence *dma_fence_get(struct dma_fence *f) { if (f) f->refs++; return f; }
static void dma_fence_put(struct dma_fence *f) {
    if (f) { assert(f->refs); if (!--f->refs) { fence_count--; free(f); } }
}
static void dma_fence_signal(struct dma_fence *f) { assert(f && !f->signalled); f->signalled = true; }
static void dma_fence_set_error(struct dma_fence *f, int e) { assert(!f->signalled && e < 0); f->error = e; }
static void get_dma_buf(struct dma_buf *b) { assert(b->refs); b->refs++; }
static void dma_buf_put(struct dma_buf *b) {
    assert(b->refs);
    if (--b->refs) return;
    released++;
    dma_fence_put(b->resv->fence);
    free(b->resv); free(b->priv); free(b);
}
static void ww_acquire_init(struct ww_acquire_ctx *c, int *k) { (void)c; (void)k; }
static void ww_acquire_done(struct ww_acquire_ctx *c) { (void)c; }
static void ww_acquire_fini(struct ww_acquire_ctx *c) { (void)c; }
static void dma_resv_unlock(struct dma_resv *r) { assert(r->locked); r->locked = false; }
static int dma_resv_lock_interruptible(struct dma_resv *r, struct ww_acquire_ctx *c) {
    (void)c;
    assert(!r->locked);
    if (r->id == fail_lock) { fail_lock = -1; return lock_error; }
    r->locked = true; return 0;
}
static int dma_resv_lock_slow_interruptible(struct dma_resv *r, struct ww_acquire_ctx *c) {
    return dma_resv_lock_interruptible(r, c);
}
static long dma_resv_wait_timeout(struct dma_resv *r, unsigned usage, bool intr, unsigned long timeout) {
    (void)intr;
    assert(timeout && timeout <= DEPENDENCY_TIMEOUT && r->locked && !capture_lock.locked);
    assert(usage == DMA_RESV_USAGE_READ);
    waits++;
    return r->id == fail_wait ? wait_error : 1;
}
static int dma_resv_reserve_fences(struct dma_resv *r, unsigned count) {
    assert(r->locked && count == 1); return r->id == fail_reserve ? -ENOMEM : 0;
}
static void dma_resv_add_fence(struct dma_resv *r, struct dma_fence *f, unsigned usage) {
    assert(r->locked); dma_fence_put(r->fence); r->fence = dma_fence_get(f); r->usage = usage;
}
'''
    code += structs
    code += r'''
static struct dma_buf *allocate_surface(struct device *dev, size_t bytes) {
    (void)dev;
    struct dma_buf *b = calloc(1, sizeof(*b));
    struct capture_surface *s = calloc(1, sizeof(*s));
    assert(b && s);
    b->refs = 1; b->size = bytes; b->priv = s; b->resv = calloc(1, sizeof(*b->resv));
    assert(b->resv); b->resv->id = allocated++; s->bytes = bytes; INIT_LIST_HEAD(&s->mappings);
    return b;
}
static struct dma_fence *allocate_fence(void) {
    if (fence_failure && !--fence_failure) return NULL;
    struct dma_fence *f = calloc(1, sizeof(*f));
    assert(f); f->refs = 1; fence_count++; return f;
}
static void dma_sync_sgtable_for_cpu(struct device *d, struct sg_table *s, enum dma_data_direction dir) {
    (void)d; (void)s; (void)dir; assert(capture_lock.locked); cpu_syncs++;
}
static void dma_sync_sgtable_for_device(struct device *d, struct sg_table *s, enum dma_data_direction dir) {
    (void)d; (void)s; (void)dir; assert(capture_lock.locked); device_syncs++;
}
static void invalidate_kernel_vmap_range(void *p, size_t n) { (void)p; (void)n; assert(capture_lock.locked); }
static void flush_kernel_vmap_range(void *p, size_t n) { (void)p; (void)n; assert(capture_lock.locked); }
'''
    names = ('mt6797_picture_bytes', 'mt6797_capture_size',
             'surface_to_cpu', 'surface_to_device', 'capture_wait_owner', 'capture_lock_owner',
             'capture_unlock_owner', 'capture_begin_cpu', 'capture_end_cpu',
             'capture_view_put', 'capture_alloc', 'capture_num_users', 'capture_get_dmabuf',
             'capture_queue_transition', 'capture_prepare_view', 'capture_finish_view',
             'mt6797_capture_prepare', 'mt6797_capture_finish_error',
             'mt6797_picture_from_vb2', 'mt6797_picture_get', 'mt6797_picture_put',
             'unlock_surfaces', 'lock_surfaces', 'release_job', 'mt6797_surface_job_begin',
             'mt6797_surface_job_to_device', 'mt6797_surface_job_to_cpu',
             'mt6797_surface_job_finish', 'mt6797_surface_job_poison')
    for name in names:
        code += function(name)
    code += r'''
int main(void) {
    assert(mt6797_picture_bytes(5120) == 196608);
    assert(mt6797_picture_bytes(SIZE_MAX) == 0);
    const unsigned sizes[][2] = {{5120,7680}, {196609,204801}, {208897,196611}, {196608,196608}};
    const size_t capacities[] = {196608,208896,212992,196608};
    for (unsigned i = 0; i < 4; i++) {
        size_t capacity = 0;
        assert(!mt6797_capture_size(5120,sizes[i][0],sizes[i][1],&capacity));
        assert(capacity == capacities[i]);
        struct vb2_buffer v = {.num_planes=2};
        for (unsigned p = 0; p < 2; p++) v.planes[p].length = sizes[i][p];
        for (unsigned p = 0; p < 2; p++) {
            v.planes[p].mem_priv = capture_alloc(&v,NULL,PAGE_ALIGN((size_t)sizes[i][p]));
            assert(!IS_ERR(v.planes[p].mem_priv));
        }
        struct capture_view *first = v.planes[0].mem_priv, *second = v.planes[1].mem_priv;
        assert(first->buffer == second->buffer && first->buffer->size == capacities[i]);
        struct mt6797_picture picture;
        assert(!mt6797_picture_from_vb2(&v,5120,&picture));
        assert(picture.bytes == 196608 && picture.buffer->size == capacities[i]);
        assert(!mt6797_capture_prepare(&v));
        capture_view_put(first); capture_view_put(second);
    }
    assert(allocated == released); allocated = released = 0;
    const size_t bad[][3] = {{0,196608,196608},{5120,5119,7680},{5120,196608,7679},
                            {5120,UINT32_MAX,196608},{5120,196608,UINT32_MAX},
                            {SIZE_MAX,SIZE_MAX,SIZE_MAX},{5120,268435457,196608}};
    for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); i++) {
        size_t capacity = 99;
        assert(mt6797_capture_size(bad[i][0],bad[i][1],bad[i][2],&capacity) == -EINVAL);
        assert(capacity == 99);
    }
    size_t capacity = 0;
    assert(!mt6797_capture_size(5120,268435455,196608,&capacity) && capacity == 268435456);
    assert(!mt6797_capture_size(5120,196608,268435456,&capacity) && capacity == 268435456);
    struct vb2_buffer bad_view = {.num_planes=2};
    bad_view.planes[0].length = 196609; bad_view.planes[1].length = 204801;
    assert(PTR_ERR(capture_alloc(&bad_view,NULL,196608)) == -EINVAL);
    struct vb2_buffer vb[3] = { 0 };
    struct mt6797_picture pictures[4] = { 0 };
    for (unsigned i = 0; i < 3; i++) {
        vb[i].num_planes = 2;
        vb[i].planes[0].length = vb[i].planes[1].length = 196608;
        for (unsigned j = 0; j < 2; j++) {
            vb[i].planes[j].mem_priv = capture_alloc(&vb[i], NULL, 196608);
            assert(!IS_ERR(vb[i].planes[j].mem_priv));
            assert(capture_num_users(vb[i].planes[j].mem_priv) == 1);
        }
        struct mt6797_picture borrowed;
        assert(!mt6797_picture_from_vb2(&vb[i], 5120, &borrowed));
        mt6797_picture_get(&pictures[i], &borrowed);
        assert(pictures[i].buffer->refs == 3);
    }
    pictures[3] = pictures[1]; /* Duplicate reference must share one reservation. */
    assert(IS_ERR(capture_get_dmabuf(&vb[0], vb[0].planes[0].mem_priv, O_RDONLY)));
    struct dma_buf *export = capture_get_dmabuf(&vb[0], vb[0].planes[1].mem_priv, O_RDWR);
    assert(export == pictures[0].buffer); dma_buf_put(export);
    for (unsigned i = 0; i < 3; i++) {
        fail_lock = i; lock_error = -EDEADLK;
        struct mt6797_surface_job *job = mt6797_surface_job_begin(pictures, 4, 0);
        assert(!IS_ERR(job) && job->count == 3);
        assert(pictures[0].buffer->resv->usage == DMA_RESV_USAGE_WRITE);
        assert(pictures[1].buffer->resv->usage == DMA_RESV_USAGE_WRITE);
        mt6797_surface_job_to_device(job);
        mt6797_surface_job_to_cpu(job);
        mt6797_surface_job_finish(job, -ETIMEDOUT, 0);
        assert(pictures[0].buffer->resv->fence->error == -ETIMEDOUT);
        assert(pictures[1].buffer->resv->fence->error == 0);
        for (unsigned j = 0; j < 3; j++) {
            struct capture_surface *s = pictures[j].buffer->priv;
            assert(!s->busy && s->device_owned && !capture_lock.locked);
            assert(!pictures[j].buffer->resv->locked && pictures[j].buffer->refs == 3);
        }
    }
    for (unsigned scenario = 0; scenario < 5; scenario++) {
        fail_lock = fail_reserve = fail_wait = -1; fence_failure = 0;
        if (scenario == 0) { fail_lock = 2; lock_error = -EINTR; }
        if (scenario == 1) fail_reserve = 1;
        if (scenario == 2) fail_wait = 2;
        if (scenario == 3) fence_failure = 1;
        if (scenario == 4) fence_failure = 2;
        struct mt6797_surface_job *job = mt6797_surface_job_begin(pictures, 4, 0);
        assert(IS_ERR(job));
        for (unsigned j = 0; j < 3; j++) {
            struct capture_surface *s = pictures[j].buffer->priv;
            assert(!s->busy && !capture_lock.locked);
            assert(!pictures[j].buffer->resv->locked && pictures[j].buffer->refs == 3);
        }
    }
    fail_lock = fail_reserve = fail_wait = -1; fence_failure = 0;
    struct capture_surface *surface = pictures[0].buffer->priv;
    struct capture_mapping mappings[2] = { 0 };
    mappings[0].direction = DMA_TO_DEVICE;
    mappings[1].direction = DMA_BIDIRECTIONAL;
    for (unsigned i = 0; i < 2; i++) list_add_tail(&mappings[i].list, &surface->mappings);
    int cpu_before = cpu_syncs, device_before = device_syncs;
    assert(!capture_begin_cpu(pictures[0].buffer, DMA_BIDIRECTIONAL));
    assert(cpu_syncs == cpu_before + 3 && surface->cpu_accesses == 1 && !surface->device_owned);
    assert(!capture_begin_cpu(pictures[0].buffer, DMA_TO_DEVICE));
    assert(cpu_syncs == cpu_before + 3 && surface->cpu_accesses == 2);
    assert(mt6797_capture_prepare(&vb[0]) == -EBUSY);
    struct mt6797_surface_job *blocked = mt6797_surface_job_begin(pictures, 4, 0);
    assert(IS_ERR(blocked) && PTR_ERR(blocked) == -EBUSY);
    assert(!capture_end_cpu(pictures[0].buffer, DMA_TO_DEVICE));
    assert(device_syncs == device_before && surface->cpu_accesses == 1);
    assert(!capture_end_cpu(pictures[0].buffer, DMA_BIDIRECTIONAL));
    assert(device_syncs == device_before + 3 && !surface->cpu_accesses && surface->device_owned);
    assert(capture_end_cpu(pictures[0].buffer, DMA_BIDIRECTIONAL) == -EINVAL);
    assert(!mt6797_capture_prepare(&vb[0]));
    for (unsigned i = 0; i < 2; i++) capture_prepare_view(vb[0].planes[i].mem_priv);
    assert(device_syncs == device_before + 3);
    for (unsigned i = 0; i < 2; i++) capture_finish_view(vb[0].planes[i].mem_priv);
    assert(cpu_syncs == cpu_before + 6 && !mt6797_capture_finish_error(&vb[0]));
    assert(!surface->device_owned && !surface->cpu_accesses);
    assert(!mt6797_capture_prepare(&vb[0]));
    assert(device_syncs == device_before + 6 && surface->device_owned);
    cpu_before = cpu_syncs; device_before = device_syncs;
    fail_wait = pictures[0].buffer->resv->id;
    assert(capture_begin_cpu(pictures[0].buffer, DMA_FROM_DEVICE) == -ETIMEDOUT);
    capture_finish_view(vb[0].planes[0].mem_priv);
    assert(mt6797_capture_finish_error(&vb[0]) == -ETIMEDOUT);
    wait_error = -EINTR;
    assert(capture_begin_cpu(pictures[0].buffer, DMA_FROM_DEVICE) == -EINTR);
    assert(cpu_syncs == cpu_before && device_syncs == device_before);
    assert(!surface->cpu_accesses && !capture_lock.locked && !pictures[0].buffer->resv->locked);
    fail_wait = -1; wait_error = 0;
    fail_lock = pictures[0].buffer->resv->id; lock_error = -EINTR;
    assert(mt6797_capture_prepare(&vb[0]) == -EINTR);
    assert(!mt6797_capture_prepare(&vb[0]) && !mt6797_capture_finish_error(&vb[0]));
    INIT_LIST_HEAD(&surface->mappings);
    struct mt6797_surface_job *job = mt6797_surface_job_begin(pictures, 4, 0);
    assert(!IS_ERR(job)); mt6797_surface_job_to_device(job);
    unsigned before = cpu_syncs;
    mt6797_surface_job_poison(job);
    assert(!job->output_fence->signalled && !job->reference_fence->signalled);
    assert(cpu_syncs == (int)before);
    int waits_before = waits;
    assert(capture_begin_cpu(job->buffers[0], DMA_FROM_DEVICE) == -EIO);
    capture_finish_view(vb[0].planes[0].mem_priv);
    assert(mt6797_capture_finish_error(&vb[0]) == -EIO && waits == waits_before);
    assert(cpu_syncs == (int)before && !capture_lock.locked);
    for (unsigned i = 0; i < 3; i++) {
        capture_view_put(vb[i].planes[0].mem_priv);
        capture_view_put(vb[i].planes[1].mem_priv);
        mt6797_picture_put(&pictures[i]);
        struct capture_surface *s = job->buffers[i]->priv;
        assert(job->buffers[i]->refs == 1 && s->poisoned && s->busy && s->device_owned);
        assert(IS_ERR(capture_get_dmabuf(&vb[i], &(struct capture_view){.buffer=job->buffers[i]}, O_RDWR)));
    }
    assert(!released); /* Closing every frontend owner cannot release live hardware memory. */
    /* Host-only reboot boundary: production deliberately has no such release. */
    for (unsigned i = 0; i < job->count; i++) {
        struct capture_surface *s = job->buffers[i]->priv;
        s->poisoned = false;
    }
    mt6797_surface_job_finish(job, -EIO, -EIO);
    assert(released == allocated && !fence_count && device_syncs > 0);
    puts("Actual surface owner: views/export/DPB, WW unwind, CPU/MMAP cache ownership and bounded poison waits, scoped fences and fatal-close retention: PASS");
    return 0;
}
'''
    # The host instruments ownership primitives; DMA/cache/MMIO behavior is
    # deliberately outside this regression's qualification scope.
    with tempfile.TemporaryDirectory(prefix='vdec-surface-owner-host-') as tmp:
        path = Path(tmp)
        (path/'owner.c').write_text(code)
        compiler = shlex.split(os.environ.get('HOSTCC', os.environ.get('CC', 'cc')))
        flags = shlex.split(os.environ.get('CFLAGS', ''))
        subprocess.run(compiler + ['-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter'] + flags +
                       [str(path/'owner.c'), '-o', str(path/'owner')], check=True)
        subprocess.run([str(path/'owner')], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-source', type=Path, default=REPO/'research/mt6797-vdec-v4l2/request-test.c')
    parser.add_argument('--qualifier-source', type=Path, default=Path(__file__).with_name('qualify-vdec-irq.py'))
    args = parser.parse_args()
    check_cli(args.request_source)
    check_native_gpu(args.request_source)
    check_capture(args.request_source)
    check_native_buffers(args.request_source)
    check_create_buffers(args.request_source)
    check_surface_jobs(REPO/'research/mt6797-vdec-v4l2/buffer.c')
    check_qualification(args.qualifier_source)
