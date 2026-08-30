#!/bin/sh
set -eu

# Trex-owned observe-always-rollback supervisor. It starts before candidate
# reboot and survives loss of the workstation harness. It never accepts a
# candidate: after the bounded observation window it stages the immutable
# rescue copy and invokes the reviewed Download Only p22 wrapper.
RUN_SHARED=$1
CANDIDATE_STATE=$2
RESCUE_IMAGE=$3
ROLLBACK_SHA=$4
STAGE_IMAGE=$5
XML=$6
FLASH_LOCK=$7
ACCEPTANCE_WINDOW=$8
WRAPPER=$9
ROLLBACK_STATE=${10}
ROLLBACK_LOG=${11}
SUPERVISOR_STATE=${12}
SIZE=16777216
SUPERVISOR_TERMINAL=no

write_state() {
    printf '%s %s\n' "$1" "$(date -Is)" > "$SUPERVISOR_STATE"
    case "$1" in
        supervisor_rollback_succeeded_rescue_verified|supervisor_rollback_failed|supervisor_rollback_unverified|supervisor_rollback_timeout|supervisor_blocked_*|supervisor_candidate_flash_failed)
            SUPERVISOR_TERMINAL=yes ;;
    esac
}

# shellcheck disable=SC2329 # invoked by the EXIT trap below
on_exit() {
    rc=$?
    trap - EXIT
    if [ "$rc" -ne 0 ] && [ "$SUPERVISOR_TERMINAL" != yes ]; then
        write_state supervisor_blocked_unexpected_exit
    fi
    exit "$rc"
}
trap on_exit EXIT

case "$ACCEPTANCE_WINDOW" in
    ''|*[!0-9]*) write_state supervisor_blocked_bad_window; exit 2 ;;
esac
[ "$ACCEPTANCE_WINDOW" -ge 3 ] || { write_state supervisor_blocked_bad_window; exit 2; }
[ "$ACCEPTANCE_WINDOW" -lt 90 ] || { write_state supervisor_blocked_bad_window; exit 2; }
write_state supervisor_waiting_candidate

deadline=$(( $(date +%s) + 300 ))
candidate_failed=no
while [ "$(date +%s)" -lt "$deadline" ]; do
    state=$(cat "$CANDIDATE_STATE" 2>/dev/null || true)
    case "$state" in
        'flash_rc=0 '*) break ;;
        flash_rc=*) candidate_failed=yes; break ;;
    esac
    sleep 1
done
case "$(cat "$CANDIDATE_STATE" 2>/dev/null || true)" in
    'flash_rc=0 '*) ;;
    flash_rc=*) candidate_failed=yes ;;
    *)
        # A missing completion state after the bounded wrapper lifetime is
        # ambiguous (the write may have been partial). Treat it as unsafe and
        # enter the same exact rescue path rather than abandoning ownership.
        candidate_failed=yes ;;
esac

# Give the candidate its complete acceptance window. The harness collects
# evidence concurrently; no acceptance marker is ever consulted or written.
if [ "$candidate_failed" = no ]; then
    window_end=$(( $(date +%s) + ACCEPTANCE_WINDOW ))
    while [ "$(date +%s)" -lt "$window_end" ]; do
        sleep 1
    done
else
    # A failed/partial candidate transaction is still unsafe to boot. Roll
    # back immediately after the post-flash reboot dispatch; do not abandon
    # ownership merely because candidate Flash Tool returned nonzero.
    :
fi

test "$(stat -Lc %s "$RESCUE_IMAGE")" -eq "$SIZE"
test "$(sha256sum "$RESCUE_IMAGE" | cut -d' ' -f1)" = "$ROLLBACK_SHA"
cp "$RESCUE_IMAGE" "$STAGE_IMAGE"
test "$(stat -Lc %s "$STAGE_IMAGE")" -eq "$SIZE"
test "$(sha256sum "$STAGE_IMAGE" | cut -d' ' -f1)" = "$ROLLBACK_SHA"
write_state supervisor_rollback_armed

rm -f "$ROLLBACK_STATE"
pid_file=$RUN_SHARED/supervisor-rollback.pid
pgid_file=$RUN_SHARED/supervisor-rollback.pgid
sid_file=$RUN_SHARED/supervisor-rollback.sid
setsid sh "$WRAPPER" "$ROLLBACK_STATE" "$ROLLBACK_LOG" "$XML" \
    "$pid_file" "$pgid_file" "$FLASH_LOCK" "$RUN_SHARED/transaction-owner" "$sid_file" \
    </dev/null >/dev/null 2>&1 &
launch_pid=$!
deadline=$(( $(date +%s) + 300 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    state=$(cat "$ROLLBACK_STATE" 2>/dev/null || true)
    case "$state" in
        'flash_rc=0 '*)
            # Trex has no Gemini SSH credential. This terminal state proves
            # the exact rescue bytes were staged and the p22-only wrapper
            # returned success; the live harness must perform device-side
            # p22/p30/p31 readback when connectivity is available.
            test "$(sha256sum "$STAGE_IMAGE" | cut -d' ' -f1)" = "$ROLLBACK_SHA"
            write_state supervisor_rollback_succeeded_rescue_verified
            exit 0 ;;
        flash_rc=*) write_state supervisor_rollback_failed; exit 1 ;;
    esac
    sleep 1
done

# The wrapper owns a private session and publishes its exact pgid. Kill only
# that exact group on timeout; never use a broad process-name kill.
pid=$(cat "$pid_file" 2>/dev/null || true)
pgid=$(cat "$pgid_file" 2>/dev/null || true)
sid=$(cat "$sid_file" 2>/dev/null || true)
if [ "$pid" = "$launch_pid" ] && [ "$sid" = "$pid" ] && [ "$pid" -gt 1 ]; then
    if [ "$pgid" = "$pid" ]; then
        kill -KILL "-$pgid" 2>/dev/null || true
    else
        ps -eo pid=,sid= | awk -v sid="$sid" -v self="$pid" '$2 == sid && $1 != self {print $1}' |
            while read -r child; do kill -KILL "$child" 2>/dev/null || true; done
        kill -KILL "$pid" 2>/dev/null || true
    fi
fi
write_state supervisor_rollback_timeout
exit 1
