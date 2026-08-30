#!/bin/sh
set -eu

# Explicitly opt-in host harness for the default boot/p22 slot. There is no
# default execution path: --execute is required. This script never writes p30
# or p31 and rejects any XML/scatter that does not prove boot-only operation.

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CANDIDATE=$ROOT/artifacts/mainline-connectivity-reviewed-p22/boot-padded-p22.img
ROLLBACK=$ROOT/artifacts/mainline-nixos-connectivity-m0/boot-padded-p22.img
CANDIDATE_SHA=1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc
ROLLBACK_SHA=08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3
SIZE=16777216
SCATTER=/mnt/Home/src/nixos-gemini-flash-p22-20260829/Gemini_NixOS_boot_only.txt
XML=/mnt/Home/src/nixos-gemini-flash-p22-20260829/download-only-strix-4.xml
STAGE_IMAGE=/mnt/Home/src/nixos-gemini-flash-p22-20260829/boot.img
TREX_CAPTURE_ROOT=/mnt/Home/src/nixos-gemini-flash-p22-20260829

device_ssh() {
    ssh -J trex -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes \
        -o ConnectTimeout=8 root@10.15.19.82 "$@"
}

usage() {
    echo "usage: $0 --dry-run | --execute" >&2
    exit 2
}
[ "${1:-}" = --dry-run ] || [ "${1:-}" = --execute ] || usage
MODE=$1

hash_size() {
    expected=$1
    image=$2
    test "$(stat -Lc %s "$image")" -eq "$SIZE"
    test "$(sha256sum "$image" | cut -d' ' -f1)" = "$expected"
}

preflight_scatter() {
    test "$(sha256sum "$SCATTER" | cut -d' ' -f1)" = 19f5d2cba03310e744056036fb9805dfc4686b54e2c25e08d532895efd6650f8
    test "$(sha256sum "$XML" | cut -d' ' -f1)" = 90eec878d01866f37f927f0e6d1d768517a758790d818d6252091fca7b212605
    test "$(grep -c 'is_download: true' "$SCATTER")" -eq 1
    grep -A8 -B2 'partition_name: boot$' "$SCATTER" | grep -q 'file_name: boot.img'
    grep -A12 -B2 'partition_name: boot$' "$SCATTER" | grep -q 'linear_start_addr: 0xb100000'
    grep -A12 -B2 'partition_name: boot$' "$SCATTER" | grep -q 'partition_size: 0x1000000'
    grep -A12 -B2 'partition_name: boot$' "$SCATTER" | grep -q 'region: EMMC_USER'
    # The full MTK scatter necessarily describes other partitions, including
    # boot2/boot3/recovery. The safety property is that exactly one entry is
    # downloadable, and the entry proven above is boot/p22.
}

preflight_local() {
    hash_size "$CANDIDATE_SHA" "$CANDIDATE"
    hash_size "$ROLLBACK_SHA" "$ROLLBACK"
    preflight_scatter
}

preflight_device() {
    device_ssh 'set -eu
target=$(readlink -f /dev/disk/by-partlabel/boot)
test "$target" = /dev/mmcblk0p22
test "$target" != /dev/mmcblk0p29
! grep -q "^$target " /proc/mounts
test "$(blockdev --getsize64 "$target")" -eq 16777216
p22=$(sha256sum "$target" | cut -d" " -f1)
test "$p22" = 1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc \
  || test "$p22" = 08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3
test "$(sha256sum /dev/mmcblk0p30 | cut -d" " -f1)" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test "$(sha256sum /dev/mmcblk0p31 | cut -d" " -f1)" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
sha256sum "$target" /dev/mmcblk0p30 /dev/mmcblk0p31'
}

stage_image() {
    source_image=$1
    expected=$2
    cp "$source_image" "$STAGE_IMAGE"
    test "$(stat -Lc %s "$STAGE_IMAGE")" -eq "$SIZE"
    test "$(sha256sum "$STAGE_IMAGE" | cut -d' ' -f1)" = "$expected"
}

start_capture() {
    run_name=p22-recovery-$(date +%Y%m%d-%H%M%S)
    RUN_LOCAL=$ROOT/artifacts/$run_name
    RUN_SHARED=$TREX_CAPTURE_ROOT/$run_name
    mkdir -p "$RUN_LOCAL" "$RUN_SHARED"
    STATE=$RUN_SHARED/state
    printf 'preflight %s mode=%s\n' "$(date -Is)" "$MODE" > "$RUN_LOCAL/state"
    device_ssh 'cat /sys/fs/pstore/console-ramoops-0' > "$RUN_LOCAL/pstore-pre" 2>/dev/null || true
    device_ssh 'dmesg' > "$RUN_LOCAL/dmesg-pre"
    device_ssh 'sha256sum /dev/mmcblk0p22' > "$RUN_LOCAL/p22-pre-hash"
    ssh trex "mkdir -p '$RUN_SHARED'; nohup timeout 900 journalctl -k -f -o short-iso > '$RUN_SHARED/trex-kernel.log' 2>&1 & echo \$! > '$RUN_SHARED/kernel.pid'; nohup timeout 900 ip monitor link addr > '$RUN_SHARED/trex-ip.log' 2>&1 & echo \$! > '$RUN_SHARED/ip.pid'; nohup timeout 900 sh -c 'while :; do date -Is; lsusb; sleep 0.10; done' > '$RUN_SHARED/trex-usb.log' 2>&1 & echo \$! > '$RUN_SHARED/usb.pid'"
    scp "$ROOT/research/p22-flash-wrapper.sh" trex:"$RUN_SHARED/flash-wrapper.sh" >/dev/null
}

