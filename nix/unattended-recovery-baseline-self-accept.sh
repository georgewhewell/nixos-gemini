#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Self-accept only the explicitly capability-bearing, full-NixOS baseline.
# The capability is an image-selection guard, not a secret: its value is
# carried in the Android boot cmdline and in the immutable NixOS closure.  A
# candidate image receives neither value and therefore continues to expire
# unless a reviewer writes the existing external acceptance marker.
set -eu

busybox=${GEMINI_BASELINE_ACCEPT_BUSYBOX:-/bin/busybox}
run_root=${GEMINI_BASELINE_ACCEPT_RUN_ROOT:-/run}
proc_root=${GEMINI_BASELINE_ACCEPT_PROC_ROOT:-/proc}
sys_root=${GEMINI_BASELINE_ACCEPT_SYS_ROOT:-/sys}
cmdline_file=${GEMINI_BASELINE_ACCEPT_CMDLINE_FILE:-$proc_root/cmdline}
mounts_file=${GEMINI_BASELINE_ACCEPT_MOUNTS_FILE:-$proc_root/mounts}
system_link=${GEMINI_BASELINE_ACCEPT_SYSTEM_LINK:-$run_root/current-system}
systemctl=${GEMINI_BASELINE_ACCEPT_SYSTEMCTL:-$system_link/sw/bin/systemctl}
ip_fixture=${GEMINI_BASELINE_ACCEPT_IP_FILE:-}
kmsg_file=${GEMINI_BASELINE_ACCEPT_KMSG_FILE:-/dev/kmsg}
# ramoops' pmsg zone survives the lease reset independently of the console
# zone, which a noisy driver can overwrite.  Only a character device (or an
# explicit test file) is written.
pmsg_file=${GEMINI_BASELINE_ACCEPT_PMSG_FILE:-/dev/pmsg0}
token=${GEMINI_BASELINE_ACCEPT_TOKEN:-}

accepted_file=$run_root/unattended-recovery.accepted
deadline_file=$run_root/unattended-recovery.lease-deadline
expired_file=$run_root/unattended-recovery.lease-expired
baseline_accept_lock=$run_root/unattended-recovery.baseline-self-accept.lock
expected_system_file=$run_root/gemini-lease-expected-system
handoff_file=$run_root/stage1-handoff
success_file=$run_root/gemini-mainline-success
stage1_log=$run_root/stage1.log
display_activation_file=$run_root/gemini-display-activation
# The latest outcome, rewritten on every attempt, for the host to read.
status_file=$run_root/gemini-baseline-self-accept.status
detail=

uptime_now() {
  # shellcheck disable=SC2016 # $1 belongs to awk, not this shell.
  "$busybox" awk '{ print $1; exit }' "$proc_root/uptime" 2>/dev/null || true
}

log() {
  line="GEMINI_MAINLINE_NIXOS: $*"
  printf '%s\n' "$line" >> "$stage1_log" 2>/dev/null || true
  printf '<6>%s\n' "$line" > "$kmsg_file" 2>/dev/null || true
  if [ -c "$pmsg_file" ] || [ -n "${GEMINI_BASELINE_ACCEPT_PMSG_FILE:-}" ]; then
    printf '%s uptime=%s\n' "$line" "$(uptime_now)" >> "$pmsg_file" 2>/dev/null || true
  fi
}

record() {
  {
    printf 'uptime=%s\n' "$(uptime_now)"
    printf 'result=%s\n' "$1"
    printf 'reason=%s\n' "$2"
    [ -z "$detail" ] || printf 'detail=%s\n' "$detail"
  } > "$status_file.tmp.$$" 2>/dev/null &&
    "$busybox" mv -f "$status_file.tmp.$$" "$status_file" 2>/dev/null || true
}

# Unit names only, comma-joined and bounded; diagnostics, never a gate.
unit_list() {
  # shellcheck disable=SC2016 # $1 belongs to awk, not this shell.
  "$busybox" awk 'NF { if (n++ < 12) out = out (out == "" ? "" : ",") $1 }
    END { print (out == "" ? "none" : out) }' 2>/dev/null || echo unknown
}

fail() {
  record withheld "$1"
  log "baseline_self_accept=withheld reason=$1${detail:+ $detail}"
  exit 1
}

valid_token() {
  prefix=gemini-baseline-lease-v1-
  case "$token" in
    "$prefix"*) ;;
    *) return 1 ;;
  esac
  suffix=${token#"$prefix"}
  [ "${#token}" -eq 89 ] && [ "${#suffix}" -eq 64 ] || return 1
  case "$suffix" in *[!0-9a-f]*) return 1 ;; esac
}

