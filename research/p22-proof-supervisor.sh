#!/bin/sh
set -eu

# Trex-owned rollback supervisor. It starts before candidate reboot and
# survives loss of the workstation harness. Ordinary proof runs always roll
# back. A baseline self-accept run may terminate without another writer only
# after the host publishes the exact candidate-SHA record and the already
# running bounded BROM scan finishes normally without finding preloader.
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
LEASE_SECONDS=${13:-90}
SELF_ACCEPT_STATE=${14:-}
CANDIDATE_SHA=${15:-}
SIZE=16777216
SUPERVISOR_TERMINAL=no
ROLLBACK_WAIT_SECONDS=${16:-${P22_SUPERVISOR_ROLLBACK_TIMEOUT:-300}}
CANDIDATE_WAIT_SECONDS=${17:-300}
# The candidate flash completes while the device is still leaving the
# preloader session used for the write.  Give that first boot a short,
# measured grace period, then keep an exact rescue writer scanning throughout
# the observation window.  On Gemini the first post-flash preloader is gone
# within about ten seconds and the earliest failed-kernel watchdog return is
# about thirty seconds after that, so fifteen seconds separates the two.
ROLLBACK_ARM_DELAY_SECONDS=${P22_SUPERVISOR_ARM_DELAY:-15}

write_state() {
    printf '%s %s\n' "$1" "$(date -Is)" > "$SUPERVISOR_STATE"
    case "$1" in
        supervisor_candidate_self_accepted|supervisor_rollback_succeeded_rescue_verified|supervisor_rollback_failed|supervisor_rollback_unverified|supervisor_rollback_timeout|supervisor_blocked_*|supervisor_candidate_flash_failed)
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
case "$LEASE_SECONDS" in
    ''|*[!0-9]*) write_state supervisor_blocked_bad_lease; exit 2 ;;
esac
[ "$LEASE_SECONDS" -ge 3 ] || { write_state supervisor_blocked_bad_lease; exit 2; }
case "$ROLLBACK_ARM_DELAY_SECONDS" in
    ''|*[!0-9]*) write_state supervisor_blocked_bad_arm_delay; exit 2 ;;
esac
case "$ROLLBACK_WAIT_SECONDS" in
    ''|*[!0-9]*) write_state supervisor_blocked_bad_rollback_wait; exit 2 ;;
esac
[ "$ROLLBACK_WAIT_SECONDS" -ge 1 ] || { write_state supervisor_blocked_bad_rollback_wait; exit 2; }
case "$CANDIDATE_WAIT_SECONDS" in
    ''|*[!0-9]*) write_state supervisor_blocked_bad_candidate_wait; exit 2 ;;
esac
[ "$CANDIDATE_WAIT_SECONDS" -ge 1 ] || { write_state supervisor_blocked_bad_candidate_wait; exit 2; }
[ "$ACCEPTANCE_WINDOW" -lt "$LEASE_SECONDS" ] || { write_state supervisor_blocked_bad_window; exit 2; }
if [ -n "$SELF_ACCEPT_STATE$CANDIDATE_SHA" ]; then
    [ "$SELF_ACCEPT_STATE" = "$RUN_SHARED/candidate-self-accepted" ] || {
        write_state supervisor_blocked_bad_self_accept_path
        exit 2
    }
    case "$CANDIDATE_SHA" in
        *[!0-9a-f]*|'') write_state supervisor_blocked_bad_candidate_sha; exit 2 ;;
    esac
    [ "${#CANDIDATE_SHA}" -eq 64 ] || {
        write_state supervisor_blocked_bad_candidate_sha
        exit 2
    }
fi
write_state supervisor_waiting_candidate

