#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# gemini-storage-provision: one-time, explicit repartitioning of the Gemini
# eMMC user area for persistent storage (handoff/power-policy.md).
#
#   p32 "userdata" keeps its start, name, type GUID, unique GUID and
#       attributes and shrinks to 10.6 GiB; it becomes ext4 "gemini-data"
#       (/home and the registered Nix store under /persist/nixos/nix).
#   p34 "swap"     is a new 5 GiB Linux swap partition, 1 MiB aligned,
#       ending just before p33 "flashinfo" (which does not move).
#
# Nothing runs unless invoked by hand.  Every run first saves the primary
# and backup GPT to /run/gemini-gpt-backup (copy it off the device).  The
# GPT is only changed from the exact factory layout below, and only with
# --confirm-repartition-userdata; an already provisioned layout is accepted
# unchanged (idempotent); anything else is refused.
#
# usage: gemini-storage-provision --dump-only
#        gemini-storage-provision --confirm-repartition-userdata
set -euo pipefail

readonly DISK_SECTORS=122142720
# name start size (512-byte sectors), factory layout.
readonly P29=(linux 6586368 82720768)
readonly P30=(boot2 89307136 32768)
readonly P31=(boot3 89339904 32768)
readonly P32=(userdata 89372672 32737247)
readonly P33=(flashinfo 122109919 32768)
# Provisioned layout.
readonly P32_NEW_SIZE=22249472
readonly P34=(swap 111622144 10485760)
readonly P34_TYPE=0657FD6D-A4AB-43C4-84E5-0933C84B4F4F # Linux swap
readonly P34_GUID=@SWAP_PARTUUID@
readonly DATA_LABEL=@DATA_LABEL@
readonly SWAP_LABEL=gemini-swap
BACKUP_DIR=/run/gemini-gpt-backup

die() { echo "gemini-storage-provision: $*" >&2; exit 1; }
say() { echo "gemini-storage-provision: $*"; }

prepare_data_layout() {
  local data_root=$1 entry
  for entry in home nixos nixos/nix nixos/nix/store nixos/nix/var; do
    [ ! -L "$data_root/$entry" ] || die "symlink in data layout: $entry"
    [ ! -e "$data_root/$entry" ] || [ -d "$data_root/$entry" ] ||
      die "non-directory in data layout: $entry"
  done
  mkdir -p "$data_root/home" "$data_root/nixos/nix/store" "$data_root/nixos/nix/var"
  chmod 0755 "$data_root/home" "$data_root/nixos" "$data_root/nixos/nix" "$data_root/nixos/nix/var"
  chown root:30000 "$data_root/nixos/nix/store" # nixbld, as /nix/store
  chmod 1775 "$data_root/nixos/nix/store"
}

mode=
case "${1:-}" in
  --dump-only) mode=dump ;;
  --confirm-repartition-userdata) mode=apply ;;
  *) die "usage: $0 --dump-only | --confirm-repartition-userdata" ;;
esac
[ "$#" -eq 1 ] || die "exactly one argument"

# Host test hook (nix/test-gemini-storage-provision.sh): run the GPT steps on
# a disk image file and stop before the kernel re-read and the filesystems.
test_image=${GEMINI_PROVISION_TEST_IMAGE:-}
if [ -n "$test_image" ]; then
  dev=$test_image
  BACKUP_DIR=$GEMINI_PROVISION_TEST_BACKUP_DIR
  [ "$(( $(stat -c %s "$dev") / 512 ))" = "$DISK_SECTORS" ] || die "test image size"
else
[ "$(id -u)" = 0 ] || die "must run as root"

