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
# shellcheck disable=SC2029 # deliberate remote shell expansion
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
XML_RUN_FILE=
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
PROBE_CAPTURE_PID=
P22_WRITE_MARKER=no
PROOF_VALIDATED=no
ROOTFS_POLICY=
HOST_NET_POLICY=
SSH_PATH_POLICY=
POWER_PREFLIGHT_POLICY=
TRANSACTION_POLICY=
# Full-NixOS candidates opt into the explicit Stage1 -> switch_root -> Stage2
# contract below.  Existing probe-only manifests leave stage2_policy=none and
# retain their previous validation semantics.
STAGE2_POLICY=
STAGE1_WATCHDOG_OWNER_MARKER=
STAGE1_HANDOFF_PATH=
STAGE2_WATCHDOG_OWNER_UNIT=
STAGE2_WATCHDOG_STATE=
STAGE2_WATCHDOG_EVIDENCE=
STAGE2_SUCCESS_MARKER=
STAGE2_STORE_SOURCE=
STAGE2_STORE_SHA=
STAGE2_STORE_SIZE=
STAGE2_STORE_TARGET=
STAGE2_STORE_TARGET_LIVE=
STAGE1_STORE_TARGET=
STAGE1_STORE_SHA=
STAGE1_STORE_SIZE=
STAGE1_PROVISION_WAIT_SECONDS=
STAGE2_STORE_TEMP=
STAGE2_STORE_PROVISIONED=no
LEASE_SECONDS=
ACCEPTANCE_DEADLINE=
HOST_NET_FALLBACK_ARMED=no
CANDIDATE_HOSTKEY_MODE=no
VALIDATION_GADGET_ONLY=no
SSH_DEADLINE_SECONDS=15
SCP_DEADLINE_SECONDS=30
# Derived from the exact manifest timing profile after schema validation.
PROVISION_UPLOAD_TIMEOUT_SECONDS=
STAGE2_READINESS_TIMEOUT_SECONDS=5
STAGE2_READINESS_CONNECT_TIMEOUT_SECONDS=2
# Both known-good and candidate initramfs hold their user-visible services
# behind the approximately 48-second DVFSP late-validation gate.  Trex may
# finish restoring p22 before that boot reaches SSH, so recovery readback must
# cover the measured gate plus USB/dropbear settling time.
RECOVERY_SSH_TIMEOUT_SECONDS=90
ACCEPTANCE_COMMITTED=no
ATTEMPT_COUNTER=0
TOOL_PID_FILE=
TOOL_PGID_FILE=
TOOL_SID_FILE=
TOOL_STARTTIME_FILE=
TOOL_LAUNCH_PID_FILE=
TOOL_LOCK_FILE=
FLASH_LOCK_FILE=
TRANSACTION_LOCK_FILE=
TRANSACTION_UNIT=
SUPERVISOR_UNIT=
SUPERVISOR_STATE=
ROLLBACK_RESCUE_IMAGE=
SUPERVISOR_KEEP=no

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
            rootfs_policy) [ -z "$ROOTFS_POLICY" ] || die "duplicate rootfs_policy"; ROOTFS_POLICY=$value ;;
            host_net_policy) [ -z "$HOST_NET_POLICY" ] || die "duplicate host_net_policy"; HOST_NET_POLICY=$value ;;
            ssh_path_policy) [ -z "$SSH_PATH_POLICY" ] || die "duplicate ssh_path_policy"; SSH_PATH_POLICY=$value ;;
            power_preflight_policy) [ -z "$POWER_PREFLIGHT_POLICY" ] || die "duplicate power_preflight_policy"; POWER_PREFLIGHT_POLICY=$value ;;
            transaction_policy) [ -z "$TRANSACTION_POLICY" ] || die "duplicate transaction_policy"; TRANSACTION_POLICY=$value ;;
            stage2_policy) [ -z "$STAGE2_POLICY" ] || die "duplicate stage2_policy"; STAGE2_POLICY=$value ;;
            stage1_watchdog_owner_marker) [ -z "$STAGE1_WATCHDOG_OWNER_MARKER" ] || die "duplicate stage1_watchdog_owner_marker"; STAGE1_WATCHDOG_OWNER_MARKER=$value ;;
            stage1_handoff_path) [ -z "$STAGE1_HANDOFF_PATH" ] || die "duplicate stage1_handoff_path"; STAGE1_HANDOFF_PATH=$value ;;
            stage2_watchdog_owner_unit) [ -z "$STAGE2_WATCHDOG_OWNER_UNIT" ] || die "duplicate stage2_watchdog_owner_unit"; STAGE2_WATCHDOG_OWNER_UNIT=$value ;;
            stage2_watchdog_state) [ -z "$STAGE2_WATCHDOG_STATE" ] || die "duplicate stage2_watchdog_state"; STAGE2_WATCHDOG_STATE=$value ;;
            stage2_watchdog_evidence) [ -z "$STAGE2_WATCHDOG_EVIDENCE" ] || die "duplicate stage2_watchdog_evidence"; STAGE2_WATCHDOG_EVIDENCE=$value ;;
            stage2_success_marker) [ -z "$STAGE2_SUCCESS_MARKER" ] || die "duplicate stage2_success_marker"; STAGE2_SUCCESS_MARKER=$value ;;
            stage2_store_source) [ -z "$STAGE2_STORE_SOURCE" ] || die "duplicate stage2_store_source"; STAGE2_STORE_SOURCE=$value ;;
            stage2_store_sha256) [ -z "$STAGE2_STORE_SHA" ] || die "duplicate stage2_store_sha256"; STAGE2_STORE_SHA=$value ;;
            stage2_store_size) [ -z "$STAGE2_STORE_SIZE" ] || die "duplicate stage2_store_size"; STAGE2_STORE_SIZE=$value ;;
            stage2_store_target) [ -z "$STAGE2_STORE_TARGET" ] || die "duplicate stage2_store_target"; STAGE2_STORE_TARGET=$value ;;
            stage2_store_target_live) [ -z "$STAGE2_STORE_TARGET_LIVE" ] || die "duplicate stage2_store_target_live"; STAGE2_STORE_TARGET_LIVE=$value ;;
            stage1_store_target) [ -z "$STAGE1_STORE_TARGET" ] || die "duplicate stage1_store_target"; STAGE1_STORE_TARGET=$value ;;
            stage1_store_sha256) [ -z "$STAGE1_STORE_SHA" ] || die "duplicate stage1_store_sha256"; STAGE1_STORE_SHA=$value ;;
            stage1_store_size) [ -z "$STAGE1_STORE_SIZE" ] || die "duplicate stage1_store_size"; STAGE1_STORE_SIZE=$value ;;
            stage1_provision_wait_seconds) [ -z "$STAGE1_PROVISION_WAIT_SECONDS" ] || die "duplicate stage1_provision_wait_seconds"; STAGE1_PROVISION_WAIT_SECONDS=$value ;;
            lease_seconds) [ -z "$LEASE_SECONDS" ] || die "duplicate lease_seconds"; LEASE_SECONDS=$value ;;
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
    [ -n "$ROOTFS_POLICY" ] || die "manifest field is missing: rootfs_policy"
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
    case "$ROOTFS_POLICY" in nixos-stage2|enumeration-only) ;; *) die "unknown rootfs_policy" ;; esac
    case "$HOST_NET_POLICY" in none|required) ;; *) die "unknown host_net_policy" ;; esac
    case "$SSH_PATH_POLICY" in fallback|both) ;; *) die "unknown ssh_path_policy" ;; esac
    case "$POWER_PREFLIGHT_POLICY" in none|required) ;; *) die "unknown power_preflight_policy" ;; esac
    case "$TRANSACTION_POLICY" in persistent-acceptance|observe-always-rollback) ;; *) die "unknown transaction_policy" ;; esac
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
    [ -n "$LEASE_SECONDS" ] || LEASE_SECONDS=90
    [ -n "$STAGE1_PROVISION_WAIT_SECONDS" ] || STAGE1_PROVISION_WAIT_SECONDS=65
    case "$LEASE_SECONDS" in *[!0-9]*|'') die "lease_seconds must be numeric" ;; esac
    case "$STAGE1_PROVISION_WAIT_SECONDS" in *[!0-9]*|'') die "stage1_provision_wait_seconds must be numeric" ;; esac
    [ "$LEASE_SECONDS" -ge 3 ] || die "lease_seconds must be at least 3"
    [ "$STAGE1_PROVISION_WAIT_SECONDS" -ge 30 ] || die "stage1_provision_wait_seconds must be at least 30"
    if [ "$WATCHDOG_PROFILE" = initramfs-petter ] && [ "$ACCEPTANCE_WINDOW_SECONDS" -ge "$LEASE_SECONDS" ]; then
        die "watchdog acceptance_window_seconds must be less than lease_seconds"
    fi
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
    require_token "$ROOTFS_POLICY"
    require_token "$HOST_NET_POLICY"
    case "$STAGE2_POLICY" in
        none)
            [ -z "$STAGE1_WATCHDOG_OWNER_MARKER$STAGE1_HANDOFF_PATH$STAGE2_WATCHDOG_OWNER_UNIT$STAGE2_WATCHDOG_STATE$STAGE2_WATCHDOG_EVIDENCE$STAGE2_SUCCESS_MARKER$STAGE2_STORE_SOURCE$STAGE2_STORE_SHA$STAGE2_STORE_SIZE$STAGE2_STORE_TARGET$STAGE2_STORE_TARGET_LIVE$STAGE1_STORE_TARGET$STAGE1_STORE_SHA$STAGE1_STORE_SIZE" ] ||
                die "stage2 watchdog fields require stage2_policy=watchdog-takeover-required" ;;
        watchdog-takeover-required)
            [ "$ROOTFS_POLICY" = nixos-stage2 ] || die "stage2 watchdog takeover requires rootfs_policy=nixos-stage2"
            [ "$WATCHDOG_PROFILE" = initramfs-petter ] || die "stage2 watchdog takeover requires watchdog_profile=initramfs-petter"
            [ "$SSH_PATH_POLICY" = both ] || die "stage2 watchdog takeover requires ssh_path_policy=both"
            [ "$POWER_PREFLIGHT_POLICY" = required ] || die "stage2 watchdog takeover requires power_preflight_policy=required"
            [ "$TRANSACTION_POLICY" = observe-always-rollback ] || die "stage2 watchdog takeover requires observe-always-rollback"
            [ -n "$STAGE1_WATCHDOG_OWNER_MARKER" ] || die "manifest field is missing: stage1_watchdog_owner_marker"
            [ "$STAGE1_WATCHDOG_OWNER_MARKER" = watchdog=petting ] || die "stage1_watchdog_owner_marker must be watchdog=petting"
            [ "$STAGE1_HANDOFF_PATH" = /run/stage1-handoff ] || die "stage1_handoff_path must be /run/stage1-handoff"
            [ -n "$STAGE2_WATCHDOG_OWNER_UNIT" ] || die "manifest field is missing: stage2_watchdog_owner_unit"
            [ -n "$STAGE2_WATCHDOG_STATE" ] || die "manifest field is missing: stage2_watchdog_state"
            [ "$STAGE2_WATCHDOG_STATE" = active ] || die "stage2_watchdog_state must be active"
            [ "$STAGE2_WATCHDOG_EVIDENCE" = 'stage2=multi-user watchdog=petting acceptance=external' ] || die "stage2_watchdog_evidence does not match the Stage2 handoff contract"
            [ -n "$STAGE2_SUCCESS_MARKER" ] || die "manifest field is missing: stage2_success_marker"
            [ "$STAGE2_SUCCESS_MARKER" = /run/gemini-mainline-success ] || die "stage2_success_marker must be /run/gemini-mainline-success"
            [ -n "$STAGE2_STORE_SOURCE" ] || die "manifest field is missing: stage2_store_source"
            [ -n "$STAGE2_STORE_SHA" ] || die "manifest field is missing: stage2_store_sha256"
            [ -n "$STAGE2_STORE_SIZE" ] || die "manifest field is missing: stage2_store_size"
            [ -n "$STAGE2_STORE_TARGET_LIVE" ] || die "manifest field is missing: stage2_store_target_live"
            [ -n "$STAGE1_STORE_TARGET" ] || die "manifest field is missing: stage1_store_target"
            [ -n "$STAGE1_STORE_SHA" ] || die "manifest field is missing: stage1_store_sha256"
            [ -n "$STAGE1_STORE_SIZE" ] || die "manifest field is missing: stage1_store_size"
            case "$STAGE2_STORE_TARGET" in /nixos/*.squashfs) ;; *) die "stage2_store_target must be a unique /nixos/*.squashfs path" ;; esac
            case "$STAGE2_STORE_TARGET_LIVE" in /gemian/nixos/*.squashfs) ;; *) die "stage2_store_target_live must be /gemian/nixos/*.squashfs" ;; esac
            [ "${STAGE2_STORE_TARGET_LIVE##/gemian}" = "$STAGE2_STORE_TARGET" ] || die "live and Stage2 store targets must name the same file"
            [ "$STAGE2_STORE_TARGET" != /nixos/mainline-nixos-connectivity-m0.squashfs ] || die "Stage2 store target must not replace the Stage-A store"
            [ "$STAGE1_STORE_TARGET" = /gemian/nixos/mainline-nixos-connectivity-m0.squashfs ] || die "stage1_store_target must be the Stage-A store path"
            require_token "$STAGE1_WATCHDOG_OWNER_MARKER"
            require_token "$STAGE2_WATCHDOG_OWNER_UNIT"
            require_token "$STAGE2_WATCHDOG_STATE"
            require_sha "$STAGE2_STORE_SHA" stage2_store_sha256
            case "$STAGE2_STORE_SIZE" in ''|*[!0-9]*) die "stage2_store_size must be numeric" ;; esac
            [ "$STAGE2_STORE_SIZE" -gt 0 ] || die "stage2_store_size must be positive"
            require_sha "$STAGE1_STORE_SHA" stage1_store_sha256
            case "$STAGE1_STORE_SIZE" in ''|*[!0-9]*) die "stage1_store_size must be numeric" ;; esac
            [ "$STAGE1_STORE_SIZE" -gt 0 ] || die "stage1_store_size must be positive"
            require_path "$STAGE1_HANDOFF_PATH" stage1_handoff_path
            require_path "$STAGE2_STORE_SOURCE" stage2_store_source
            require_path "$STAGE2_STORE_TARGET" stage2_store_target
            require_path "$STAGE2_STORE_TARGET_LIVE" stage2_store_target_live
            require_path "$STAGE1_STORE_TARGET" stage1_store_target
            require_path "$STAGE2_SUCCESS_MARKER" stage2_success_marker
            case "$STAGE2_WATCHDOG_OWNER_UNIT" in *.service) ;; *) die "stage2_watchdog_owner_unit must end in .service" ;; esac
            case "$STAGE1_PROVISION_WAIT_SECONDS:$LEASE_SECONDS:$ACCEPTANCE_WINDOW_SECONDS" in
                65:90:80|120:180:150) ;;
                *) die "unknown Stage1 provision/watchdog/acceptance timing profile" ;;
            esac ;;
        *) die "unknown stage2_policy" ;;
    esac
}

load_manifest
[ -n "$HOST_NET_POLICY" ] || HOST_NET_POLICY=none
[ -n "$SSH_PATH_POLICY" ] || SSH_PATH_POLICY=fallback
[ -n "$POWER_PREFLIGHT_POLICY" ] || POWER_PREFLIGHT_POLICY=none
[ -n "$TRANSACTION_POLICY" ] || TRANSACTION_POLICY=persistent-acceptance
[ -n "$STAGE2_POLICY" ] || STAGE2_POLICY=none
[ -n "$LEASE_SECONDS" ] || LEASE_SECONDS=90
[ -n "$STAGE1_PROVISION_WAIT_SECONDS" ] || STAGE1_PROVISION_WAIT_SECONDS=65
require_manifest

# Leave ten seconds for the remote size/hash/move/sync contract after the
# bounded stream exits. The two accepted profiles yield 55s and 110s.
PROVISION_UPLOAD_TIMEOUT_SECONDS=$((STAGE1_PROVISION_WAIT_SECONDS - 10))

if [ "$PROOF_LEASE" = yes ]; then
    [ "$MODE" = --execute ] || die "--proof-lease requires --execute"
    [ "$WATCHDOG_PROFILE" = initramfs-petter ] || die "--proof-lease requires initramfs-petter manifest"
fi
if [ "$MODE" = --execute ] && [ "$TRANSACTION_POLICY" = observe-always-rollback ] &&
    [ "$PROOF_LEASE" != yes ]; then
    die "observe-always-rollback requires --proof-lease; persistent acceptance is disabled"
fi

if [ "$WATCHDOG_PROFILE" = initramfs-petter ]; then
    LEASE_MARKER=unattended_recovery=healthy
else
    LEASE_MARKER=$EXPECTED_MARKER
fi

device_ssh_gadget() {
    if [ "$CANDIDATE_HOSTKEY_MODE" = yes ] && candidate_hostkey_allowed; then
        timeout "$SSH_DEADLINE_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
            -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
            -o ServerAliveCountMax=2 -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null root@10.15.19.82 "$@"
    else
        timeout "$SSH_DEADLINE_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
            -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
            -o ServerAliveCountMax=2 root@10.15.19.82 "$@"
    fi
}

device_ssh_gadget_provision() {
    if [ "$CANDIDATE_HOSTKEY_MODE" = yes ] && candidate_hostkey_allowed; then
        timeout "$PROVISION_UPLOAD_TIMEOUT_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
            -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
            -o ServerAliveCountMax=2 -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null root@10.15.19.82 "$@"
    else
        timeout "$PROVISION_UPLOAD_TIMEOUT_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
            -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
            -o ServerAliveCountMax=2 root@10.15.19.82 "$@"
    fi
}

device_ssh_gadget_fast() {
    # Stage2 readiness is a gadget-only liveness check. A right-NIC fallback
    # here can spend another full SSH timeout and starve Stage1 provisioning.
    if [ "$CANDIDATE_HOSTKEY_MODE" = yes ] && candidate_hostkey_allowed; then
        timeout "$STAGE2_READINESS_TIMEOUT_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout="$STAGE2_READINESS_CONNECT_TIMEOUT_SECONDS" \
            -o ConnectionAttempts=1 -o ServerAliveInterval=1 \
            -o ServerAliveCountMax=1 -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null root@10.15.19.82 "$@"
    else
        timeout "$STAGE2_READINESS_TIMEOUT_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout="$STAGE2_READINESS_CONNECT_TIMEOUT_SECONDS" \
            -o ConnectionAttempts=1 -o ServerAliveInterval=1 \
            -o ServerAliveCountMax=1 root@10.15.19.82 "$@"
    fi
}

device_ssh_right() {
    if [ "$CANDIDATE_HOSTKEY_MODE" = yes ] && candidate_hostkey_allowed; then
        timeout "$SSH_DEADLINE_SECONDS" ssh -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
            -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
            -o ServerAliveCountMax=2 -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null "root@$EXPECTED_ETHERNET_IP" "$@"
    else
        timeout "$SSH_DEADLINE_SECONDS" ssh -i /home/grw/.ssh/id_ed25519 \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
            -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
            -o ServerAliveCountMax=2 "root@$EXPECTED_ETHERNET_IP" "$@"
    fi
}

host_net_fallback_allowed() {
    [ "$HOST_NET_FALLBACK_ARMED" = yes ] || return 1
    [ "$HOST_NET_POLICY" = required ] || return 1
    [ -n "${RUN_SHARED:-}" ] || return 1
    identity=$(trex_ssh "cat '$RUN_SHARED/trex-host-net.state'" 2>/dev/null) || return 1
    case "$identity" in
        "identity=verified usb=0525:a4a2 mac=42:00:15:19:82:00 iface="*" epoch="[0-9]*) ;;
        *) return 1 ;;
    esac
    epoch=${identity##* epoch=}
    now=$(date +%s)
    case "$epoch" in *[!0-9]*|'') return 1 ;; esac
    [ "$epoch" -le "$now" ] || return 1
    # The per-run marker is exact-MAC/USB-bound and short-lived.  Full remote
    # candidate validation still requires the expected model, SHA, and the
    # device's own host-net marker before acceptance.
    [ $((now - epoch)) -le 300 ]
}

candidate_hostkey_allowed() {
    [ "$CANDIDATE_HOSTKEY_MODE" = yes ] || return 1
    host_net_fallback_allowed || return 1
    # The ephemeral host-key policy is permitted only while the exact Gemini
    # USB gadget is physically enumerated and the exact-MAC watcher marker is
    # fresh.  It is never used by preflight, reboot dispatch, or rollback.
    trex_ssh 'lsusb -d 0525:a4a2 >/dev/null 2>&1'
}

device_ssh() {
    if [ "$VALIDATION_GADGET_ONLY" = yes ]; then
        device_ssh_gadget "$@"
        return $?
    fi
    if device_ssh_gadget "$@"; then
        return 0
    else
        gadget_rc=$?
    fi
    if host_net_fallback_allowed; then
        device_ssh_right "$@"
    else
        return "$gadget_rc"
    fi
}

trex_ssh() {
    timeout "$SSH_DEADLINE_SECONDS" ssh -o BatchMode=yes -o ConnectTimeout=8 \
        -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
        -o ServerAliveCountMax=2 trex "$@"
}

trex_scp() {
    timeout "$SCP_DEADLINE_SECONDS" scp -o BatchMode=yes -o ConnectTimeout=8 \
        -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
        -o ServerAliveCountMax=2 "$@"
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
    if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
        test "$(stat -Lc %s "$STAGE2_STORE_SOURCE")" -eq "$STAGE2_STORE_SIZE"
        test "$(sha256sum "$STAGE2_STORE_SOURCE" | cut -d' ' -f1)" = "$STAGE2_STORE_SHA"
    fi
    preflight_scatter
}

preflight_device() {
    stage2_store_checks=
    if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
stage2_store_checks="test -d /gemian/nixos
test -f '$STAGE1_STORE_TARGET'
test \"\$(stat -Lc %s '$STAGE1_STORE_TARGET')\" -eq '$STAGE1_STORE_SIZE'
test \"\$(sha256sum '$STAGE1_STORE_TARGET' | cut -d' ' -f1)\" = '$STAGE1_STORE_SHA'
test ! -b '$STAGE1_STORE_TARGET'
test ! -L '$STAGE1_STORE_TARGET'
test ! -L '$STAGE2_STORE_TARGET_LIVE'
if test -e '$STAGE2_STORE_TARGET_LIVE'; then
  test ! -L '$STAGE2_STORE_TARGET_LIVE'
  test ! -b '$STAGE2_STORE_TARGET_LIVE'
  test \"\$(stat -Lc %s '$STAGE2_STORE_TARGET_LIVE')\" -eq '$STAGE2_STORE_SIZE'
  test \"\$(sha256sum '$STAGE2_STORE_TARGET_LIVE' | cut -d' ' -f1)\" = '$STAGE2_STORE_SHA'
fi"
    fi
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
    if [ -n "$stage2_store_checks" ]; then
        device_ssh "set -eu
$stage2_store_checks"
    fi
}

stage_image() {
    source_image=$1
    expected=$2
    cp "$source_image" "$STAGE_IMAGE"
    test "$(stat -Lc %s "$STAGE_IMAGE")" -eq "$SIZE"
    test "$(sha256sum "$STAGE_IMAGE" | cut -d' ' -f1)" = "$expected"
    # /mnt/Home is shared storage, but the writer runs on Trex. Verify the
    # bytes from Trex immediately before every candidate/rollback wrapper.
    trex_ssh "test \"\$(stat -Lc %s '$STAGE_IMAGE')\" -eq '$SIZE'; test \"\$(sha256sum '$STAGE_IMAGE' | cut -d' ' -f1)\" = '$expected'"
}

provision_stage2_store() {
    [ "$STAGE2_POLICY" = watchdog-takeover-required ] || return 0
    init_target=/mnt$STAGE2_STORE_TARGET_LIVE
    init_stage1_target=/mnt$STAGE1_STORE_TARGET
    provision_tmp=$init_target.provision.tmp
    # The manifest schema and source preflight already prove this is the exact,
    # positive Stage2 byte count.  df -Pk reports 1024-byte blocks, so round
    # the payload up before comparing it with p29's non-root-available space.
    # No source establishes an ext4 metadata allowance for this transaction;
    # do not invent a magic headroom value here.
    required_kib=$(((STAGE2_STORE_SIZE + 1023) / 1024))
    STAGE2_STORE_TEMP=$provision_tmp
    required_line="store-provision=required target=$init_target temp=$provision_tmp sha256=$STAGE2_STORE_SHA size=$STAGE2_STORE_SIZE"
    ready_line="store-provision=ready sha256=$STAGE2_STORE_SHA size=$STAGE2_STORE_SIZE"
    # Stage1 alone opens p29 journaled rw. The host streams over gadget SSH
    # only after Stage1 publishes the exact request marker.
    if device_ssh_gadget "set -eu
test -f '$init_target'
test ! -L '$init_target'
test \"\$(stat -Lc %s '$init_target')\" -eq '$STAGE2_STORE_SIZE'
test \"\$(sha256sum '$init_target' | cut -d' ' -f1)\" = '$STAGE2_STORE_SHA'
test \"\$(stat -Lc %s '$init_stage1_target')\" -eq '$STAGE1_STORE_SIZE'
test \"\$(sha256sum '$init_stage1_target' | cut -d' ' -f1)\" = '$STAGE1_STORE_SHA'"; then
        STAGE2_STORE_TEMP=
        STAGE2_STORE_PROVISIONED=yes
        return 0
    fi
    if device_ssh_gadget "set -eu
test -f '$STAGE2_STORE_TARGET_LIVE'
test ! -L '$STAGE2_STORE_TARGET_LIVE'
test \"\$(stat -Lc %s '$STAGE2_STORE_TARGET_LIVE')\" -eq '$STAGE2_STORE_SIZE'
test \"\$(sha256sum '$STAGE2_STORE_TARGET_LIVE' | cut -d' ' -f1)\" = '$STAGE2_STORE_SHA'
test -f '$STAGE1_STORE_TARGET'
test \"\$(stat -Lc %s '$STAGE1_STORE_TARGET')\" -eq '$STAGE1_STORE_SIZE'
test \"\$(sha256sum '$STAGE1_STORE_TARGET' | cut -d' ' -f1)\" = '$STAGE1_STORE_SHA'"; then
        STAGE2_STORE_TEMP=
        STAGE2_STORE_PROVISIONED=yes
        return 0
    fi
    # log() prefixes every Stage1 line; require the complete emitted line so
    # a similarly named or embedded token cannot authorize provisioning.
    device_ssh_gadget "grep -Fqx -- 'GEMINI_MAINLINE_NIXOS: $required_line' /run/stage1.log" || return 1
    if ! device_ssh_gadget_provision "set -eu
test ! -e '$init_target'
if test -e '$provision_tmp' || test -L '$provision_tmp'; then
  test ! -L '$provision_tmp'
  test -f '$provision_tmp'
  test ! -b '$provision_tmp'
  test \"\$(stat -Lc %h '$provision_tmp')\" -eq 1
  stale_size=\$(stat -Lc %s '$provision_tmp')
  test \"\$stale_size\" -le '$STAGE2_STORE_SIZE'
  rm -- '$provision_tmp'
  test ! -e '$provision_tmp'
  test ! -L '$provision_tmp'
fi
# BusyBox df supports POSIX -P output and -k 1024-byte blocks.  Pin both the
# backing device and mountpoint: a nested mount must not authorize a p29 write.
available_kib=\$(df -Pk /mnt/gemian/nixos | awk 'NR == 2 && \$1 == \"/dev/mmcblk0p29\" && \$6 == \"/mnt/gemian\" { print \$4; exit }')
case \"\$available_kib\" in
  ''|*[!0-9]*) exit 1 ;;
esac
test \"\$available_kib\" -ge '$required_kib'
cat > '$provision_tmp'
test \"\$(stat -Lc %s '$provision_tmp')\" -eq '$STAGE2_STORE_SIZE'
test \"\$(sha256sum '$provision_tmp' | cut -d' ' -f1)\" = '$STAGE2_STORE_SHA'
test ! -e '$init_target'
test ! -L '$init_target'
mv '$provision_tmp' '$init_target'
sync
test \"\$(stat -Lc %s '$init_target')\" -eq '$STAGE2_STORE_SIZE'
test \"\$(sha256sum '$init_target' | cut -d' ' -f1)\" = '$STAGE2_STORE_SHA'
test \"\$(stat -Lc %s '$init_stage1_target')\" -eq '$STAGE1_STORE_SIZE'
test \"\$(sha256sum '$init_stage1_target' | cut -d' ' -f1)\" = '$STAGE1_STORE_SHA'
printf '%s\\n' '$ready_line' > /run/store-provision.ready
test \"\$(cat /run/store-provision.ready)\" = '$ready_line'" < "$STAGE2_STORE_SOURCE"; then
        return 1
    fi
    device_ssh_gadget "set -eu
test \"\$(cat /run/store-provision.ready)\" = '$ready_line'
test \"\$(stat -Lc %s '$init_target')\" -eq '$STAGE2_STORE_SIZE'
test \"\$(sha256sum '$init_target' | cut -d' ' -f1)\" = '$STAGE2_STORE_SHA'
test \"\$(stat -Lc %s '$init_stage1_target')\" -eq '$STAGE1_STORE_SIZE'
test \"\$(sha256sum '$init_stage1_target' | cut -d' ' -f1)\" = '$STAGE1_STORE_SHA'" || return 1
    STAGE2_STORE_TEMP=
    STAGE2_STORE_PROVISIONED=yes
}

start_capture() {
    run_name=p22-recovery-$(date +%Y%m%d-%H%M%S)
    run_name=$run_name-$$
    RUN_LOCAL=$ROOT/artifacts/$run_name
    RUN_SHARED=$TREX_CAPTURE_ROOT/$run_name
    # The pid suffix prevents ordinary same-second collisions; mkdir without
    # -p is the final guard against a reused pid or a stale run directory.
    mkdir "$RUN_LOCAL"
    trex_ssh "test -d '$TREX_CAPTURE_ROOT'; mkdir '$RUN_SHARED'"
    STATE=$RUN_SHARED/state
    FLASH_LOCK_FILE=$TREX_CAPTURE_ROOT/.p22-flash-writer.lock
    TRANSACTION_LOCK_FILE=$TREX_CAPTURE_ROOT/.p22-transaction.lock
    TRANSACTION_UNIT=p22-transaction-$run_name
    SUPERVISOR_UNIT=p22-proof-$run_name
    ROLLBACK_RESCUE_IMAGE=$RUN_SHARED/rollback-rescue.img
    XML_RUN_FILE=$RUN_SHARED/download-only-p22.xml
    printf 'preflight %s mode=%s\n' "$(date -Is)" "$MODE" > "$RUN_LOCAL/state"
    device_ssh 'cat /sys/fs/pstore/console-ramoops-0' > "$RUN_LOCAL/pstore-pre" 2>/dev/null || true
    device_ssh 'dmesg' > "$RUN_LOCAL/dmesg-pre"
    device_ssh 'sha256sum /dev/mmcblk0p22' > "$RUN_LOCAL/p22-pre-hash"
    # Acquire a Trex-owned transaction lease before staging any image.  The
    # service is bounded by its holder script and survives loss of this SSH
    # session; a second harness cannot enter the writer lane concurrently.
    trex_scp "$ROOT/research/p22-trex-transaction-holder.sh" "trex:$RUN_SHARED/p22-trex-transaction-holder.sh" >/dev/null
    trex_ssh "chmod 700 '$RUN_SHARED/p22-trex-transaction-holder.sh'; systemd-run --user --unit='$TRANSACTION_UNIT' --collect --quiet '$RUN_SHARED/p22-trex-transaction-holder.sh' '$TRANSACTION_LOCK_FILE' '$RUN_SHARED/transaction-owner' 900"
    transaction_ready=no
    transaction_wait=0
    while [ "$transaction_wait" -lt 15 ]; do
        if trex_ssh "systemctl --user is-active --quiet '$TRANSACTION_UNIT' && test -s '$RUN_SHARED/transaction-owner'"; then
            transaction_ready=yes
            break
        fi
        sleep 1
        transaction_wait=$((transaction_wait + 1))
    done
    if [ "$transaction_ready" != yes ]; then
        printf 'recovery_blocked_transaction_owner %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    # These are diagnostics only; the holder above owns the transaction lock.
    # shellcheck disable=SC2029
    trex_ssh "nohup timeout 900 journalctl -k -f -o short-iso > '$RUN_SHARED/trex-kernel.log' 2>&1 & echo \$! > '$RUN_SHARED/kernel.pid'; nohup timeout 900 ip monitor link addr > '$RUN_SHARED/trex-ip.log' 2>&1 & echo \$! > '$RUN_SHARED/ip.pid'; nohup timeout 900 sh -c 'while :; do date -Is; lsusb; sleep 0.10; done' > '$RUN_SHARED/trex-usb.log' 2>&1 & echo \$! > '$RUN_SHARED/usb.pid'"
    # Preserve an immutable rescue copy before candidate staging.  The
    # supervisor can therefore restore the known-good p22 even if this host
    # process dies after candidate flash and before recover().
    cp "$ROLLBACK" "$ROLLBACK_RESCUE_IMAGE"
    test "$(stat -Lc %s "$ROLLBACK_RESCUE_IMAGE")" -eq "$SIZE"
    test "$(sha256sum "$ROLLBACK_RESCUE_IMAGE" | cut -d' ' -f1)" = "$ROLLBACK_SHA"
    trex_ssh "test \"\$(stat -Lc %s '$ROLLBACK_RESCUE_IMAGE')\" -eq '$SIZE'; test \"\$(sha256sum '$ROLLBACK_RESCUE_IMAGE' | cut -d' ' -f1)\" = '$ROLLBACK_SHA'"
    cp "$XML" "$XML_RUN_FILE"
    test "$(sha256sum "$XML_RUN_FILE" | cut -d' ' -f1)" = "$XML_SHA"
    trex_ssh "test \"\$(sha256sum '$XML_RUN_FILE' | cut -d' ' -f1)\" = '$XML_SHA'"
    trex_scp "$ROOT/research/p22-proof-supervisor.sh" "trex:$RUN_SHARED/p22-proof-supervisor.sh" >/dev/null
    trex_scp "$ROOT/research/p22-flash-wrapper.sh" "trex:$RUN_SHARED/flash-wrapper.sh" >/dev/null
    trex_scp "$ROOT/research/trex-gadget-net-watcher.sh" "trex:$RUN_SHARED/trex-gadget-net-watcher.sh" >/dev/null
    # This watcher starts before Flash Tool/reboot and repairs only the exact
    # Gemini gadget interface after each USB recreation.
    # shellcheck disable=SC2029
    trex_ssh "nohup setsid sh '$RUN_SHARED/trex-gadget-net-watcher.sh' '$RUN_SHARED/trex-host-net.log' '$RUN_SHARED/trex-host-net.state' </dev/null > '$RUN_SHARED/trex-host-net.log' 2>&1 & echo \$! > '$RUN_SHARED/host-net.pid'"
    HOST_NET_FALLBACK_ARMED=yes
}

cleanup_stage2_store_temp() {
    [ -n "${STAGE2_STORE_TEMP:-}" ] || return 0
    case "$STAGE2_STORE_TEMP" in
        /mnt/gemian/nixos/*.provision.tmp) ;;
        *) return 0 ;;
    esac
    # Only remove the exact Stage1-owned temporary for this manifest. Never
    # remove a final store or anything on a block device.
    device_ssh_gadget "test ! -L '$STAGE2_STORE_TEMP' && test -f '$STAGE2_STORE_TEMP' && rm -f '$STAGE2_STORE_TEMP'" >/dev/null 2>&1 || true
    STAGE2_STORE_TEMP=
}

# shellcheck disable=SC2329 # reached through the EXIT/INT/TERM cleanup trap
stop_capture() {
    [ -n "${RUN_SHARED:-}" ] || return 0
    if [ "$SUPERVISOR_KEEP" = yes ]; then
        supervisor_state=$(trex_ssh "cat '$RUN_SHARED/supervisor.state'" 2>/dev/null || true)
        case "$supervisor_state" in
            supervisor_rollback_succeeded_rescue_verified\ *|supervisor_rollback_failed\ *|supervisor_rollback_unverified\ *|supervisor_rollback_timeout\ *|supervisor_candidate_flash_failed\ *|supervisor_blocked_*) SUPERVISOR_KEEP=no ;;
        esac
    fi
    if [ "$SUPERVISOR_KEEP" = yes ]; then
        # Local EXIT/TERM must not strand recovery: leave the Trex-owned
        # supervisor, transaction lease, watcher, and any rollback child alive.
        return 0
    fi
    cleanup_stage2_store_temp
    if [ -n "${SUPERVISOR_UNIT:-}" ]; then
        # A terminal supervisor has completed or failed its bounded work;
        # stopping the transient unit merely releases its service record.
        trex_ssh "systemctl --user stop '$SUPERVISOR_UNIT'" 2>/dev/null || true
    fi
    if [ -n "${TRANSACTION_UNIT:-}" ]; then
        trex_ssh "systemctl --user stop '$TRANSACTION_UNIT'" 2>/dev/null || true
    fi
    # The three timeout-based diagnostics are intentionally allowed to expire
    # at their bounded 900-second lifetime. Only the exact run-specific
    # watcher is stopped, after validating its argv; never trust *.pid files
    # generically or risk a recycled PID.
    # shellcheck disable=SC2029
    trex_ssh "pid=\$(cat '$RUN_SHARED/host-net.pid' 2>/dev/null || true); case \"\$pid\" in ''|*[!0-9]*) exit 0 ;; esac; ps -o args= -p \"\$pid\" | grep -F -- '$RUN_SHARED/trex-gadget-net-watcher.sh' >/dev/null || exit 0; kill -TERM \"\$pid\" 2>/dev/null || true" 2>/dev/null || true
}

start_probe_capture() {
    proof_log=$RUN_LOCAL/probe-status-proof.log
    (
        while :; do
            if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
                printf 'stage2-evidence %s\n' "$(date -Is)"
                if ! device_ssh 'for f in /run/stage1.log /run/stage1-handoff /run/store-provision.ready; do if test -e "$f"; then printf "--- %s ---\n" "$f"; cat "$f"; fi; done'; then
                    printf 'stage2-disconnected %s\n' "$(date -Is)"
                    break
                fi
            else
                printf 'probe-status %s\n' "$(date -Is)"
                if ! device_ssh 'cat /run/probe-status'; then
                    printf 'probe-status-disconnected %s\n' "$(date -Is)"
                    break
                fi
            fi
            sleep 3
        done
    ) > "$proof_log" 2>&1 &
    PROBE_CAPTURE_PID=$!
}

# shellcheck disable=SC2329 # reached through the EXIT/INT/TERM cleanup trap
stop_probe_capture() {
    [ -n "${PROBE_CAPTURE_PID:-}" ] || return 0
    kill "$PROBE_CAPTURE_PID" 2>/dev/null || true
    wait "$PROBE_CAPTURE_PID" 2>/dev/null || true
    PROBE_CAPTURE_PID=
}

verify_lease_expiry_evidence() {
    if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
        # Full NixOS has no probe-status file. Require the literal lease line
        # captured from /run/stage1.log, followed by the observed disconnect;
        # SSH loss alone is never converted into a synthetic lease claim.
        grep -Fq -- 'unattended_recovery=lease-expired watchdog_userspace=stopped' \
            "$RUN_LOCAL/probe-status-proof.log" || return 1
        grep -Fq -- "$STAGE2_WATCHDOG_EVIDENCE" "$RUN_LOCAL/probe-status-proof.log" || return 1
        grep -Fq -- 'stage2-disconnected ' "$RUN_LOCAL/probe-status-proof.log" || return 1
        [ -n "${SUPERVISOR_STATE:-}" ] || return 1
        trex_ssh "grep -Fq 'supervisor_rollback_succeeded_rescue_verified ' '$SUPERVISOR_STATE'" || return 1
        return 0
    fi
    grep -Fq 'unattended_recovery=lease-expired watchdog_userspace=stopped' \
        "$RUN_LOCAL/probe-status-proof.log"
}

start_supervisor() {
    [ "$TRANSACTION_POLICY" = observe-always-rollback ] || return 0
    SUPERVISOR_STATE=$RUN_SHARED/supervisor.state
    rm -f "$SUPERVISOR_STATE"
    # This service is Trex-owned and independent of the local harness. It
    # starts before candidate reboot, then owns the always-rollback decision
    # if the harness or its SSH session disappears.
    trex_ssh "systemd-run --user --unit='$SUPERVISOR_UNIT' --collect --quiet '$RUN_SHARED/p22-proof-supervisor.sh' '$RUN_SHARED' '$STATE' '$ROLLBACK_RESCUE_IMAGE' '$ROLLBACK_SHA' '$STAGE_IMAGE' '$XML_RUN_FILE' '$FLASH_LOCK_FILE' '$ACCEPTANCE_WINDOW_SECONDS' '$RUN_SHARED/flash-wrapper.sh' '$RUN_SHARED/supervisor-rollback.state' '$RUN_SHARED/supervisor-rollback.log' '$SUPERVISOR_STATE' '$LEASE_SECONDS'"
    supervisor_ready=no
    supervisor_wait=0
    while [ "$supervisor_wait" -lt 15 ]; do
        if trex_ssh "systemctl --user is-active --quiet '$SUPERVISOR_UNIT' && grep -Fq 'supervisor_waiting_candidate ' '$SUPERVISOR_STATE'"; then
            supervisor_ready=yes
            break
        fi
        sleep 1
        supervisor_wait=$((supervisor_wait + 1))
    done
    if [ "$supervisor_ready" != yes ]; then
        printf 'recovery_blocked_supervisor_launch %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    SUPERVISOR_KEEP=yes
}

wait_supervisor_rollback() {
    [ -n "${SUPERVISOR_STATE:-}" ] || return 1
    deadline=$(( $(date +%s) + 360 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        supervisor_state=$(trex_ssh "cat '$SUPERVISOR_STATE'" 2>/dev/null || true)
        case "$supervisor_state" in
            supervisor_rollback_succeeded_rescue_verified\ *) SUPERVISOR_KEEP=no; return 0 ;;
            supervisor_waiting_candidate\ *|supervisor_rollback_armed\ *) ;;
            supervisor_rollback_failed\ *|supervisor_rollback_unverified\ *|supervisor_rollback_timeout\ *|supervisor_blocked_*|supervisor_candidate_flash_failed\ *) SUPERVISOR_KEEP=no; return 1 ;;
        esac
        case "$supervisor_state" in
            supervisor_waiting_candidate\ *|supervisor_rollback_armed\ *)
                unit_state=$(trex_ssh "systemctl --user is-active '$SUPERVISOR_UNIT'" 2>/dev/null || true)
                case "$unit_state" in
                    inactive|failed|deactivating) SUPERVISOR_KEEP=no; return 1 ;;
                esac ;;
        esac
        sleep 2
    done
    return 1
}

verify_recovered_stage_a() {
    CANDIDATE_HOSTKEY_MODE=no
    recovery_deadline=$(( $(date +%s) + RECOVERY_SSH_TIMEOUT_SECONDS ))
    : > "$RUN_LOCAL/recovered-partition-hashes"
    while [ "$(date +%s)" -lt "$recovery_deadline" ]; do
        if device_ssh "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $ROLLBACK_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
sha256sum /dev/mmcblk0p22 /dev/mmcblk0p30 /dev/mmcblk0p31" \
            > "$RUN_LOCAL/recovered-partition-hashes" 2>&1; then
            return 0
        fi
        sleep 3
    done
    return 1
}

# shellcheck disable=SC2329 # reached through the EXIT/INT/TERM cleanup trap
stop_tool() {
    [ -n "${RUN_SHARED:-}" ] || return 0
    # The wrapper runs in a private session. Validate PID/PGID/SID, starttime,
    # and the attempt-unique XML before taking a process snapshot.
    xml_owner=${XML_RUN_FILE:-${XML:-}}
    [ -n "$xml_owner" ] || return 0
    XML=$xml_owner
    # shellcheck disable=SC2029
    trex_ssh "
pid=; pgid=; sid=; launch=; start=
case \"\$(cat '$STATE' 2>/dev/null || true)\" in
  flash_rc=*) exit 0 ;;
esac
test -s '$TOOL_PID_FILE' && pid=\$(cat '$TOOL_PID_FILE') || true
test -s '$TOOL_PGID_FILE' && pgid=\$(cat '$TOOL_PGID_FILE') || true
test -s '$TOOL_SID_FILE' && sid=\$(cat '$TOOL_SID_FILE') || true
test -s '$TOOL_STARTTIME_FILE' && start=\$(cat '$TOOL_STARTTIME_FILE') || true
test -s '$TOOL_LAUNCH_PID_FILE' && launch=\$(cat '$TOOL_LAUNCH_PID_FILE') || true
case \"\$pid\" in ''|*[!0-9]*) exit 0 ;; esac
case \"\$sid\" in ''|*[!0-9]*) exit 0 ;; esac
case \"\$start\" in ''|*[!0-9]*) exit 0 ;; esac
case \"\$launch\" in ''|*[!0-9]*) exit 0 ;; esac
test \"\$launch\" -gt 1 || exit 0
if test \"\$launch\" != \"\$pid\" && ! ps -o args= -p \"\$launch\" | grep -F -- '$STATE' >/dev/null; then exit 0; fi
test \"\$sid\" = \"\$pid\" || exit 0
# Validate the live leader identity before touching the private session.
if test -d /proc/\$pid; then
  test \$(awk '{print \$22}' /proc/\$pid/stat 2>/dev/null) = \$start || exit 0
  test \$(ps -o sid= -p \$pid | tr -d ' ') = \$sid || exit 0
  test \$(ps -o pgid= -p \$pid | tr -d ' ') = \$pgid || exit 0
  ps -o args= -p \$pid | grep -F -- '$STATE' >/dev/null ||
  ps -o args= -p \$pid | grep -F -- '$xml_owner' >/dev/null || exit 0
fi
if test \"\$launch\" != \"\$pid\" && test -d /proc/\$launch; then
  ps -o args= -p \$launch | grep -F -- '$STATE' >/dev/null || exit 0
fi
ps -eo pid=,sid=,args= | awk -v sid=\$sid -v xml='$xml_owner' \
    '\$2 == sid && index(\$0, xml) {found=1} END {exit(found ? 0 : 1)}' || exit 0
# GNU timeout without --foreground historically escaped into a child PGID.
# Enumerate only this private session so cleanup remains safe even when the
# wrapper leader has already exited; never use a process-name kill.
session_owner=no
if ps -o args= -p \"\$pid\" | grep -F -- '$STATE' >/dev/null ||
   ps -eo pid=,sid=,args= | awk -v sid=\"\$sid\" -v state='$STATE' -v xml='$XML' \
       '\$2 == sid && (index(\$0, state) || index(\$0, xml))' | grep -q .; then
  session_owner=yes
fi
test \"\$session_owner\" = yes || exit 0
snapshot='$RUN_SHARED/stop-session.snapshot'
: > \"\$snapshot\"
ps -eo pid=,sid=,pgid= | awk -v sid=\"\$sid\" '\$2 == sid {print \$1, \$2, \$3}' |
while read -r member msid mpgid; do
  case \"\$member\" in ''|*[!0-9]*) exit 1 ;; esac
  test \"\$msid\" = \"\$sid\" || exit 1
  test \"\$mpgid\" = \"\$pgid\" || exit 1
  mstart=\$(awk '{print \$22}' /proc/\$member/stat 2>/dev/null || true)
  case \"\$mstart\" in ''|*[!0-9]*) exit 1 ;; esac
  printf '%s %s %s %s\\n' \"\$member\" \"\$msid\" \"\$mpgid\" \"\$mstart\" >> \"\$snapshot\"
done || exit 0
test -s \"\$snapshot\" || exit 0
validate_snapshot() {
  while read -r member msid mpgid mstart; do
    test -n \"\$member\" || continue
    test -d /proc/\$member || return 1
    test \$(awk '{print \$22}' /proc/\$member/stat 2>/dev/null) = \$mstart || return 1
    test \$(ps -o sid= -p \$member | tr -d ' ') = \$msid || return 1
    test \$(ps -o pgid= -p \$member | tr -d ' ') = \$mpgid || return 1
  done < \"\$snapshot\"
}
validate_snapshot || exit 0
terminate_snapshot() {
  while read -r member msid mpgid mstart; do
    test -n "\$member" || continue
    test -d /proc/\$member || return 1
    test \$(awk '{print \$22}' /proc/\$member/stat 2>/dev/null) = \$mstart || return 1
    test \$(ps -o sid= -p \$member | tr -d ' ') = \$msid || return 1
    test \$(ps -o pgid= -p \$member | tr -d ' ') = \$mpgid || return 1
    kill -TERM \$member 2>/dev/null || true
  done < "\$snapshot"
  sleep 2
  while read -r member msid mpgid mstart; do
    test -n "\$member" || continue
    test -d /proc/\$member || continue
    test \$(awk '{print \$22}' /proc/\$member/stat 2>/dev/null) = \$mstart || continue
    test \$(ps -o sid= -p \$member | tr -d ' ') = \$msid || continue
    test \$(ps -o pgid= -p \$member | tr -d ' ') = \$mpgid || continue
    kill -KILL \$member 2>/dev/null || true
  done < "\$snapshot"
}
terminate_snapshot || exit 0
rm -f "\$snapshot"
exit 0
" 2>/dev/null || true
}

# shellcheck disable=SC2329 # invoked by the EXIT/INT/TERM trap below
cleanup() {
    rc=$?
    trap - EXIT INT TERM
    stop_probe_capture
    if [ "$SUPERVISOR_KEEP" != yes ]; then
        stop_tool
    fi
    stop_capture
    if [ "$rc" -ne 0 ] && [ -n "${RUN_LOCAL:-}" ] && [ -f "$RUN_LOCAL/state" ]; then
        case "$(cat "$RUN_LOCAL/state" 2>/dev/null || true)" in
            accepted_p22*|recovered_known_good_p22*|recovery_failed*|recovery_flash_failed*|recovery_validation_failed*|manual_reset_required_*|recovery_blocked_*|recovered_but_proof_failed_*|lease_proof_passed_recovered_stage_a*) ;;
            *) printf 'harness_failed rc=%s %s\n' "$rc" "$(date -Is)" > "$RUN_LOCAL/state" ;;
        esac
    fi
    exit "$rc"
}

wait_state() {
    state_file=$1
    wanted=$2
    limit=$3
    deadline=$(( $(date +%s) + limit ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        # State is written by Trex processes. Never depend on the shared
        # mount's local attribute cache to observe tool_started/flash_rc.
        state=$(trex_ssh "cat '$state_file'" 2>/dev/null || true)
        case "$state" in
            "$wanted"*) return 0 ;;
            flash_rc=*) return 1 ;;
        esac
        sleep 1
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

validate_candidate_stage2() {
    device_ssh "set -eu
accept_deadline=$ACCEPTANCE_DEADLINE
test \"\$(date +%s)\" -lt \"\$accept_deadline\"
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $CANDIDATE_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
grep -q \"^/dev/mmcblk0p29 /gemian .* ro,\" /proc/mounts
grep -q \"^/dev/loop0 /nix/store squashfs ro,\" /proc/mounts
while ! test -s /run/bq2589x-preflight.pass; do
  test ! -e /run/bq2589x-preflight.fail
  test \"\$(date +%s)\" -lt \"\$accept_deadline\"
  sleep 1
done
grep -Fqx 'result=pass watchdog_lease=unchanged remote_review_required=yes' /run/bq2589x-preflight.pass
grep -Fq 'GEMINI_BQ2589X_PREFLIGHT: result=pass watchdog_lease=unchanged remote_review_required=yes' /run/bq2589x-preflight.status
grep -Fq -- $EXPECTED_MODEL /proc/device-tree/model
grep -Fq -- $EXPECTED_COMPATIBLE /proc/device-tree/compatible
grep -Fq -- $EXPECTED_CMDLINE /proc/cmdline
test \"\$(cat /sys/devices/system/cpu/online)\" = $EXPECTED_CPU_ONLINE
gadget_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_GADGET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
ethernet_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_ETHERNET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
test -n \"\$gadget_if\"
test -n \"\$ethernet_if\"
test \"\$(basename \"\$(readlink -f \"/sys/class/net/\$ethernet_if/device/driver\")\")\" = r8152
usb_node=\$(readlink -f \"/sys/class/net/\$ethernet_if/device\")
usb_ok=no
while [ \"\$usb_node\" != / ]; do
  if test -r \"\$usb_node/idVendor\" && test -r \"\$usb_node/idProduct\" &&
     test \"\$(cat \"\$usb_node/idVendor\")\" = 0bda &&
     test \"\$(cat \"\$usb_node/idProduct\")\" = 8156; then
    usb_ok=yes
    break
  fi
  next_node=\$(dirname \"\$usb_node\")
  test \"\$next_node\" != \"\$usb_node\" || break
  usb_node=\$next_node
done
test \"\$usb_ok\" = yes
stage2_state=\$(systemctl is-active \"$STAGE2_WATCHDOG_OWNER_UNIT\")
test \"\$stage2_state\" = \"$STAGE2_WATCHDOG_STATE\"
stage2_pid=\$(systemctl show -p MainPID --value \"$STAGE2_WATCHDOG_OWNER_UNIT\")
case \"\$stage2_pid\" in ''|*[!0-9]*) exit 1 ;; esac
test \"\$stage2_pid\" -gt 1
test -d \"/proc/\$stage2_pid\"
stage2_device=\$(for fd in /proc/\$stage2_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
test -n \"\$stage2_device\"
success_first=\$(sed -n '1p' \"$STAGE2_SUCCESS_MARKER\")
test \"\$success_first\" = 'mainline NixOS reached multi-user.target'
grep -Fq -- \"watchdog-state=$STAGE2_WATCHDOG_STATE\" \"$STAGE2_SUCCESS_MARKER\"
grep -Fq -- \"watchdog-owner=\$stage2_pid\" \"$STAGE2_SUCCESS_MARKER\"
grep -Eq '^/dev/mmcblk0p29 /gemian .* ro[, ]' \"$STAGE2_SUCCESS_MARKER\"
grep -Eq \"watchdog=petting .*lease=${LEASE_SECONDS}s handoff=stage1\" /run/stage1.log
test -s \"$STAGE1_HANDOFF_PATH\"
grep -Fq -- \"$STAGE1_WATCHDOG_OWNER_MARKER\" /run/stage1.log
grep -Fq -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
stage2_state=\$(systemctl is-active \"$STAGE2_WATCHDOG_OWNER_UNIT\")
test \"\$stage2_state\" = \"$STAGE2_WATCHDOG_STATE\"
stage2_pid=\$(systemctl show -p MainPID --value \"$STAGE2_WATCHDOG_OWNER_UNIT\")
case \"\$stage2_pid\" in ''|*[!0-9]*) exit 1 ;; esac
test \"\$stage2_pid\" -gt 1
test -d \"/proc/\$stage2_pid\"
stage2_device=\$(for fd in /proc/\$stage2_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
test -n \"\$stage2_device\"
grep -Fq -- 'panic=5' /proc/cmdline
grep -Fq -- 'mtk_wdt.start_at_boot=1' /proc/cmdline
test \"\$(cat /sys/class/watchdog/watchdog0/identity)\" = \"$EXPECTED_WATCHDOG_IDENTITY\"
test \"\$(cat /sys/class/watchdog/watchdog0/state)\" = \"$EXPECTED_WATCHDOG_STATE\"
test \"\$(cat /sys/class/watchdog/watchdog0/timeout)\" = \"$EXPECTED_WATCHDOG_TIMEOUT\"
test -r /sys/class/watchdog/watchdog0/bootstatus
printf 'stage1_watchdog_owner_marker=%s\\n' \"$STAGE1_WATCHDOG_OWNER_MARKER\"
printf 'stage1_handoff_path=%s\\n' \"$STAGE1_HANDOFF_PATH\"
printf 'stage2_watchdog_owner_unit=%s state=%s pid=%s device=%s\\n' \"$STAGE2_WATCHDOG_OWNER_UNIT\" \"\$stage2_state\" \"\$stage2_pid\" \"\$stage2_device\"
printf 'stage2_success_marker=%s\\n' \"$STAGE2_SUCCESS_MARKER\"
printf '%s\\n' \"$STAGE2_WATCHDOG_EVIDENCE\"
"
}

validate_candidate() {
    if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
        validate_candidate_stage2
        return $?
    fi
    device_ssh "set -eu
accept_deadline=$ACCEPTANCE_DEADLINE
test \"\$(date +%s)\" -lt \"\$accept_deadline\"
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $CANDIDATE_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
case \"$ROOTFS_POLICY\" in
  nixos-stage2)
    grep -q \"^/dev/mmcblk0p29 /gemian .* ro,\" /proc/mounts
    grep -q \"^/dev/loop0 /nix/store squashfs ro,\" /proc/mounts
    if [ \"$STAGE2_POLICY\" = watchdog-takeover-required ]; then
      test -s \"$STAGE2_SUCCESS_MARKER\"
      grep -Eq \"watchdog=petting .*lease=${LEASE_SECONDS}s handoff=stage1\" /run/stage1.log
      test -s \"$STAGE1_HANDOFF_PATH\"
      grep -Fq -- \"$STAGE1_WATCHDOG_OWNER_MARKER\" /run/stage1.log
      grep -Fq -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
      stage2_state=\$(systemctl is-active \"$STAGE2_WATCHDOG_OWNER_UNIT\")
      test \"\$stage2_state\" = \"$STAGE2_WATCHDOG_STATE\"
      stage2_pid=\$(systemctl show -p MainPID --value \"$STAGE2_WATCHDOG_OWNER_UNIT\")
      case \"\$stage2_pid\" in ''|*[!0-9]*) exit 1 ;; esac
      test \"\$stage2_pid\" -gt 1
      test -d \"/proc/\$stage2_pid\"
      stage2_device=\$(for fd in /proc/\$stage2_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
      test -n \"\$stage2_device\"
      printf 'stage1_watchdog_owner_marker=%s\\n' \"$STAGE1_WATCHDOG_OWNER_MARKER\"
      printf 'stage1_handoff_path=%s\\n' \"$STAGE1_HANDOFF_PATH\"
      grep -E 'watchdog=petting .*lease=[0-9]+s handoff=stage1' /run/stage1.log
      printf 'stage2_watchdog_owner_unit=%s state=%s pid=%s device=%s\\n' \"$STAGE2_WATCHDOG_OWNER_UNIT\" \"\$stage2_state\" \"\$stage2_pid\" \"\$stage2_device\"
      grep -F -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
      printf 'stage2_success_marker=%s\\n' \"$STAGE2_SUCCESS_MARKER\"
    fi ;;
  enumeration-only)
    ! grep -Eq '^/dev/mmcblk[0-9]+p[0-9]+ ' /proc/mounts
    ! grep -Eq '[[:space:]]/(gemian|nix/store)([[:space:]]|/)' /proc/mounts
    while ! grep -Fq 'emmc=present' /run/probe-status 2>/dev/null ||
          ! grep -Fq 'userspace_block_reads=none' /run/probe-status 2>/dev/null ||
          ! grep -Fq 'mounts=none' /run/probe-status 2>/dev/null; do
      test \"\$(date +%s)\" -lt \"\$accept_deadline\" || exit 1
      sleep 1
    done ;;
  *) exit 1 ;;
esac
case \"$POWER_PREFLIGHT_POLICY\" in
  required)
    while ! test -s /run/bq2589x-preflight.pass; do
      test ! -e /run/bq2589x-preflight.fail || exit 1
      test \"\$(date +%s)\" -lt \"\$accept_deadline\" || exit 1
      sleep 1
    done
    grep -Fqx 'result=pass watchdog_lease=unchanged remote_review_required=yes' \
      /run/bq2589x-preflight.pass
    grep -Fq 'GEMINI_BQ2589X_PREFLIGHT: result=pass watchdog_lease=unchanged remote_review_required=yes' \
      /run/bq2589x-preflight.status
    echo '--- bq2589x-preflight.status ---'
    cat /run/bq2589x-preflight.status
    echo '--- bq2589x-preflight.dmesg ---'
    cat /run/bq2589x-preflight.dmesg
    echo '--- bq2589x-preflight.pass ---'
    cat /run/bq2589x-preflight.pass
    ;;
  none) : ;;
  *) exit 1 ;;
esac
grep -Fq -- $EXPECTED_MODEL /proc/device-tree/model
grep -Fq -- $EXPECTED_COMPATIBLE /proc/device-tree/compatible
grep -Fq -- $EXPECTED_CMDLINE /proc/cmdline
test \"\$(cat /sys/devices/system/cpu/online)\" = $EXPECTED_CPU_ONLINE
gadget_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_GADGET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
ethernet_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_ETHERNET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
test -n \"\$gadget_if\"
case \"$HOST_NET_POLICY\" in
  required)
    while :; do
      ethernet_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_ETHERNET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
      if test -n \"\$ethernet_if\"; then
        if [ \"$STAGE2_POLICY\" = watchdog-takeover-required ]; then
          test \"\$(basename \"\$(readlink -f \"/sys/class/net/\$ethernet_if/device/driver\")\")\" = r8152 || continue
          usb_node=\$(readlink -f \"/sys/class/net/\$ethernet_if/device\")
          usb_ok=no
          while [ \"\$usb_node\" != / ]; do
            if test -r \"\$usb_node/idVendor\" && test -r \"\$usb_node/idProduct\" &&
               test \"\$(cat \"\$usb_node/idVendor\")\" = 0bda &&
               test \"\$(cat \"\$usb_node/idProduct\")\" = 8156; then
              usb_ok=yes
              break
            fi
            next_node=\$(dirname \"\$usb_node\")
            test \"\$next_node\" != \"\$usb_node\" || break
            usb_node=\$next_node
          done
          test \"\$usb_ok\" = yes || continue
        elif ! grep -Eq \"usb-host-net=ready iface=\$ethernet_if address=$EXPECTED_ETHERNET_IP/[^ ]+ action=(bound|renew) usb=0bda:8156\" /run/probe-status; then
          continue
        fi
        break
      fi
      test \"\$(date +%s)\" -lt \"\$accept_deadline\" || exit 1
      sleep 1
    done ;;
  none) : ;;
  *) exit 1 ;;
esac
if [ \"$STAGE2_POLICY\" = watchdog-takeover-required ]; then
  success_first=\$(sed -n '1p' \"$STAGE2_SUCCESS_MARKER\")
  test \"\$success_first\" = 'mainline NixOS reached multi-user.target'
  grep -Fq -- \"watchdog-state=$STAGE2_WATCHDOG_STATE\" \"$STAGE2_SUCCESS_MARKER\"
  grep -Fq -- \"watchdog-owner=\$stage2_pid\" \"$STAGE2_SUCCESS_MARKER\"
  grep -Eq '^/dev/mmcblk0p29 /gemian .* ro[, ]' \"$STAGE2_SUCCESS_MARKER\"
  grep -Fq -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
else
  grep -Fq -- \"$EXPECTED_MARKER\" /run/probe-status
  ! grep -Fq -- 'unattended_recovery=failed' /run/probe-status
fi
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
  test \"\$(cat /sys/class/watchdog/watchdog0/identity)\" = \"$EXPECTED_WATCHDOG_IDENTITY\"
  test \"\$(cat /sys/class/watchdog/watchdog0/state)\" = \"$EXPECTED_WATCHDOG_STATE\"
  test \"\$(cat /sys/class/watchdog/watchdog0/timeout)\" = \"$EXPECTED_WATCHDOG_TIMEOUT\"
  test -r /sys/class/watchdog/watchdog0/bootstatus
  if [ \"$STAGE2_POLICY\" = watchdog-takeover-required ]; then
    grep -Eq \"watchdog=petting .*lease=${LEASE_SECONDS}s handoff=stage1\" /run/stage1.log
    test -s \"$STAGE1_HANDOFF_PATH\"
    grep -Fq -- \"$STAGE1_WATCHDOG_OWNER_MARKER\" /run/stage1.log
    grep -Fq -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
  else
    watchdog_pid=\$(sed -n 's/.*watchdog_pid=\([0-9][0-9]*\).*/\1/p' /run/probe-status | tail -n 1)
    test -n \"\$watchdog_pid\"
    test -d \"/proc/\$watchdog_pid\"
    owner_device=\$(for fd in /proc/\$watchdog_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
    test -n \"\$owner_device\"
  fi
fi
# The caller keeps validation marker-free and commits the lease separately
# after every required SSH path succeeds.
" > "$RUN_LOCAL/candidate-validation.log" 2>&1
}

