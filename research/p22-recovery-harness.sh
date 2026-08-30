#!/bin/sh
set -eu

# Explicitly opt-in host harness for the default boot/p22 slot. There is no
# default execution path: --execute is required. This script never writes p30
# or p31 and rejects any XML/scatter that does not prove boot-only operation.
# The handoff manifest is data, never shell: unknown keys and unsafe values
# fail closed before the device is contacted.
# The accepted Stage-A image has watchdog0 inactive/nowayout=0, so its dry-run
# cannot prove pre-init recovery. Unattended manifests add a nowayout watchdog
# and a bounded initramfs lease; --proof-lease is the explicit opt-in path for
# proving that rollback is armed before the lease kills its petter. Any
# pre-MTK-probe hang remains outside this guarantee and stops at a manual-reset
# state if no preloader appears.

# shellcheck disable=SC1007 # zsh/NixOS-compatible scoped CDPATH assignment
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MANIFEST=$ROOT/research/p22-next-experiment.manifest
SIZE=16777216

die() {
    echo "p22-recovery-harness: $*" >&2
    exit 2
}

usage() {
    echo "usage: $0 [--manifest PATH] [--proof-lease] --dry-run | --execute" >&2
    exit 2
}

MODE=
PROOF_LEASE=no
while [ "$#" -gt 0 ]; do
    case "$1" in
        --manifest)
            [ "$#" -ge 2 ] || usage
            MANIFEST=$2
            shift 2
            ;;
        --dry-run|--execute)
            [ -z "$MODE" ] || usage
            MODE=$1
            shift
            ;;
        --proof-lease)
            [ "$PROOF_LEASE" = no ] || usage
            PROOF_LEASE=yes
            shift
            ;;
        *) usage ;;
    esac
done
[ -n "$MODE" ] || usage

CANDIDATE=
CANDIDATE_SHA=
CANDIDATE_SIZE=
ROLLBACK=
ROLLBACK_SHA=
ROLLBACK_SIZE=
TARGET_PARTITION=
TARGET_DEVICE=
SCATTER=
SCATTER_SHA=
XML=
XML_SHA=
STAGE_IMAGE=
TREX_CAPTURE_ROOT=
EXPECTED_MODEL=
EXPECTED_COMPATIBLE=
EXPECTED_CMDLINE=
EXPECTED_CPU_ONLINE=
EXPECTED_GADGET_IP=
EXPECTED_ETHERNET_IP=
EXPECTED_MARKER=
FEATURE_POLICY=
ACCEPTANCE_WINDOW_SECONDS=
WATCHDOG_PROFILE=
EXPECTED_WATCHDOG_IDENTITY=
EXPECTED_WATCHDOG_STATE=
EXPECTED_WATCHDOG_TIMEOUT=