candidate_self_accepted() {
    [ -n "$SELF_ACCEPT_STATE" ] || return 1
    [ -f "$SELF_ACCEPT_STATE" ] || return 1
    [ ! -L "$SELF_ACCEPT_STATE" ] || return 1
    [ "$(stat -Lc %h "$SELF_ACCEPT_STATE" 2>/dev/null || true)" = 1 ] || return 1
    [ "$(cat "$SELF_ACCEPT_STATE" 2>/dev/null || true)" = \
        "candidate_self_accepted sha256=$CANDIDATE_SHA" ]
}

deadline=$(( $(date +%s) + CANDIDATE_WAIT_SECONDS ))
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

# A successful candidate gets its complete acceptance window, but the rescue
# scanner must already be alive when an early watchdog reset exposes
# preloader.  Waiting out the acceptance window before launching Flash Tool
# loses precisely that recovery window and can strand a repeatedly failing
# candidate once the boot firmware stops retrying it.
if [ "$candidate_failed" = no ]; then
    rollback_deadline=$(( $(date +%s) + ACCEPTANCE_WINDOW + ROLLBACK_WAIT_SECONDS ))
    arm_at=$(( $(date +%s) + ROLLBACK_ARM_DELAY_SECONDS ))
    while [ "$(date +%s)" -lt "$arm_at" ]; do
        sleep 1
    done
else
    # A failed/partial candidate transaction is still unsafe to boot. Roll
    # back at the first available preloader; do not abandon ownership merely
    # because candidate Flash Tool returned nonzero.
    rollback_deadline=$(( $(date +%s) + ROLLBACK_WAIT_SECONDS ))
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
starttime_file=$RUN_SHARED/supervisor-rollback.starttime
deadline=$rollback_deadline
rollback_attempt=1
while [ "$(date +%s)" -lt "$deadline" ]; do
    if candidate_self_accepted; then
        write_state supervisor_candidate_self_accepted
        exit 0
    fi
    rm -f "$ROLLBACK_STATE"
    setsid sh "$WRAPPER" "$ROLLBACK_STATE" "$ROLLBACK_LOG" "$XML" \
        "$pid_file" "$pgid_file" "$FLASH_LOCK" "$RUN_SHARED/transaction-owner" "$sid_file" \
        "$starttime_file" \
        </dev/null >/dev/null 2>&1 &
    launch_pid=$!
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
            'flash_rc=1 '*) break ;;
            flash_rc=*) write_state supervisor_rollback_failed; exit 1 ;;
        esac
        sleep 1
    done
    state=$(cat "$ROLLBACK_STATE" 2>/dev/null || true)
    if printf '%s\n' "$state" | grep -Fq 'flash_rc=1 '; then
        # A healthy self-accepted candidate keeps its USB gadget online, so
        # the in-flight BROM scan ends with the ordinary bounded timeout.
        # Observe the exact candidate-SHA commit only at this quiescent point:
        # never interrupt a scanner that might already own preloader/DA.
        if candidate_self_accepted; then
            wait "$launch_pid" 2>/dev/null || true
            write_state supervisor_candidate_self_accepted
            exit 0
        fi
        # Flash Tool's own BROM scan is 120 seconds. Reap each missed scan and
        # immediately reopen the same exact p22-only rescue transaction. This
        # keeps coverage continuous from the first possible failed-kernel
        # reset through the watchdog lease-expiry proof, under one absolute
        # deadline and the same global writer lock.
        wait "$launch_pid" 2>/dev/null || true
        printf '[%s] rollback attempt %s missed/failed rc=1; retrying exact p22 within deadline\n' \
            "$(date -Is)" "$rollback_attempt" >> "$ROLLBACK_LOG"
        rollback_attempt=$((rollback_attempt + 1))
        continue
    fi
    break
done

case "$(cat "$ROLLBACK_STATE" 2>/dev/null || true)" in
    flash_rc=*) write_state supervisor_rollback_failed; exit 1 ;;
esac

