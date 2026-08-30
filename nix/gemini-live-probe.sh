#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Host-side runner for one Gemini runtime-DT-overlay probe.  It does not flash
# or reboot the device.  The overlay-loader module is intentionally loaded by
# an absolute /run path and is removed only with --unload.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: gemini-live-probe.sh --module PATH --dtbo PATH --class CLASS [options]

CLASS is one of: touch microsd fgadc audio thermal-hall usb11 display gnss pmic-write.
display, gnss, and pmic-write require their matching --allow-* switch.  All
other classes are still subject to the DT-content denylist.  --unload is
explicit because a failed in-kernel overlay removal must be investigated, not
silently retried.

Options:
  --target USER@HOST       SSH target (default root@10.15.19.82 via trex)
  --expect-path PATH      require this /proc/device-tree path after apply
  --unload                remove the overlay, then rmmod the helper
  --allow-display          permit a display-class overlay
  --allow-gnss             permit a GNSS-class overlay
  --allow-pmic-write       permit a PMIC-write-class overlay
  --artifacts DIR          local evidence directory (default ./gemini-live-probe-TIMESTAMP)
EOF
  exit 2
}

module=
dtbo=
overlay_class=
target=root@10.15.19.82
expect_path=
unload=no
allow_display=no
allow_gnss=no
allow_pmic_write=no
artifacts=

while (($#)); do
  case $1 in
    --module) module=${2-}; shift 2 ;;
    --dtbo) dtbo=${2-}; shift 2 ;;
    --class) overlay_class=${2-}; shift 2 ;;
    --target) target=${2-}; shift 2 ;;
    --expect-path) expect_path=${2-}; shift 2 ;;
    --unload) unload=yes; shift ;;
    --allow-display) allow_display=yes; shift ;;
    --allow-gnss) allow_gnss=yes; shift ;;
    --allow-pmic-write) allow_pmic_write=yes; shift ;;
    --artifacts) artifacts=${2-}; shift 2 ;;
    *) usage ;;
  esac
done

[[ -f $module && -f $dtbo && -n $overlay_class ]] || usage
[[ $module == *.ko && $dtbo == *.dtbo ]] || {
  echo '--module must be a .ko and --dtbo must be a .dtbo' >&2; exit 2;
}
for base in "$(basename "$module")" "$(basename "$dtbo")"; do
  [[ $base =~ ^[A-Za-z0-9._-]+$ ]] || {
    echo 'module and DTBO basenames may contain only letters, digits, dot, underscore, and hyphen' >&2
    exit 2
  }
done
case $overlay_class in
  touch|microsd|fgadc|audio|thermal-hall|usb11) ;;
  display) [[ $allow_display == yes ]] || { echo 'display requires --allow-display' >&2; exit 2; } ;;
  gnss) [[ $allow_gnss == yes ]] || { echo 'GNSS requires --allow-gnss' >&2; exit 2; } ;;
  pmic-write) [[ $allow_pmic_write == yes ]] || { echo 'PMIC write requires --allow-pmic-write' >&2; exit 2; } ;;
  *) usage ;;