load_manifest() {
    [ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"
    while IFS='=' read -r key value || [ -n "${key:-}${value:-}" ]; do
        case "$key" in
            ''|'#'*) continue ;;
            candidate) [ -z "$CANDIDATE" ] || die "duplicate candidate"; CANDIDATE=$value ;;
            candidate_sha256) [ -z "$CANDIDATE_SHA" ] || die "duplicate candidate_sha256"; CANDIDATE_SHA=$value ;;
            candidate_size) [ -z "$CANDIDATE_SIZE" ] || die "duplicate candidate_size"; CANDIDATE_SIZE=$value ;;
            rollback) [ -z "$ROLLBACK" ] || die "duplicate rollback"; ROLLBACK=$value ;;
            rollback_sha256) [ -z "$ROLLBACK_SHA" ] || die "duplicate rollback_sha256"; ROLLBACK_SHA=$value ;;
            rollback_size) [ -z "$ROLLBACK_SIZE" ] || die "duplicate rollback_size"; ROLLBACK_SIZE=$value ;;
            target_partition) [ -z "$TARGET_PARTITION" ] || die "duplicate target_partition"; TARGET_PARTITION=$value ;;
            target_device) [ -z "$TARGET_DEVICE" ] || die "duplicate target_device"; TARGET_DEVICE=$value ;;
            scatter) [ -z "$SCATTER" ] || die "duplicate scatter"; SCATTER=$value ;;
            scatter_sha256) [ -z "$SCATTER_SHA" ] || die "duplicate scatter_sha256"; SCATTER_SHA=$value ;;
            xml) [ -z "$XML" ] || die "duplicate xml"; XML=$value ;;
            xml_sha256) [ -z "$XML_SHA" ] || die "duplicate xml_sha256"; XML_SHA=$value ;;
            stage_image) [ -z "$STAGE_IMAGE" ] || die "duplicate stage_image"; STAGE_IMAGE=$value ;;
            trex_capture_root) [ -z "$TREX_CAPTURE_ROOT" ] || die "duplicate trex_capture_root"; TREX_CAPTURE_ROOT=$value ;;
            expected_model) [ -z "$EXPECTED_MODEL" ] || die "duplicate expected_model"; EXPECTED_MODEL=$value ;;
            expected_compatible) [ -z "$EXPECTED_COMPATIBLE" ] || die "duplicate expected_compatible"; EXPECTED_COMPATIBLE=$value ;;
            expected_cmdline_token) [ -z "$EXPECTED_CMDLINE" ] || die "duplicate expected_cmdline_token"; EXPECTED_CMDLINE=$value ;;
            expected_cpu_online) [ -z "$EXPECTED_CPU_ONLINE" ] || die "duplicate expected_cpu_online"; EXPECTED_CPU_ONLINE=$value ;;
            expected_gadget_ip) [ -z "$EXPECTED_GADGET_IP" ] || die "duplicate expected_gadget_ip"; EXPECTED_GADGET_IP=$value ;;
            expected_ethernet_ip) [ -z "$EXPECTED_ETHERNET_IP" ] || die "duplicate expected_ethernet_ip"; EXPECTED_ETHERNET_IP=$value ;;
            expected_marker) [ -z "$EXPECTED_MARKER" ] || die "duplicate expected_marker"; EXPECTED_MARKER=$value ;;
            feature_policy) [ -z "$FEATURE_POLICY" ] || die "duplicate feature_policy"; FEATURE_POLICY=$value ;;
            acceptance_window_seconds) [ -z "$ACCEPTANCE_WINDOW_SECONDS" ] || die "duplicate acceptance_window_seconds"; ACCEPTANCE_WINDOW_SECONDS=$value ;;
            watchdog_profile) [ -z "$WATCHDOG_PROFILE" ] || die "duplicate watchdog_profile"; WATCHDOG_PROFILE=$value ;;
            expected_watchdog_identity) [ -z "$EXPECTED_WATCHDOG_IDENTITY" ] || die "duplicate expected_watchdog_identity"; EXPECTED_WATCHDOG_IDENTITY=$value ;;
            expected_watchdog_state) [ -z "$EXPECTED_WATCHDOG_STATE" ] || die "duplicate expected_watchdog_state"; EXPECTED_WATCHDOG_STATE=$value ;;
            expected_watchdog_timeout) [ -z "$EXPECTED_WATCHDOG_TIMEOUT" ] || die "duplicate expected_watchdog_timeout"; EXPECTED_WATCHDOG_TIMEOUT=$value ;;
            *) die "unknown manifest key: $key" ;;
        esac
    done < "$MANIFEST"
}

