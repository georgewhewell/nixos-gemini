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
static int export_buffers, live;
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
        for extra in (['--single'], ['--single', 'pcm64'], ['--other', 'grey64'],
                      ['--single', 'grey64', 'extra'], ['--single', 'grey64', '64', 'mmap']):
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
    status = dict(result=0, fetched=1, submitted=1, quiesced=1, guards=1, error=0,
                  message=0, reset=0, irq_events=1, irq_unexpected=0, jobs=1,
                  fetch_commands=1, frame_commands=1, nal_bytes=20, header_bits=28,
                  irq_clock_result=0, state=0x80000001, irq_status=0x13001,
                  irq_command=1, irq_received_command=1, irq_clock_trace_valid=0x1f,
                  irq_clock_submit=0x101, irq_clock_guard=0x101)
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
                      irq_clock_submit=0x111, irq_clock_guard=0x111)
    bad_fields['break'] = 1
    for field, value in bad_fields.items():
        changed = copy.deepcopy(good)
        changed['statuses']['grey64'][field] = value
        reject(changed, field)
    for field in ('irq_status', 'irq_command', 'irq_received_command', 'irq_clock_result',
                  'irq_clock_trace_valid', 'irq_clock_submit', 'irq_clock_guard'):
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
    print(f'Actual qualifier: grey-only and legacy acceptance, {rejected} missing/unsafe/foreign evidence cases rejected: PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-source', type=Path, default=REPO/'research/mt6797-vdec-v4l2/request-test.c')
    parser.add_argument('--qualifier-source', type=Path, default=Path(__file__).with_name('qualify-vdec-irq.py'))
    args = parser.parse_args()
    check_cli(args.request_source)
    check_qualification(args.qualifier_source)