valid_system_path() {
  path=$1
  case "$path" in
    /nix/store/*-nixos-system-gemini-mainline-nixos-?*) ;;
    *) return 1 ;;
  esac
  store_name=${path#/nix/store/}
  case "$store_name" in */*) return 1 ;; esac
  store_hash=${store_name%%-*}
  [ "${#store_hash}" -eq 32 ] || return 1
  # Nix's base32 alphabet deliberately omits e, o, t and u.
  case "$store_hash" in
    *[!0123456789abcdfghijklmnpqrsvwxyz]*) return 1 ;;
  esac
  case "$store_name" in
    "$store_hash"-nixos-system-gemini-mainline-nixos-?*) ;;
    *) return 1 ;;
  esac
  system_suffix=${store_name#"$store_hash"-nixos-system-gemini-mainline-nixos-}
  case "$system_suffix" in
    ''|*[!A-Za-z0-9+._?=-]*) return 1 ;;
  esac
}

unit_active() {
  "$systemctl" is-active --quiet "$1"
}

has_address() {
  address=$1
  if [ -n "$ip_fixture" ]; then
    "$busybox" grep -Fq -- "$address" "$ip_fixture"
  else
    "$busybox" ip -4 -o addr show | "$busybox" grep -Fq -- "$address"
  fi
}

watchdog_owned() {
  owner=$1
  case "$owner" in ''|*[!0-9]*) return 1 ;; esac
  [ -d "$proc_root/$owner" ] || return 1
  for fd in "$proc_root/$owner"/fd/*; do
    [ -e "$fd" ] || [ -L "$fd" ] || continue
    target=$("$busybox" readlink "$fd" 2>/dev/null || true)
    case "$target" in
      /dev/watchdog|/dev/watchdog0) return 0 ;;
    esac
  done
  return 1
}

before_deadline() {
  format=
  clock=
  started=
  deadline=
  lease_seconds=
  record_valid=yes
  [ -r "$deadline_file" ] || return 1
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
  case "$record_valid:$format:$clock:$started:$deadline:$lease_seconds" in
    yes:gemini-unattended-recovery-lease-v1:monotonic-uptime-seconds:[0-9]*:[0-9]*:[1-9]*) ;;
    *) return 1 ;;
  esac
  case "$started$deadline$lease_seconds" in *[!0-9]*) return 1 ;; esac
  [ "$deadline" -ge "$started" ] || return 1
  [ "$deadline" -eq $((started + lease_seconds)) ] || return 1
  # shellcheck disable=SC2016 # $1 belongs to awk, not this shell.
  now=$("$busybox" awk '{ sub(/\..*/, "", $1); print $1; exit }' \
    "$proc_root/uptime" 2>/dev/null || true)
  case "$now" in ''|*[!0-9]*) return 1 ;; esac
  # The enforcer samples once per second.  Leave a conservative handoff
  # window; the lock below then makes it reject any delayed publication.
  [ "$now" -lt $((deadline - 5)) ]
}

valid_token || fail invalid-capability
[ -x "$systemctl" ] || fail systemctl-unavailable
[ ! -e "$expired_file" ] || fail lease-already-expired

"$busybox" tr ' ' '\n' < "$cmdline_file" | \
  "$busybox" grep -Fqx -- "gemini.baseline_lease_capability=$token" || \
  fail cmdline-capability-mismatch

expected_system=$("$busybox" cat "$expected_system_file" 2>/dev/null || true)
current_system=$("$busybox" readlink -f "$system_link" 2>/dev/null || true)
valid_system_path "$expected_system" || fail expected-system-invalid
[ "$current_system" = "$expected_system" ] || fail system-identity-mismatch
"$busybox" grep -Fqx -- "GEMINI_MAINLINE_NIXOS: stage1=switch-root system=$expected_system" \
  "$handoff_file" || fail handoff-identity-mismatch

system_state=$("$systemctl" is-system-running 2>/dev/null || true)
if [ "$system_state" != running ]; then
  detail="state=${system_state:-unknown} failed=$("$systemctl" --failed --no-legend --plain 2>/dev/null | unit_list)"
  # shellcheck disable=SC2016 # $2 belongs to awk, not this shell.
  detail="$detail jobs=$("$systemctl" list-jobs --no-legend --plain 2>/dev/null | "$busybox" awk '{ print $2 }' 2>/dev/null | unit_list)"
  fail system-not-running
fi
unit_active gemini-watchdog-takeover.service || fail watchdog-takeover-inactive
unit_active gemini-mainline-usb.service || fail gadget-service-inactive
unit_active gemini-input-observe.service || fail input-observe-inactive
unit_active sshd.service || fail sshd-inactive
failed_units=$("$systemctl" --failed --no-legend --plain 2>/dev/null || true)
if [ -n "$failed_units" ]; then
  detail="failed=$(printf '%s\n' "$failed_units" | unit_list)"
  fail failed-units-present