require_manifest() {
    [ -n "$CANDIDATE" ] || die "manifest field is missing: candidate"
    [ -n "$CANDIDATE_SHA" ] || die "manifest field is missing: candidate_sha256"
    [ -n "$CANDIDATE_SIZE" ] || die "manifest field is missing: candidate_size"
    [ -n "$ROLLBACK" ] || die "manifest field is missing: rollback"
    [ -n "$ROLLBACK_SHA" ] || die "manifest field is missing: rollback_sha256"
    [ -n "$ROLLBACK_SIZE" ] || die "manifest field is missing: rollback_size"
    [ -n "$TARGET_PARTITION" ] || die "manifest field is missing: target_partition"
    [ -n "$TARGET_DEVICE" ] || die "manifest field is missing: target_device"
    [ -n "$SCATTER" ] || die "manifest field is missing: scatter"
    [ -n "$SCATTER_SHA" ] || die "manifest field is missing: scatter_sha256"
    [ -n "$XML" ] || die "manifest field is missing: xml"
    [ -n "$XML_SHA" ] || die "manifest field is missing: xml_sha256"
    [ -n "$STAGE_IMAGE" ] || die "manifest field is missing: stage_image"
    [ -n "$TREX_CAPTURE_ROOT" ] || die "manifest field is missing: trex_capture_root"
    [ -n "$EXPECTED_MODEL" ] || die "manifest field is missing: expected_model"
    [ -n "$EXPECTED_COMPATIBLE" ] || die "manifest field is missing: expected_compatible"
    [ -n "$EXPECTED_CMDLINE" ] || die "manifest field is missing: expected_cmdline_token"
    [ -n "$EXPECTED_CPU_ONLINE" ] || die "manifest field is missing: expected_cpu_online"
    [ -n "$EXPECTED_GADGET_IP" ] || die "manifest field is missing: expected_gadget_ip"
    [ -n "$EXPECTED_ETHERNET_IP" ] || die "manifest field is missing: expected_ethernet_ip"
    [ -n "$EXPECTED_MARKER" ] || die "manifest field is missing: expected_marker"
    [ -n "$FEATURE_POLICY" ] || die "manifest field is missing: feature_policy"
    [ -n "$ACCEPTANCE_WINDOW_SECONDS" ] || die "manifest field is missing: acceptance_window_seconds"
    [ -n "$WATCHDOG_PROFILE" ] || die "manifest field is missing: watchdog_profile"
    require_sha() {
        sha=$1
        label=$2
        case "$sha" in
            *[!0-9a-f]*|'') die "$label must be 64 lowercase hex characters" ;;
        esac
        [ "${#sha}" -eq 64 ] || die "$label must be 64 lowercase hex characters"
    }
    require_sha "$CANDIDATE_SHA" candidate_sha256
    require_sha "$ROLLBACK_SHA" rollback_sha256
    require_sha "$SCATTER_SHA" scatter_sha256
    require_sha "$XML_SHA" xml_sha256
    case "$ACCEPTANCE_WINDOW_SECONDS" in *[!0-9]*|'') die "acceptance_window_seconds must be numeric" ;; esac
    [ "$ACCEPTANCE_WINDOW_SECONDS" -ge 3 ] || die "acceptance_window_seconds must be at least 3"
    case "$FEATURE_POLICY" in connectivity-no-radio|allow-platform) ;; *) die "unknown feature_policy" ;; esac
    case "$WATCHDOG_PROFILE" in
        none)
            [ -z "$EXPECTED_WATCHDOG_IDENTITY$EXPECTED_WATCHDOG_STATE$EXPECTED_WATCHDOG_TIMEOUT" ] || die "watchdog fields are forbidden for watchdog_profile=none" ;;
        initramfs-petter)
            [ -n "$EXPECTED_WATCHDOG_IDENTITY" ] || die "manifest field is missing: expected_watchdog_identity"
            [ -n "$EXPECTED_WATCHDOG_STATE" ] || die "manifest field is missing: expected_watchdog_state"
            [ -n "$EXPECTED_WATCHDOG_TIMEOUT" ] || die "manifest field is missing: expected_watchdog_timeout"
            case "$EXPECTED_WATCHDOG_TIMEOUT" in *[!0-9]*|'') die "expected_watchdog_timeout must be numeric" ;; esac ;;
        *) die "unknown watchdog_profile" ;;
    esac
    [ "$TARGET_PARTITION" = boot/p22 ] || die "target_partition must be boot/p22"
    [ "$TARGET_DEVICE" = /dev/mmcblk0p22 ] || die "target_device must be /dev/mmcblk0p22"
    [ "$CANDIDATE_SIZE" = "$SIZE" ] || die "candidate_size must be $SIZE"
    [ "$ROLLBACK_SIZE" = "$SIZE" ] || die "rollback_size must be $SIZE"
    require_path() {
        path=$1
        label=$2
        case "$path" in
            /*) ;;
            *) die "$label must be absolute" ;;
        esac
        case "$path" in
            *[!A-Za-z0-9._:/=-]*) die "unsafe path in manifest: $label" ;;
        esac
    }
    require_path "$CANDIDATE" candidate
    require_path "$ROLLBACK" rollback
    require_path "$SCATTER" scatter
    require_path "$XML" xml
    require_path "$STAGE_IMAGE" stage_image
    require_path "$TREX_CAPTURE_ROOT" trex_capture_root
    case "$STAGE_IMAGE" in
        */boot.img) ;;
        *) die "stage_image must end in boot.img" ;;
    esac
    require_token() {
        token=$1
        case "$token" in
            *[!A-Za-z0-9._:/=,-]*) die "unsafe acceptance token in manifest" ;;
        esac
    }
    require_token "$EXPECTED_MODEL"
    require_token "$EXPECTED_COMPATIBLE"
    require_token "$EXPECTED_CMDLINE"
    require_token "$EXPECTED_CPU_ONLINE"
    require_token "$EXPECTED_GADGET_IP"
    require_token "$EXPECTED_ETHERNET_IP"
    require_token "$EXPECTED_MARKER"
    require_token "$EXPECTED_WATCHDOG_IDENTITY"
    require_token "$EXPECTED_WATCHDOG_STATE"
}

