#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Host test of the GPT steps of gemini-storage-provision on a sparse image
# with the Gemini eMMC geometry.  usage: $0 <provision-script> <workdir>
set -euo pipefail
script=$1
work=$2
img=$work/emmc.img
# Checksum of both GPT copies (the rest of the sparse image is never written).
gptsum() {
  { dd if="$img" bs=512 count=34 status=none
    dd if="$img" bs=512 skip=$((122142720 - 33)) count=33 status=none; } | sha256sum
}
fail() { echo "test-gemini-storage-provision: $*" >&2; exit 1; }
run() {
  GEMINI_PROVISION_TEST_IMAGE=$img GEMINI_PROVISION_TEST_BACKUP_DIR=$work/backup \
    bash "$script" "$@"
}
geom() {
  local info
  info=$(sgdisk -i "$1" "$img")
  printf '%s %s %s %s %s\n' \
    "$(sed -n "s/^Partition name: '\(.*\)'$/\1/p" <<< "$info")" \
    "$(sed -n 's/^First sector: \([0-9]*\).*/\1/p' <<< "$info")" \
    "$(sed -n 's/^Last sector: \([0-9]*\).*/\1/p' <<< "$info")" \
    "$(sed -n 's/^Partition unique GUID: \(.*\)$/\1/p' <<< "$info")" \
    "$(sed -n 's/^Attribute flags: \(.*\)$/\1/p' <<< "$info")"
}
factory() {
  rm -f "$img"
  truncate -s $((122142720 * 512)) "$img"
  sgdisk -o "$img" > /dev/null
  # p1..p28 stand-ins below p29; only p29..p33 are checked.
  local start=2048 n
  for n in $(seq 1 28); do
    sgdisk -n "$n:$start:$((start + 2047))" -c "$n:part$n" "$img" > /dev/null
    start=$((start + 2048))
  done
  sgdisk -a 1 \
    -n 29:6586368:$((6586368 + 82720768 - 1)) -c 29:linux \
    -n 30:89307136:$((89307136 + 32768 - 1)) -c 30:boot2 \
    -n 31:89339904:$((89339904 + 32768 - 1)) -c 31:boot3 \
    -n 32:89372672:$((89372672 + 32737247 - 1)) -c 32:userdata \
    -u 32:11111111-2222-3333-4444-555555555555 -A 32:set:60 \
    -n 33:122109919:$((122109919 + 32768 - 1)) -c 33:flashinfo \
    "$img" > /dev/null
}

factory
before32=$(geom 32)
run --dump-only > "$work/dump.log"
grep -q 'entries=128' "$work/dump.log" || fail "dump manifest"
dumps=("$work"/backup/*/primary-gpt.bin)
test -s "${dumps[0]}" || fail "no primary dump"
[ "$(geom 32)" = "$before32" ] || fail "--dump-only changed the GPT"

if run --bogus 2> /dev/null; then fail "accepted a bogus flag"; fi

run --confirm-repartition-userdata > "$work/apply.log"
read -r name first last guid attrs <<< "$(geom 32)"
[ "$name $first $last" = "userdata 89372672 111622143" ] || fail "p32 geometry: $(geom 32)"
[ "$guid" = 11111111-2222-3333-4444-555555555555 ] || fail "p32 GUID not kept"
[ "$attrs" = "$(awk '{print $5}' <<< "$before32")" ] || fail "p32 attributes not kept"
read -r name first last guid _ <<< "$(geom 34)"
[ "$name $first $last" = "swap 111622144 122107903" ] || fail "p34 geometry: $(geom 34)"
sgdisk -i 34 "$img" | grep -q '0657FD6D-A4AB-43C4-84E5-0933C84B4F4F' || fail "p34 type"
[ "$(geom 33 | cut -d' ' -f1-3)" = "flashinfo 122109919 122142686" ] || fail "p33 moved"
sgdisk -v "$img" | grep -q 'No problems found' || fail "verify"

# Idempotent.
sum=$(gptsum)
run --confirm-repartition-userdata > "$work/again.log"
grep -q 'layout already provisioned' "$work/again.log" || fail "second run"
[ "$(gptsum)" = "$sum" ] || fail "second run changed the image"

# Foreign p34 geometry is refused.
sgdisk -a 1 -d 34 -n 34:111622144:122000000 -c 34:swap "$img" > /dev/null
sum=$(gptsum)
if run --confirm-repartition-userdata 2> /dev/null; then fail "accepted foreign p34"; fi
[ "$(gptsum)" = "$sum" ] || fail "refusal changed the image"

# A changed p33 is refused before anything is written.
factory
sgdisk -a 1 -d 33 -n 33:122109919:122142685 -c 33:flashinfo "$img" > /dev/null
sum=$(gptsum)
if run --confirm-repartition-userdata 2> /dev/null; then fail "accepted a changed p33"; fi
[ "$(gptsum)" = "$sum" ] || fail "refusal changed the image"

echo "test-gemini-storage-provision: pass"
