#!/bin/sh
# One boot, bounded volatile FS and protocol qualification; never copy back.
set -eu
umask 077
out=/run/gemini-cellular
: "${GEMINI_CELLULAR_RESTORE:?}" "${GEMINI_CELLULAR_HELPER:?}" "${GEMINI_CELLULAR_BUSYBOX:?}"

lease_ok() {
    record=/run/unattended-recovery.lease-deadline
    test "$(wc -l < "$record")" -eq 5
    grep -Fxq 'format=gemini-unattended-recovery-lease-v1' "$record"
    grep -Fxq 'clock=monotonic-uptime-seconds' "$record"
    for key in started deadline lease_seconds; do
        test "$(grep -c "^$key=" "$record")" -eq 1
    done
    started=$(sed -n 's/^started=//p' "$record")
    deadline=$(sed -n 's/^deadline=//p' "$record")
    duration=$(sed -n 's/^lease_seconds=//p' "$record")
    case "$started:$deadline:$duration" in *[!0-9:]*|:*|*::*) return 1 ;; esac
    test -n "$duration"
    test "$started" -ge 0 && test "$duration" -gt 0
    test "$deadline" -eq $((started + duration))
    read -r uptime unused < /proc/uptime
    seconds=${uptime%%.*}
    case "$seconds" in ''|*[!0-9]*) return 1 ;; esac
    test "$seconds" -lt $((deadline - $1))
}

