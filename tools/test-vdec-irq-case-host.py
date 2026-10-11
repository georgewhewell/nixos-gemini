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


def check_surface_jobs(source):
    """Exercise actual owner callbacks with instrumented kernel primitives."""
    original = source.read_text()
    def function(name):
        match = re.search(r'(?m)^(?:static )?(?:struct \w+ \*|void \*|void |int |long |bool |unsigned int )' +
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
struct vb2_buffer { unsigned num_planes; struct { void *mem_priv; } planes[2]; };
struct ww_acquire_ctx { int unused; };
struct mt6797_picture { struct dma_buf *buffer; u8 *cpu; dma_addr_t dma; size_t bytes; };
#define SURFACE_LIMIT 17U
#define DEPENDENCY_TIMEOUT 1000U
#define GFP_KERNEL 0
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
    names = ('surface_to_cpu', 'surface_to_device', 'capture_wait_owner', 'capture_lock_owner',
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
    struct vb2_buffer vb[3] = { 0 };
    struct mt6797_picture pictures[4] = { 0 };
    for (unsigned i = 0; i < 3; i++) {
        vb[i].num_planes = 2;
        for (unsigned j = 0; j < 2; j++) {
            vb[i].planes[j].mem_priv = capture_alloc(&vb[i], NULL, 196608);
            assert(!IS_ERR(vb[i].planes[j].mem_priv));
            assert(capture_num_users(vb[i].planes[j].mem_priv) == 1);
        }
        struct mt6797_picture borrowed;
        assert(!mt6797_picture_from_vb2(&vb[i], &borrowed));
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
    check_capture(args.request_source)
    check_surface_jobs(REPO/'research/mt6797-vdec-v4l2/buffer.c')
    check_qualification(args.qualifier_source)
