#!/bin/sh
# SPDX-License-Identifier: MIT
# Host-only acceptance-contract tests. No hardware paths are opened.
# shellcheck disable=SC1007 # zsh/NixOS-compatible scoped CDPATH assignment
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d /mnt/Home/src/nixos-gemini-baseline-accept-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
TOKEN=gemini-baseline-lease-v1-4e8e71c5b0c2aa1543c6fb079cc22964d0a7e25b942cb350f7a1e3d69b8c4052
SYSTEM_HASH=42h659ml5kvdmvwcp64i3dypmgwbg4wz
SYSTEM=/nix/store/$SYSTEM_HASH-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade

fail() { echo "test-unattended-recovery-baseline-self-accept: $*" >&2; exit 1; }

make_fixture() {
  d=$1
  mkdir -p "$d/run" "$d/proc/440/fd" "$d/sys/class/watchdog/watchdog0" \
    "$d/bin" "$d/sys/class/drm/card0-DSI-1"
  printf '%s\n' connected > "$d/sys/class/drm/card0-DSI-1/status"
  printf '%s\n' enabled > "$d/sys/class/drm/card0-DSI-1/enabled"
  cat > "$d/bin/fake-busybox" <<'BUSYBOX'
#!/bin/sh
exec "$@"
BUSYBOX
  chmod 0755 "$d/bin/fake-busybox"
  ln -s "$SYSTEM" "$d/run/current-system"
  printf '%s\n' "$SYSTEM" > "$d/run/gemini-lease-expected-system"
  printf '%s\n' "GEMINI_MAINLINE_NIXOS: stage1=switch-root system=$SYSTEM" > "$d/run/stage1-handoff"
  printf '%s\n' \
    'mainline NixOS reached multi-user.target' \
    'watchdog-owner=440' \
    'watchdog-state=active' > "$d/run/gemini-mainline-success"
  printf '%s\n' 'result=pass watchdog_lease=unchanged remote_review_required=yes' > "$d/run/bq2589x-preflight.pass"
  printf '%s\n' \
    'display=activated gate=14000000.syscon/activate_drm dsi_irq=pre-host-registration' \
    > "$d/run/gemini-display-activation"
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
grep -Fqx 'result=accepted' "$ok/run/gemini-baseline-self-accept.status"

overlay_store=$WORK/overlay-store
make_fixture "$overlay_store"
printf '%s\n' \
  '/dev/mmcblk0p29 /gemian ext4 ro,nosuid,nodev,noexec 0 0' \
  '/dev/loop0 /nix/.ro-store squashfs ro,nodev 0 0' \
  '/dev/mmcblk0p32 /persist ext4 rw,nosuid,nodev,noatime 0 0' \
  'overlay /nix/store overlay rw,relatime,lowerdir=/mnt/nixos/nix/.ro-store,upperdir=/mnt/nixos/persist/nix/upper,workdir=/mnt/nixos/persist/nix/work 0 0' \
  > "$overlay_store/proc/mounts"
run_fixture "$overlay_store"
grep -Fqx unattended_recovery=healthy "$overlay_store/run/unattended-recovery.accepted"

for broken in no-lower foreign-lower; do
  bad_store=$WORK/store-$broken
  make_fixture "$bad_store"
  case "$broken" in
    no-lower) lower='/dev/loop0 /nix/.ro-store tmpfs rw 0 0' ;;
    foreign-lower) lower='/dev/loop0 /nix/.ro-store squashfs ro,nodev 0 0' ;;
  esac
  overlay='overlay /nix/store overlay rw,lowerdir=/mnt/nixos/persist/nix/other,upperdir=/x,workdir=/y 0 0'
  [ "$broken" = no-lower ] && overlay='overlay /nix/store overlay rw,lowerdir=/mnt/nixos/nix/.ro-store,upperdir=/x,workdir=/y 0 0'
  printf '%s\n' '/dev/mmcblk0p29 /gemian ext4 ro,nosuid,nodev,noexec 0 0' "$lower" "$overlay" \
    > "$bad_store/proc/mounts"
  if run_fixture "$bad_store"; then fail "accepted store $broken"; fi
  test ! -e "$bad_store/run/unattended-recovery.accepted"
done

missing_display=$WORK/missing-display
make_fixture "$missing_display"
rm "$missing_display/run/gemini-display-activation"
if run_fixture "$missing_display"; then fail 'accepted without display activation'; fi
test ! -e "$missing_display/run/unattended-recovery.accepted"

