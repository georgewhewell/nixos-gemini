#!/bin/sh
# Focused host-only tests for the Stage-1 -> Stage-2 watchdog lease protocol.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d /mnt/Home/src/nixos-gemini-lease-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

fail() {
  echo "test-unattended-recovery-lease: $*" >&2
  exit 1
}

wait_for_log() {
  file=$1
  pattern=$2
  attempt=0
  while ! grep -Fq "$pattern" "$file" 2>/dev/null; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 50 ] || fail "timed out waiting for $pattern"
    sleep 0.1
  done
}

stop_enforcer() {
  pid=$1
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

write_record() {
  run_root=$1
  started=$2
  deadline=$3
  lease_seconds=$4
  printf '%s\n' \
    'format=gemini-unattended-recovery-lease-v1' \
    'clock=monotonic-uptime-seconds' \
    "started=$started" \
    "deadline=$deadline" \
    "lease_seconds=$lease_seconds" > "$run_root/unattended-recovery.lease-deadline"
}

make_busybox() {
  fixture=$1
  printf '%s\n' \
    '#!/bin/sh' \
    'set -eu' \
    'command=$1' \
    'shift' \
    'case "$command" in' \
    '  sleep)' \
    '    if [ "${1:-}" = 3600 ]; then exec sleep 1; fi' \
    '    count_file=$GEMINI_LEASE_RUN_ROOT/sleep-count' \
    '    count=$(cat "$count_file" 2>/dev/null || echo 0)' \
    '    count=$((count + 1))' \
    '    printf "%s\\n" "$count" > "$count_file"' \
    '    if [ "${GEMINI_LEASE_TEST_ACCEPT_ON_SLEEP:-0}" = "$count" ]; then' \
    '      printf "%s\\n" unattended_recovery=healthy > "$GEMINI_LEASE_RUN_ROOT/unattended-recovery.accepted"' \
    '    fi' \
    '    exit 0' \
    '    ;;' \
    '  kill)' \
    '    test -e "$GEMINI_LEASE_RUN_ROOT/unattended-recovery.lease-expired"' \
    '    printf "%s\\n" "$*" >> "$GEMINI_LEASE_RUN_ROOT/kill.log"' \
    '    exit 0' \
    '    ;;' \
    '  *) exec "$command" "$@" ;;' \
    'esac' > "$fixture/fake-busybox"
  chmod 0755 "$fixture/fake-busybox"
}

# Stage 1 records an integer, monotonic deadline atomically under the run
# mount that will move into Stage 2.  No wall clock is consulted.
record_root=$WORK/record-run
mkdir -p "$record_root"
printf '%s\n' '100.42 0.00' > "$WORK/uptime"
GEMINI_LEASE_RUN_ROOT=$record_root \
GEMINI_LEASE_UPTIME_FILE=$WORK/uptime \
  sh "$ROOT/nix/unattended-recovery-lease-record.sh" 720
printf '%s\n' \
  'format=gemini-unattended-recovery-lease-v1' \
  'clock=monotonic-uptime-seconds' \
  'started=100' \
  'deadline=820' \
  'lease_seconds=720' > "$WORK/expected-record"
cmp "$WORK/expected-record" "$record_root/unattended-recovery.lease-deadline"

# Stage 1 must retain its own bounded timer while provisioning.  Stage 2 is a
# continuation of the same deadline, not a replacement for pre-handoff
# enforcement.  Record failure must also stop the petter instead of entering
# fail() with a userspace process keeping the nowayout watchdog alive.
grep -Fq 'sleep @WATCHDOG_LEASE_SECONDS@' "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'reason=stage1-deadline-reached' "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'reason=watchdog-lease-deadline-record-failed watchdog_userspace=stopped' \
  "$ROOT/nix/mainline-nixos.nix"
record_line=$(grep -n -F 'if ! /bin/unattended-recovery-lease-record @WATCHDOG_LEASE_SECONDS@; then' \
  "$ROOT/nix/mainline-nixos.nix" | cut -d: -f1)
timer_line=$(grep -n -F 'sleep @WATCHDOG_LEASE_SECONDS@' \
  "$ROOT/nix/mainline-nixos.nix" | cut -d: -f1)
[ "$record_line" -lt "$timer_line" ]

# A transferred record remains live in Stage 2.  The fake clock does not
# advance, but the enforcer must stay up until the later exact acceptance.
continuation=$WORK/continuation
mkdir -p "$continuation/run" "$continuation/proc"
write_record "$continuation/run" 100 102 2
printf '%s\n' '100.00 0.00' > "$continuation/proc/uptime"
make_busybox "$continuation"
GEMINI_LEASE_BUSYBOX=$continuation/fake-busybox \
GEMINI_LEASE_RUN_ROOT=$continuation/run \
GEMINI_LEASE_PROC_ROOT=$continuation/proc \
GEMINI_LEASE_LOG_FILE=$continuation/run/stage1.log \
GEMINI_LEASE_KMSG_FILE=$continuation/run/kmsg \
GEMINI_LEASE_TEST_ACCEPT_ON_SLEEP=2 \
  sh "$ROOT/nix/unattended-recovery-lease-enforcer.sh" &
continuation_pid=$!
wait_for_log "$continuation/run/stage1.log" \
  'unattended_recovery=lease-accepted lease_enforcer=holding'
test ! -e "$continuation/run/unattended-recovery.lease-expired"
test ! -e "$continuation/run/kill.log"
kill -0 "$continuation_pid"
stop_enforcer "$continuation_pid"

# Exact external acceptance is the only bypass, including when the record is
# unavailable after handoff.  A near-match is deliberately not accepted below.
accepted=$WORK/accepted
mkdir -p "$accepted/run" "$accepted/proc"
printf '%s\n' unattended_recovery=healthy > "$accepted/run/unattended-recovery.accepted"
make_busybox "$accepted"
GEMINI_LEASE_BUSYBOX=$accepted/fake-busybox \
GEMINI_LEASE_RUN_ROOT=$accepted/run \
GEMINI_LEASE_PROC_ROOT=$accepted/proc \
GEMINI_LEASE_LOG_FILE=$accepted/run/stage1.log \
GEMINI_LEASE_KMSG_FILE=$accepted/run/kmsg \
  sh "$ROOT/nix/unattended-recovery-lease-enforcer.sh" &
accepted_pid=$!
wait_for_log "$accepted/run/stage1.log" \
  'unattended_recovery=lease-accepted lease_enforcer=holding'
test ! -e "$accepted/run/unattended-recovery.lease-expired"
test ! -e "$accepted/run/kill.log"
kill -0 "$accepted_pid"
stop_enforcer "$accepted_pid"

# Deadline expiry writes the marker before it signals a verified watchdog
# owner.  The fake kill rejects any reverse ordering.
expired=$WORK/expired
mkdir -p "$expired/run" "$expired/proc/440/fd"
write_record "$expired/run" 99 100 1
printf '%s\n' '100.00 0.00' > "$expired/proc/uptime"
printf '%s\n' 440 > "$expired/run/unattended-recovery.watchdog-owner"
# A trailing byte makes this a non-acceptance; expiry must remain fail-closed.
printf '%s\n' 'unattended_recovery=healthy ' > "$expired/run/unattended-recovery.accepted"
ln -s /dev/watchdog "$expired/proc/440/fd/3"
make_busybox "$expired"
GEMINI_LEASE_BUSYBOX=$expired/fake-busybox \
GEMINI_LEASE_RUN_ROOT=$expired/run \
GEMINI_LEASE_PROC_ROOT=$expired/proc \
GEMINI_LEASE_LOG_FILE=$expired/run/stage1.log \
GEMINI_LEASE_KMSG_FILE=$expired/run/kmsg \
  sh "$ROOT/nix/unattended-recovery-lease-enforcer.sh"
test -e "$expired/run/unattended-recovery.lease-expired"
grep -Fqx -- '-KILL 440' "$expired/run/kill.log"
grep -Fq 'unattended_recovery=lease-expired watchdog_userspace=stopped watchdog_reset_expected=31s reason=deadline-reached' \
  "$expired/run/stage1.log"

# The generated services establish the required Stage-2 ordering without
# making their watchdog PID ownership depend on one another.
grep -Fqx '  systemd.services.gemini-unattended-recovery-lease-enforcer = {' \
  "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '    before = ["gemini-watchdog-takeover.service" "sshd.service" "gemini-mainline-success.service"];' \
  "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '    after = ["gemini-unattended-recovery-lease-enforcer.service"];' \
  "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '    requires = ["gemini-unattended-recovery-lease-enforcer.service"];' \
  "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '      KillMode = "process";' "$ROOT/nixos/mainline-configuration.nix"

echo 'test-unattended-recovery-lease: PASS'
