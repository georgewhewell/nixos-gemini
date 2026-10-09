#!/usr/bin/env bash
# Hibernate the accepted U-Boot baseline once and verify a genuine resume.
#   hibernate-test.sh MODE OUTDIR    MODE: test_resume | reboot
# Safety: the baseline self-heals (watchdog -> fresh baseline boot). The USB
# gadget is soft-disconnected (mtu3 refuses to freeze while hosted); an
# independent timer reconnects it after 240 s whatever happens.
set -euo pipefail
mode=$1; out=$2; mkdir -p "$out"
case "$mode" in test_resume|reboot) ;; *) echo "bad mode" >&2; exit 2;; esac
SSH=(ssh -F /dev/null -i /home/grw/.ssh/gemini-stage1-ed25519 -o IdentitiesOnly=yes -o BatchMode=yes
     -o ConnectTimeout=5 -o ControlPath=none -o StrictHostKeyChecking=yes -o HostKeyAlias=192.168.23.70
     root@10.15.19.82)
HEADER=807f5f949455432666930598531247d0b6dc2bb23ba2ab3b18bc60f1f7382e7d
header() { "${SSH[@]}" 'dd if=/dev/mmcblk0 bs=512 skip=111622144 count=8 status=none iflag=direct | sha256sum | cut -d" " -f1'; }

"${SSH[@]}" "set -eu
grep -qx unattended_recovery=healthy /run/unattended-recovery.accepted
test \"\$(cat /sys/bus/platform/devices/11015000.dvfsp-handoff/state)\" = ready
grep -q 'mmcblk0p34.*partition.*[[:space:]]0[[:space:]]' /proc/swaps
test \"\$(cat /sys/power/resume)\" = 259:2
cat /proc/sys/kernel/random/boot_id" > "$out/before-boot-id"
[ "$(header)" = "$HEADER" ] || { echo "swap header not pinned before test" >&2; exit 1; }
token=$(date +%s)
"${SSH[@]}" "set -eu
printf %s $token > /run/hibernate-token
cat > /run/hibernate-run.sh <<'EOF'
#!/bin/sh
PATH=/run/current-system/sw/bin
udc=/sys/class/udc/11271000.usb
{
echo \"start boot_id=\$(cat /proc/sys/kernel/random/boot_id) uptime=\$(cut -d' ' -f1 /proc/uptime)\"
echo $mode > /sys/power/disk; echo \"disk=\$(cat /sys/power/disk)\"
printf disconnect > \$udc/soft_connect; sleep 2
echo disk > /sys/power/state; echo \"state_rc=\$?\"
echo shutdown > /sys/power/disk
printf connect > \$udc/soft_connect
echo \"end boot_id=\$(cat /proc/sys/kernel/random/boot_id) uptime=\$(cut -d' ' -f1 /proc/uptime)\"
} > /run/hibernate-run.log 2>&1
EOF
chmod 0700 /run/hibernate-run.sh
systemd-run --quiet --unit=hibernate-gadget-fallback-$token --collect --on-active=240 \
  /run/current-system/sw/bin/sh -c 'printf connect > /sys/class/udc/11271000.usb/soft_connect'
systemd-run --quiet --unit=hibernate-run-$token --collect /run/hibernate-run.sh"
echo "launched $mode token=$token"
sleep 30
for i in $(seq 60); do
  if "${SSH[@]}" true 2>/dev/null; then break; fi; sleep 5
done
"${SSH[@]}" "cat /run/hibernate-run.log; echo token=\$(cat /run/hibernate-token 2>/dev/null || echo missing)
echo boot_id=\$(cat /proc/sys/kernel/random/boot_id); echo dvfsp=\$(cat /sys/bus/platform/devices/11015000.dvfsp-handoff/state)
journalctl -k -b --no-pager | grep -E 'PM: (hibernation|Image|Restor|Wrote|Read|Load|Using)|hibernate' | tail -12
echo errors=\$(journalctl -k -b --no-pager | grep -cE 'BUG:|Oops|WARNING:|Call trace|set voltage|state=faulted|CCI update failed')" | tee "$out/after.txt"
before=$(cat "$out/before-boot-id")
grep -qx "boot_id=$before" "$out/after.txt" && grep -qx "token=$token" "$out/after.txt" \
  && grep -qx 'dvfsp=ready' "$out/after.txt" && grep -qx 'errors=0' "$out/after.txt" \
  && grep -q 'state_rc=0' "$out/after.txt" && result=passed || result=failed
# Hibernation leaves swsusp image fields in the swap header tail; mkswap zeroes them.
"${SSH[@]}" "set -eu
swapoff /dev/mmcblk0p34; dd if=/dev/zero of=/dev/mmcblk0p34 bs=1 seek=4056 count=30 conv=notrunc,fsync status=none
sync; blockdev --flushbufs /dev/mmcblk0; swapon /dev/mmcblk0p34"
[ "$(header)" = "$HEADER" ] || { echo "swap header restore failed" >&2; result=failed; }
echo "result=$result" | tee "$out/result.txt"
[ "$result" = passed ]
