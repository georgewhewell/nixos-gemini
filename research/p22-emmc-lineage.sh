# Resolve the Gemini eMMC by its fixed 11230000.mmc controller lineage.
# This file is injected into bounded target-side probes; it intentionally has
# no side effects and refuses ambiguous or unrelated MMC devices.
EMMC_SYSFS_ROOT=${EMMC_SYSFS_ROOT:-/sys}
EMMC_DEV_ROOT=${EMMC_DEV_ROOT:-/dev}

resolve_emmc_controller() {
  controller=
  for candidate in \
    "$EMMC_SYSFS_ROOT/devices/platform/11230000.mmc" \
    "$EMMC_SYSFS_ROOT/devices/platform"/*/11230000.mmc \
    "$EMMC_SYSFS_ROOT/devices/platform"/*/*/11230000.mmc; do
    [ -d "$candidate" ] || continue
    resolved=$(readlink -f "$candidate" 2>/dev/null || true)
    [ -n "$resolved" ] || continue
    if [ -n "$controller" ] && [ "$controller" != "$resolved" ]; then
      return 1
    fi
    controller=$resolved
  done
  [ -n "$controller" ] || return 1
  printf '%s\n' "$controller"
}

emmc_block_on_controller() {
  sysblock=$1
  controller=$2
  [ -e "$sysblock" ] || return 1
  parent=$(readlink -f "$sysblock/device" 2>/dev/null || true)
  while [ -n "$parent" ] && [ "$parent" != / ]; do
    [ "$parent" = "$controller" ] && return 0
    next_parent=${parent%/*}
    [ "$next_parent" != "$parent" ] || break
    parent=$next_parent
  done
  return 1
}

resolve_emmc_device() {
  controller=$(resolve_emmc_controller) || return 1
  found=
  for node in "$EMMC_SYSFS_ROOT/class/block"/mmcblk*; do
    [ -e "$node" ] || continue
    name=${node##*/}
    case "$name" in
      mmcblk[0-9]*) suffix=${name#mmcblk}; case "$suffix" in *[!0-9]*|'') continue ;; esac ;;
      *) continue ;;
    esac
    [ ! -e "$node/partition" ] || continue
    if emmc_block_on_controller "$node" "$controller"; then
      [ -z "$found" ] || return 1
      found=$EMMC_DEV_ROOT/${node##*/}
    fi
  done
  [ -n "$found" ] || return 1
  printf '%s\n' "$found"
}

resolve_emmc_partition() {
  label=$1
  case "$label" in
    boot) part=22 ;;
    boot2) part=30 ;;
    boot3) part=31 ;;
    *) return 1 ;;
  esac
  emmc=$(resolve_emmc_device) || return 1
  path="$emmc"p$part
  [ -e "$EMMC_SYSFS_ROOT/class/block/${path##*/}" ] || return 1
  printf '%s\n' "$path"
}
