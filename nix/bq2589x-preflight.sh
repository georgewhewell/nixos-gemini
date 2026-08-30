#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Bounded observer for the Gemini's opt-in BQ2589x recovery overlay.
#
# This script never opens /dev/i2c-*, runs i2c-tools, writes sysfs, accesses
# the MT6351 fuel gauge, or opens/pets/closes the platform watchdog.  It only
# reads the five properties published by the ti,read-only BQ25890 driver and
# kernel log text already collected by dmesg.  Its /run result is deliberately
# not the watchdog lease: a remote reviewer must make that decision.

set -u

PATH=${GEMINI_PREFLIGHT_BIN_PATH:-/bin}
export PATH

SYSFS_ROOT=${GEMINI_PREFLIGHT_SYSFS_ROOT:-/sys}
RUN_ROOT=${GEMINI_PREFLIGHT_RUN_ROOT:-/run}
DMESG_FILE=${GEMINI_PREFLIGHT_DMESG_FILE:-}
PREFIX=GEMINI_BQ2589X_PREFLIGHT
STATUS_FILE="$RUN_ROOT/bq2589x-preflight.status"
DMESG_CAPTURE="$RUN_ROOT/bq2589x-preflight.dmesg"
PASS_MARKER="$RUN_ROOT/bq2589x-preflight.pass"
FAIL_MARKER="$RUN_ROOT/bq2589x-preflight.fail"
ERROR_CONTEXT='(bq2589|0-006b|11007000|i2c-mt65xx)'
ERROR_FAILURE='(error|fail|timeout|timed out|nack|abort|unknown chip|'
ERROR_FAILURE="${ERROR_FAILURE}unknown device revision|cannot)"
ERROR_PATTERN="${ERROR_CONTEXT}.*${ERROR_FAILURE}"

record()
{
	line="$PREFIX: $*"
	printf '%s\n' "$line" >> "$STATUS_FILE" 2>/dev/null || true
	{ printf '<6>%s\n' "$line" > /dev/kmsg; } 2>/dev/null || true
	printf '%s\n' "$line"
}

fail()
{
	record "result=fail reason=$1"
	printf '%s\n' "result=fail reason=$1" > "$FAIL_MARKER" 2>/dev/null || true
	rm -f "$PASS_MARKER"
	exit 1
}

read_property()
{
	value=$(cat "$1" 2>/dev/null) || return 1
	[ -n "$value" ] || return 1
	printf '%s\n' "$value"
}

mkdir -p "$RUN_ROOT" 2>/dev/null || exit 1
rm -f "$PASS_MARKER" "$FAIL_MARKER"
record "stage=start mode=sysfs-and-dmesg-only watchdog=untouched"

if [ -n "$DMESG_FILE" ]; then
	[ -r "$DMESG_FILE" ] || fail "dmesg_file_unreadable"
	cat "$DMESG_FILE" > "$DMESG_CAPTURE" 2>/dev/null || fail "dmesg_capture_failed"
else
	dmesg > "$DMESG_CAPTURE" 2>/dev/null || fail "dmesg_capture_failed"
fi

# A failed ID read, an unknown part/revision, or an I2C transport error for
# this controller/client is a stop condition.  Do not retry: a retry would be
# another hardware transaction, and recovery must retain control of the
# watchdog decision.  Capture this before checking binding, so every failure
# marker has the relevant boot log alongside it.
if grep -Eqi "$ERROR_PATTERN" "$DMESG_CAPTURE"; then
	record "dmesg_relevant_errors=present"
	grep -Ei "$ERROR_PATTERN" "$DMESG_CAPTURE" >> "$STATUS_FILE" 2>/dev/null || true
	fail "dmesg_i2c_or_identity_error"
fi
record "dmesg_relevant_errors=absent"

# The DT overlay's precise route is I2C0, 7-bit address 0x6b.  Checking the
# already-created I2C client is metadata-only; it does not issue an I2C
# transfer.  The driver name check also proves that the generic I2C client did
# not bind to an unexpected driver.
i2c_client="$SYSFS_ROOT/bus/i2c/devices/0-006b"
[ -d "$i2c_client" ] || fail "i2c_client_missing"
driver=$(readlink "$i2c_client/driver" 2>/dev/null || true)
case "$driver" in
*/bq25890-charger) ;;
*) fail "unexpected_i2c_driver" ;;
esac
record "i2c_client=0-006b driver=bq25890-charger"

charger=
charger_count=0
for candidate in "$SYSFS_ROOT"/class/power_supply/bq25890-charger-*; do
	[ -d "$candidate" ] || continue
	charger=$candidate
	charger_count=$((charger_count + 1))
done
[ "$charger_count" -eq 1 ] || fail "charger_supply_count=$charger_count"

# A ti,read-only instance exposes exactly the following data-bearing BQ
# properties.  Never read ADC-backed values, REG0C fault state, a fuel-gauge
# power supply, or battery capacity here.
for property in manufacturer model_name status charge_type online; do
	value=$(read_property "$charger/$property") || fail "property_unreadable=$property"
	record "property=$property value=$value"
done

# Do not treat normal live values (online=0, Discharging, Unknown, ...) as a
# failure: the gate is driver identity/binding and safe observability, not the
# presence of external power.  Instead reject a node which unexpectedly grew a
# control/ADC/fault property, as that would show the wrong driver mode.
for property in health constant_charge_current constant_charge_current_max \
	constant_charge_voltage constant_charge_voltage_max precharge_current \
	charge_term_current input_current_limit voltage_now current_now temp; do
	[ ! -e "$charger/$property" ] || fail "unexpected_property=$property"
done
result='result=pass watchdog_lease=unchanged remote_review_required=yes'
record "$result"
printf '%s\n' "$result" > "$PASS_MARKER" 2>/dev/null || true
rm -f "$FAIL_MARKER"
exit 0