esac
[[ -z $expect_path || $expect_path == /proc/device-tree/* ]] || {
  echo '--expect-path must be below /proc/device-tree' >&2; exit 2;
}
[[ -z $expect_path || $expect_path =~ ^/proc/device-tree/[A-Za-z0-9._/@+-]+$ ]] || {
  echo '--expect-path contains unsafe characters' >&2; exit 2;
}

for tool in dtc modinfo sha256sum ssh scp; do command -v "$tool" >/dev/null || {
  echo "missing host tool: $tool" >&2; exit 2;
}; done

# Refuse a disguised activation before a root-capable target sees it.  This is
# a conservative content gate, not a replacement for review of the DTBO.
overlay_dts=$(dtc -I dtb -O dts "$dtbo")
deny_if_present() {
  local expression=$1 label=$2 allowed=$3
  if grep -Eiq "$expression" <<<"$overlay_dts" && [[ $allowed != yes ]]; then
    echo "refusing DTBO containing $label without its explicit --allow-* switch" >&2
    exit 2
  fi
}
deny_if_present 'drm|dsi|display|panel|backlight|smi|larb' display "$allow_display"
deny_if_present 'gnss|gps' GNSS "$allow_gnss"
deny_if_present 'regulator-(always-on|boot-on)|regulator-initial-mode|charger@|bq258' PMIC-write "$allow_pmic_write"

module_vermagic=$(modinfo -F vermagic "$module")
module_release=${module_vermagic%% *}
[[ -n $module_release ]] || { echo 'module has no vermagic' >&2; exit 2; }
module_sha=$(sha256sum "$module" | awk '{print $1}')
dtbo_sha=$(sha256sum "$dtbo" | awk '{print $1}')

ssh_opts=(
  -o 'ProxyCommand=ssh -o ControlMaster=no -o ControlPath=none -W %h:%p trex'
  -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes
  -o ConnectTimeout=12 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
)
remote_release=$(ssh "${ssh_opts[@]}" "$target" uname -r)
[[ $module_release == "$remote_release" ]] || {
  echo "vermagic mismatch: module=$module_release target=$remote_release" >&2; exit 2;
}

stamp=$(date -u +%Y%m%dT%H%M%SZ)
artifacts=${artifacts:-"$PWD/gemini-live-probe-$stamp"}
mkdir -p "$artifacts"
remote_dir=/run/gemini-live-probe-$stamp-$$
module_base=gemini-live-overlay.ko
dtbo_base=probe.dtbo

ssh "${ssh_opts[@]}" "$target" "umask 077 && mkdir -p '$remote_dir'"
scp -q -o 'ProxyCommand=ssh -o ControlMaster=no -o ControlPath=none -W %h:%p trex' \
  -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes \
  "$module" "$dtbo" "$target:$remote_dir/"

# Keep target names fixed even if the reviewed source artifact has a longer
# name.  request_firmware_direct() only sees this basename below /run.
ssh "${ssh_opts[@]}" "$target" "mv '$remote_dir/$(basename "$module")' '$remote_dir/$module_base'; mv '$remote_dir/$(basename "$dtbo")' '$remote_dir/$dtbo_base'"

set +e
ssh "${ssh_opts[@]}" "$target" sh -s -- \
  "$remote_dir" "$module_base" "$dtbo_base" "$module_sha" "$dtbo_sha" "$unload" "$expect_path" <<'REMOTE'
set -eu
work=$1 ko_base=$2 dtbo_base=$3 expected_ko_sha=$4 expected_dtbo_sha=$5 unload=$6 expect_path=$7

snapshot() {
  label=$1
  dmesg > "$work/dmesg-$label"
  {
    printf 'kernel=%s\n' "$(uname -a)"
    printf 'cmdline='; cat /proc/cmdline
    find /sys/bus /sys/class /sys/devices -maxdepth 4 -printf '%p\n' 2>/dev/null | sort
    find /proc/device-tree -maxdepth 4 -printf '%p\n' 2>/dev/null | sort
  } > "$work/sysfs-$label"
}

watchdog_owner=none
for proc in /proc/[0-9]*; do
  for fd in "$proc"/fd/*; do
    target=$(readlink "$fd" 2>/dev/null || true)
    case $target in /dev/watchdog|/dev/watchdog0) watchdog_owner=${proc##*/}; break 2;; esac
  done
done
if [ "$watchdog_owner" = none ]; then
  test -x /bin/watchdog || { echo 'no existing watchdog petter and /bin/watchdog is absent' >&2; exit 1; }
  # The fallback petter is deliberately bounded.  It keeps a probe alive long
  # enough to gather evidence, but cannot mask a failed cleanup indefinitely.
  nohup setsid /bin/busybox timeout 90 /bin/watchdog -F -t 10 -T 31 /dev/watchdog0 \
    > "$work/watchdog.log" 2>&1 < /dev/null &
  watchdog_owner=$!
  sleep 1
  kill -0 "$watchdog_owner" 2>/dev/null || { cat "$work/watchdog.log" >&2; exit 1; }
  printf '%s\n' "$watchdog_owner" > "$work/watchdog-owner"
fi
printf 'watchdog_owner=%s fallback_lease_seconds=90\n' "$watchdog_owner" > "$work/watchdog-state"

test -e /sys/module/firmware_class/parameters/path
test ! -e /sys/module/gemini_live_overlay
old_firmware_path=$(cat /sys/module/firmware_class/parameters/path)
firmware_path_changed=no
restore_firmware_path() {
  if [ "$firmware_path_changed" = yes ]; then
    printf '%s\n' "$old_firmware_path" > /sys/module/firmware_class/parameters/path || true
  fi
}
trap restore_firmware_path EXIT HUP INT TERM
printf '%s\n' "$old_firmware_path" > "$work/firmware-class-path-before"
printf '%s\n' "$work" > /sys/module/firmware_class/parameters/path
firmware_path_changed=yes
sha256sum "$work/$ko_base" "$work/$dtbo_base" > "$work/transferred-sha256"
test "$(sha256sum "$work/$ko_base" | awk '{print $1}')" = "$expected_ko_sha"
test "$(sha256sum "$work/$dtbo_base" | awk '{print $1}')" = "$expected_dtbo_sha"
snapshot before

if ! insmod "$work/$ko_base" "firmware=$dtbo_base"; then
  snapshot failed
  exit 1
fi
printf '%s\n' "$old_firmware_path" > /sys/module/firmware_class/parameters/path
firmware_path_changed=no
test -e /sys/module/gemini_live_overlay
if [ -n "$expect_path" ]; then test -e "$expect_path"; fi
snapshot applied

if [ "$unload" = yes ]; then
  # The helper owns a module reference until this explicit cleanup succeeds.
  # A failed write leaves that reference and the overlay in place for a
  # reviewed retry; never call rmmod first.
  test -e /sys/module/gemini_live_overlay/parameters/remove_overlay
  if ! printf '1\n' > /sys/module/gemini_live_overlay/parameters/remove_overlay; then
    snapshot remove-failed
    exit 1
  fi
  if [ -n "$expect_path" ] && test -e "$expect_path"; then
    snapshot remove-failed
    exit 1
  fi
  if ! rmmod gemini_live_overlay; then
    snapshot rmmod-failed
    exit 1
  fi
  snapshot removed
  test ! -e /sys/module/gemini_live_overlay
fi
REMOTE
remote_rc=$?
set -e

scp -q -r -o 'ProxyCommand=ssh -o ControlMaster=no -o ControlPath=none -W %h:%p trex' \
  -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes \
  "$target:$remote_dir/." "$artifacts/" || true
printf 'remote_dir=%s\nremote_rc=%s\nmodule_vermagic=%s\n' \
  "$remote_dir" "$remote_rc" "$module_vermagic" > "$artifacts/RESULT"
exit "$remote_rc"
