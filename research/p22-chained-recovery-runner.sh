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
EMMC_RESOLVER=$(cat "$ROOT/research/p22-emmc-lineage.sh")
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

candidate_hostkey_allowed() {
    # The runner has no per-harness marker path, so prove the physical identity
    # directly before allowing the candidate's per-boot host key.  This check
    # is read-only and is never used for preflight or Stage-A rollback.
    trex_ssh 'lsusb -d 0525:a4a2 >/dev/null 2>&1 && ip -o link show | grep -Eq "link/ether 42:00:15:19:82:00 "'
}

candidate_device_ssh() {
    candidate_hostkey_allowed || return 1
    timeout "$SSH_DEADLINE_SECONDS" ssh -J trex -i /home/grw/.ssh/id_ed25519 \
        -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
        -o ConnectionAttempts=1 -o ServerAliveInterval=3 \
        -o ServerAliveCountMax=2 -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null root@10.15.19.82 "$@"
}

check_tool_idle() {
    # shellcheck disable=SC2016
    trex_ssh 'ps -eo comm=,args= | awk '\''$1 != "awk" && ($1 == "flash_tool" || $0 ~ /\/flash-wrapper.sh( |$)/) {found=1} END {exit found}'\'''
}

check_partitions() {
    expected=$1
    label=$2
    if [ "$expected" = "$CANDIDATE_SHA" ]; then
        check_ssh=candidate_device_ssh
    else
        check_ssh=device_ssh
    fi
    "$check_ssh" "$EMMC_RESOLVER
set -eu
p22=\$(resolve_emmc_partition boot)
p30=\$(resolve_emmc_partition boot2)
p31=\$(resolve_emmc_partition boot3)
test \"\$(sha256sum \"\$p22\" | cut -d' ' -f1)\" = $expected
test \"\$(sha256sum \"\$p30\" | cut -d' ' -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum \"\$p31\" | cut -d' ' -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513
echo \"$label p22=$expected p30=122c0f461e... p31=1fa78de9...\""
}

check_allowed_partitions() {
    # shellcheck disable=SC2016
    device_ssh "$EMMC_RESOLVER
set -eu
p22=\$(resolve_emmc_partition boot)
p30=\$(resolve_emmc_partition boot2)
p31=\$(resolve_emmc_partition boot3)
p22_hash=\$(sha256sum \"\$p22\" | cut -d\" \" -f1)
test \"\$p22_hash\" = a0bc87d21227158e2e925a6f05affdfdec773a5e44e248d41f8b6684e2bd37eb || test \"\$p22_hash\" = 1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc
test \"\$(sha256sum \"\$p30\" | cut -d\" \" -f1)\" = 122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
test \"\$(sha256sum \"\$p31\" | cut -d\" \" -f1)\" = 1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513"
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