watchdog_ok() {
    test ! -e /run/unattended-recovery.lease-expired
    lease_ok 5
    test "$(cat /sys/class/watchdog/watchdog0/identity)" = mtk-wdt
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    test "$(cat /sys/class/watchdog/watchdog0/nowayout)" = 1
    test "$(cat /sys/class/watchdog/watchdog0/timeout)" = 31
    test "$(systemctl is-active gemini-watchdog-takeover.service)" = active
    pid=$(systemctl show -p MainPID --value gemini-watchdog-takeover.service)
    case "$pid" in ''|0|*[!0-9]*) return 1 ;; esac
    test "$(cat /run/unattended-recovery.watchdog-owner)" = "$pid"
    kill -0 "$pid"
    test "$(tr '\000' ' ' < /proc/"$pid"/cmdline)" = "$GEMINI_CELLULAR_BUSYBOX watchdog -F -t 10 -T 31 /dev/watchdog "
    owns=no
    for fd in /proc/"$pid"/fd/*; do
        target=$(readlink "$fd" 2>/dev/null || true)
        case "$target" in /dev/watchdog|/dev/watchdog0) owns=yes ;; esac
    done
    test "$owns" = yes
}
identity_ok() {
    grep -wFq GEMINI_A72_CI9_M11 /proc/cmdline
    test "$(cat /sys/module/mt6797_md1_fs_provider/parameters/enable)" = Y
    test "$(cat /sys/module/mt6797_md1_fs_provider/parameters/enable_volatile)" = Y
    watchdog_ok
}
protocol_ok() {
    grep -Fq 'MD1 accepted CCCI HS1 v2; runtime reply queued' "$1"
    grep -Fq 'MD1 completed CCCI HS2' "$1"
    if grep -Eq 'Kernel panic|Internal error:|BUG:|SError Interrupt|MT6797_CCCI_TERMINAL_FAILURE|FIRST_FATAL' "$1"; then return 1; fi
    tr -d '\r' < "$out/at-response" | grep -Fxq OK
}
source_for() {
    case "$1" in
        Z) source_name=nvdata; source_device=/dev/mmcblk0p6; ram_name=ram ;;
        X) source_name=protect1; source_device=/dev/mmcblk0p8; ram_name=ramX ;;
        Y) source_name=protect2; source_device=/dev/mmcblk0p9; ram_name=ramY ;;
        *) return 1 ;;
    esac
}
check_backup() {
    sha256sum /dev/mmcblk0p19 > "$out/nvram-$1.sha256"
    cmp "$out/nvram-before.sha256" "$out/nvram-$1.sha256"
}
check_sources() {
    check_backup "$1"
    for drive in Z X Y; do
        source_for "$drive"
        sha256sum "$source_device" > "$out/$source_name-$1.sha256"
        cmp "$out/$source_name-before.sha256" "$out/$source_name-$1.sha256"
    done
}
verify() {
    identity_ok
    test "$(cat "$out/boot-id")" = "$(cat /proc/sys/kernel/random/boot_id)"
    grep -Fxq 'CELLULAR_STAGE2_PASS hs2=ready at=OK backing=volatile roots=ZXY attach=untested data=untested' "$out/success"
    protocol_ok "$out/dmesg-final"
    dmesg > "$out/dmesg-live"
    protocol_ok "$out/dmesg-live"
    check_sources live
}
if [ "${1:-}" = --verify ]; then verify; exit 0; fi
[ "$#" = 0 ]
mkdir "$out" # Persistent for this boot: failures and restarts cannot repeat registration.
exec > "$out/result.log" 2>&1
capture() {
    dmesg > "$out/dmesg-final" || :
    cat /proc/self/mountinfo > "$out/mountinfo-final" || :
}
trap capture EXIT
cat /proc/sys/kernel/random/boot_id > "$out/boot-id"
identity_ok
lease_ok 320 # Keep setup inside the original Stage1 deadline; never extend it.
dmesg > "$out/dmesg-before"
if grep -Eq 'MD1 accepted CCCI HS1|MD1 completed CCCI HS2|MT6797_CCCI_TERMINAL_FAILURE|FIRST_FATAL' "$out/dmesg-before"; then exit 1; fi
timeout -k 1 5 "$GEMINI_CELLULAR_HELPER" --check-roots-device
sha256sum /dev/mmcblk0p19 > "$out/nvram-before.sha256"
for drive in Z X Y; do
    source_for "$drive"
    sha256sum "$source_device" > "$out/$source_name-before.sha256"
    mkdir "$out/$source_name" "$out/$ram_name"
    timeout -k 1 10 mount -t ext4 -o ro,noload,nosuid,nodev,noexec "$source_device" "$out/$source_name"
    timeout -k 1 5 "$GEMINI_CELLULAR_HELPER" --check-root-mount "$drive" "$out/$source_name"
    timeout -k 1 10 mount -t tmpfs -o size=64m,nr_inodes=4096,mode=0700,nosuid,nodev,noexec tmpfs "$out/$ram_name"
    if ! timeout -k 1 30 cp -a "$out/$source_name/md" "$out/$ram_name/" >/dev/null 2>&1; then
        echo CELLULAR_RAM_SEED_FAILED; exit 1
    fi
    watchdog_ok
done
check_sources seeded
watchdog_ok
timeout -k 1 30 "$GEMINI_CELLULAR_RESTORE" --profile gemini-stock-ecci-md3-v1 --sha256 1b7fb822e90492b4d14eee735c4b16bf0d34638b14407c1ee108ba8e459240c9
check_backup prepared
watchdog_ok
timeout -k 1 60 "$GEMINI_CELLULAR_HELPER" --ram-roots "$out/nvdata" "$out/ram" "$out/protect1" "$out/ramX" "$out/protect2" "$out/ramY"
attempt=0
while :; do
    dmesg > "$out/dmesg-wait"
    if grep -Eq 'FIRST_FATAL|MT6797_CCCI_TERMINAL_FAILURE|Kernel panic|Internal error:|BUG:|SError Interrupt' "$out/dmesg-wait"; then exit 1; fi
    if grep -Fq 'MD1 completed CCCI HS2' "$out/dmesg-wait"; then break; fi
    attempt=$((attempt + 1)); [ "$attempt" -lt 40 ]
    watchdog_ok
    sleep 1
done
set -- /dev/wwan*at*
[ "$#" = 1 ] && [ -c "$1" ]
exec 3<>"$1"
printf 'AT\r' >&3
read_status=0
timeout -k 1 5 cat <&3 > "$out/at-response" 2> "$out/at-read-error" || read_status=$?
exec 3<&- 3>&-
echo "at_read_status=$read_status"
capture
protocol_ok "$out/dmesg-final"
watchdog_ok
test "$(cat "$out/boot-id")" = "$(cat /proc/sys/kernel/random/boot_id)"
check_sources after
echo 'CELLULAR_STAGE2_PASS hs2=ready at=OK backing=volatile roots=ZXY attach=untested data=untested' > "$out/success.tmp"
mv "$out/success.tmp" "$out/success"
