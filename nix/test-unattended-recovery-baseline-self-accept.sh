#!/bin/sh
# SPDX-License-Identifier: MIT
# Host-only acceptance-contract tests. No hardware paths are opened.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d /mnt/Home/src/nixos-gemini-baseline-accept-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
TOKEN=gemini-baseline-lease-v1-4e8e71c5b0c2aa1543c6fb079cc22964d0a7e25b942cb350f7a1e3d69b8c4052

fail() { echo "test-unattended-recovery-baseline-self-accept: $*" >&2; exit 1; }

make_fixture() {
  d=$1
  system=$d/nix/store/nixos-system-gemini-mainline-nixos-test-baseline
  mkdir -p "$d/run" "$d/proc/440/fd" "$d/sys/class/watchdog/watchdog0" \
    "$d/nix/store" "$d/bin"
  cat > "$d/bin/fake-busybox" <<'BUSYBOX'
#!/bin/sh
exec "$@"
BUSYBOX
  chmod 0755 "$d/bin/fake-busybox"
  ln -s "$system" "$d/run/current-system"
  mkdir -p "$system/sw/bin"
  printf '%s\n' "$system" > "$d/run/gemini-lease-expected-system"
  printf '%s\n' "GEMINI_MAINLINE_NIXOS: stage1=switch-root system=$system" > "$d/run/stage1-handoff"
  printf '%s\n' \
    'mainline NixOS reached multi-user.target' \
    'watchdog-owner=440' \
    'watchdog-state=active' > "$d/run/gemini-mainline-success"
  printf '%s\n' 'result=pass watchdog_lease=unchanged remote_review_required=yes' > "$d/run/bq2589x-preflight.pass"
  printf '%s\n' \
    'format=gemini-unattended-recovery-lease-v1' \
    'clock=monotonic-uptime-seconds' \
    'started=100' 'deadline=820' 'lease_seconds=720' > "$d/run/unattended-recovery.lease-deadline"
  printf '%s\n' 440 > "$d/run/unattended-recovery.watchdog-owner"
  printf '%s\n' '101.00 0.00' > "$d/proc/uptime"
  printf '%s\n' "bootopt=64S3,32N2,64N2 gemini.baseline_lease_capability=$TOKEN" > "$d/proc/cmdline"
  printf '%s\n' \
    '/dev/mmcblk0p29 /gemian ext4 ro,nosuid,nodev,noexec 0 0' \
    '/dev/loop0 /nix/store squashfs ro,nodev 0 0' > "$d/proc/mounts"
  printf '%s\n' mtk-wdt > "$d/sys/class/watchdog/watchdog0/identity"
  printf '%s\n' active > "$d/sys/class/watchdog/watchdog0/state"
  printf '%s\n' 31 > "$d/sys/class/watchdog/watchdog0/timeout"
  ln -s /dev/watchdog "$d/proc/440/fd/3"
  printf '%s\n' 'usb0 10.15.19.82/24' 'enu1 192.168.23.70/24' > "$d/ip"
  cat > "$d/bin/systemctl" <<'SYSTEMCTL'
#!/bin/sh
case "$1${2:-}" in
  is-system-running) echo running ;;
  is-active--quiet) exit 0 ;;
  --failed--no-legend) exit 0 ;;
  *) exit 2 ;;
esac
SYSTEMCTL
  chmod 0755 "$d/bin/systemctl"
}

run_fixture() {
  d=$1
  GEMINI_BASELINE_ACCEPT_BUSYBOX="$d/bin/fake-busybox" \
  GEMINI_BASELINE_ACCEPT_RUN_ROOT="$d/run" \
  GEMINI_BASELINE_ACCEPT_PROC_ROOT="$d/proc" \
  GEMINI_BASELINE_ACCEPT_SYS_ROOT="$d/sys" \
  GEMINI_BASELINE_ACCEPT_SYSTEMCTL="$d/bin/systemctl" \
  GEMINI_BASELINE_ACCEPT_SYSTEM_PREFIX="$d/nix/store/nixos-system-gemini-mainline-nixos-" \
  GEMINI_BASELINE_ACCEPT_IP_FILE="$d/ip" \
  GEMINI_BASELINE_ACCEPT_KMSG_FILE="$d/kmsg" \
  GEMINI_BASELINE_ACCEPT_TOKEN="$TOKEN" \
    sh "$ROOT/nix/unattended-recovery-baseline-self-accept.sh"
}

ok=$WORK/ok
make_fixture "$ok"
run_fixture "$ok"
grep -Fqx unattended_recovery=healthy "$ok/run/unattended-recovery.accepted"
test -d "$ok/run/unattended-recovery.baseline-self-accept.lock"
grep -Fq 'baseline_self_accept=accepted' "$ok/run/stage1.log"

bad_token=$WORK/bad-token
make_fixture "$bad_token"
printf '%s\n' bootopt=64S3,32N2 > "$bad_token/proc/cmdline"
if run_fixture "$bad_token"; then fail 'accepted without cmdline capability'; fi
test ! -e "$bad_token/run/unattended-recovery.accepted"

bad_system=$WORK/bad-system
make_fixture "$bad_system"
rm "$bad_system/run/current-system"
ln -s "$bad_system/nix/store/nixos-system-gemini-mainline-nixos-other" "$bad_system/run/current-system"
mkdir -p "$bad_system/nix/store/nixos-system-gemini-mainline-nixos-other"
if run_fixture "$bad_system"; then fail 'accepted mismatched Stage2 system'; fi
test ! -e "$bad_system/run/unattended-recovery.accepted"

late=$WORK/late
make_fixture "$late"
printf '%s\n' '820.00 0.00' > "$late/proc/uptime"
if run_fixture "$late"; then fail 'accepted at deadline'; fi
test ! -e "$late/run/unattended-recovery.accepted"

failed=$WORK/failed
make_fixture "$failed"
cat > "$failed/bin/systemctl" <<'SYSTEMCTL'
#!/bin/sh
case "$1${2:-}" in
  is-system-running) echo running ;;
  is-active--quiet) exit 0 ;;
  --failed--no-legend) echo 'bad.service loaded failed failed bad' ;;
  *) exit 2 ;;
esac
SYSTEMCTL
chmod 0755 "$failed/bin/systemctl"
if run_fixture "$failed"; then fail 'accepted with failed unit'; fi
test ! -e "$failed/run/unattended-recovery.accepted"

echo 'test-unattended-recovery-baseline-self-accept: PASS'
