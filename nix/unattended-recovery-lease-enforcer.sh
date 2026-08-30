#!/bin/sh
# Enforce the Stage-1 watchdog deadline after switch_root.  It owns no
# watchdog file descriptor: the owner file is atomically replaced by the
# Stage-2 takeover service, and expiry first publishes a stop marker so that
# a concurrent takeover cannot reopen the nowayout watchdog.
set -eu

busybox=${GEMINI_LEASE_BUSYBOX:-/bin/busybox}
run_root=${GEMINI_LEASE_RUN_ROOT:-/run}
proc_root=${GEMINI_LEASE_PROC_ROOT:-/proc}
uptime_file=${GEMINI_LEASE_UPTIME_FILE:-$proc_root/uptime}
log_file=${GEMINI_LEASE_LOG_FILE:-$run_root/stage1.log}
kmsg_file=${GEMINI_LEASE_KMSG_FILE:-/dev/kmsg}

accepted_file=$run_root/unattended-recovery.accepted
deadline_file=$run_root/unattended-recovery.lease-deadline
expired_file=$run_root/unattended-recovery.lease-expired
owner_file=$run_root/unattended-recovery.watchdog-owner

log() {
  line="GEMINI_MAINLINE_NIXOS: $*"
  printf '%s\n' "$line" >> "$log_file" 2>/dev/null || true
  printf '<6>%s\n' "$line" > "$kmsg_file" 2>/dev/null || true
}

accepted() {
  [ "$("$busybox" cat "$accepted_file" 2>/dev/null || true)" = \
    'unattended_recovery=healthy' ]
}

hold_after_acceptance() {
  log 'unattended_recovery=lease-accepted lease_enforcer=holding'
  # Keep this unit active after acceptance.  The takeover unit Requires it,
  # and a successful acceptance must not deactivate (and therefore stop) the
  # replacement watchdog petter merely because the deadline is no longer
  # relevant.
  while :; do
    "$busybox" sleep 3600
  done
}

uptime_seconds() {
  "$busybox" awk '{ sub(/\..*/, "", $1); print $1; exit }' "$uptime_file" 2>/dev/null
}

expire() {
  reason=$1
  # This marker is intentionally before any PID lookup or signal.  The
  # watchdog takeover tests it both before opening the device and before
  # publishing its replacement owner PID.
  : > "$expired_file"
  log "unattended_recovery=lease-expired watchdog_userspace=stopped watchdog_reset_expected=31s reason=$reason"

  pass=0
  while [ "$pass" -lt 5 ]; do
    owner_pid=$("$busybox" cat "$owner_file" 2>/dev/null || true)
    case "$owner_pid" in
      ''|*[!0-9]*) ;;
      *)
        owns_watchdog=
        for fd in "$proc_root/$owner_pid"/fd/*; do
          [ -e "$fd" ] || [ -L "$fd" ] || continue
          target=$("$busybox" readlink "$fd" 2>/dev/null || true)
          case "$target" in
            /dev/watchdog|/dev/watchdog0) owns_watchdog=yes ;;
          esac
        done
        if [ "$owns_watchdog" = yes ]; then
          "$busybox" kill -KILL "$owner_pid" 2>/dev/null || true
        fi
        ;;
    esac
    pass=$((pass + 1))
    "$busybox" sleep 1
  done
}

# An acceptance action is external to both stages.  Once it has atomically
# recorded the exact marker, do not turn a missing/corrupt handoff record into
# a surprise rollback.
if accepted; then
  hold_after_acceptance
fi

format=
clock=
started=
deadline=
lease_seconds=
record_valid=yes
if [ -r "$deadline_file" ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      format) format=$value ;;
      clock) clock=$value ;;
      started) started=$value ;;
      deadline) deadline=$value ;;
      lease_seconds) lease_seconds=$value ;;
      *) record_valid= ;;
    esac
  done < "$deadline_file"
fi

case "$record_valid:$format:$clock:$started:$deadline:$lease_seconds" in
  yes:gemini-unattended-recovery-lease-v1:monotonic-uptime-seconds:[0-9]*:[0-9]*:[1-9]*) ;;
  *) expire lease-record-invalid; exit 0 ;;
esac

# Shell patterns do not guarantee that an apparently numeric field contains
# only digits when it begins with one.  Keep parsing fail-closed.
case "$started$deadline$lease_seconds" in
  *[!0-9]*) expire lease-record-invalid; exit 0 ;;
esac
[ "$deadline" -ge "$started" ] || { expire lease-record-invalid; exit 0; }
[ "$deadline" -eq $((started + lease_seconds)) ] || {
  expire lease-record-invalid
  exit 0
}

while :; do
  if accepted; then
    hold_after_acceptance
  fi
  now=$(uptime_seconds || true)
  case "$now" in
    ''|*[!0-9]*) expire monotonic-clock-invalid; exit 0 ;;
  esac
  if [ "$now" -ge "$deadline" ]; then
    expire deadline-reached
    exit 0
  fi
  "$busybox" sleep 1
done
