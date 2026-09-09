#!/bin/sh
# Run under the qualification's explicit ALSA/coreutils PATH.
set -eu
work=${GEMINI_HEADSET_WORK:-/run/gemini-audio/headset}
pcm_status=${GEMINI_HEADSET_PCM_STATUS:-/proc/asound/card0/pcm3c/sub0/status}
pmic_registers=${GEMINI_HEADSET_PMIC_REGISTERS:-/sys/kernel/debug/regmap/1000d000.pwrap/registers}
: "${GEMINI_AUDIO_CONTROLS:?missing stable mixer snapshot command}"
test "$(cat "$pcm_status")" = closed
mkdir "$work"
"$GEMINI_AUDIO_CONTROLS" > "$work/controls-before.txt"
alsactl -f "$work/alsa-state" store mt6797mt6351
capture_pid=
cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    if test -n "$capture_pid"; then
        kill -TERM "$capture_pid" 2>/dev/null || :
        wait "$capture_pid" 2>/dev/null || :
    fi
    # Also restore if a signal interrupted the preserving PCM hooks.
    alsactl -P -I -U -f "$work/alsa-state" restore mt6797mt6351 || rc=1
    "$GEMINI_AUDIO_CONTROLS" > "$work/controls-after.txt" || rc=1
    cmp "$work/controls-before.txt" "$work/controls-after.txt" || rc=1
    test "$(cat "$pcm_status")" = closed || rc=1
    if test "$rc" = 0; then
        echo headset-capture=mono-left-route-and-restoration-passed > "$work/result"
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

read_pmic() {
    address=$1
    # The PWRAP regmap uses 16-bit values, stride 2, max register 0xffff:
    # its fixed-width lines are "0d08: 5123\n" (11 bytes). Check the address
    # too, so a changed debugfs layout cannot silently validate other data.
    line=$(dd if="$pmic_registers" bs=11 skip=$((0x$address / 2)) count=1 status=none)
    set -- $line
    test "$#" = 2
    test "$1" = "$address:"
    test "${#2}" = 4
    case "$2" in *[!0-9a-fA-F]*) return 1 ;; esac
    pmic_value=$((0x$2))
    printf '%s\n' "$line" >> "$work/pmic-$phase.txt"
}
phase=before
read_pmic 0d1c
bias_before=$pmic_value
test "$((bias_before & 0x00f5))" = "$((0x00f0))"

timeout --signal=TERM --kill-after=2 8 \
    arecord -q -D gemini_headset_mic -t raw -f S16_LE -r 48000 -c 1 -d 2 /dev/null &
capture_pid=$!
for attempt in $(seq 1 50); do
    if grep -Fq RUNNING "$pcm_status"; then break; fi
    kill -0 "$capture_pid"
    sleep 0.02
done
grep -Fq RUNNING "$pcm_status"
cat "$pcm_status" > "$work/pcm-active.txt"
for control in 'ADC L Mux' 'ADC R Mux' 'PGA L Mux' 'PGA R Mux'; do
    amixer -c mt6797mt6351 cget "name='$control'" >> "$work/controls-active.txt"
done

phase=active
read_pmic 0d08
# Left ADC and PGA on, ADC input left PGA, PGA input AIN1, DCC settled.
test "$((pmic_value & 0x7037))" = "$((0x5023))"
read_pmic 0d0a
# Right ADC/PGA off and both input selectors idle.
test "$((pmic_value & 0x7031))" = 0
read_pmic 0d1a
# Internal and reference microphone bias power bits remain off.
test "$((pmic_value & 0x0101))" = 0
read_pmic 0d1c
# Headset bias on at normal-power 2.7 V with its DCC pull-high switch.
test "$((pmic_value & 0x00f5))" = "$((0x0075))"
grep -Fq RUNNING "$pcm_status"
wait "$capture_pid"
capture_pid=
test "$(cat "$pcm_status")" = closed

phase=after
read_pmic 0d08
test "$((pmic_value & 0x1001))" = 0
read_pmic 0d0a
test "$((pmic_value & 0x1001))" = 0
read_pmic 0d1c
test "$pmic_value" = "$bias_before"
