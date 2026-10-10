#!/usr/bin/env python3
"""Qualify GPU OPP rendering before the normal supervised trial may keep an image.

Uses the existing boot/storage recovery owner. Frequency pins are temporary,
restored by a shell trap and an independent device timer; normal boot runs none
of these tests. A failed GPU check prevents candidate promotion.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gpu_boot', ROOT/'tools/test-boot.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
p = boot.p
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES += ('tools/test-gpu-dvfs.py', 'nix/gpu-kernel-log-check.sh')
POINTS = ((238000000, 850000), (365000000, 912500), (442500000, 937500),
          (520000000, 975000), (610000000, 1018750), (780000000, 1106250),
          (900000000, 1156250))


def gpu_evidence(runner, ssh, state, directory):
    out = directory/'gpu-dvfs'
    out.mkdir(mode=0o700)
    program = Path(p.SYSTEM)/'etc/gemini/gpu-render'
    program = program.resolve(strict=True)
    program_sha = hashlib.sha256(program.read_bytes()).hexdigest()
    guard = 'set -eu\n'
    guard += 'test "$(cat /proc/sys/kernel/random/boot_id)" = '+shlex.quote(state['boot_id'])+'\n'
    guard += 'test "$(readlink /run/current-system)" = '+shlex.quote(p.SYSTEM)+'\n'
    script = guard + r'''
gpu=/sys/class/devfreq/13040000.gpu
test "$(cat "$gpu/governor")" = simple_ondemand
test "$(cat "$gpu/available_frequencies")" = '238000000 365000000 442500000 520000000 610000000 780000000 900000000'
test "$(cat "$gpu/min_freq")" = 238000000
test "$(cat "$gpu/max_freq")" = 900000000
old_min=$(cat "$gpu/min_freq")
old_max=$(cat "$gpu/max_freq")
restore() {
 echo 0 > "$gpu/min_freq"
 echo "$old_max" > "$gpu/max_freq"
 echo "$old_min" > "$gpu/min_freq"
}
trap restore EXIT
cleanup='echo 0 > /sys/class/devfreq/13040000.gpu/min_freq; echo 900000000 > /sys/class/devfreq/13040000.gpu/max_freq'
systemd-run --quiet --unit=gemini-gpu-dvfs-restore --on-active=75s \
 --timer-property=AccuracySec=1s sh -c "$cleanup"
deadline=$(( $(date +%s) + 65 ))
soc=/sys/class/thermal/thermal_zone2/temp
test "$(cat "$soc")" -lt 70000
reg=
for candidate in /sys/class/regulator/regulator.*; do
 if test "$(cat "$candidate/name")" = vgpu; then
  test -z "$reg"
  reg=$candidate
 fi
done
test -n "$reg"
irq=$(awk '$NF == "panfrost-job" {n++;gsub(":","",$1);print $1} END{if(n!=1)exit 1}' /proc/interrupts)
test -n "$irq"
printf 'irq_before='; cat /sys/kernel/irq/$irq/per_cpu_count
printf 'program_sha256='; sha256sum /etc/gemini/gpu-render | cut -d' ' -f1
for pair in 238000000:850000 365000000:912500 442500000:937500 \
            520000000:975000 610000000:1018750 780000000:1106250 900000000:1156250; do
 hz=${pair%:*}
 uv=${pair#*:}
 test "$(date +%s)" -lt "$deadline"
 test "$(cat "$soc")" -lt 75000
 echo 0 > "$gpu/min_freq"
 echo "$hz" > "$gpu/max_freq"
 echo "$hz" > "$gpu/min_freq"
 n=0
 while test "$(cat "$gpu/cur_freq")" != "$hz"; do
  n=$((n+1))
  test "$n" -lt 25
  sleep 0.05
 done
 timeout --signal=TERM --kill-after=2 4 /etc/gemini/gpu-render /dev/dri/renderD128
 test "$(cat "$reg/microvolts")" = "$uv"
 printf 'point=%s voltage=%s clock=%s temp=%s\n' "$hz" "$uv" \
  "$(cat /sys/kernel/debug/clk/mfg_bg3d/clk_rate)" "$(cat "$soc")"
done
# Return downwards across every OPP too; clock and regulator readbacks agree.
for pair in 780000000:1106250 610000000:1018750 520000000:975000 \
            442500000:937500 365000000:912500 238000000:850000; do
 hz=${pair%:*}
 uv=${pair#*:}
 test "$(date +%s)" -lt "$deadline"
 echo 0 > "$gpu/min_freq"
 echo "$hz" > "$gpu/max_freq"
 echo "$hz" > "$gpu/min_freq"
 n=0
 while test "$(cat "$gpu/cur_freq")" != "$hz"; do
  n=$((n+1))
  test "$n" -lt 25
  sleep 0.05
 done
 timeout --signal=TERM --kill-after=2 4 /etc/gemini/gpu-render /dev/dri/renderD128
 test "$(cat "$reg/microvolts")" = "$uv"
 printf 'return=%s voltage=%s clock=%s temp=%s\n' "$hz" "$uv" \
  "$(cat /sys/kernel/debug/clk/mfg_bg3d/clk_rate)" "$(cat "$soc")"
done
printf 'irq_after='; cat /sys/kernel/irq/$irq/per_cpu_count
restore
trap - EXIT
systemctl stop gemini-gpu-dvfs-restore.timer
printf 'governor='; cat "$gpu/governor"
printf 'min='; cat "$gpu/min_freq"
printf 'max='; cat "$gpu/max_freq"
printf 'taint='; cat /proc/sys/kernel/tainted
systemctl is-active display-manager gemini-core-parking NetworkManager ModemManager \
 gemini-bluetooth bluetooth
test -d /sys/class/bluetooth/hci0
test "$(busctl get-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered)" = 'b true'
! systemctl is-active --quiet gemini-bluetooth-trace
test -c /dev/fuse
uid=$(id -u gemini)
env XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus \
 runuser -u gemini -- systemctl --user is-active xdg-document-portal
test "$(findmnt -n -o FSTYPE --mountpoint /run/user/$uid/doc)" = fuse.portal
set -- /sys/bus/platform/devices/180f0000.wifi/net/*
test "$#" = 1 && test -d "$1"
test "$(basename "$(readlink -f /sys/bus/platform/devices/180f0000.wifi/driver)")" = mt6797-wifi
echo bluetooth_boot_registration=passed
echo fuse_document_portal=passed
echo wlan_netdev=present
echo GPU_DVFS_PASS
'''
    raw = runner.persistence.run(ssh, script, out, 'points', timeout=100)
    if raw.count('GPU_RENDER_PASS backend=panfrost draws=2 pixels=8192') != 13:
        raise RuntimeError('Incomplete GPU pixel checks')
    observed = re.findall(r'^(point|return)=(\d+) voltage=(\d+) clock=(\d+) temp=(\d+)$', raw, re.M)
    expected = [('point', hz, uv) for hz, uv in POINTS]
    expected += [('return', hz, uv) for hz, uv in reversed(POINTS[:-1])]
    if ([(kind, int(hz), int(uv)) for kind, hz, uv, clock, temp in observed] != expected
            or any(int(temp) >= 75000 or abs(int(clock)-int(hz)) > int(hz)//1000
                   for kind, hz, uv, clock, temp in observed)):
        raise RuntimeError('GPU operating-point readbacks differ or exceed the thermal bound')
    records = {}
    for line in raw.splitlines():
        if '=' in line and not line.startswith(('point=', 'return=')):
            key, value = line.split('=', 1)
            records[key] = value
    if (records.get('program_sha256') != program_sha or
            records.get('governor') != 'simple_ondemand' or
            records.get('min') != '238000000' or records.get('max') != '900000000' or
            records.get('bluetooth_boot_registration') != 'passed' or
            records.get('fuse_document_portal') != 'passed' or
            records.get('wlan_netdev') != 'present' or
            records.get('taint') != '0' or not raw.endswith('GPU_DVFS_PASS\n')):
        raise RuntimeError('GPU identity or restored policy differs')
    before = [int(v) for v in records['irq_before'].split(',')]
    after = [int(v) for v in records['irq_after'].split(',')]
    if len(before) != 10 or len(after) != 10 or sum(after) <= sum(before):
        raise RuntimeError('No GPU job IRQ progress across all possible CPUs')
    kernel = runner.persistence.run(ssh, guard+'dmesg\n', out, 'kernel', timeout=15)
    check = subprocess.run(['bash', str(ROOT/'nix/gpu-kernel-log-check.sh'),
                            str(out/'kernel.stdout'), str(out/'kernel-scoped.txt')],
                           capture_output=True, text=True)
    (out/'kernel-check.stdout').write_text(check.stdout)
    (out/'kernel-check.stderr').write_text(check.stderr)
    check.check_returncode()
    if 'Failed to register cooling device' in kernel:
        raise RuntimeError('GPU thermal cooling registration failed')
    result = dict(result='passed', boot_id=state['boot_id'], system=p.SYSTEM,
                  kernel=str(p.KERNEL), governor='simple_ondemand',
                  operating_points=[dict(hz=hz, microvolts=uv) for hz, uv in POINTS],
                  clock_readbacks=[dict(direction=kind, target_hz=int(hz), clock_hz=int(clock))
                                   for kind, hz, uv, clock, temp in observed],
                  pixel_checks=13, pixels_per_check=8192, job_irq_delta=sum(after)-sum(before),
                  program=str(program), program_sha256=program_sha,
                  normal_cpu_parking_retained=True, policy_restored=True,
                  bluetooth_boot_registration=True, document_portal_mounted=True,
                  wlan_netdev_present=True,
                  sustained_thermal_qualified=False,
                  subjective_desktop_responsiveness_qualified=False)
    runner.qualify.save(out, 'result.json', result)
    print('PASS: GPU renders at all seven OPPs in both directions; normal policy restored', flush=True)


base_configure = p.configure


def configure(*args, **kwargs):
    runner = base_configure(*args, **kwargs)
    candidate = runner.candidate_return

    def qualified(ssh, before, directory, profile):
        state = candidate(ssh, before, directory, profile)
        gpu_evidence(runner, ssh, state, directory)
        return state

    runner.candidate_return = qualified
    return runner


p.configure = configure
if __name__ == '__main__':
    try:
        p.main(boot.artifacts, boot.migration_artifacts)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
