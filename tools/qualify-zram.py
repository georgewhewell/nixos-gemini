#!/usr/bin/env python3
"""RAM-only paging checks for the normal durable boot runner."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def verify_config(raw):
    lines = raw.decode().splitlines()
    required = {'CONFIG_ZRAM=y', 'CONFIG_ZRAM_BACKEND_LZ4=y',
                'CONFIG_ZRAM_DEF_COMP_LZ4=y', '# CONFIG_ZRAM_WRITEBACK is not set',
                '# CONFIG_ZSWAP is not set'}
    if not required.issubset(lines) or any(lines.count(line) != 1 for line in required):
        raise RuntimeError('Normal paging requires built-in LZ4 zram, with zswap and zram writeback disabled')
    for key in ('CONFIG_ZRAM', 'CONFIG_ZRAM_BACKEND_LZ4', 'CONFIG_ZRAM_DEF_COMP_LZ4',
                'CONFIG_ZRAM_WRITEBACK', 'CONFIG_ZSWAP'):
        definitions = [line for line in lines if line.startswith(key+'=') or line == '# '+key+' is not set']
        if len(definitions) != 1:
            raise RuntimeError('Ambiguous kernel paging configuration: '+key)


def probe_identity(context):
    verify_config((context.KERNEL/'kernel.config').read_bytes())
    source = Path(context.SYSTEM)/'sw/bin/gemini-zram-probe'
    executable = source.resolve(strict=True)
    raw = executable.read_bytes()
    if (len(raw) < 64 or raw[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<H', raw, 18)[0] != 183):
        raise RuntimeError('The zram probe is not an ARM64 ELF executable')
    expected = hashlib.sha256((ROOT/'nix/gemini-zram-probe.c').read_bytes()).hexdigest()
    recorded = (executable.parent.parent/'share/gemini-zram-probe/source.sha256').read_text().strip()
    if recorded != expected:
        raise RuntimeError('The selected system contains another zram probe source')
    return raw, hashlib.sha256(raw).hexdigest()


def policy_script(boot_id):
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot_id):
        raise ValueError('Invalid boot identity')
    return f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot_id}
test ! -e /sys/module/zswap
test ! -e /sys/class/block/zram0/backing_dev
test "$(cat /sys/class/block/zram0/initstate)" = 1
grep -Fq '[lz4]' /sys/class/block/zram0/comp_algorithm
systemctl is-active dev-zram0.swap >/dev/null
awk 'NR == 1 {{ next }}
     {{ n++; if (NF != 5 || $1 != "/dev/zram0" || $2 != "partition" || $3 < 131072) bad=1 }}
     END {{ exit !(n == 1 && !bad) }}' /proc/swaps
cat /proc/swaps
test "$(cat /proc/sys/kernel/random/boot_id)" = {boot_id}
'''


def verify_swaps(raw):
    rows = [line.split() for line in raw.splitlines()]
    if (len(rows) != 2 or rows[0] != ['Filename', 'Type', 'Size', 'Used', 'Priority'] or
            len(rows[1]) != 5 or rows[1][:2] != ['/dev/zram0', 'partition'] or
            not all(re.fullmatch(r'[0-9]+', v) for v in rows[1][2:4]) or
            not re.fullmatch(r'-?[0-9]+', rows[1][4]) or
            int(rows[1][2]) < 131072 or int(rows[1][3]) > int(rows[1][2])):
        raise RuntimeError('Expected zram0 as the only active swap device; flash swap is forbidden')
    return dict(device='/dev/zram0', size_kib=int(rows[1][2]), used_kib=int(rows[1][3]),
                priority=int(rows[1][4]), flash_swap_active=False, writeback=False)


def policy(context, ssh, state, directory, persistence, qualify, name):
    raw = persistence.run(ssh, policy_script(state['boot_id']), directory, name)
    result = verify_swaps(raw)
    qualify.save(directory, name+'.json', result)
    return result


def verify_probe(paging, raw, service, status):
    result = paging.verify_probe(raw, service, status)
    if type(result.get('flash_swap_written_sectors')) is not int or result['flash_swap_written_sectors'] != 0:
        raise RuntimeError('The reserved eMMC swap partition received writes')
    return result


def run_probe(context, ssh, state, directory, persistence, qualify):
    unit = 'gemini-zram-io-'+str(int(time.time()))+'-'+str(os.getpid())
    remote = '/run/'+unit
    raw, sha = probe_identity(context)
    (directory/'probe').write_bytes(raw)
    (directory/'probe').chmod(0o400)
    guard = policy_script(state['boot_id'])+'\n'
    transfer = guard+f'''umask 077
mkdir {remote}
cat > {remote}/probe
chmod 0500 {remote}/probe
test "$(sha256sum {remote}/probe | cut -d' ' -f1)" = {sha}
'''
    (directory/'transfer.sh').write_text(transfer)
    sent = subprocess.run(ssh+[transfer], input=raw, capture_output=True, timeout=30)
    qualify.save(directory, 'transfer.json', dict(returncode=sent.returncode,
                                               stderr=sent.stderr.decode(errors='replace')))
    sent.check_returncode()
    command = guard+f'''test "$(sha256sum {remote}/probe | cut -d' ' -f1)" = {sha}
systemd-run --quiet --unit={unit} --setenv=PATH=/run/current-system/sw/bin \
 --property=RuntimeMaxSec=90 --property=RemainAfterExit=yes \
 --property=TimeoutStopSec=5 --property=MemoryMax=67108864 \
 --property=MemorySwapMax=268435456 --property=KillMode=control-group \
 --property=StandardOutput=file:{remote}/stdout --property=StandardError=file:{remote}/stderr \
 {remote}/probe
'''
    (directory/'probe.sh').write_text(command)
    launched = subprocess.run(ssh+[command], capture_output=True, text=True, timeout=30)
    qualify.save(directory, 'probe-launch.json', dict(returncode=launched.returncode,
                            stdout=launched.stdout, stderr=launched.stderr))
    launched.check_returncode()
    deadline = time.monotonic()+110
    while time.monotonic() < deadline:
        raw = persistence.run(ssh, guard+f'''systemctl show {unit}.service \
 -p ActiveState -p Result -p ExecMainCode -p ExecMainStatus -p SubState -p MainPID \
 -p RemainAfterExit -p MemoryMax -p MemorySwapMax -p RuntimeMaxUSec -p TimeoutStopUSec -p KillMode
''', directory, 'target-service', timeout=25)
        # The policy guard prints /proc/swaps first. Service properties follow.
        service = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        if service.get('SubState') in ('exited', 'dead', 'failed'):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError('The bounded zram probe did not terminate; durable rescue remains armed')
    qualify.save(directory, 'target-service.json', service)
    stdout = persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
cat {remote}/stdout
''', directory, 'probe-output')
    persistence.run(ssh, f'''set -eu
test "$(cat /proc/sys/kernel/random/boot_id)" = {state['boot_id']}
cat {remote}/stderr
cat /sys/class/block/zram0/mm_stat
cat /sys/class/block/mmcblk0p34/stat
''', directory, 'probe-diagnostics')
    verified = verify_probe(context.paging, stdout, service, launched.returncode)
    policy(context, ssh, state, directory, persistence, qualify, 'paging-policy-after')
    qualify.save(directory, 'paging.json', verified)
    persistence.run(ssh, guard+f'systemctl stop {unit}.service\n', directory, 'target-stop')
    return verified


def install(context):
    """Replace normal paging hooks; historical flash profiles remain explicit."""
    context.PAGING_POLICY = 'zram'
    context.probe_identity = lambda: probe_identity(context)[1]

    def baseline_paging(runner, directory, state):
        if runner.qualify.BASELINE.get('paging_policy') == 'none':
            recovery = context.f.q.module('qualified_ram_recovery', ROOT/'tools/qualify-ram-only-recovery.py')
            return recovery.accepted_policy(context, runner, state, directory)
        if runner.qualify.BASELINE.get('paging_policy') != 'zram':
            raise RuntimeError('The accepted recovery image still enables flash swap. '
                               'Qualify a RAM-only recovery baseline before running normal boot trials.')
        return policy(context, context.f.q.SSH, state, directory, runner.persistence,
                      runner.qualify, 'baseline-zram-policy')

    def evidence(ssh, boot_id, directory, qualify, persistence, require_efi=False):
        verify_config((context.KERNEL/'kernel.config').read_bytes())
        boot_guard = ('test "$(cat /sys/firmware/efi/fw_platform_size)" = 64'
                      if require_efi else 'test ! -e /sys/firmware/efi')
        expected = dict(boot_id=boot_id, system=context.SYSTEM, notes_sha256=context.NOTES_SHA,
                       config_sha256=hashlib.sha256((context.KERNEL/'kernel.config').read_bytes()).hexdigest(),
                       pm_test='[none] core processors platform devices freezer', mem_sleep='[s2idle]',
                       disk='[shutdown] reboot suspend test_resume', hibernation='false', suspend_then_hibernate='false')
        raw = persistence.run(ssh, f'''set -eu
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'system='; readlink /run/current-system
printf 'notes_sha256='; sha256sum /sys/kernel/notes | cut -d' ' -f1
printf 'config_sha256='; zcat /proc/config.gz | sha256sum | cut -d' ' -f1
for name in pm_test mem_sleep disk; do printf '%s=' "$name"; cat /sys/power/$name; done
printf 'hibernation='; sed -n 's/^AllowHibernation=//p' /etc/systemd/sleep.conf
printf 'suspend_then_hibernate='; sed -n 's/^AllowSuspendThenHibernate=//p' /etc/systemd/sleep.conf
{boot_guard}
grep -Eq ' [tT] mtk_wdt_pm_notify$' /proc/kallsyms
test "$(cat /proc/sys/kernel/random/boot_id)" = {shlex.quote(boot_id)}
''', directory, 'power-zram-state')
        rows = raw.splitlines()
        state = dict(row.split('=', 1) for row in rows)
        if len(rows) != len(state) or state != expected:
            raise RuntimeError('Selected kernel identity or sleep policy differs')
        current = policy(context, ssh, state, directory, persistence, qualify, 'paging-policy-before')
        watchdog = context.paging.watchdog(directory, state, 'candidate-watchdog')
        out = directory/'candidate-paging'; out.mkdir(mode=0o700)
        result = run_probe(context, ssh, state, out, persistence, qualify)
        qualify.save(directory, 'power-swap-evidence.json', dict(**state, watchdog=watchdog,
            paging_policy='zram', swap=current, paging=result, default_policy_paging_qualified=True,
            ram_only_paging_qualified=True, sleep_requested=False, hibernation_io_qualified=False,
            runtime_policy_writes=False))
        return state

    context.baseline_paging = baseline_paging
    context.evidence = evidence
