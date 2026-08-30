#!/bin/sh
set -u

# Runs on trex. The caller must have staged the exact p22 image as boot.img and
# independently checked the boot-only XML/scatter before starting this wrapper.
STATE=$1
LOG=$2
XML=$3
PID_FILE=${4:-${STATE%/*}/tool.pid}
PGID_FILE=${5:-${STATE%/*}/tool.pgid}
LOCK_FILE=${6:-${STATE%/*}/flash.lock}
TRANSACTION_OWNER_FILE=${7:-}
TOOL=/nix/store/wlgln84hg9k6hnqdm6r24vn21fxf85b7-mtk-flash-tool-2018-04-07/opt/mtk-flash-tool/flash_tool
STATE_DIR=${STATE%/*}

if [ -n "$TRANSACTION_OWNER_FILE" ] && ! test -s "$TRANSACTION_OWNER_FILE"; then
    printf 'flash_rc=76 %s\n' "$(date -Is)" > "$STATE"
    printf '[%s] transaction owner is not present; refusing writer\n' "$(date -Is)" >> "$LOG"
    exit 76
fi
if [ -n "$TRANSACTION_OWNER_FILE" ]; then
    owner_pid=$(sed -n 's/.* pid=\([0-9][0-9]*\) .*/\1/p' "$TRANSACTION_OWNER_FILE")
    case "$owner_pid" in
        ''|*[!0-9]*) owner_pid=invalid ;;
    esac
    if [ "$owner_pid" = invalid ] || [ "$owner_pid" -le 1 ] ||
       ! test -d "/proc/$owner_pid" ||
       ! ps -o args= -p "$owner_pid" | grep -F -- 'p22-trex-transaction-holder.sh' >/dev/null; then
        printf 'flash_rc=76 %s\n' "$(date -Is)" > "$STATE"
        printf '[%s] transaction owner is stale; refusing writer\n' "$(date -Is)" >> "$LOG"
        exit 76
    fi
fi

# The lock covers the entire timeout/sudo/Flash Tool lifetime and rejects
# duplicate writers even when harnesses were started concurrently.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    printf 'flash_rc=75 %s\n' "$(date -Is)" > "$STATE"
    printf '[%s] Flash Tool lock busy; refusing duplicate writer\n' "$(date -Is)" >> "$LOG"
    exit 75
fi

# The wrapper is launched in its own session by the harness.  Publish both
# identifiers before starting the bounded tool so an interrupted harness can
# terminate the whole flash process group, not just this shell.  The equality
# check is repeated by the harness before it ever sends a negative-PID signal.
printf '%s\n' "$$" > "$PID_FILE"
pgid=$(ps -o pgid= -p "$$" | tr -d ' ')
case "$pgid" in
    ''|*[!0-9]*) pgid=unknown ;;
esac
printf '%s\n' "$pgid" > "$PGID_FILE"

printf 'tool_started %s\n' "$(date -Is)" > "$STATE"
{
    printf '[%s] wrapper_pid=%s wrapper_pgid=%s\n' "$(date -Is)" "$$" "$pgid"
    printf '[%s] exact p22 Download Only wrapper started\n' "$(date -Is)"
} >> "$LOG"
# Keep this above the harness's 250-second state wait so timeout completion
# cannot race the final poll; the tool's own BROM wait remains bounded.
timeout 240 sudo -n "$TOOL" -i "$XML" -r >> "$LOG" 2>&1
rc=$?
printf 'flash_rc=%s %s\n' "$rc" "$(date -Is)" > "$STATE"
printf '[%s] Flash Tool exited rc=%s\n' "$(date -Is)" "$rc" >> "$LOG"
exit "$rc"