stop_capture() {
    [ -n "${RUN_SHARED:-}" ] || return 0
    ssh trex "for f in '$RUN_SHARED'/*.pid; do test -f \"\$f\" && kill \"\$(cat \"\$f\")\" 2>/dev/null || true; done" 2>/dev/null || true
}

wait_state() {
    wanted=$1
    limit=$2
    i=0
    while [ "$i" -lt "$limit" ]; do
        state=$(cat "$STATE" 2>/dev/null || true)
        case "$state" in
            "$wanted"*) return 0 ;;
            flash_rc=*) return 1 ;;
        esac
        sleep 1
        i=$((i + 1))
    done
    return 1
}

wait_ssh() {
    limit=$1
    i=0
    while [ "$i" -lt "$limit" ]; do
        if device_ssh 'test -s /proc/cmdline' >/dev/null 2>&1; then return 0; fi
        sleep 3
        i=$((i + 1))
    done
    return 1
}

accept_candidate() {
    device_ssh 'set -eu
test "$(sha256sum /dev/mmcblk0p22 | cut -d" " -f1)" = 1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc
grep -q "^/dev/mmcblk0p29 /gemian .* ro," /proc/mounts
grep -q "^/dev/loop0 /nix/store squashfs ro," /proc/mounts
grep -q "planet,gemini-pda" /proc/device-tree/compatible
grep -q "maxcpus=8" /proc/cmdline
test "$(cat /sys/devices/system/cpu/online)" = 0-7
test -n "$(ip -4 -o addr show dev usb0 | grep 10.15.19.82)"
test -n "$(ip -4 -o addr show dev enu1 | grep 192.168.23.70)"
! dmesg | grep -Eiq "request_firmware|Direct firmware|wmt|btif|mtk-wifi|gnss|bluetooth|radio|fm|modem|afe"
! ls /sys/bus/platform/devices | grep -Eiq "consys|btif|wmt"'
}

start_tool() {
    log=$1
    ssh trex "nohup setsid -f sh '$RUN_SHARED/flash-wrapper.sh' '$STATE' '$log' '$XML' </dev/null > '$log' 2>&1 & echo \$! > '$RUN_SHARED/tool.pid'"
    if wait_state tool_started 20; then
        return 0
    fi
    # A fast tool failure is still a valid transaction state: let the caller
    # enter the rollback path instead of aborting before it can recover.
    case "$(cat "$STATE" 2>/dev/null || true)" in
        flash_rc=*) return 0 ;;
        *) return 1 ;;
    esac
}

request_reboot() {
    device_ssh 'systemctl reboot --no-wall' >> "$RUN_LOCAL/reboot.log" 2>&1 || true
}

recover() {
    printf 'candidate_acceptance_failed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    stage_image "$ROLLBACK" "$ROLLBACK_SHA"
    rollback_log=$RUN_SHARED/rollback-flash.log
    start_tool "$rollback_log"
    # If candidate userspace is still reachable, request a clean restart only
    # after rollback is waiting. If it is hung before init, wait for a natural
    # watchdog/preloader transition; no unsafe force-reset is attempted.
    if wait_ssh 1; then request_reboot; fi
    if ! wait_state flash_rc 180; then
        printf 'recovery_failed_no_flash_result %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    state=$(cat "$STATE")
    case "$state" in flash_rc=0*) ;; *) printf 'recovery_flash_failed %s\n' "$state" > "$RUN_LOCAL/state"; return 1;; esac
    if ! wait_ssh 40; then printf 'recovery_failed_no_ssh %s\n' "$(date -Is)" > "$RUN_LOCAL/state"; return 1; fi
    device_ssh 'set -eu
test "$(sha256sum /dev/mmcblk0p22 | cut -d" " -f1)" = 08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3
test "$(sha256sum /dev/mmcblk0p30 | cut -d" " -f1)" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test "$(sha256sum /dev/mmcblk0p31 | cut -d" " -f1)" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513'
    printf 'recovered_known_good_p22 %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
}

preflight_local
preflight_device > /dev/null
if [ "$MODE" = --dry-run ]; then
    printf 'dry-run-preflight-ok %s\n' "$(date -Is)"
    exit 0
fi

start_capture
trap stop_capture EXIT INT TERM
stage_image "$CANDIDATE" "$CANDIDATE_SHA"
candidate_log=$RUN_SHARED/candidate-flash.log
start_tool "$candidate_log"
request_reboot
if wait_ssh 40 && accept_candidate; then
    device_ssh 'set -eu
test "$(sha256sum /dev/mmcblk0p22 | cut -d" " -f1)" = 1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc
test "$(sha256sum /dev/mmcblk0p30 | cut -d" " -f1)" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test "$(sha256sum /dev/mmcblk0p31 | cut -d" " -f1)" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
sha256sum /dev/mmcblk0p22 /dev/mmcblk0p30 /dev/mmcblk0p31' > "$RUN_LOCAL/final-partition-hashes"
    printf 'accepted_p22 %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    exit 0
fi
recover