# The eMMC is the mmcblk disk under the 11230000.mmc controller.
disk=
for node in /sys/class/block/mmcblk*; do
  name=${node##*/}
  [[ $name =~ ^mmcblk[0-9]+$ ]] || continue
  case "$(readlink -f "$node/device")" in
    */11230000.mmc/*) [ -z "$disk" ] || die "two eMMC disks"; disk=$name ;;
  esac
done
[ -n "$disk" ] || die "eMMC (11230000.mmc) not found"
dev=/dev/$disk
[ "$(cat "/sys/class/block/$disk/size")" = "$DISK_SECTORS" ] ||
  die "$dev is not $DISK_SECTORS sectors"
fi

# --- 1. save both GPT copies ------------------------------------------------
mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out=$BACKUP_DIR/$stamp
mkdir -p "$out"
# Header fields (LE): entries LBA @72, count @80, entry size @84.
hdr() { od -An -t u"$2" -j "$((512 + $1))" -N "$2" "$dev" | tr -d ' '; }
entries_lba=$(hdr 72 8)
entries=$(hdr 80 4)
entry_size=$(hdr 84 4)
[ "$(dd if="$dev" bs=1 skip=512 count=8 status=none)" = "EFI PART" ] ||
  die "no primary GPT header"
entry_sectors=$(( (entries * entry_size + 511) / 512 ))
primary=$(( entries_lba + entry_sectors ))
[ "$primary" -ge 34 ] || primary=34
backup=$(( entry_sectors + 1 ))
[ "$backup" -ge 33 ] || backup=33
dd if="$dev" of="$out/primary-gpt.bin" bs=512 count="$primary" status=none
dd if="$dev" of="$out/backup-gpt.bin" bs=512 skip=$((DISK_SECTORS - backup)) \
  count="$backup" status=none
sgdisk --backup="$out/sgdisk.backup" "$dev" > /dev/null
sgdisk -p "$dev" > "$out/sgdisk-print.txt"
for n in $(seq 1 64); do
  sgdisk -i "$n" "$dev" 2>/dev/null | grep -q 'Partition GUID code' || continue
  echo "== $n"; sgdisk -i "$n" "$dev"
done > "$out/sgdisk-info.txt"
{
  echo "disk=$dev sectors=$DISK_SECTORS"
  echo "primary=primary-gpt.bin lba=0 sectors=$primary"
  echo "backup=backup-gpt.bin lba=$((DISK_SECTORS - backup)) sectors=$backup"
  echo "entries=$entries entry_size=$entry_size entries_lba=$entries_lba"
  (cd "$out" && sha256sum primary-gpt.bin backup-gpt.bin sgdisk.backup)
} > "$out/MANIFEST"
say "GPT saved to $out; copy it off now: scp -r root@<device>:$out ."
cat "$out/MANIFEST"
[ "$mode" = dump ] && exit 0

# --- 2. check the layout ----------------------------------------------------
geom() { # number -> "name start size", or empty
  local info first last name
  info=$(sgdisk -i "$1" "$dev" 2>/dev/null) || return 0
  grep -q 'Partition GUID code' <<< "$info" || return 0
  first=$(sed -n 's/^First sector: \([0-9]*\).*/\1/p' <<< "$info")
  last=$(sed -n 's/^Last sector: \([0-9]*\).*/\1/p' <<< "$info")
  name=$(sed -n "s/^Partition name: '\(.*\)'$/\1/p" <<< "$info")
  echo "$name $first $((last - first + 1))"
}
expect() { # number name start size
  [ "$(geom "$1")" = "$2 $3 $4" ] || die "p$1 is '$(geom "$1")', expected '$2 $3 $4'"
}
expect 29 "${P29[@]}"
expect 30 "${P30[@]}"
expect 31 "${P31[@]}"
expect 33 "${P33[@]}"
[ "$entries" -ge 34 ] || die "the GPT holds only $entries entries"
sgdisk -v "$dev" | grep -q 'No problems found' || die "sgdisk -v reports problems"

for part in "${dev}p32" "${dev}p34"; do
  [ -z "$test_image" ] || break
  if grep -q "^$part " /proc/mounts || grep -q "^$part " /proc/swaps; then
    die "$part is in use"
  fi
done

