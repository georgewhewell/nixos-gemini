#!/bin/sh
# Record the watchdog lease in the monotonic clock domain that survives the
# Stage-1 switch_root handoff.  The caller deliberately supplies the lease:
# there is no default which could silently alter a profile's deadline.
set -eu

lease_seconds=${1:?lease seconds required}
run_root=${GEMINI_LEASE_RUN_ROOT:-/run}
uptime_file=${GEMINI_LEASE_UPTIME_FILE:-/proc/uptime}

case "$lease_seconds" in
  ''|*[!0-9]*) exit 1 ;;
esac
[ "$lease_seconds" -gt 0 ] || exit 1

started=$(awk '{ sub(/\..*/, "", $1); print $1; exit }' "$uptime_file")
case "$started" in
  ''|*[!0-9]*) exit 1 ;;
esac

deadline=$((started + lease_seconds))
lease_file=$run_root/unattended-recovery.lease-deadline
lease_tmp=$lease_file.tmp.$$

umask 077
printf '%s\n' \
  'format=gemini-unattended-recovery-lease-v1' \
  'clock=monotonic-uptime-seconds' \
  "started=$started" \
  "deadline=$deadline" \
  "lease_seconds=$lease_seconds" > "$lease_tmp"
mv -f "$lease_tmp" "$lease_file"