commit_acceptance_marker() {
    device_ssh "set -eu
accept_tmp=/run/unattended-recovery.accepted.tmp.\$\$
printf '%s\\n' \"$LEASE_MARKER\" > \"\$accept_tmp\"
mv -f \"\$accept_tmp\" /run/unattended-recovery.accepted
test \"\$(cat /run/unattended-recovery.accepted)\" = \"$LEASE_MARKER\""
}

validate_candidate_right_path_stage2() {
    [ "$SSH_PATH_POLICY" = both ] || return 0
    device_ssh_right "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $CANDIDATE_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
grep -Fq -- $EXPECTED_MODEL /proc/device-tree/model
grep -Fq -- $EXPECTED_COMPATIBLE /proc/device-tree/compatible
grep -Fq -- $EXPECTED_CMDLINE /proc/cmdline
ethernet_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_ETHERNET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
test -n \"\$ethernet_if\"
test \"\$(basename \"\$(readlink -f \"/sys/class/net/\$ethernet_if/device/driver\")\")\" = r8152
usb_node=\$(readlink -f \"/sys/class/net/\$ethernet_if/device\")
usb_ok=no
while [ \"\$usb_node\" != / ]; do
  if test -r \"\$usb_node/idVendor\" && test -r \"\$usb_node/idProduct\" &&
     test \"\$(cat \"\$usb_node/idVendor\")\" = 0bda &&
     test \"\$(cat \"\$usb_node/idProduct\")\" = 8156; then
    usb_ok=yes
    break
  fi
  next_node=\$(dirname \"\$usb_node\")
  test \"\$next_node\" != \"\$usb_node\" || break
  usb_node=\$next_node
done
test \"\$usb_ok\" = yes
stage2_state=\$(systemctl is-active \"$STAGE2_WATCHDOG_OWNER_UNIT\")
test \"\$stage2_state\" = \"$STAGE2_WATCHDOG_STATE\"
stage2_pid=\$(systemctl show -p MainPID --value \"$STAGE2_WATCHDOG_OWNER_UNIT\")
case \"\$stage2_pid\" in ''|*[!0-9]*) exit 1 ;; esac
test \"\$stage2_pid\" -gt 1
test -d \"/proc/\$stage2_pid\"
stage2_device=\$(for fd in /proc/\$stage2_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
test -n \"\$stage2_device\"
success_first=\$(sed -n '1p' \"$STAGE2_SUCCESS_MARKER\")
test \"\$success_first\" = 'mainline NixOS reached multi-user.target'
grep -Fq -- \"watchdog-state=$STAGE2_WATCHDOG_STATE\" \"$STAGE2_SUCCESS_MARKER\"
grep -Fq -- \"watchdog-owner=\$stage2_pid\" \"$STAGE2_SUCCESS_MARKER\"
grep -Eq '^/dev/mmcblk0p29 /gemian .* ro[, ]' \"$STAGE2_SUCCESS_MARKER\"
grep -Eq \"watchdog=petting .*lease=${LEASE_SECONDS}s handoff=stage1\" /run/stage1.log
test -s \"$STAGE1_HANDOFF_PATH\"
grep -Fq -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
printf 'stage2-watchdog-right-path state=%s pid=%s device=%s\\n' \"\$stage2_state\" \"\$stage2_pid\" \"\$stage2_device\""
}

validate_candidate_right_path() {
    if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
        validate_candidate_right_path_stage2
        return $?
    fi
    [ "$SSH_PATH_POLICY" = both ] || return 0
    # The gadget path performs the full profile validation.  This independent
    # right-NIC session proves the second SSH transport reaches the same exact
    # candidate before the lease marker is committed.
    device_ssh_right "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $CANDIDATE_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
grep -Fq -- $EXPECTED_MODEL /proc/device-tree/model
grep -Fq -- $EXPECTED_COMPATIBLE /proc/device-tree/compatible
grep -Fq -- $EXPECTED_CMDLINE /proc/cmdline
ethernet_if=\$(ip -4 -o addr show | awk -v ip=\"$EXPECTED_ETHERNET_IP\" '\$4 ~ (\"^\" ip \"/\") {print \$2; exit}')
test -n \"\$ethernet_if\"
if [ \"$STAGE2_POLICY\" = watchdog-takeover-required ]; then
  test \"\$(basename \"\$(readlink -f \"/sys/class/net/\$ethernet_if/device/driver\")\")\" = r8152
  usb_node=\$(readlink -f \"/sys/class/net/\$ethernet_if/device\")
  usb_ok=no
  while [ \"\$usb_node\" != / ]; do
    if test -r \"\$usb_node/idVendor\" && test -r \"\$usb_node/idProduct\" &&
       test \"\$(cat \"\$usb_node/idVendor\")\" = 0bda &&
       test \"\$(cat \"\$usb_node/idProduct\")\" = 8156; then
      usb_ok=yes
      break
    fi
    next_node=\$(dirname \"\$usb_node\")
    test \"\$next_node\" != \"\$usb_node\" || break
    usb_node=\$next_node
  done
  test \"\$usb_ok\" = yes
  test -s \"$STAGE2_SUCCESS_MARKER\"
  grep -Eq \"watchdog=petting .*lease=${LEASE_SECONDS}s handoff=stage1\" /run/stage1.log
  test -s \"$STAGE1_HANDOFF_PATH\"
  grep -Fq -- \"$STAGE2_WATCHDOG_EVIDENCE\" /run/stage1.log
  stage2_state=\$(systemctl is-active \"$STAGE2_WATCHDOG_OWNER_UNIT\")
  test \"\$stage2_state\" = \"$STAGE2_WATCHDOG_STATE\"
  stage2_pid=\$(systemctl show -p MainPID --value \"$STAGE2_WATCHDOG_OWNER_UNIT\")
  case \"\$stage2_pid\" in ''|*[!0-9]*) exit 1 ;; esac
  test \"\$stage2_pid\" -gt 1
  test -d \"/proc/\$stage2_pid\"
  stage2_device=\$(for fd in /proc/\$stage2_pid/fd/*; do readlink \"\$fd\"; done | grep -E '/dev/watchdog(0)?$' | head -n 1)
  test -n \"\$stage2_device\"
else
  test -s /run/probe-status
fi"
}

accept_candidate_until_deadline() {
    marker_requested=$P22_WRITE_MARKER
    # Candidate validation is always marker-free.  Marker creation is a
    # separate commit after every required SSH path has passed.
    P22_WRITE_MARKER=no
    ACCEPTANCE_DEADLINE=$(( $(date +%s) + ACCEPTANCE_WINDOW_SECONDS ))
    while [ "$(date +%s)" -lt "$ACCEPTANCE_DEADLINE" ]; do
        if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
            device_ssh_gadget_fast 'test -s /proc/cmdline' >/dev/null 2>&1 || {
                sleep 1
                continue
            }
        elif ! device_ssh 'test -s /proc/cmdline' >/dev/null 2>&1; then
            sleep 1
            continue
        fi
        if [ "$PROOF_LEASE" = yes ] && [ -z "${PROBE_CAPTURE_PID:-}" ]; then
            # Capture probe status before validation can fail or recovery
            # arms rollback, preserving the lease-expiry evidence window.
            start_probe_capture
        fi
        if [ "$STAGE2_POLICY" = watchdog-takeover-required ] &&
            [ "$STAGE2_STORE_PROVISIONED" != yes ]; then
            if ! provision_stage2_store; then
                sleep 1
                continue
            fi
        fi
        old_validation_gadget_only=$VALIDATION_GADGET_ONLY
        if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
            # Full-NixOS acceptance must prove the gadget path itself;
            # right-NIC success alone is not a substitute.
            VALIDATION_GADGET_ONLY=yes
        fi
        validation_rc=0
        validate_candidate || validation_rc=1
        if [ "$validation_rc" -eq 0 ]; then
            validate_candidate_right_path || validation_rc=1
        fi
        VALIDATION_GADGET_ONLY=$old_validation_gadget_only
        if [ "$validation_rc" -eq 0 ]; then
            if [ "$marker_requested" = yes ] && commit_acceptance_marker; then
                ACCEPTANCE_COMMITTED=yes
            elif [ "$marker_requested" = yes ]; then
                continue
            fi
            return 0
        fi
        sleep 2
    done
    return 1
}

start_tool() {
    log=$1
    ATTEMPT_COUNTER=$((ATTEMPT_COUNTER + 1))
    attempt_tag=$(date +%s)-$$-$ATTEMPT_COUNTER
    attempt_state=$RUN_SHARED/flash-attempt-$attempt_tag.state
    TOOL_PID_FILE=$RUN_SHARED/flash-attempt-$attempt_tag.pid
    TOOL_PGID_FILE=$RUN_SHARED/flash-attempt-$attempt_tag.pgid
    TOOL_SID_FILE=$RUN_SHARED/flash-attempt-$attempt_tag.sid
    TOOL_STARTTIME_FILE=$RUN_SHARED/flash-attempt-$attempt_tag.starttime
    TOOL_LAUNCH_PID_FILE=$RUN_SHARED/flash-attempt-$attempt_tag.launch.pid
    # This pathname is intentionally outside RUN_SHARED. Every run and every
    # candidate/rollback attempt therefore contends for the same Trex-global
    # writer lock; state/PID/PGID files remain per-attempt.
    TOOL_LOCK_FILE=$FLASH_LOCK_FILE
    STATE=$attempt_state
    # A private session lets cleanup terminate timeout, sudo, and flash_tool
    # together.  The wrapper publishes its actual PID/PGID after launch.
    # shellcheck disable=SC2029
    launch_rc=0
    trex_ssh "nohup setsid sh '$RUN_SHARED/flash-wrapper.sh' '$STATE' '$log' '$XML_RUN_FILE' '$TOOL_PID_FILE' '$TOOL_PGID_FILE' '$TOOL_LOCK_FILE' '$RUN_SHARED/transaction-owner' '$TOOL_SID_FILE' '$TOOL_STARTTIME_FILE' </dev/null >/dev/null 2>&1 & echo \$! > '$TOOL_LAUNCH_PID_FILE'" || launch_rc=$?
    if wait_state "$STATE" tool_started 20; then
        if ! trex_ssh "pid=\$(cat '$TOOL_PID_FILE' 2>/dev/null || true); pgid=\$(cat '$TOOL_PGID_FILE' 2>/dev/null || true); sid=\$(cat '$TOOL_SID_FILE' 2>/dev/null || true); launch=\$(cat '$TOOL_LAUNCH_PID_FILE' 2>/dev/null || true); test \"\$pid\" = \"\$pgid\"; test \"\$pid\" = \"\$sid\"; test \"\$pid\" -gt 1; case \"\$launch\" in ''|*[!0-9]*) exit 1 ;; esac; test \"\$launch\" -gt 1; ps -o args= -p \"\$pid\" | grep -F -- '$STATE' >/dev/null; if test \"\$launch\" != \"\$pid\"; then ps -o args= -p \"\$launch\" | grep -F -- '$STATE' >/dev/null; fi"; then
            printf 'recovery_blocked_tool_identity %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            return 1
        fi
        return 0
    fi
    # A fast tool failure is still a valid transaction state: let the caller
    # enter the rollback path instead of aborting before it can recover.
    case "$(trex_ssh "cat '$STATE'" 2>/dev/null || true)" in
        flash_rc=75*|flash_rc=76*)
            printf 'recovery_blocked_tool_lock_or_owner %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            return 1 ;;
        flash_rc=*) return 0 ;;
        *)
            if [ "$launch_rc" -ne 0 ] && trex_ssh "ps -eo args= | grep -F -- '$STATE' | grep -v grep >/dev/null"; then
                printf 'recovery_blocked_tool_launch_uncertain rc=%s %s\n' "$launch_rc" "$(date -Is)" > "$RUN_LOCAL/state"
            else
                printf 'recovery_blocked_tool_launch rc=%s %s\n' "$launch_rc" "$(date -Is)" > "$RUN_LOCAL/state"
            fi
            return 1 ;;
    esac
}

wait_ssh_down() {
    limit=$1
    deadline=$(( $(date +%s) + limit ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if ! device_ssh 'true' >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    return 1
}

request_reboot() {
    printf 'reboot-dispatch begin=%s\n' "$(date -Is)" >> "$RUN_LOCAL/reboot.log"
    set +e
    device_ssh_gadget 'if command -v systemctl >/dev/null 2>&1; then echo reboot-path=systemd; systemctl reboot --no-wall; elif [ -x /bin/reboot ]; then echo reboot-path=busybox; /bin/reboot -f; else echo reboot-path=missing; exit 127; fi' >> "$RUN_LOCAL/reboot.log" 2>&1
    dispatch_rc=$?
    set -e
    printf 'reboot-dispatch rc=%s\n' "$dispatch_rc" >> "$RUN_LOCAL/reboot.log"
    if wait_ssh_down 20; then
        printf 'reboot-dispatch disconnected=%s\n' "$(date -Is)" >> "$RUN_LOCAL/reboot.log"
        return 0
    fi
    printf 'reboot-dispatch ssh-still-up=%s\n' "$(date -Is)" >> "$RUN_LOCAL/reboot.log"
    return 1
}

recover() {
    CANDIDATE_HOSTKEY_MODE=no
    # A normal initramfs-petter failure is still pre-commit here.  Because the
    # candidate host key is intentionally not trusted for rollback dispatch,
    # the bounded initramfs lease expires and exposes the next WDT/preloader
    # window; this is explicit, finite, and never a post-marker recovery path.
    printf 'candidate_acceptance_failed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    # Never launch a second Flash Tool while the candidate wrapper might still
    # own the USB port. The extra ten seconds avoids an exact timeout race;
    # failure here is a manual boundary, not an unsafe concurrent retry.
    if ! wait_state "$STATE" flash_rc 250; then
        printf 'recovery_blocked_candidate_tool_timeout %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    stage_image "$ROLLBACK" "$ROLLBACK_SHA"
    rollback_log=$RUN_SHARED/rollback-flash.log
    if ! start_tool "$rollback_log"; then
        case "$(cat "$RUN_LOCAL/state" 2>/dev/null || true)" in
            recovery_blocked_*) ;;
            *) printf 'recovery_blocked_rollback_tool_launch %s\n' "$(date -Is)" > "$RUN_LOCAL/state" ;;
        esac
        return 1
    fi
    if [ "$PROOF_LEASE" = yes ]; then
        printf 'lease_proof_rollback_armed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    fi
    # If candidate userspace is still reachable, request a clean restart only
    # after rollback is waiting. If it is hung before init, wait for a natural
    # watchdog/preloader transition; no unsafe force-reset is attempted.
    if [ "$PROOF_LEASE" != yes ] && wait_ssh 1; then
        if ! request_reboot; then
            printf 'manual_reset_required_reboot_dispatch_failed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            return 1
        fi
    fi
    if ! wait_state "$STATE" flash_rc 250; then
        printf 'manual_reset_required_no_preloader %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    state=$(trex_ssh "cat '$STATE'")
    case "$state" in flash_rc=0*) ;; *) printf 'recovery_flash_failed %s\n' "$state" > "$RUN_LOCAL/state"; return 1;; esac
    if ! wait_ssh "$RECOVERY_SSH_TIMEOUT_SECONDS"; then printf 'manual_reset_required_no_ssh %s\n' "$(date -Is)" > "$RUN_LOCAL/state"; return 1; fi
    if ! device_ssh "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $ROLLBACK_SHA
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
$(if [ "$STAGE2_POLICY" = watchdog-takeover-required ]; then
    printf '%s\n' "test \"\$(stat -Lc %s '$STAGE1_STORE_TARGET')\" -eq '$STAGE1_STORE_SIZE'" \
        "test \"\$(sha256sum '$STAGE1_STORE_TARGET' | cut -d' ' -f1)\" = '$STAGE1_STORE_SHA'"
fi)"; then
        printf 'recovery_validation_failed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        return 1
    fi
    printf 'recovered_known_good_p22 %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
}

finalize_accepted_candidate() {
    final_record_rc=0
    # Marker creation is the irreversible commit point.  This readback is
    # evidence only; a transient host-plane failure must not enter recover and
    # cannot revoke a candidate whose remote p22/p30/p31 validation committed.
    device_ssh "set -eu
sha256sum /dev/mmcblk0p22 /dev/mmcblk0p30 /dev/mmcblk0p31" \
        > "$RUN_LOCAL/final-partition-hashes" 2>&1 || final_record_rc=$?
    printf 'post-marker-final-record rc=%s\n' "$final_record_rc" \
        > "$RUN_LOCAL/final-record-status"
    [ "$ACCEPTANCE_COMMITTED" = yes ] || return 1
    printf 'accepted_p22 %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    return 0
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
if ! start_tool "$candidate_log"; then
    # A launch/owner failure is terminal: the wrapper may be alive despite a
    # lost Trex SSH ACK, so never guess and start a second writer or reboot.
    case "$(cat "$RUN_LOCAL/state" 2>/dev/null || true)" in
        recovery_blocked_*) ;;
        *) printf 'recovery_blocked_candidate_tool_launch %s\n' "$(date -Is)" > "$RUN_LOCAL/state" ;;
    esac
    exit 1
fi
if ! start_supervisor; then
    # Do not reboot into a candidate without the durable rollback owner.
    printf 'recovery_blocked_supervisor_not_armed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    exit 1
fi
if ! request_reboot; then
    if [ "$TRANSACTION_POLICY" = observe-always-rollback ]; then
        if ! wait_supervisor_rollback || ! verify_recovered_stage_a; then
            printf 'manual_reset_required_supervisor_or_readback %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            exit 1
        fi
        exit 1
    elif recover; then
        exit 1
    else
        exit $?
    fi
fi
CANDIDATE_HOSTKEY_MODE=yes
if [ "$PROOF_LEASE" = yes ]; then
    # Deliberately do not write the acceptance marker. recover() starts the
    # rollback tool first, then waits for the candidate lease to kill its
    # petter and expose the next watchdog/preloader window.
    if accept_candidate_until_deadline; then
        PROOF_VALIDATED=yes
    else
        printf 'proof_candidate_validation_failed %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    fi
    if [ "$TRANSACTION_POLICY" = observe-always-rollback ]; then
        if ! wait_supervisor_rollback || ! verify_recovered_stage_a; then
            printf 'manual_reset_required_supervisor_or_readback %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            exit 1
        fi
        recovery_rc=1
    elif recover; then
        if [ "$PROOF_VALIDATED" != yes ]; then
            printf 'recovered_but_proof_failed_candidate_validation %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            exit 1
        fi
        if ! verify_lease_expiry_evidence; then
            printf 'recovered_but_proof_failed_no_lease_expiry %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            exit 1
        fi
        printf 'lease_proof_passed_recovered_stage_a %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
    else
        recovery_rc=$?
        exit "$recovery_rc"
    fi
    if [ "$TRANSACTION_POLICY" = observe-always-rollback ]; then
        if [ "$PROOF_VALIDATED" != yes ]; then
            printf 'recovered_but_proof_failed_candidate_validation %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            exit 1
        fi
        if ! verify_lease_expiry_evidence; then
            printf 'recovered_but_proof_failed_no_lease_expiry %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
            exit 1
        fi
        printf 'lease_proof_passed_recovered_stage_a %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        exit 0
    fi
elif P22_WRITE_MARKER=yes accept_candidate_until_deadline; then
    if finalize_accepted_candidate; then
        exit 0
    fi
fi
if [ "$ACCEPTANCE_COMMITTED" = yes ]; then
    # Defensive guard: a committed marker always terminates successfully and
    # can never fall through to automatic recovery.
    exit 0
fi
if [ "$TRANSACTION_POLICY" = observe-always-rollback ]; then
    if ! wait_supervisor_rollback || ! verify_recovered_stage_a; then
        printf 'manual_reset_required_supervisor_or_readback %s\n' "$(date -Is)" > "$RUN_LOCAL/state"
        exit 1
    fi
    exit 1
elif recover; then
    exit 1
else
    exit $?
fi