load_manifest
require_manifest

if [ "$PROOF_LEASE" = yes ]; then
    [ "$MODE" = --execute ] || die "--proof-lease requires --execute"
    [ "$WATCHDOG_PROFILE" = initramfs-petter ] || die "--proof-lease requires initramfs-petter manifest"
fi

if [ "$WATCHDOG_PROFILE" = initramfs-petter ]; then
    LEASE_MARKER=unattended_recovery=healthy
else
    LEASE_MARKER=$EXPECTED_MARKER
fi

device_ssh() {
    ssh -J trex -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes \
        -o ConnectTimeout=8 root@10.15.19.82 "$@"
}

hash_size() {
    expected=$1
    image=$2
    test "$(stat -Lc %s "$image")" -eq "$SIZE"
    test "$(sha256sum "$image" | cut -d' ' -f1)" = "$expected"
}

preflight_scatter() {
    test "$(sha256sum "$SCATTER" | cut -d' ' -f1)" = "$SCATTER_SHA"
    test "$(sha256sum "$XML" | cut -d' ' -f1)" = "$XML_SHA"
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
    test "$CANDIDATE_SIZE" -eq "$SIZE"
    test "$ROLLBACK_SIZE" -eq "$SIZE"
    preflight_scatter
}

preflight_device() {
    device_ssh "set -eu
target=\$(readlink -f /dev/disk/by-partlabel/boot)
test \"\$target\" = $TARGET_DEVICE
test \"\$target\" != /dev/mmcblk0p29
! grep -q \"^\$target \" /proc/mounts
test \"\$(blockdev --getsize64 \"\$target\")\" -eq 16777216
p22=\$(sha256sum \"\$target\" | cut -d' ' -f1)
test \"\$p22\" = $CANDIDATE_SHA || test \"\$p22\" = $ROLLBACK_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
sha256sum \"\$target\" /dev/mmcblk0p30 /dev/mmcblk0p31"
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

cleanup() {
    rc=$?
    trap - EXIT INT TERM
    stop_capture
    if [ "$rc" -ne 0 ] && [ -n "${RUN_LOCAL:-}" ] && [ -f "$RUN_LOCAL/state" ]; then
        case "$(cat "$RUN_LOCAL/state" 2>/dev/null || true)" in
            accepted_p22*|recovered_known_good_p22*|recovery_failed*|recovery_flash_failed*) ;;
            *) printf 'harness_failed rc=%s %s\n' "$rc" "$(date -Is)" > "$RUN_LOCAL/state" ;;
        esac
    fi
    exit "$rc"
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
    deadline=$(( $(date +%s) + limit ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if device_ssh 'test -s /proc/cmdline' >/dev/null 2>&1; then return 0; fi
        sleep 3
    done
    return 1
}

accept_candidate() {
    device_ssh "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $CANDIDATE_SHA
grep -q \"^/dev/mmcblk0p29 /gemian .* ro,\" /proc/mounts
grep -q \"^/dev/loop0 /nix/store squashfs ro,\" /proc/mounts
grep -Fq -- $EXPECTED_MODEL /proc/device-tree/model
grep -Fq -- $EXPECTED_COMPATIBLE /proc/device-tree/compatible
grep -Fq -- $EXPECTED_CMDLINE /proc/cmdline
test \"\$(cat /sys/devices/system/cpu/online)\" = $EXPECTED_CPU_ONLINE
gadget_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_GADGET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
ethernet_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_ETHERNET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
test -n \"\$gadget_if\"
test -n \"\$ethernet_if\"
grep -Fq -- \"$EXPECTED_MARKER\" /run/probe-status
! grep -Fq -- 'unattended_recovery=failed' /run/probe-status
case \"$FEATURE_POLICY\" in
  connectivity-no-radio)
    ! dmesg | grep -Eiq 'request_firmware|Direct firmware|wmt|btif|mtk-wifi|gnss|bluetooth|radio|fm|modem'
    ! ls /sys/bus/platform/devices | grep -Eiq 'consys|btif|wmt' ;;
  allow-platform) : ;;
  *) exit 1 ;;
