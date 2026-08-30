#!/bin/sh
set -u

# Runs on trex. The caller must have staged the exact p22 image as boot.img and
# independently checked the boot-only XML/scatter before starting this wrapper.
STATE=$1
LOG=$2
XML=$3
TOOL=/nix/store/wlgln84hg9k6hnqdm6r24vn21fxf85b7-mtk-flash-tool-2018-04-07/opt/mtk-flash-tool/flash_tool
STATE_DIR=${STATE%/*}

# The wrapper is launched in its own session by the harness.  Publish both
# identifiers before starting the bounded tool so an interrupted harness can
# terminate the whole flash process group, not just this shell.  The equality
# check is repeated by the harness before it ever sends a negative-PID signal.
printf '%s\n' "$$" > "$STATE_DIR/tool.pid"
pgid=$(ps -o pgid= -p "$$" | tr -d ' ')
case "$pgid" in
    ''|*[!0-9]*) pgid=unknown ;;
esac
printf '%s\n' "$pgid" > "$STATE_DIR/tool.pgid"

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
