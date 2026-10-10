#!/usr/bin/env python3
"""Check decoder IRQ delivery and pixels within a durable boot observation window."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--module-build', type=Path, required=True)
    parser.add_argument('--request-test', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    args = parser.parse_args()
    trial = args.trial.resolve()
    metadata_file = args.module_build.resolve(strict=True)
    metadata = json.loads(metadata_file.read_text())
    KERNEL = Path(metadata['kernel_package']).resolve(strict=True)
    module = Path(metadata['module']['path'])
    program = args.request_test.resolve(strict=True)
    assert sha(module) == metadata['module']['sha256']
    assert sha(program) == 'faf139e405d6a24480635583c765f431a3ad53625cfbdfc3aadfbca2c48bc6eb'
    assert subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip() == metadata['module']['vermagic']
    assert sha(KERNEL/'kernel.config') == metadata['kernel_config_sha256']
    assert sha(KERNEL/'Module.symvers') == metadata['module_symvers_sha256']
    assert metadata['build_exit_code'] == 0 and metadata['strict_modpost'] is True
    for name, expected in metadata['source_sha256'].items():
        assert sha(REPO/'research'/name) == expected, name
    assert sha(REPO/'research/mt6797-vdec-v4l2/request-test.c') == 'b2a8e564e0d2a8c491cd7efaa3d260dd704dd66ead90fd584d484a3a2dbd5597'
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
    out = trial/'decoder-irq'
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
    fixtures = args.fixtures.resolve(strict=True)
    (out/'fixtures').mkdir()
    for name in ('pcm64', 'pcm64-p', 'grey64', 'pattern64'):
        for suffix in ('.json', '.yuv'):
            shutil.copy2(fixtures/(name+suffix), out/'fixtures'/(name+suffix))
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
    command = 'mkdir '+base+'/output\nset +e\ntimeout --kill-after=2 12 '+base+'/request-test '+shlex.join(nodes)+' '+base+'/output '+DEVICE+'/last_job > '+base+'/output/stdout.txt 2> '+base+'/output/stderr.txt\n'
    command += 'rc=$?\nset -e\nprintf "%s\\n" "$rc" > '+base+'/output/returncode.txt\n'
    for source, name in [('last_job', 'last-job'), ('last_engine_failure', 'engine-failure'), ('first_context_failure', 'context-failure')]:
        command += 'cat '+DEVICE+'/'+source+' > '+base+'/output/'+name+'.txt\n'
    command += 'cat /proc/interrupts > '+base+'/output/proc-interrupts-after.txt\n'
    command += '{\n'+irq_snapshot_script()+'} > '+base+'/output/interrupts-after.txt\n'
    command += 'dmesg > '+base+'/output/dmesg.txt\ntar -cf - -C '+base+'/output .'
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
    for name in ('pcm64', 'pcm64-p', 'grey64', 'pattern64'):
        file = out/(name+'.bin')
        if not file.exists():
            continue
        reference = (out/'fixtures'/(name+'.yuv')).read_bytes()
        reference_info = json.loads((out/'fixtures'/(name+'.json')).read_text())
        assert reference_info['software_decode_verified'] and sha(out/'fixtures'/(name+'.yuv')) == reference_info['hashes'][name+'.yuv']
        assert file.stat().st_size == len(reference) == 6144
        actual = compare.unpack(file.read_bytes(), 64, 64, 64, 4096, 'mm21')
        comparisons[name] = dict(passed=actual == reference, different_samples=sum(a != b for a, b in zip(actual, reference)), actual_sha256=hashlib.sha256(actual).hexdigest(), expected_sha256=hashlib.sha256(reference).hexdigest())
    valid = ('pcm64', 'pcm64-p', 'grey64', 'pattern64')
    passed = int((out/'returncode.txt').read_text()) == 0 and safe
    passed = passed and set(statuses) == set(valid)|{'missing-reference'} and set(comparisons) == set(valid)
    passed = passed and all(result['passed'] for result in comparisons.values())
    for name in valid:
        s = statuses.get(name, {})
        expected = dict(result=0, fetched=1, submitted=1, quiesced=1, guards=1,
                        error=0, message=0, reset=0, irq_events=1, irq_unexpected=0)
        expected['break'] = 0
        passed = passed and all(s.get(k) == v for k, v in expected.items())
        passed = passed and bool(s.get('state', 0)&(1<<31)) and bool(s.get('irq_status', 0)&(1<<16))
        passed = passed and s.get('irq_command', 0)>0 and s.get('irq_command') == s.get('irq_received_command')
    negative = statuses.get('missing-reference', {})
    passed = passed and negative.get('result') == -2 and negative.get('fetched') == negative.get('submitted') == 0
    passed = passed and len({statuses.get(n, {}).get('irq_command') for n in valid}) == 4
    passed = passed and start['irq'] == finish['irq'] and len(start['counts']) == len(finish['counts'])
    passed = passed and all(b >= a for a, b in zip(start['counts'], finish['counts']))
    passed = passed and finish['total']-start['total'] == 4
    result = dict(passed=bool(passed), safe_quiescence=safe, boot_id=boot, module_sha256=sha(module),
                  returncode=int((out/'returncode.txt').read_text()), statuses=statuses, cached=cached,
                  irq_before=start, irq_after=finish, irq_delta=finish['total']-start['total'], comparisons=comparisons,
                  system_profile_qualification_pending=True, unloaded=False)
    save(out/'result.json', result)
    if safe:
        remote('rmmod mt6797_vdec\ntest ! -e /sys/module/mt6797_vdec\ncat /proc/interrupts; cat /proc/sys/kernel/tainted', 'unload', require_window=False)
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
        raise RuntimeError('Decoder IRQ trial did not qualify; preserve evidence and await supervised recovery')


if __name__ == '__main__':
    main()