esac
if [ \"$WATCHDOG_PROFILE\" = initramfs-petter ]; then
  grep -Fq -- 'panic=5' /proc/cmdline
  grep -Fq -- 'mtk_wdt.start_at_boot=1' /proc/cmdline
  watchdog_pid=\$(sed -n 's/.*watchdog_pid=\([0-9][0-9]*\).*/\1/p' /run/probe-status | tail -n 1)
  test -n \"\$watchdog_pid\"
  test -d \"/proc/\$watchdog_pid\"
  test \"\$(cat /sys/class/watchdog/watchdog0/identity)\" = \"$EXPECTED_WATCHDOG_IDENTITY\"
  test \"\$(cat /sys/class/watchdog/watchdog0/state)\" = \"$EXPECTED_WATCHDOG_STATE\"
  test \"\$(cat /sys/class/watchdog/watchdog0/timeout)\" = \"$EXPECTED_WATCHDOG_TIMEOUT\"
  test -r /sys/class/watchdog/watchdog0/bootstatus
  owner_device=\$(for fd in /proc/\$watchdog_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
  test -n \"\$owner_device\"
fi
accept_tmp=/run/unattended-recovery.accepted.tmp.\$\$
printf '%s\\n' \"$LEASE_MARKER\" > \"\$accept_tmp\"
mv -f \"\$accept_tmp\" /run/unattended-recovery.accepted
test \"\$(cat /run/unattended-recovery.accepted)\" = \"$LEASE_MARKER\""
}

start_tool() {
    log=$1
    # Keep the wrapper PID (no setsid fork) so a future bounded abort can
    # identify the owner. The wrapper's timeout remains the final kill
    # boundary for Flash Tool itself.
    ssh trex "nohup sh '$RUN_SHARED/flash-wrapper.sh' '$STATE' '$log' '$XML' </dev/null > '$log' 2>&1 & echo \$! > '$RUN_SHARED/tool.pid'"
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
    # Never launch a second Flash Tool while the candidate wrapper might still
    # own the USB port. The extra ten seconds avoids an exact timeout race;
    # failure here is a manual boundary, not an unsafe concurrent retry.
    if ! wait_state flash_rc 250; then
        printf 'recovery_blocked_candidate_tool_timeout %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    stage_image "$ROLLBACK" "$ROLLBACK_SHA"
    rollback_log=$RUN_SHARED/rollback-flash.log
    start_tool "$rollback_log"
    if [ "$PROOF_LEASE" = yes ]; then
        printf 'lease_proof_rollback_armed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    fi
    # If candidate userspace is still reachable, request a clean restart only
    # after rollback is waiting. If it is hung before init, wait for a natural
    # watchdog/preloader transition; no unsafe force-reset is attempted.
    if [ "$PROOF_LEASE" != yes ] && wait_ssh 1; then request_reboot; fi
    if ! wait_state flash_rc 250; then
        printf 'manual_reset_required_no_preloader %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    state=$(cat "$STATE")
    case "$state" in flash_rc=0*) ;; *) printf 'recovery_flash_failed %s\n' "$state" > "$RUN_LOCAL/state"; return 1;; esac
    if ! wait_ssh 40; then printf 'manual_reset_required_no_ssh %s\n' "$(date -Is)" > "$RUN_LOCAL/state"; return 1; fi
    device_ssh "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $ROLLBACK_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513"
    printf 'recovered_known_good_p22 %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
}

preflight_local
preflight_device > /dev/null
if [ "$MODE" = --dry-run ]; then
    printf 'dry-run-preflight-ok %s\n' "$(date -Is)"
    exit 0
fi

trap cleanup EXIT INT TERM
start_capture
stage_image "$CANDIDATE" "$CANDIDATE_SHA"
candidate_log=$RUN_SHARED/candidate-flash.log
start_tool "$candidate_log"
request_reboot
if [ "$PROOF_LEASE" = yes ]; then
    # Deliberately do not write the acceptance marker. recover() starts the
    # rollback tool first, then waits for the candidate lease to kill its
    # petter and expose the next watchdog/preloader window.
    wait_ssh "$ACCEPTANCE_WINDOW_SECONDS" || true
    recover
elif wait_ssh "$ACCEPTANCE_WINDOW_SECONDS" && accept_candidate; then
    device_ssh "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $CANDIDATE_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
sha256sum /dev/mmcblk0p22 /dev/mmcblk0p30 /dev/mmcblk0p31" > "$RUN_LOCAL/final-partition-hashes"
    printf 'accepted_p22 %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    exit 0
fi
recover
