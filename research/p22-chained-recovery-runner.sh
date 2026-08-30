#!/bin/sh
set -eu

# Deliberate three-phase p22 transaction:
#   1. normal candidate acceptance;
#   2. candidate lease-expiry proof with Stage-A rollback;
#   3. final normal candidate acceptance.
# Each phase is a separate harness invocation. The runner never selects a
# different partition and never permits two Flash Tool owners concurrently.
# shellcheck disable=SC1007 # zsh/NixOS-compatible scoped CDPATH assignment

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HARNESS=$ROOT/research/p22-recovery-harness.sh
MANIFEST=$ROOT/research/p22-unattended-recovery-watchdog-hostnet-v2.manifest
MODE=
SSH_DEADLINE_SECONDS=15

die() {
    echo "p22-chained-recovery-runner: $*" >&2
    exit 2
}

usage() {
    echo "usage: $0 [--manifest PATH] [--dry-run|--execute]" >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --manifest) [ "$#" -ge 2 ] || usage; MANIFEST=$2; shift 2 ;;
        --dry-run|--execute) [ -z "$MODE" ] || usage; MODE=$1; shift ;;
        *) usage ;;
    esac
done
[ -n "$MODE" ] || usage
[ -x "$HARNESS" ] || die "harness is not executable: $HARNESS"
[ -f "$MANIFEST" ] || die "manifest not found: $MANIFEST"

manifest_value() {
    key=$1
    value=$(awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2); found++} END {if (found != 1) exit 1}' "$MANIFEST") ||
        die "manifest key missing or duplicated: $key"
    printf '%s\n' "$value"
}

CANDIDATE_SHA=$(manifest_value candidate_sha256)
ROLLBACK_SHA=$(manifest_value rollback_sha256)
[ "$CANDIDATE_SHA" = 567ac4302dda7c12f734306af56ad8fba04986fadcd6f70d53ad3b89df747638 ] ||
    die "manifest is not the reviewed hostnet candidate"
[ "$ROLLBACK_SHA" = 1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc ] ||
    die "manifest rollback is not accepted Stage A"

device_ssh() {
    timeout "$SSH_DEADLINE_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
        -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
        -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
        -o ServerAliveCountMax=2 root@10.15.19.82 "$@"
}

trex_ssh() {
    timeout "$SSH_DEADLINE_SECONDS" ssh -o BatchMode=yes -o ConnectTimeout=8 \
        -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
        -o ServerAliveCountMax=2 trex "$@"
}

check_tool_idle() {
    # shellcheck disable=SC2016
    trex_ssh 'ps -eo comm=,args= | awk '\''$1 != "awk" && ($1 == "flash_tool" || $0 ~ /\/flash-wrapper.sh( |$)/) {found=1} END {exit found}'\'''
}

check_partitions() {
    expected=$1
    label=$2
    device_ssh "set -eu
test \"\$(sha256sum /dev/mmcblk0p22 | cut -d' ' -f1)\" = $expected
test \"\$(sha256sum /dev/mmcblk0p30 | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum /dev/mmcblk0p31 | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
echo \"$label p22=$expected p30=122c0f461e... p31=1fa78de9...\""
}

check_allowed_partitions() {
    # shellcheck disable=SC2016
    device_ssh 'set -eu
p22=$(sha256sum /dev/mmcblk0p22 | cut -d" " -f1)
test "$p22" = a0bc87d21227158e2e925a6f05affdfdec773a5e44e248d41f8b6684e2bd37eb || test "$p22" = 1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc
test "$(sha256sum /dev/mmcblk0p30 | cut -d" " -f1)" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test "$(sha256sum /dev/mmcblk0p31 | cut -d" " -f1)" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513'
}

run_phase() {
    name=$1
    proof=$2
    expected=$3
    echo "phase=$name begin mode=$MODE"
    check_tool_idle
    if [ "$MODE" = --dry-run ]; then
        "$HARNESS" --manifest "$MANIFEST" --dry-run
        check_allowed_partitions
    elif [ "$proof" = yes ]; then
        "$HARNESS" --manifest "$MANIFEST" --execute --proof-lease
        check_partitions "$expected" "$name"
    else
        "$HARNESS" --manifest "$MANIFEST" --execute
        check_partitions "$expected" "$name"
    fi
    check_tool_idle
    echo "phase=$name complete"
}

run_phase normal-before-proof no "$CANDIDATE_SHA"
run_phase lease-proof yes "$ROLLBACK_SHA"
run_phase normal-final no "$CANDIDATE_SHA"
echo "chain=passed mode=$MODE"
