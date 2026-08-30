#!/bin/sh
# Read-only Gemini input-board inventory.  This intentionally never opens an
# input-event or I2C character device, scans an I2C bus, changes a GPIO, or
# writes any sysfs attribute.  The touchscreen client is disabled in DT; this
# is only the metadata we can observe without changing that contract.
set -eu

stage=${1:-}
case "$stage" in
	stage1|stage2) ;;
	*) exit 64 ;;
esac

SYSFS_ROOT=${GEMINI_INPUT_OBSERVE_SYSFS_ROOT:-/sys}
RUN_ROOT=${GEMINI_INPUT_OBSERVE_RUN_ROOT:-/run}
case "$SYSFS_ROOT:$RUN_ROOT" in
	/*:/*) ;;
	*) exit 64 ;;
esac

mkdir -p "$RUN_ROOT"
log="$RUN_ROOT/gemini-input-observe-$stage.log"
umask 077
exec > "$log" 2>&1

record() {
	printf '%s\n' "GEMINI_INPUT_OBSERVE: $*"
}

read_attribute() {
	attribute=$1
	if [ -r "$attribute" ]; then
		cat "$attribute" 2>/dev/null || true
	else
		printf '%s' unknown
	fi
}

record "stage=$stage mode=sysfs-read-only i2c_transfers=none input_events=unopened touchscreen_client=untouched"

input_count=0
for device in "$SYSFS_ROOT"/class/input/input*; do
	[ -d "$device" ] || continue
	input_count=$((input_count + 1))
	record "input-device=${device##*/} name=$(read_attribute "$device/name")"
done
record "input-device-count=$input_count"

i2c_count=0
for adapter in "$SYSFS_ROOT"/class/i2c-adapter/i2c-*; do
	[ -d "$adapter" ] || continue
	i2c_count=$((i2c_count + 1))
	record "i2c-adapter=${adapter##*/} name=$(read_attribute "$adapter/name")"
done
record "i2c-adapter-count=$i2c_count"

thermal_count=0
for zone in "$SYSFS_ROOT"/class/thermal/thermal_zone*; do
	[ -d "$zone" ] || continue
	thermal_count=$((thermal_count + 1))
	record "thermal-zone=${zone##*/} type=$(read_attribute "$zone/type") temp=$(read_attribute "$zone/temp")"
done
record "thermal-zone-count=$thermal_count"
record "result=pass writes=run-log-only"
