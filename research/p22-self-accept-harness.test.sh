#!/bin/sh
# shellcheck disable=SC1007,SC2034
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HARNESS=$ROOT/research/p22-recovery-harness.sh
WORK=$(mktemp -d /mnt/Home/src/p22-self-accept-harness-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT INT TERM

# The Trex transaction owner must outlive the complete supervisor envelope,
# including the interval beyond the old fixed 900-second holder lifetime.
sed -n '/^derive_transaction_lease_seconds() {/,/^}/p' "$HARNESS" > "$WORK/lease.sh"
# shellcheck disable=SC1091
. "$WORK/lease.sh"
candidate_wait=300
acceptance_window=690
rollback_wait=300
margin=120
transaction_lease=$(derive_transaction_lease_seconds \
    "$candidate_wait" "$acceptance_window" "$rollback_wait" "$margin")
supervisor_envelope=$((candidate_wait + acceptance_window + rollback_wait))
test "$transaction_lease" -eq 1410
test "$transaction_lease" -gt 900
test "$transaction_lease" -gt "$supervisor_envelope"
# Model writer attempts on both sides of the former fixed expiry without
# sleeping: recovery ownership remains valid at t=901 and through t=1290.
old_expiry_crossing=901
last_supervisor_writer=$supervisor_envelope
test "$old_expiry_crossing" -gt 900
test "$old_expiry_crossing" -lt "$transaction_lease"
test "$last_supervisor_writer" -lt "$transaction_lease"
grep -Fq "'\$TRANSACTION_LEASE_SECONDS'" "$HARNESS"
grep -Fq "'\$SUPERVISOR_ROLLBACK_WAIT_SECONDS' '\$SUPERVISOR_CANDIDATE_WAIT_SECONDS'" "$HARNESS"

# The publication helper owns one exact per-run path and publishes one exact
# candidate-bound record atomically.
sed -n '/^publish_self_acceptance() {/,/^}/p' "$HARNESS" > "$WORK/publish.sh"
# shellcheck disable=SC1091
. "$WORK/publish.sh"
trex_ssh() { sh -c "$1"; }
SELF_ACCEPT=yes
CANDIDATE_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
RUN_SHARED=$WORK/run
mkdir "$RUN_SHARED"
SELF_ACCEPT_STATE=$RUN_SHARED/candidate-self-accepted
publish_self_acceptance
grep -Fqx "candidate_self_accepted sha256=$CANDIDATE_SHA" "$SELF_ACCEPT_STATE"
SELF_ACCEPT_STATE=$WORK/outside
if publish_self_acceptance; then
    exit 1
fi
test ! -e "$WORK/outside"

# Terminal-state decoding never confuses exact rollback with acceptance.
sed -n '/^wait_supervisor_self_accept() {/,/^}/p' "$HARNESS" > "$WORK/wait.sh"
# shellcheck disable=SC1091
. "$WORK/wait.sh"
SUPERVISOR_STATE=$RUN_SHARED/supervisor.state
SUPERVISOR_KEEP=yes
printf 'supervisor_candidate_self_accepted now\n' > "$SUPERVISOR_STATE"
wait_supervisor_self_accept
test "$SUPERVISOR_KEEP" = no
SUPERVISOR_KEEP=yes
printf 'supervisor_rollback_succeeded_rescue_verified now\n' > "$SUPERVISOR_STATE"
set +e
wait_supervisor_self_accept
rc=$?
set -e
test "$rc" -eq 2
test "$SUPERVISOR_KEEP" = no
printf 'supervisor_rollback_failed now\n' > "$SUPERVISOR_STATE"
if wait_supervisor_self_accept; then
    exit 1
fi

# The final device readback command is valid shell and remains candidate/hash
# bound.  This stub parses it but opens no hardware path.
sed -n '/^verify_self_accepted_candidate() {/,/^}/p' "$HARNESS" > "$WORK/verify.sh"
# shellcheck disable=SC1091
. "$WORK/verify.sh"
device_ssh() { sh -n -c "$1"; }
EMMC_RESOLVER='resolve_emmc_partition() { echo /dev/mmcblk0p22; }; resolve_emmc_device() { echo /dev/mmcblk0; }'
STAGE2_STORE_TARGET_LIVE=/gemian/nixos/candidate.squashfs
STAGE2_STORE_SIZE=123
STAGE2_STORE_SHA=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
STAGE2_WATCHDOG_OWNER_UNIT=gemini-watchdog-takeover.service
EXPECTED_GADGET_IP=10.15.19.82
EXPECTED_ETHERNET_IP=192.168.23.70
RUN_LOCAL=$WORK/final
mkdir "$RUN_LOCAL"
verify_self_accepted_candidate

# Static ordering checks guard the commit boundary: full validation precedes
# publication; the supervisor's quiescent terminal precedes final readback.
accept_line=$(grep -n -F 'if accept_candidate_until_deadline; then' "$HARNESS" | head -n 1 | cut -d: -f1)
publish_line=$(grep -n -F 'publish_self_acceptance; then' "$HARNESS" | cut -d: -f1)
wait_line=$(grep -n -F 'wait_supervisor_self_accept' "$HARNESS" | tail -n 2 | head -n 1 | cut -d: -f1)
readback_line=$(grep -n -F 'verify_self_accepted_candidate; then' "$HARNESS" | cut -d: -f1)
test "$accept_line" -lt "$publish_line"
test "$publish_line" -lt "$wait_line"
test "$wait_line" -lt "$readback_line"

grep -Fq 'baseline_self_accept=accepted capability=' "$HARNESS"
grep -Fq 'card0-DSI-1/status' "$HARNESS"
grep -Fq -- '--autologin root' "$HARNESS"
! grep -Fq '/run/current-system/sw/bin/btop' "$HARNESS"
grep -Fq 'keyboard-matrix' "$HARNESS"
grep -Fq 'physical_event=unproven' "$HARNESS"
grep -Fq "ln '\$provision_tmp' '\$init_target'" "$HARNESS"
if grep -Fq "mv '\$provision_tmp' '\$init_target'" "$HARNESS"; then
    exit 1
fi
# The p29 publication primitive is additive: link(2) cannot replace a final
# path that appears after the explicit collision check.
mkdir "$WORK/no-clobber"
printf 'candidate\n' > "$WORK/no-clobber/payload.provision.tmp"
printf 'existing\n' > "$WORK/no-clobber/payload.squashfs"
if ln "$WORK/no-clobber/payload.provision.tmp" "$WORK/no-clobber/payload.squashfs" 2>/dev/null; then
    exit 1
fi
grep -Fqx existing "$WORK/no-clobber/payload.squashfs"
grep -Fqx candidate "$WORK/no-clobber/payload.provision.tmp"

echo 'p22 self-accept harness tests: passed'
