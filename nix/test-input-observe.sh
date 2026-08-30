#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d "$ROOT/input-observe-test.XXXXXX")
trap 'rm -rf "$work"' EXIT

fixture=$work/fixture
mkdir -p \
	"$fixture/sys/class/input/input0" \
	"$fixture/sys/class/i2c-adapter/i2c-4" \
	"$fixture/sys/class/thermal/thermal_zone0" \
	"$fixture/run"
printf '%s\n' 'AW9523 matrix keypad' > "$fixture/sys/class/input/input0/name"
printf '%s\n' 'mt6797-i2c' > "$fixture/sys/class/i2c-adapter/i2c-4/name"
printf '%s\n' 'mtktscpu' > "$fixture/sys/class/thermal/thermal_zone0/type"
printf '%s\n' '42000' > "$fixture/sys/class/thermal/thermal_zone0/temp"

GEMINI_INPUT_OBSERVE_SYSFS_ROOT="$fixture/sys" \
	GEMINI_INPUT_OBSERVE_RUN_ROOT="$fixture/run" \
	"$ROOT/nix/input-observe.sh" stage1

log=$fixture/run/gemini-input-observe-stage1.log
grep -Fqx 'GEMINI_INPUT_OBSERVE: stage=stage1 mode=sysfs-read-only i2c_transfers=none input_events=unopened touchscreen_client=untouched' "$log"
grep -Fqx 'GEMINI_INPUT_OBSERVE: input-device=input0 name=AW9523 matrix keypad' "$log"
grep -Fqx 'GEMINI_INPUT_OBSERVE: i2c-adapter=i2c-4 name=mt6797-i2c' "$log"
grep -Fqx 'GEMINI_INPUT_OBSERVE: thermal-zone=thermal_zone0 type=mtktscpu temp=42000' "$log"
grep -Fqx 'GEMINI_INPUT_OBSERVE: result=pass writes=run-log-only' "$log"

if grep -Eq '/dev/(i2c|input)|i2cdetect|i2cget|i2cset' "$ROOT/nix/input-observe.sh"; then
	echo 'input observer gained a transfer or input-device access path' >&2
	exit 1
fi
