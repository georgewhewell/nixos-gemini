#!/bin/sh
# SPDX-License-Identifier: MIT

set -eu

CDPATH=
export CDPATH
script_dir=$(dirname -- "$0")
script_dir=$(cd -- "$script_dir" && pwd)
script=$script_dir/bq2589x-preflight.sh
work_root=${GEMINI_PREFLIGHT_TEST_WORK_ROOT:-/mnt/Home/src}
work=$(mktemp -d "$work_root/bq2589x-preflight-test.XXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM

make_fixture()
{
	root=$1
	mkdir -p \
		"$root/sys/bus/i2c/devices/0-006b" \
		"$root/sys/class/power_supply/bq25890-charger-0" \
		"$root/run"
	ln -s /sys/bus/i2c/drivers/bq25890-charger \
		"$root/sys/bus/i2c/devices/0-006b/driver"
	for pair in \
		'manufacturer=Texas Instruments' \
		'model_name=bq25896' \
		'status=Charging' \
		'charge_type=Fast' \
		'online=1'; do
		property=${pair%%=*}
		value=${pair#*=}
		printf '%s\n' "$value" > "$root/sys/class/power_supply/bq25890-charger-0/$property"
	done
	: > "$root/dmesg"
}

pass_fixture="$work/pass"
make_fixture "$pass_fixture"
GEMINI_PREFLIGHT_SYSFS_ROOT="$pass_fixture/sys" \
	GEMINI_PREFLIGHT_RUN_ROOT="$pass_fixture/run" \
	GEMINI_PREFLIGHT_DMESG_FILE="$pass_fixture/dmesg" \
	GEMINI_PREFLIGHT_BIN_PATH="$PATH" \
	"$script"
grep -Fqx 'result=pass watchdog_lease=unchanged remote_review_required=yes' \
	"$pass_fixture/run/bq2589x-preflight.pass"
grep -Fqx 'GEMINI_BQ2589X_PREFLIGHT: property=model_name value=bq25896' \
	"$pass_fixture/run/bq2589x-preflight.status"

error_fixture="$work/error"
make_fixture "$error_fixture"
printf '%s\n' 'bq25890 0-006b: Cannot read chip ID: -110' > "$error_fixture/dmesg"
if GEMINI_PREFLIGHT_SYSFS_ROOT="$error_fixture/sys" \
	GEMINI_PREFLIGHT_RUN_ROOT="$error_fixture/run" \
	GEMINI_PREFLIGHT_DMESG_FILE="$error_fixture/dmesg" \
	GEMINI_PREFLIGHT_BIN_PATH="$PATH" \
	"$script"; then
	echo 'preflight accepted a BQ I2C error' >&2
	exit 1
fi
grep -Fqx 'result=fail reason=dmesg_i2c_or_identity_error' \
	"$error_fixture/run/bq2589x-preflight.fail"
cmp "$error_fixture/dmesg" "$error_fixture/run/bq2589x-preflight.dmesg"

echo 'bq2589x preflight tests: PASS'