if [ "$(geom 32)" = "${P32[*]}" ] && [ -z "$(geom 34)" ]; then
  say "factory layout found; repartitioning p32 and adding p34"
  info=$(sgdisk -i 32 "$dev")
  type=$(sed -n 's/^Partition GUID code: \([0-9A-F-]*\).*/\1/p' <<< "$info")
  guid=$(sed -n 's/^Partition unique GUID: \([0-9A-F-]*\)$/\1/p' <<< "$info")
  attrs=$(sed -n 's/^Attribute flags: \([0-9a-f]*\)$/\1/p' <<< "$info")
  if [ -z "$type" ] || [ -z "$guid" ] || [ -z "$attrs" ]; then die "cannot read p32 identity"; fi
  # A new entry starts with no attribute bits.  Only carry non-zero ones over:
  # sgdisk 1.0.10 rejects an all-zero 16-digit mask ("Could not convert hex
  # attribute mask") and then aborts without writing anything.
  attr_args=()
  if [ -n "${attrs//0/}" ]; then
    attr_args=(--attributes="32:=:${attrs#"${attrs%%[!0]*}"}")
  fi
  sgdisk --set-alignment=2048 \
    --delete=32 \
    --new="32:${P32[1]}:$((P32[1] + P32_NEW_SIZE - 1))" \
    --change-name=32:userdata --typecode="32:$type" \
    --partition-guid="32:$guid" "${attr_args[@]}" \
    --new="34:${P34[1]}:$((P34[1] + P34[2] - 1))" \
    --change-name=34:swap --typecode="34:$P34_TYPE" \
    --partition-guid="34:$P34_GUID" \
    "$dev"
  sgdisk -v "$dev" | grep -q 'No problems found' || die "sgdisk -v failed after the change"
elif [ "$(geom 32)" = "userdata ${P32[1]} $P32_NEW_SIZE" ] &&
     [ "$(geom 34)" = "${P34[*]}" ]; then
  say "layout already provisioned; GPT unchanged"
else
  die "unexpected p32/p34: '$(geom 32)' / '$(geom 34)'; refusing"
fi
expect 32 userdata "${P32[1]}" "$P32_NEW_SIZE"
expect 34 "${P34[@]}"
sgdisk -i 34 "$dev" | grep -qi "unique GUID: $P34_GUID" || die "p34 GUID mismatch"
if [ -n "$test_image" ]; then
  say "test image: GPT steps done"
  exit 0
fi

# Tell the kernel (BLKPG per partition; p29 stays mounted).
partx -u "$dev"
udevadm settle || true
[ "$(cat "/sys/class/block/${disk}p32/size")" = "$P32_NEW_SIZE" ] || die "kernel still sees old p32"
[ "$(cat "/sys/class/block/${disk}p34/size")" = "${P34[2]}" ] || die "kernel does not see p34"
# The p34 name is checked in the GPT above ("expect 34").  partx -u updates
# the kernel's partitions through BLKPG, which carries no names, so
# PARTNAME only appears in uevent after the next boot's full rescan.

# --- 3. filesystems -----------------------------------------------------------
if [ "$(blkid -o value -s TYPE "${dev}p32" 2>/dev/null)" = ext4 ] &&
   [ "$(blkid -o value -s LABEL "${dev}p32" 2>/dev/null)" = "$DATA_LABEL" ]; then
  say "p32 already ext4 '$DATA_LABEL'"
else
  say "creating ext4 '$DATA_LABEL' on ${dev}p32"
  wipefs -a "${dev}p32"
  mkfs.ext4 -q -F -L "$DATA_LABEL" -b 4096 -m 0 "${dev}p32"
fi
mnt=$(mktemp -d /run/gemini-data.XXXXXX)
mount -t ext4 "${dev}p32" "$mnt"
trap 'umount "$mnt"; rmdir "$mnt"' EXIT
prepare_data_layout "$mnt"
umount "$mnt"
rmdir "$mnt"
trap - EXIT

if [ "$(blkid -o value -s TYPE "${dev}p34" 2>/dev/null)" = swap ]; then
  say "p34 already swap"
else
  say "creating swap on ${dev}p34"
  mkswap -L "$SWAP_LABEL" "${dev}p34"
fi
sync
say "layout ready; copy the NixOS closure into /persist/nixos before booting the normal system"
