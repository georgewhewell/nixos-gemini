#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Diagnostics for the baseline self-accept gate.  It never gates, never
# writes the acceptance marker and always exits 0.  The gate itself logs only
# when it runs; if a Requires= dependency fails, or the boot transaction never
# settles, it never runs and nothing explains the lease expiry.  This records
# what the gate is waiting on:
#   - the full snapshot in $run_root/gemini-baseline-self-accept.watch;
#   - one kmsg and pmsg line whenever the one-line summary changes, so the
#     reason survives the lease reset in ramoops (pmsg zone) as well.
set -u

busybox=${GEMINI_SELF_ACCEPT_WATCH_BUSYBOX:-/bin/busybox}
systemctl=${GEMINI_SELF_ACCEPT_WATCH_SYSTEMCTL:-/run/current-system/sw/bin/systemctl}
journalctl=${GEMINI_SELF_ACCEPT_WATCH_JOURNALCTL:-/run/current-system/sw/bin/journalctl}
run_root=${GEMINI_SELF_ACCEPT_WATCH_RUN_ROOT:-/run}
proc_root=${GEMINI_SELF_ACCEPT_WATCH_PROC_ROOT:-/proc}
kmsg_file=${GEMINI_SELF_ACCEPT_WATCH_KMSG_FILE:-/dev/kmsg}
pmsg_file=${GEMINI_SELF_ACCEPT_WATCH_PMSG_FILE:-/dev/pmsg0}
interval=${GEMINI_SELF_ACCEPT_WATCH_INTERVAL:-15}
max_rounds=${GEMINI_SELF_ACCEPT_WATCH_MAX_ROUNDS:-0}

unit=gemini-baseline-self-accept.service
accepted_file=$run_root/unattended-recovery.accepted
expired_file=$run_root/unattended-recovery.lease-expired
status_file=$run_root/gemini-baseline-self-accept.status
out=$run_root/gemini-baseline-self-accept.watch
# The gate's Requires= chain, in boot order.
chain="gemini-cellular.service gemini-gpu.service gemini-audio.service gemini-connectivity.service display-manager.service gemini-gnome-qualify.service gemini-manager-bus-check.service"

emit() {
  line="GEMINI_MAINLINE_NIXOS: self_accept_watch $*"
  printf '<6>%s\n' "$line" > "$kmsg_file" 2>/dev/null || true
  if [ -c "$pmsg_file" ] || [ -n "${GEMINI_SELF_ACCEPT_WATCH_PMSG_FILE:-}" ]; then
    printf '%s\n' "$line" >> "$pmsg_file" 2>/dev/null || true
  fi
}

units() {
  # shellcheck disable=SC2016 # $1 belongs to awk, not this shell.
  "$busybox" awk 'NF { if (n++ < 12) out = out (out == "" ? "" : ",") $1 }
    END { print (out == "" ? "none" : out) }' 2>/dev/null || echo unknown
}

show() {
  "$systemctl" show -p "$2" --value "$1" 2>/dev/null || echo unknown
}

last=
round=0
while :; do
  round=$((round + 1))
  # shellcheck disable=SC2016 # $1 belongs to awk, not this shell.
  now=$("$busybox" awk '{ print $1; exit }' "$proc_root/uptime" 2>/dev/null || echo unknown)
  system=$("$systemctl" is-system-running 2>/dev/null || true)
  gate="$(show "$unit" ActiveState)/$(show "$unit" SubState)/$(show "$unit" Result)/restarts=$(show "$unit" NRestarts)"
  failed=$("$systemctl" --failed --no-legend --plain 2>/dev/null | units)
  # shellcheck disable=SC2016 # $2 belongs to awk, not this shell.
  jobs=$("$systemctl" list-jobs --no-legend --plain 2>/dev/null | "$busybox" awk '{ print $2 }' 2>/dev/null | units)
  # shellcheck disable=SC2016 # $1/$2 belong to awk, not this shell.
  withheld=$("$busybox" awk -F= '$1 == "reason" { print $2 }' "$status_file" 2>/dev/null || true)
  summary="system=${system:-unknown} gate=$gate last_reason=${withheld:-none} failed=$failed jobs=$jobs"

  {
    printf 'uptime=%s round=%s\n%s\n' "$now" "$round" "$summary"
    echo '--- gate status file'
    "$busybox" cat "$status_file" 2>/dev/null || echo absent
    echo '--- systemctl --failed'
    "$systemctl" --failed --no-legend --plain 2>&1 || true
    echo '--- systemctl list-jobs'
    "$systemctl" list-jobs --no-legend --plain 2>&1 || true
    for u in $chain $unit; do
      echo "--- $u $(show "$u" ActiveState)/$(show "$u" SubState)/$(show "$u" Result)"
    done
    # shellcheck disable=SC2016 # $1 belongs to awk, not this shell.
    for u in $("$systemctl" --failed --no-legend --plain 2>/dev/null |
               "$busybox" awk 'NF { print $1 }' 2>/dev/null); do
      echo "--- journal $u"
      "$journalctl" -b -u "$u" -n 40 --no-pager 2>&1 || true
    done
  } > "$out.tmp.$$" 2>/dev/null && "$busybox" mv -f "$out.tmp.$$" "$out" 2>/dev/null

  if [ -e "$accepted_file" ]; then
    emit "accepted uptime=$now $summary"
    exit 0
  fi
  if [ -e "$expired_file" ]; then
    emit "lease-expired uptime=$now $summary"
    exit 0
  fi
  if [ "$summary" != "$last" ]; then
    emit "waiting uptime=$now $summary"
    last=$summary
  fi
  if [ "$max_rounds" -gt 0 ] && [ "$round" -ge "$max_rounds" ]; then
    exit 0
  fi
  "$busybox" sleep "$interval" 2>/dev/null || sleep "$interval" || exit 0
done
