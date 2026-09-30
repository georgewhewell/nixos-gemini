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
		"$root/sys/bus/i2c/devices" \
		"$root/sys/devices/platform/11007000.i2c/i2c-2/2-006b" \
		"$root/sys/class/power_supply/bq25890-charger-0" \
		"$root/run"
	ln -s ../../../devices/platform/11007000.i2c/i2c-2/2-006b \
		"$root/sys/bus/i2c/devices/2-006b"
	ln -s /sys/bus/i2c/drivers/bq25890-charger \
		"$root/sys/devices/platform/11007000.i2c/i2c-2/2-006b/driver"
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
grep -Fqx 'GEMINI_BQ2589X_PREFLIGHT: i2c_client=2-006b controller=11007000.i2c driver=bq25890-charger' \
	"$pass_fixture/run/bq2589x-preflight.status"

guard_fixture="$work/i2c6-guard"
make_fixture "$guard_fixture"
printf '%s\n' \
	'i2c-mt65xx 1100e000.i2c: GEMINI_MT6797_I2C6_GUARD handoff=ready clock_validation_failures=0 transfer_attempts=24 dma_starts=0 nonzero_starts=24 irq_count=24' \
	> "$guard_fixture/dmesg"
GEMINI_PREFLIGHT_SYSFS_ROOT="$guard_fixture/sys" \
	GEMINI_PREFLIGHT_RUN_ROOT="$guard_fixture/run" \
	GEMINI_PREFLIGHT_DMESG_FILE="$guard_fixture/dmesg" \
	GEMINI_PREFLIGHT_BIN_PATH="$PATH" \
	"$script"
grep -Fqx 'result=pass watchdog_lease=unchanged remote_review_required=yes' \
	"$guard_fixture/run/bq2589x-preflight.pass"

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

i2c0_error_fixture="$work/i2c0-error"
make_fixture "$i2c0_error_fixture"
printf '%s\n' 'i2c-mt65xx 11007000.i2c: transfer timeout' \
	> "$i2c0_error_fixture/dmesg"
if GEMINI_PREFLIGHT_SYSFS_ROOT="$i2c0_error_fixture/sys" \
	GEMINI_PREFLIGHT_RUN_ROOT="$i2c0_error_fixture/run" \
	GEMINI_PREFLIGHT_DMESG_FILE="$i2c0_error_fixture/dmesg" \
	GEMINI_PREFLIGHT_BIN_PATH="$PATH" \
	"$script"; then
	echo 'preflight accepted an I2C0 controller error' >&2
	exit 1
fi
grep -Fqx 'result=fail reason=dmesg_i2c_or_identity_error' \
	"$i2c0_error_fixture/run/bq2589x-preflight.fail"

# Charger mode: the driver's limit properties must exist; their values and
# health are recorded, never judged.
add_limits()
{
	for pair in health=Good constant_charge_current=2048000 \
		constant_charge_voltage=4352000 precharge_current=128000 \
		charge_term_current=192000; do
		printf '%s\n' "${pair#*=}" > "$1/sys/class/power_supply/bq25890-charger-0/${pair%%=*}"
	done
}
run_mode()
{
	GEMINI_PREFLIGHT_SYSFS_ROOT="$1/sys" \
		GEMINI_PREFLIGHT_RUN_ROOT="$1/run" \
		GEMINI_PREFLIGHT_DMESG_FILE="$1/dmesg" \
		GEMINI_PREFLIGHT_BIN_PATH="$PATH" \
		GEMINI_PREFLIGHT_EXPECTED_MODE=$2 \
		"$script"
}
charger_fixture="$work/charger"
make_fixture "$charger_fixture"
add_limits "$charger_fixture"
run_mode "$charger_fixture" charger
grep -Fqx 'result=pass watchdog_lease=unchanged remote_review_required=yes' \
	"$charger_fixture/run/bq2589x-preflight.pass"
grep -Fqx 'GEMINI_BQ2589X_PREFLIGHT: property=constant_charge_voltage value=4352000' \
	"$charger_fixture/run/bq2589x-preflight.status"
# Overheat is recorded but must not fail boot acceptance.
printf '%s\n' Overheat > "$charger_fixture/sys/class/power_supply/bq25890-charger-0/health"
run_mode "$charger_fixture" charger
# The observer must reject the charging driver ...
if run_mode "$charger_fixture" observe; then
	echo 'observe mode accepted a charging driver' >&2
	exit 1
fi
# ... and charger mode must reject the read-only observer.
readonly_fixture="$work/readonly"
make_fixture "$readonly_fixture"
if run_mode "$readonly_fixture" charger; then
	echo 'charger mode accepted a read-only driver' >&2
	exit 1
fi
grep -Fqx 'result=fail reason=property_unreadable=health' \
	"$readonly_fixture/run/bq2589x-preflight.fail"
if run_mode "$readonly_fixture" bogus; then
	echo 'preflight accepted an unknown mode' >&2
	exit 1
fi

echo 'bq2589x preflight tests: PASS'
