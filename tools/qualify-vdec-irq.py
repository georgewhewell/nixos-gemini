#!/usr/bin/env python3
"""Check decoder completion or native buffers in a durable boot observation window."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import time

REPO = Path(__file__).resolve().parents[1]
RELEASE = '7.2.9-gemini-da921x-lkro'
DEVICE = '/sys/bus/platform/devices/16020000.video-codec'
SSH = ['ssh', '-F', '/dev/null', '-i', '/home/grw/.ssh/gemini-stage1-ed25519',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
       '-o', 'ControlPath=none', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'HostKeyAlias=192.168.23.70', '-o', 'ServerAliveInterval=2',
       '-o', 'ServerAliveCountMax=3', 'root@10.15.19.82']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def fields(text):
    return {k: int(v, 0) for k, v in re.findall(r'(\w+)=(-?0x[0-9a-f]+|-?\d+)', text)}


def irq_snapshot_script():
    # /proc identifies the IRQ only; its counts omit offline CPUs.
    return """irq=$(awk '$NF == "16020000.video-codec" {n++; gsub(":", "", $1); print $1} END {if(n!=1)exit 1}' /proc/interrupts)
case "$irq" in ''|*[!0-9]*) exit 1;; esac
printf 'irq=%s\\n' "$irq"
printf 'actions='; cat /sys/kernel/irq/$irq/actions
printf 'counts='; cat /sys/kernel/irq/$irq/per_cpu_count
"""


def irq_counter(text):
    rows = text.splitlines()
    if len(rows) != 3 or [r.split('=', 1)[0] for r in rows] != ['irq', 'actions', 'counts']:
        raise RuntimeError('Incomplete decoder IRQ snapshot')
    value = dict(r.split('=', 1) for r in rows)
    if not re.fullmatch(r'[0-9]+', value['irq']) or value['actions'] != '16020000.video-codec':
        raise RuntimeError('Foreign or ambiguous decoder IRQ')
    if not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', value['counts']):
        raise RuntimeError('Invalid possible-CPU IRQ counter')
    counts = [int(v) for v in value['counts'].split(',')]
    return dict(irq=int(value['irq']), counts=counts, total=sum(counts),
                actions=value['actions'], counter='sysfs-all-possible-cpus')


def check_kernel_revision(kernel, expected):
    revisions = [row.removeprefix('source-revision=')
                 for row in (kernel/'BUILD-MANIFEST').read_text().splitlines()
                 if row.startswith('source-revision=')]
    if not re.fullmatch(r'[0-9a-f]{40}', expected) or revisions != [expected]:
        raise RuntimeError('Kernel source revision differs; matching module ABI is insufficient')


def buffers_qualified(reports, cached, start, finish, returncode, safe, statuses):
    expected = dict(native_buffers_test_passed=True,
                    scope='native-buffers', width=80, height=64,
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
    if returncode != 0 or not safe or statuses or len(reports) != 1:
        return False
    record = reports[0]
    if not isinstance(record, dict) or set(record) != set(expected):
        return False
    for key, value in expected.items():
        if type(record[key]) is not type(value) or record[key] != value:
            return False
        if isinstance(value, list) and any(type(item) is not int for item in record[key]):
            return False
    if set(cached) != {'last-job', 'engine-failure', 'context-failure'}:
        return False
    zero = ('jobs', 'failures', 'fetch_commands', 'frame_commands', 'fetched',
            'submitted', 'irq_events', 'irq_unexpected', 'result', 'engine_result')
    if any(any(status.get(key) != 0 for key in zero) for status in cached.values()):
        return False
    return (start['irq'] == finish['irq'] and start['counts'] == finish['counts']
            and start['total'] == finish['total'])


def completion_qualified(statuses, comparisons, start, finish, returncode,
                         safe, program_complete, single=None):
    valid = (single,) if single else ('pcm64', 'pcm64-p', 'grey64', 'pattern64')
    expected_names = set(valid) if single else set(valid) | {'missing-reference'}
    passed = returncode == 0 and safe and program_complete
    passed = passed and set(statuses) == expected_names and set(comparisons) == set(valid)
    passed = passed and all(result['passed'] for result in comparisons.values())
    for name in valid:
        s = statuses.get(name, {})
        expected = dict(result=0, fetched=1, submitted=1, quiesced=1, guards=1,
                        error=0, message=0, reset=0, irq_events=1, irq_unexpected=0)
        expected['break'] = 0
        if single:
            expected.update(jobs=1, fetch_commands=1, frame_commands=1,
                            nal_bytes=20, header_bits=28, irq_clock_result=0)
        passed = passed and all(s.get(k) == v for k, v in expected.items())
        passed = passed and bool(s.get('state', 0) & (1 << 31)) and bool(s.get('irq_status', 0) & (1 << 16))
        passed = passed and s.get('irq_command', 0) > 0 and s.get('irq_command') == s.get('irq_received_command')
        if single:
            passed = passed and s.get('irq_clock_trace_valid', 0) == 0x1f
            passed = passed and not (s.get('irq_clock_submit', 1 << 4) & (1 << 4))
            passed = passed and not (s.get('irq_clock_guard', 1 << 4) & (1 << 4))
    if not single:
        negative = statuses.get('missing-reference', {})
        passed = passed and negative.get('result') == -2 and negative.get('fetched') == negative.get('submitted') == 0
    passed = passed and len({statuses.get(n, {}).get('irq_command') for n in valid}) == len(valid)
    passed = passed and start['irq'] == finish['irq'] and len(start['counts']) == len(finish['counts'])
    passed = passed and all(b >= a for a, b in zip(start['counts'], finish['counts']))
    return bool(passed and finish['total'] - start['total'] == len(valid))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--module-build', type=Path, required=True)
    parser.add_argument('--request-test', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path)
    case = parser.add_mutually_exclusive_group()
    case.add_argument('--single', choices=('grey64',))
    case.add_argument('--buffers-only', action='store_true',
                      help='Qualify native allocation/export/import lifetime without decode')
    args = parser.parse_args()
    if not args.buffers_only and args.fixtures is None:
        parser.error('--fixtures is required for decode observations')
    trial = args.trial.resolve()
    metadata_file = args.module_build.resolve(strict=True)
    metadata = json.loads(metadata_file.read_text())
    KERNEL = Path(metadata['kernel_package']).resolve(strict=True)
    check_kernel_revision(KERNEL, metadata['kernel_revision'])
    module = Path(metadata['module']['path'])
    program = args.request_test.resolve(strict=True)
    assert sha(module) == metadata['module']['sha256']
    request_build = metadata['request_test']
    assert request_build['build_exit_code'] == 0 and request_build['build_terminal'] is True
    assert request_build['machine'] == 183
    assert program == Path(request_build['path']).resolve(strict=True)
    assert sha(program) == request_build['sha256']
    assert program.read_bytes()[:4] == b'\x7fELF' and int.from_bytes(program.read_bytes()[18:20], 'little') == 183
    for name, expected in request_build['source_sha256'].items():
        assert sha(REPO/'research'/name) == expected, name
    assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip() == metadata['module']['vermagic']
    assert sha(KERNEL/'kernel.config') == metadata['kernel_config_sha256']
    assert sha(KERNEL/'Module.symvers') == metadata['module_symvers_sha256']
    assert metadata['build_exit_code'] == 0 and metadata['build_terminal'] is True
    assert metadata['strict_modpost'] is True
    if args.buffers_only:
        assert {'mt6797-vdec-v4l2/buffer.c', 'mt6797-vdec-v4l2/buffer.h'} <= metadata['source_sha256'].keys()
        assert metadata['native_dma_contract_source_sha256']
    for name, expected in metadata['source_sha256'].items():
        assert sha(REPO/'research'/name) == expected, name
    assert {'mt6797-vdec-v4l2/request-test.c', 'mt6797-vdec/pcm64-fixture.h'} <= request_build['source_sha256'].keys()
    assert sha(REPO/'research/mt6797-vdec/pcm64-fixture.h') == 'a421fca84a63bce330492b17c94778c4801624134cfcdf36686008e8fca6e758'
    deadline = time.monotonic()+900
    while not (trial/'candidate-observation.json').exists():
        if (trial/'worker-error.txt').exists():
            raise RuntimeError((trial/'worker-error.txt').read_text())
        if (trial/'supervisor.state').exists() and 'supervisor_rollback_complete' in (trial/'supervisor.state').read_text():
            raise RuntimeError('Candidate observation never became available')
        if time.monotonic() >= deadline:
            raise RuntimeError('No candidate observation within bounded wait')
        time.sleep(1)
    observation = json.loads((trial/'candidate-observation.json').read_text())
    assert observation['seconds'] == 90 and observation['completed'] is False
    plan = json.loads((trial/'plan.json').read_text())
    bundle = Path(plan['candidate']).parent.resolve(strict=True)
    assert sha(bundle/'boot-padded-p22.img') == plan['candidate_sha256']
    assert (bundle/'kernel').resolve(strict=True) == KERNEL
    SYSTEM = str((bundle/'system').resolve(strict=True))
    boot = observation['boot_id']
    assert re.fullmatch(r'[0-9a-f-]{36}', boot)
    out = trial/('decoder-buffers' if args.buffers_only else 'decoder-irq')
    out.mkdir()
    shutil.copy2(__file__, out/'observer-at-execution.py')
    shutil.copy2(metadata_file, out/'build-result.json')
    shutil.copy2(module, out/'mt6797_vdec.ko')
    shutil.copy2(program, out/'request-test')
    for source in [REPO/'research'/name for name in metadata['source_sha256']]:
        shutil.copy2(source, out/source.name)
    for name in ['request-test.c', '../mt6797-vdec/pcm64-fixture.h', '../mt6797-vdec/compare-frame.py']:
        source = REPO/'research/mt6797-vdec-v4l2'/name
        shutil.copy2(source, out/source.name)
    fixtures = args.fixtures.resolve(strict=True) if args.fixtures else None
    (out/'fixtures').mkdir()
    valid = () if args.buffers_only else ((args.single,) if args.single else ('pcm64', 'pcm64-p', 'grey64', 'pattern64'))
    for name in valid:
        for suffix in ('.json', '.yuv', '.nal'):
            shutil.copy2(fixtures/(name+suffix), out/'fixtures'/(name+suffix))
    if args.single:
        assert sha(out/'fixtures/grey64.nal') == request_build['embedded_grey_nal_sha256'] == '855a5ef2c41f93be0348d94136d49a78fba4c22829670cd2e6526ca09fc111e7'
    guard = 'set -eu\ntest "$(cat /proc/sys/kernel/random/boot_id)" = '+boot+'\n'
    guard += 'test "$(readlink /run/current-system)" = '+SYSTEM+'\n'
    guard += 'test "$(cat /run/unattended-recovery.accepted)" = unattended_recovery=healthy\n'
    units = json.loads((trial/'units.json').read_text())

    def live_window():
        assert json.loads((trial/'candidate-observation.json').read_text())['completed'] is False
        status = subprocess.check_output(['systemctl', '--user', 'show', units['supervisor'],
                                         '-p', 'ActiveState', '-p', 'MainPID'], text=True)
        properties = dict(line.split('=', 1) for line in status.splitlines())
        assert properties['ActiveState'] == 'active' and int(properties['MainPID']) > 0

    def remote(command, name, data=None, timeout=15, require_window=True):
        if require_window:
            live_window()
        script = guard+command+'\n'
        (out/(name+'.sh')).write_text(script)
        result = subprocess.run(SSH+[script], input=data, capture_output=True, timeout=timeout)
        (out/(name+'.stdout')).write_bytes(result.stdout)
        (out/(name+'.stderr')).write_bytes(result.stderr)
        save(out/(name+'-exit.json'), dict(exit_code=result.returncode))
        result.check_returncode()
        return result.stdout

    before = remote('uname -r; systemctl is-system-running; cat /proc/sys/kernel/tainted; sha256sum '+str(KERNEL/'kernel.config'), 'before').decode().splitlines()
    assert before[:3] == [RELEASE, 'running', '0'], before
    assert before[3].split()[0] == metadata['kernel_config_sha256']
    base = '/run/mt6797-irq-'+metadata['module']['sha256'][:12]
    remote('umask 077; mkdir '+base+'; cat > '+base+'/decoder.ko', 'upload-module', module.read_bytes())
    remote('cat > '+base+'/request-test; chmod 700 '+base+'/request-test', 'upload-program', program.read_bytes())
    hashes = remote('sha256sum '+base+'/decoder.ko '+base+'/request-test', 'upload-hashes').decode().splitlines()
    assert [line.split()[0] for line in hashes] == [sha(module), sha(program)]
    commands = []
    module_root = KERNEL/'lib/modules'/RELEASE/'kernel'
    for name in ['videobuf2-common', 'videobuf2-memops', 'videobuf2-v4l2', 'videobuf2-vmalloc', 'v4l2-mem2mem']:
        folder = 'drivers/media/v4l2-core' if name == 'v4l2-mem2mem' else 'drivers/media/common/videobuf2'
        commands.append('test -e /sys/module/'+name.replace('-', '_')+' || insmod '+str(module_root/folder/(name+'.ko')))
    commands.extend(['test ! -e /sys/module/mt6797_vdec', 'insmod '+base+'/decoder.ko', 'test -r '+DEVICE+'/last_job'])
    remote('\n'.join(commands), 'load')
    nodes = remote('for node in /sys/class/video4linux/video*; do test "$(cat "$node/name")" != mt6797-vdec || echo /dev/${node##*/}; done\n'
                   'for node in '+DEVICE+'/media*; do test "$(cat "$node/model")" != "MT6797 H.264 Request decoder" || echo /dev/${node##*/}; done', 'nodes').decode().splitlines()
    assert len(nodes) == 2 and nodes[0].startswith('/dev/video') and nodes[1].startswith('/dev/media'), nodes
    start = irq_counter(remote(irq_snapshot_script(), 'irq-before').decode())
    selection = ' --single '+args.single if args.single else ''
    if args.buffers_only:
        render_nodes = remote('for node in /sys/class/drm/renderD*; do '
                              'test "$(basename "$(readlink -f "$node/device/driver")")" != panfrost || '
                              'echo /dev/dri/${node##*/}; done', 'render-nodes').decode().splitlines()
        assert len(render_nodes) == 1 and re.fullmatch(r'/dev/dri/renderD[0-9]+', render_nodes[0])
        selection = ' --buffers-only '+render_nodes[0]
    command = 'mkdir '+base+'/output\nset +e\ntimeout --kill-after=2 12 '+base+'/request-test '+shlex.join(nodes)+' '+base+'/output '+DEVICE+'/last_job'+selection+' > '+base+'/output/stdout.txt 2> '+base+'/output/stderr.txt\n'
    command += 'rc=$?\nset -e\nprintf "%s\\n" "$rc" > '+base+'/output/returncode.txt\n'
    for source, name in [('last_job', 'last-job'), ('last_engine_failure', 'engine-failure'), ('first_context_failure', 'context-failure')]:
        command += 'cat '+DEVICE+'/'+source+' > '+base+'/output/'+name+'.txt\n'
    command += '{\n'+irq_snapshot_script()+'} > '+base+'/output/interrupts-after.txt\n'
    command += 'tar -cf - -C '+base+'/output .'
    data = remote(command, 'decode', timeout=20)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        for item in archive:
            if item.isdir():
                continue
            name = item.name.removeprefix('./')
            assert '/' not in name and name not in ('.', '..') and item.isfile() and item.size <= 2000000
            (out/name).write_bytes(archive.extractfile(item).read())
    statuses = {file.name.removesuffix('-status.txt'): fields(file.read_text()) for file in out.glob('*-status.txt')}
    cached = {name: fields((out/(name+'.txt')).read_text()) for name in ('last-job', 'engine-failure', 'context-failure')}
    safety_statuses = [*statuses.values(), *cached.values()]
    safe = all({'fetched', 'submitted', 'quiesced', 'guards'} <= s.keys() and
               (not (s['fetched'] or s['submitted']) or s['quiesced'] == 1)
               for s in safety_statuses)
    finish = irq_counter((out/'interrupts-after.txt').read_text())
    spec = importlib.util.spec_from_file_location('irq_compare', out/'compare-frame.py')
    compare = importlib.util.module_from_spec(spec); spec.loader.exec_module(compare)
    comparisons = {}
    for name in valid:
        file = out/(name+'.bin')
        if not file.exists():
            continue
        reference = (out/'fixtures'/(name+'.yuv')).read_bytes()
        reference_info = json.loads((out/'fixtures'/(name+'.json')).read_text())
        assert reference_info['software_decode_verified'] and sha(out/'fixtures'/(name+'.yuv')) == reference_info['hashes'][name+'.yuv']
        assert file.stat().st_size == len(reference) == 6144
        actual = compare.unpack(file.read_bytes(), 64, 64, 64, 4096, 'mm21')
        comparisons[name] = dict(passed=actual == reference, different_samples=sum(a != b for a, b in zip(actual, reference)), actual_sha256=hashlib.sha256(actual).hexdigest(), expected_sha256=hashlib.sha256(reference).hexdigest())
    try:
        reports = [json.loads(line) for line in (out/'stdout.txt').read_text().splitlines()]
        reports_valid = True
    except json.JSONDecodeError:
        reports = []
        reports_valid = False
    returncode = int((out/'returncode.txt').read_text())
    if args.buffers_only:
        program_complete = bool(reports_valid and len(reports) == 1
                                and isinstance(reports[0], dict)
                                and reports[0].get('native_buffers_test_passed') is True)
        passed = buffers_qualified(reports, cached, start, finish, returncode, safe, statuses)
        case_scope = 'allocation-export-prime-mapping-lifetime'
    else:
        marker = dict(public_api_test_passed=True, scope='single-grey64') if args.single else dict(public_api_test_passed=True)
        program_complete = bool(reports and reports[-1] == marker)
        passed = completion_qualified(statuses, comparisons, start, finish,
                                      returncode, safe, program_complete, args.single)
        case_scope = 'single-grey64' if args.single else 'four-pictures-and-missing-reference'
    result = dict(passed=bool(passed), safe_quiescence=safe, boot_id=boot, module_sha256=sha(module),
                  returncode=returncode, statuses=statuses, cached=cached,
                  irq_before=start, irq_after=finish, irq_delta=finish['total']-start['total'], comparisons=comparisons,
                  case_scope=case_scope, native_buffer_reports=reports if args.buffers_only else [],
                  decoder_completion_qualified=bool(passed and not args.buffers_only),
                  gpu_rendering_qualified=False,
                  program_complete=program_complete, reports_valid=reports_valid,
                  native_irq_setup_and_bind_accepted=True,
                  system_profile_qualification_pending=True, unloaded=False)
    save(out/'result.json', result)
    if safe:
        remote('rmmod mt6797_vdec\ntest ! -e /sys/module/mt6797_vdec\ncat /proc/sys/kernel/tainted', 'unload', require_window=False)
        result['unloaded'] = True
        result['unload_taint'] = int((out/'unload.stdout').read_text().splitlines()[-1])
        if result['unload_taint'] != 4096:
            result['passed'] = passed = False
            result['failure'] = 'Unexpected kernel taint beyond the external GPL module'
        save(out/'result.json', result)
    else:
        (out/'fatal-fence-retained.txt').write_text('Unsafe DMA stop: module and allocations retained until supervised recovery.\n')
    print(json.dumps(result, indent=2), flush=True)
    if not passed:
        raise RuntimeError('Decoder observation did not qualify; preserve evidence and await supervised recovery')


if __name__ == '__main__':
    main()