fi

"$busybox" grep -Eq '^/dev/mmcblk[0-9]+p29 /gemian ext4 ro,' "$mounts_file" || \
  fail p29-not-readonly
# Normal generations use a registered ext4 store protected by NixOS's
# read-only bind mount. Recovery retains its image/overlay layout.
if [ "${GEMINI_BASELINE_ACCEPT_STORE:-image}" = persistent ]; then
  "$busybox" awk '
    $4 == "/" && $5 == "/persist" { data=$3 }
    $4 == "/nixos/nix/store" && $5 == "/nix/store" && $6 ~ /(^|,)ro(,|$)/ {
      for (i=7; i<=NF; i++) if ($i == "-" && $(i+1) == "ext4") store=$3
    }
    $4 == "/nixos/nix/var" && $5 == "/nix/var" { state=$3 }
    END { exit !(data != "" && store == data && state == data) }
  ' "$proc_root/self/mountinfo" || fail persistent-store-mounts
else
# The image squashfs is /nix/store itself, or, with persistent storage
# (nixos/storage.nix), the read-only lower layer of the /nix/store overlay.
if ! "$busybox" grep -Eq '^/dev/loop[0-9]+ /nix/store squashfs ro,' "$mounts_file"; then
  "$busybox" grep -Eq '^/dev/loop[0-9]+ /nix/\.ro-store squashfs ro,' "$mounts_file" || \
    fail store-not-readonly
  "$busybox" grep -Eq '^overlay /nix/store overlay [^ ]*lowerdir=[^ ,]*/nix/\.ro-store[, ]' "$mounts_file" || \
    fail store-not-readonly
fi
fi
has_address '10.15.19.82/24' || fail gadget-address-missing
has_address '192.168.23.70/' || fail right-nic-address-missing
[ -r "$display_activation_file" ] || fail display-activation-missing
"$busybox" grep -Fqx \
  'display=activated gate=14000000.syscon/activate_drm dsi_irq=pre-host-registration' \
  "$display_activation_file" || fail display-activation-missing
# An activation request can succeed while DRM still waits for components.
# Match the host acceptance contract before releasing the recovery lease.
[ "$("$busybox" cat "$sys_root/class/drm/card0-DSI-1/status" 2>/dev/null || true)" = connected ] || \
  fail display-connector-not-connected
[ "$("$busybox" cat "$sys_root/class/drm/card0-DSI-1/enabled" 2>/dev/null || true)" = enabled ] || \
  fail display-connector-not-enabled

owner=$("$busybox" cat "$run_root/unattended-recovery.watchdog-owner" 2>/dev/null || true)
watchdog_owned "$owner" || fail watchdog-owner-invalid
[ "$("$busybox" cat "$sys_root/class/watchdog/watchdog0/identity" 2>/dev/null || true)" = mtk-wdt ] || \
  fail watchdog-identity-mismatch
[ "$("$busybox" cat "$sys_root/class/watchdog/watchdog0/state" 2>/dev/null || true)" = active ] || \
  fail watchdog-state-inactive
[ "$("$busybox" cat "$sys_root/class/watchdog/watchdog0/timeout" 2>/dev/null || true)" = 31 ] || \
  fail watchdog-timeout-mismatch
"$busybox" grep -Fqx 'mainline NixOS reached multi-user.target' "$success_file" || \
  fail success-marker-missing
"$busybox" grep -Fqx "watchdog-owner=$owner" "$success_file" || fail success-owner-mismatch
"$busybox" grep -Fqx 'watchdog-state=active' "$success_file" || fail success-watchdog-mismatch
"$busybox" grep -Fqx 'result=pass watchdog_lease=unchanged remote_review_required=yes' \
  "$run_root/bq2589x-preflight.pass" || fail power-preflight-missing
before_deadline || fail deadline-invalid-or-expired

tmp=$accepted_file.baseline-self-accept.$$
umask 077
"$busybox" mkdir "$baseline_accept_lock" 2>/dev/null || \
  [ -d "$baseline_accept_lock" ] || fail acceptance-lock-unavailable
printf '%s\n' unattended_recovery=healthy > "$tmp"
[ ! -e "$expired_file" ] || { "$busybox" rm -f "$tmp"; fail lease-expired-during-gate; }
"$busybox" mv -f "$tmp" "$accepted_file"
[ "$("$busybox" cat "$accepted_file" 2>/dev/null || true)" = unattended_recovery=healthy ] || \
  fail acceptance-marker-verify-failed
record accepted health-exact
log "baseline_self_accept=accepted capability=$token system=$expected_system health=exact"