# The wrapper owns a private session and publishes its exact pgid. Kill only
# that exact group on timeout; never use a broad process-name kill.
pid=$(cat "$pid_file" 2>/dev/null || true)
pgid=$(cat "$pgid_file" 2>/dev/null || true)
sid=$(cat "$sid_file" 2>/dev/null || true)
starttime=$(cat "$starttime_file" 2>/dev/null || true)
for value in "$pid" "$pgid" "$sid" "$starttime"; do
    case "$value" in ''|*[!0-9]*) write_state supervisor_rollback_timeout; exit 1 ;; esac
done
# Never signal a stale/recycled supervisor session. The unique run XML must
# be present in a live member's argv, and every member's SID/PGID/starttime is
# snapshotted and revalidated immediately before KILL.
owner_pid=
if [ "$sid" = "$pid" ] && [ "$pid" -gt 1 ] && [ "$pgid" -gt 1 ]; then
    if test -d "/proc/$pid" &&
       test "$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null)" = "$starttime" &&
       test "$(ps -o sid= -p "$pid" | tr -d ' ')" = "$sid" &&
       test "$(ps -o pgid= -p "$pid" | tr -d ' ')" = "$pgid" &&
       ps -o args= -p "$pid" | grep -F -- "$XML" >/dev/null; then
        owner_pid=$pid
    else
        candidate_owner=$(ps -eo pid=,sid=,pgid=,args= | awk -v sid="$sid" -v pgid="$pgid" -v xml="$XML" '$2 == sid && $3 == pgid && index($0, xml) {print $1; exit}')
        if [ -n "$candidate_owner" ] &&
           test "$(awk '{print $22}' "/proc/$candidate_owner/stat" 2>/dev/null)" = "$starttime"; then
            owner_pid=$candidate_owner
        fi
    fi
fi
if [ -n "$owner_pid" ]; then
    # Re-prove ownership after selecting the member and immediately before
    # snapshotting; owner_pid alone is not a signal authorization.
    ps -eo pid=,sid=,pgid=,args= | awk -v owner="$owner_pid" -v sid="$sid" -v pgid="$pgid" -v xml="$XML" '$1 == owner && $2 == sid && $3 == pgid && index($0, xml) {found=1} END {exit(found ? 0 : 1)}' || owner_pid=
fi
if [ -n "$owner_pid" ]; then
    snapshot=$RUN_SHARED/supervisor-rollback.snapshot
    ps -eo pid=,sid=,pgid= | awk -v sid="$sid" '$2 == sid {print $1, $2, $3}' |
        while read -r member msid mpgid; do
            mstart=$(awk '{print $22}' "/proc/$member/stat" 2>/dev/null || true)
            case "$member:$mstart" in *[!0-9:]*|:*) exit 1 ;; esac
            printf '%s %s %s %s\n' "$member" "$msid" "$mpgid" "$mstart"
        done > "$snapshot" || true
    valid=yes
    while read -r member msid mpgid mstart; do
        test -n "$member" || continue
        test -d "/proc/$member" || valid=no
        test "$(awk '{print $22}' "/proc/$member/stat" 2>/dev/null)" = "$mstart" || valid=no
        test "$(ps -o sid= -p "$member" | tr -d ' ')" = "$msid" || valid=no
        test "$(ps -o pgid= -p "$member" | tr -d ' ')" = "$mpgid" || valid=no
    done < "$snapshot"
    if [ "$valid" = yes ]; then
        while read -r member msid mpgid mstart; do
            test -n "$member" || continue
            test -d "/proc/$member" || continue
            test "$(awk '{print $22}' "/proc/$member/stat" 2>/dev/null)" = "$mstart" || continue
            test "$(ps -o sid= -p "$member" | tr -d ' ')" = "$msid" || continue
            test "$(ps -o pgid= -p "$member" | tr -d ' ')" = "$mpgid" || continue
            kill -KILL "$member" 2>/dev/null || true
        done < "$snapshot"
    fi
    rm -f "$snapshot"
fi
write_state supervisor_rollback_timeout
exit 1