for state in missing disconnected disabled; do
  bad_display=$WORK/display-$state
  make_fixture "$bad_display"
  case "$state" in
    missing) rm -r "$bad_display/sys/class/drm/card0-DSI-1" ;;
    disconnected) printf '%s\n' disconnected > "$bad_display/sys/class/drm/card0-DSI-1/status" ;;
    disabled) printf '%s\n' disabled > "$bad_display/sys/class/drm/card0-DSI-1/enabled" ;;
  esac
  if run_fixture "$bad_display"; then fail "accepted display $state"; fi
  test ! -e "$bad_display/run/unattended-recovery.accepted"
done

bad_token=$WORK/bad-token
make_fixture "$bad_token"
printf '%s\n' bootopt=64S3,32N2 > "$bad_token/proc/cmdline"
if run_fixture "$bad_token"; then fail 'accepted without cmdline capability'; fi
test ! -e "$bad_token/run/unattended-recovery.accepted"

bad_system=$WORK/bad-system
make_fixture "$bad_system"
ln -sfn "/nix/store/$SYSTEM_HASH-nixos-system-gemini-mainline-nixos-other" \
  "$bad_system/run/current-system"
if run_fixture "$bad_system"; then fail 'accepted mismatched Stage2 system'; fi
test ! -e "$bad_system/run/unattended-recovery.accepted"

assert_invalid_system_path() {
  label=$1
  path=$2
  d=$WORK/$label
  make_fixture "$d"
  ln -sfn "$path" "$d/run/current-system"
  printf '%s\n' "$path" > "$d/run/gemini-lease-expected-system"
  printf '%s\n' "GEMINI_MAINLINE_NIXOS: stage1=switch-root system=$path" \
    > "$d/run/stage1-handoff"
  if run_fixture "$d"; then fail "accepted invalid system path: $label"; fi
  test ! -e "$d/run/unattended-recovery.accepted"
  grep -Fq 'baseline_self_accept=withheld reason=expected-system-invalid' \
    "$d/run/stage1.log"
}

assert_invalid_system_path hash-short \
  /nix/store/2h659ml5kvdmvwcp64i3dypmgwbg4wz-nixos-system-gemini-mainline-nixos-test
assert_invalid_system_path hash-long \
  /nix/store/042h659ml5kvdmvwcp64i3dypmgwbg4wz-nixos-system-gemini-mainline-nixos-test
assert_invalid_system_path hash-alphabet \
  /nix/store/e2h659ml5kvdmvwcp64i3dypmgwbg4wz-nixos-system-gemini-mainline-nixos-test
assert_invalid_system_path wrong-name \
  /nix/store/42h659ml5kvdmvwcp64i3dypmgwbg4wz-nixos-system-gemini-other-test

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
grep -Fqx 'reason=failed-units-present' "$failed/run/gemini-baseline-self-accept.status"
grep -Fqx 'detail=failed=bad.service' "$failed/run/gemini-baseline-self-accept.status"
grep -Fq 'baseline_self_accept=withheld reason=failed-units-present failed=bad.service' \
  "$failed/run/stage1.log"

degraded=$WORK/degraded
make_fixture "$degraded"
cat > "$degraded/bin/systemctl" <<'SYSTEMCTL'
#!/bin/sh
case "$1${2:-}" in
  is-system-running) echo degraded; exit 1 ;;
  is-active--quiet) exit 0 ;;
  --failed--no-legend) echo 'gemini-m39.service loaded failed failed m39' ;;
  list-jobs--no-legend) echo '12 gemini-desktop-qualify.service start running' ;;
  *) exit 2 ;;
esac
SYSTEMCTL
chmod 0755 "$degraded/bin/systemctl"
if GEMINI_BASELINE_ACCEPT_PMSG_FILE="$degraded/pmsg" run_fixture "$degraded"; then
  fail 'accepted a degraded system'
fi
test ! -e "$degraded/run/unattended-recovery.accepted"
grep -Fqx 'result=withheld' "$degraded/run/gemini-baseline-self-accept.status"
grep -Fqx 'reason=system-not-running' "$degraded/run/gemini-baseline-self-accept.status"
grep -Fqx 'detail=state=degraded failed=gemini-m39.service jobs=gemini-desktop-qualify.service' \
  "$degraded/run/gemini-baseline-self-accept.status"
grep -Fq 'reason=system-not-running state=degraded failed=gemini-m39.service' "$degraded/pmsg"
grep -Fq 'uptime=101.00' "$degraded/pmsg"

echo 'test-unattended-recovery-baseline-self-accept: PASS'
