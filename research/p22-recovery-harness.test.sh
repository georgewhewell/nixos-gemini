#!/bin/sh
set -eu

# Host-only regressions for the bounded transaction.  These tests deliberately
# replace ssh; they never contact trex or the Gemini and never invoke a writer.
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
HARNESS=$ROOT/research/p22-recovery-harness.sh
RUNNER=$ROOT/research/p22-chained-recovery-runner.sh
WRAPPER=$ROOT/research/p22-flash-wrapper.sh
MANIFEST=$ROOT/research/p22-unattended-recovery-watchdog-hostnet-v2.manifest
TEST_ROOT=$(mktemp -d /mnt/Home/src/p22-recovery-harness-test.XXXXXX)
trap 'rm -rf "$TEST_ROOT"' EXIT INT TERM

test_ssh_timeout() {
    test_bin=$TEST_ROOT/hanging-bin
    mkdir -p "$test_bin"
    cat > "$test_bin/ssh" <<'EOF'
#!/bin/sh
sleep 60
EOF
    chmod +x "$test_bin/ssh"
    start=$(date +%s)
    set +e
    PATH="$test_bin:$PATH" "$HARNESS" --manifest "$MANIFEST" --dry-run \
        > "$TEST_ROOT/hang.log" 2>&1
    rc=$?
    set -e
    elapsed=$(( $(date +%s) - start ))
    test "$rc" -ne 0
    # The harness-level timeout is 15 seconds; allow modest scheduler slack,
    # while proving an SSH child cannot strand the transaction indefinitely.
    test "$elapsed" -lt 22
}

test_duplicate_flash_tool_rejected() {
    test_bin=$TEST_ROOT/duplicate-bin
    mkdir -p "$test_bin"
    cat > "$test_bin/ssh" <<'EOF'
#!/bin/sh
    # Simulate the remote ps/awk check finding an existing owner.
    exit 1
EOF
    chmod +x "$test_bin/ssh"
    set +e
    PATH="$test_bin:$PATH" "$RUNNER" --manifest "$MANIFEST" --dry-run \
        > "$TEST_ROOT/duplicate.log" 2>&1
    rc=$?
    set -e
    test "$rc" -ne 0
    grep -Fq 'phase=normal-before-proof begin' "$TEST_ROOT/duplicate.log"
}

test_post_marker_failure_does_not_recover() {
    # Exercise the actual finalization function with a fake SSH failure.  The
    # acceptance marker is already committed, so the state machine must keep
    # the candidate accepted and must not invoke recover().
    sed -n '/^finalize_accepted_candidate() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/finalize-function.sh"
    RUN_LOCAL=$TEST_ROOT/finalize-run
    mkdir -p "$RUN_LOCAL"
    # shellcheck disable=SC1090,SC1091
    . "$TEST_ROOT/finalize-function.sh"
    device_ssh() { return 1; }
    recover() { : > "$TEST_ROOT/recover-called"; return 1; }
    # shellcheck disable=SC2034
    ACCEPTANCE_COMMITTED=yes
    # shellcheck disable=SC2034
    CANDIDATE_SHA=unused
    if finalize_accepted_candidate; then
        :
    else
        recover
    fi
    test "$(cat "$RUN_LOCAL/final-record-status")" = 'post-marker-final-record rc=1'
    grep -Fq 'accepted_p22 ' "$RUN_LOCAL/state"
    test ! -e "$TEST_ROOT/recover-called"
}

test_stale_attempt_state_not_reused() {
    sed -n '/^wait_state() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/wait-state-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/wait-state-function.sh"
    trex_ssh() {
        state_path=$(printf '%s\n' "$1" | sed "s/^cat '//; s/'$//")
        cat "$state_path"
    }
    stale=$TEST_ROOT/stale.state
    fresh=$TEST_ROOT/fresh.state
    printf '%s\n' 'flash_rc=0 old-attempt' > "$stale"
    printf '%s\n' 'tool_started new-attempt' > "$fresh"
    set +e
    wait_state "$stale" flash_rc 1
    stale_rc=$?
    set -e
    test "$stale_rc" -eq 0
    set +e
    wait_state "$stale" tool_started 1
    stale_tool_rc=$?
    set -e
    test "$stale_tool_rc" -ne 0
    (sleep 1; printf '%s\n' 'flash_rc=0 new-attempt' > "$fresh") &
    wait_state "$fresh" flash_rc 3
    test "$stale" != "$fresh"
}

test_observe_policy_disables_persistent_execute() {
    set +e
    "$HARNESS" --manifest \
        "$ROOT/research/p22-unattended-recovery-power-preflight-v1.manifest" \
        --execute > "$TEST_ROOT/observe-policy.log" 2>&1
    rc=$?
    set -e
    test "$rc" -eq 2
    grep -Fq 'observe-always-rollback requires --proof-lease' \
        "$TEST_ROOT/observe-policy.log"
}

test_wrapper_uses_per_attempt_pid_files() {
    test_bin=$TEST_ROOT/wrapper-bin
    mkdir -p "$test_bin"
    cat > "$test_bin/timeout" <<'EOF'
#!/bin/sh
exit 0
EOF
    chmod +x "$test_bin/timeout"
    state=$TEST_ROOT/wrapper.state
    pid_file=$TEST_ROOT/attempt.pid
    pgid_file=$TEST_ROOT/attempt.pgid
    PATH="$test_bin:$PATH" "$WRAPPER" "$state" "$TEST_ROOT/wrapper.log" \
        unused.xml "$pid_file" "$pgid_file"
    test "$(cat "$state" | cut -d= -f1)" = flash_rc
    test "$(cat "$pid_file")" -gt 1
    test "$(cat "$pgid_file")" -gt 1
    test -s "$TEST_ROOT/wrapper.log"
}

test_wrapper_lock_rejects_duplicate() {
    test_bin=$TEST_ROOT/lock-bin
    mkdir -p "$test_bin"
    cat > "$test_bin/timeout" <<'EOF'
#!/bin/sh
sleep 2
EOF
    chmod +x "$test_bin/timeout"
    lock=$TEST_ROOT/shared.lock
    mkdir "$TEST_ROOT/attempt-one" "$TEST_ROOT/attempt-two"
    first_state=$TEST_ROOT/attempt-one/first.state
    second_state=$TEST_ROOT/attempt-two/second.state
    PATH="$test_bin:$PATH" "$WRAPPER" "$first_state" "$TEST_ROOT/first.log" \
        unused.xml "$TEST_ROOT/first.pid" "$TEST_ROOT/first.pgid" "$lock" &
    first_pid=$!
    sleep 1
    set +e
    PATH="$test_bin:$PATH" "$WRAPPER" "$second_state" "$TEST_ROOT/second.log" \
        unused.xml "$TEST_ROOT/second.pid" "$TEST_ROOT/second.pgid" "$lock"
    second_rc=$?
    set -e
    wait "$first_pid"
    test "$second_rc" -eq 75
    grep -Fq 'flash_rc=75' "$second_state"
}

test_wrapper_foreground_process_tree() {
    test_bin=$TEST_ROOT/foreground-bin
    mkdir -p "$test_bin"
    printf '%s\n' '#!/bin/sh' 'test "$1" = --foreground' 'shift 2' 'exec "$@"' > "$test_bin/timeout"
    printf '%s\n' '#!/bin/sh' 'printf "%s\\n" "$$" > "$CHILD_PID_FILE"' 'sleep 60' > "$test_bin/sudo"
    chmod +x "$test_bin/timeout" "$test_bin/sudo"
    state=$TEST_ROOT/foreground.state
    CHILD_PID_FILE=$TEST_ROOT/foreground-child.pid \
        PATH="$test_bin:$PATH" setsid sh "$WRAPPER" "$state" \
        "$TEST_ROOT/foreground.log" unused.xml "$TEST_ROOT/foreground.pid" \
        "$TEST_ROOT/foreground.pgid" "$TEST_ROOT/foreground.lock" \
        '' "$TEST_ROOT/foreground.sid" &
    wrapper_launcher=$!
    sleep 1
    wrapper_pid=$(cat "$TEST_ROOT/foreground.pid")
    child_pid=$(cat "$TEST_ROOT/foreground-child.pid")
    test "$wrapper_pid" = "$(cat "$TEST_ROOT/foreground.pgid")"
    test "$wrapper_pid" = "$(cat "$TEST_ROOT/foreground.sid")"
    test "$wrapper_pid" = "$(ps -o pgid= -p "$child_pid" | tr -d ' ')"
    test "$wrapper_pid" = "$(ps -o sid= -p "$child_pid" | tr -d ' ')"
    kill -KILL "-$wrapper_pid"
    set +e
    wait "$wrapper_launcher"
    set -e
    child_gone=no
    child_wait=0
    while [ "$child_wait" -lt 2 ]; do
        if ! ps -p "$child_pid" -o stat= 2>/dev/null | grep -qv '^Z'; then
            child_gone=yes
            break
        fi
        sleep 1
        child_wait=$((child_wait + 1))
    done
    test "$child_gone" = yes
}

test_sourced_stop_tool_kills_exact_session_after_leader_exit() {
    sed -n '/^stop_tool() {/,/^cleanup() {/p' "$HARNESS" | sed '$d' > "$TEST_ROOT/stop-tool-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/stop-tool-function.sh"
    test_bin=$TEST_ROOT/stop-bin
    mkdir -p "$test_bin"
    printf '%s\n' '#!/bin/sh' 'test "$1" = --foreground' 'shift 2' 'exec "$@"' > "$test_bin/timeout"
    printf '%s\n' '#!/bin/sh' 'exec "$CHILD" "$XML_PATH"' > "$test_bin/sudo"
    printf '%s\n' '#!/bin/sh' 'sleep 60' > "$test_bin/child"
    chmod +x "$test_bin/timeout" "$test_bin/sudo" "$test_bin/child"
    run=$TEST_ROOT/stop-run
    mkdir -p "$run"
    STATE=$run/state
    TOOL_PID_FILE=$run/pid
    TOOL_PGID_FILE=$run/pgid
    TOOL_SID_FILE=$run/sid
    TOOL_STARTTIME_FILE=$run/starttime
    TOOL_LAUNCH_PID_FILE=$run/launch
    TOOL_LOCK_FILE=$run/lock
    RUN_SHARED=$run
    XML=stop-tool-exact.xml
    XML_RUN_FILE=$run/stop-tool-exact.xml
    : > "$XML_RUN_FILE"
    trex_ssh() { sh -c "$1"; }
    printf '%s\n' 'tool_started now' > "$STATE"
    CHILD="$test_bin/child" XML_PATH="$XML_RUN_FILE" PATH="$test_bin:$PATH" setsid sh "$WRAPPER" "$STATE" "$run/log" "$XML" \
        "$TOOL_PID_FILE" "$TOOL_PGID_FILE" "$TOOL_LOCK_FILE" '' \
        "$TOOL_SID_FILE" "$TOOL_STARTTIME_FILE" >/dev/null 2>&1 &
    launch=$!
    printf '%s\n' "$launch" > "$TOOL_LAUNCH_PID_FILE"
    sleep 1
    wrapper_pid=$(cat "$TOOL_PID_FILE")
    child_pid=$(pgrep -P "$wrapper_pid" | head -n 1)
    setsid "$test_bin/child" "$XML_RUN_FILE" & foreign_pid=$!
    recorded_start=$(cat "$TOOL_STARTTIME_FILE")
    printf '%s\n' 1 > "$TOOL_STARTTIME_FILE"
    stop_tool
    kill -0 "$child_pid" 2>/dev/null
    kill -0 "$foreign_pid" 2>/dev/null
    printf '%s\n' "$recorded_start" > "$TOOL_STARTTIME_FILE"
    # Simulate the observed leader-loss case; the session child retains the
    # exact XML token that stop_tool uses as its ownership proof.
    kill -TERM "$wrapper_pid"
    stop_tool
    set +e
    wait "$launch" 2>/dev/null
    set -e
    ! ps -p "$child_pid" -o stat= 2>/dev/null | grep -qv '^Z'
    kill -0 "$foreign_pid" 2>/dev/null
    kill -KILL "-$foreign_pid" 2>/dev/null || kill -KILL "$foreign_pid" 2>/dev/null || true
}

test_stop_capture_does_not_trust_stale_diagnostic_pid() {
    sed -n '/^stop_capture() {/,/^cleanup() {/p' "$HARNESS" | sed '$d' > "$TEST_ROOT/stop-capture-stale.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/stop-capture-stale.sh"
    cleanup_stage2_store_temp() { :; }
    run=$TEST_ROOT/stale-diagnostic
    mkdir -p "$run"
    stale_pid_file=$run/kernel.pid
    sleep 60 & stale_pid=$!
    printf '%s\n' "$stale_pid" > "$stale_pid_file"
    RUN_SHARED=$run
    TRANSACTION_UNIT=
    SUPERVISOR_UNIT=
    SUPERVISOR_KEEP=no
    trex_ssh() { sh -c "$1"; }
    stop_capture
    kill -0 "$stale_pid" 2>/dev/null
    kill -KILL "$stale_pid" 2>/dev/null || true
}

test_xml_is_attempt_unique_for_writer_and_supervisor() {
    grep -Fq 'XML_RUN_FILE=$RUN_SHARED/download-only-p22.xml' "$HARNESS"
    grep -Fq '$XML_RUN_FILE' "$HARNESS"
    grep -Fq 'starttime_file=$RUN_SHARED/supervisor-rollback.starttime' \
        "$ROOT/research/p22-proof-supervisor.sh"
}

test_supervisor_fake_rollback() {
    run=$TEST_ROOT/supervisor
    mkdir -p "$run"
    rescue=$run/rescue.img
    stage=$run/boot.img
    truncate -s 16777216 "$rescue"
    rollback_sha=$(sha256sum "$rescue" | cut -d' ' -f1)
    printf '%s\n' 'flash_rc=0 candidate' > "$run/candidate.state"
    fake_wrapper=$run/fake-wrapper
    cat > "$fake_wrapper" <<'EOF'
#!/bin/sh
printf 'flash_rc=0 fake\n' > "$1"
EOF
    chmod +x "$fake_wrapper"
    fake_bin=$run/bin
    mkdir "$fake_bin"
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$fake_bin/ssh"
    printf '%s\n' '#!/bin/sh' 'printf "1: usb0: <BROADCAST> mtu 1500 state UP group default qlen 1000\\n    link/ether 42:00:15:19:82:00 brd ff:ff:ff:ff:ff:ff\\n"' > "$fake_bin/ip"
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$fake_bin/lsusb"
    chmod +x "$fake_bin/ssh" "$fake_bin/ip" "$fake_bin/lsusb"
    PATH="$fake_bin:$PATH" timeout 20 "$ROOT/research/p22-proof-supervisor.sh" \
        "$run" "$run/candidate.state" "$rescue" "$rollback_sha" "$stage" \
        "$run/download.xml" "$run/global.lock" 3 "$fake_wrapper" \
        "$run/rollback.state" "$run/rollback.log" "$run/supervisor.state"
    grep -Fq 'supervisor_rollback_succeeded_rescue_verified ' "$run/supervisor.state"
    test "$(sha256sum "$stage" | cut -d' ' -f1)" = "$rollback_sha"
}

test_supervisor_rolls_back_failed_candidate() {
    run=$TEST_ROOT/supervisor-failed
    mkdir -p "$run/bin"
    rescue=$run/rescue.img
    stage=$run/boot.img
    truncate -s 16777216 "$rescue"
    rollback_sha=$(sha256sum "$rescue" | cut -d' ' -f1)
    printf '%s\n' 'flash_rc=1 candidate-partial' > "$run/candidate.state"
    fake_wrapper=$run/fake-wrapper
    # shellcheck disable=SC2016 # fake script must expand $1 when it runs
    printf '%s\n' '#!/bin/sh' 'printf "flash_rc=0 fake\\n" > "$1"' > "$fake_wrapper"
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$run/bin/ssh"
    printf '%s\n' '#!/bin/sh' 'printf "link/ether 42:00:15:19:82:00\\n"' > "$run/bin/ip"
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$run/bin/lsusb"
    chmod +x "$fake_wrapper" "$run/bin/ssh" "$run/bin/ip" "$run/bin/lsusb"
    PATH="$run/bin:$PATH" timeout 20 "$ROOT/research/p22-proof-supervisor.sh" \
        "$run" "$run/candidate.state" "$rescue" "$rollback_sha" "$stage" \
        "$run/download.xml" "$run/global.lock" 3 "$fake_wrapper" \
        "$run/rollback.state" "$run/rollback.log" "$run/supervisor.state"
    grep -Fq 'supervisor_rollback_succeeded_rescue_verified ' "$run/supervisor.state"
}

test_supervisor_records_unexpected_exit() {
    run=$TEST_ROOT/supervisor-unexpected
    mkdir -p "$run"
    rescue=$run/rescue.img
    truncate -s 16777216 "$rescue"
    printf '%s\n' 'flash_rc=0 candidate' > "$run/candidate.state"
    set +e
    timeout 20 "$ROOT/research/p22-proof-supervisor.sh" \
        "$run" "$run/candidate.state" "$rescue" \
        0000000000000000000000000000000000000000000000000000000000000000 \
        "$run/boot.img" "$run/download.xml" "$run/global.lock" 3 \
        "$run/missing-wrapper" "$run/rollback.state" "$run/rollback.log" \
        "$run/supervisor.state"
    rc=$?
    set -e
    test "$rc" -ne 0
    grep -Fq 'supervisor_blocked_unexpected_exit ' "$run/supervisor.state"
}

test_supervisor_timeout_kills_only_owned_session() {
    run=$TEST_ROOT/supervisor-timeout
    mkdir -p "$run"
    rescue=$run/rescue.img
    stage=$run/boot.img
    truncate -s 16777216 "$rescue"
    rollback_sha=$(sha256sum "$rescue" | cut -d' ' -f1)
    printf '%s\n' 'flash_rc=0 candidate' > "$run/candidate.state"
    fake_wrapper=$run/fake-wrapper
    cat > "$fake_wrapper" <<'EOF'
#!/bin/sh
printf '%s\n' "$$" > "$4"
ps -o pgid= -p "$$" | tr -d ' ' > "$5"
ps -o sid= -p "$$" | tr -d ' ' > "$8"
awk '{print $22}' "/proc/$$/stat" > "$9"
printf 'tool_started fake\n' > "$1"
while :; do sleep 60; done
EOF
    chmod +x "$fake_wrapper"
    setsid sh -c 'while :; do sleep 60; done' sh "$run/download.xml" &
    foreign_pid=$!
    set +e
    P22_SUPERVISOR_ROLLBACK_TIMEOUT=2 timeout 15 \
        "$ROOT/research/p22-proof-supervisor.sh" \
        "$run" "$run/candidate.state" "$rescue" "$rollback_sha" "$stage" \
        "$run/download.xml" "$run/global.lock" 3 "$fake_wrapper" \
        "$run/rollback.state" "$run/rollback.log" "$run/supervisor.state"
    supervisor_rc=$?
    set -e
    test "$supervisor_rc" -ne 0
    grep -Fq 'supervisor_rollback_timeout ' "$run/supervisor.state"
    kill -0 "$foreign_pid" 2>/dev/null
    kill -KILL "-$foreign_pid" 2>/dev/null || kill -KILL "$foreign_pid" 2>/dev/null || true
}

test_supervisor_stale_metadata_does_not_kill_foreign() {
    run=$TEST_ROOT/supervisor-stale
    mkdir -p "$run"
    rescue=$run/rescue.img
    stage=$run/boot.img
    truncate -s 16777216 "$rescue"
    rollback_sha=$(sha256sum "$rescue" | cut -d' ' -f1)
    printf '%s\n' 'flash_rc=0 candidate' > "$run/candidate.state"
    fake_wrapper=$run/fake-wrapper
    cat > "$fake_wrapper" <<'EOF'
#!/bin/sh
printf '%s\n' "$$" > "$4"
ps -o pgid= -p "$$" | tr -d ' ' > "$5"
ps -o sid= -p "$$" | tr -d ' ' > "$8"
awk '{print $22}' "/proc/$$/stat" > "$9"
printf 'tool_started fake\n' > "$1"
while :; do sleep 60; done
EOF
    chmod +x "$fake_wrapper"
    P22_SUPERVISOR_ROLLBACK_TIMEOUT=8 timeout 20 \
        "$ROOT/research/p22-proof-supervisor.sh" \
        "$run" "$run/candidate.state" "$rescue" "$rollback_sha" "$stage" \
        "$run/download.xml" "$run/global.lock" 3 "$fake_wrapper" \
        "$run/rollback.state" "$run/rollback.log" "$run/supervisor.state" &
    supervisor_pid=$!
    rollback_pid=
    wait_for_pid=0
    while [ "$wait_for_pid" -lt 8 ] && [ -z "$rollback_pid" ]; do
        rollback_pid=$(cat "$run/supervisor-rollback.pid" 2>/dev/null || true)
        sleep 1
        wait_for_pid=$((wait_for_pid + 1))
    done
    test -n "$rollback_pid"
    owned_pgid=$(cat "$run/supervisor-rollback.pgid")
    owned_start=$(cat "$run/supervisor-rollback.starttime")
    setsid sh -c 'while :; do sleep 60; done' sh "$run/download.xml" &
    foreign_pid=$!
    foreign_pgid=$(ps -o pgid= -p "$foreign_pid" | tr -d ' ')
    foreign_sid=$(ps -o sid= -p "$foreign_pid" | tr -d ' ')
    printf '%s\n' "$foreign_pid" > "$run/supervisor-rollback.pid"
    printf '%s\n' "$foreign_pgid" > "$run/supervisor-rollback.pgid"
    printf '%s\n' "$foreign_sid" > "$run/supervisor-rollback.sid"
    printf '%s\n' "$owned_start" > "$run/supervisor-rollback.starttime"
    set +e
    wait "$supervisor_pid"
    supervisor_rc=$?
    set -e
    test "$supervisor_rc" -ne 0
    kill -0 "$foreign_pid" 2>/dev/null
    kill -KILL "-$foreign_pid" 2>/dev/null || kill -KILL "$foreign_pid" 2>/dev/null || true
    kill -KILL "-$owned_pgid" 2>/dev/null || true
}

test_harness_waits_for_nonterminal_supervisor_states() {
    sed -n '/^wait_supervisor_rollback() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/wait-supervisor-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/wait-supervisor-function.sh"
    state_file=$TEST_ROOT/wait-supervisor.state
    printf '%s\n' 'supervisor_waiting_candidate now' > "$state_file"
    (sleep 1; printf '%s\n' 'supervisor_rollback_armed now' > "$state_file"; sleep 1; printf '%s\n' 'supervisor_rollback_succeeded_rescue_verified now' > "$state_file") &
    SUPERVISOR_STATE=$state_file
    # shellcheck disable=SC2034 # consumed by the sourced function
    SUPERVISOR_UNIT=unused
    SUPERVISOR_KEEP=yes
    # shellcheck disable=SC2329 # called by the sourced wait function
    trex_ssh() { cat "$SUPERVISOR_STATE"; }
    wait_supervisor_rollback
    test "$SUPERVISOR_KEEP" = no
}

test_local_exit_preserves_active_supervisor() {
    sed -n '/^stop_capture() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/stop-capture-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/stop-capture-function.sh"
    RUN_SHARED=$TEST_ROOT/term-run
    mkdir -p "$RUN_SHARED"
    SUPERVISOR_KEEP=yes
    stop_log=$TEST_ROOT/term-stop.log
    trex_ssh() { printf '%s\n' "$*" >> "$stop_log"; return 1; }
    stop_capture
    if grep -Fq 'systemctl --user stop' "$stop_log"; then
        echo 'active supervisor was stopped' >&2
        return 1
    fi
    if grep -Fq 'kill' "$stop_log"; then
        echo 'active supervisor child was killed' >&2
        return 1
    fi
}

test_supervisor_is_trex_owned_and_bounded() {
    grep -Fq 'systemd-run --user --unit=' "$HARNESS"
    grep -Fq 'p22-proof-supervisor.sh' "$HARNESS"
    # shellcheck disable=SC2016 # matching literal shell source
    grep -Fq 'FLASH_LOCK_FILE=$TREX_CAPTURE_ROOT/.p22-flash-writer.lock' "$HARNESS"
    # shellcheck disable=SC2016 # matching literal shell source
    grep -Fq 'TRANSACTION_LOCK_FILE=$TREX_CAPTURE_ROOT/.p22-transaction.lock' "$HARNESS"
    # shellcheck disable=SC2016 # matching literal shell source
    if grep -Fq 'flash-attempt-$attempt_tag.lock' "$HARNESS"; then
        echo 'per-attempt writer lock returned' >&2
        return 1
    fi
    grep -Fq 'transaction_policy=observe-always-rollback' "$ROOT/research/p22-unattended-recovery-power-preflight-v1.manifest"
    # shellcheck disable=SC2016 # matching literal shell source
    grep -Fq 'LIFETIME=${3:-900}' "$ROOT/research/p22-trex-transaction-holder.sh"
    grep -Fq 'SUPERVISOR_KEEP=yes' "$HARNESS"
    # shellcheck disable=SC2016 # matching literal shell source
    grep -Fq 'if [ "$SUPERVISOR_KEEP" != yes ]; then' "$HARNESS"
    grep -Fq 'supervisor_waiting_candidate' "$ROOT/research/p22-proof-supervisor.sh"
}

test_recovery_ssh_window_covers_platform_gate() {
    grep -Fq 'RECOVERY_SSH_TIMEOUT_SECONDS=90' "$HARNESS"
    test "$(grep -Fc 'wait_ssh "$RECOVERY_SSH_TIMEOUT_SECONDS"' "$HARNESS")" -eq 2
    if grep -Fq 'wait_ssh 40' "$HARNESS"; then
        echo 'stale pre-DVFSP recovery SSH window returned' >&2
        return 1
    fi
}

test_rendered_candidate_validation_is_valid_shell() {
    sed -n '/^validate_candidate() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/validate-candidate-function.sh"
    # shellcheck disable=SC1090,SC1091
    . "$TEST_ROOT/validate-candidate-function.sh"
    device_ssh() { sh -n -c "$1"; }
    RUN_LOCAL=$TEST_ROOT/validate-candidate-run
    mkdir -p "$RUN_LOCAL"
    ACCEPTANCE_DEADLINE=2000000000
    CANDIDATE_SHA=0000000000000000000000000000000000000000000000000000000000000000
    ROOTFS_POLICY=enumeration-only
    POWER_PREFLIGHT_POLICY=required
    EXPECTED_MODEL=MT6797X
    EXPECTED_COMPATIBLE=planet,gemini-pda
    EXPECTED_CMDLINE=maxcpus=8
    EXPECTED_CPU_ONLINE=0-7
    EXPECTED_GADGET_IP=10.15.19.82
    EXPECTED_ETHERNET_IP=192.168.23.70
    HOST_NET_POLICY=required
    EXPECTED_MARKER=unattended_recovery=healthy
    FEATURE_POLICY=allow-platform
    WATCHDOG_PROFILE=initramfs-petter
    EXPECTED_WATCHDOG_IDENTITY=mtk-wdt
    EXPECTED_WATCHDOG_STATE=active
    EXPECTED_WATCHDOG_TIMEOUT=31
    LEASE_SECONDS=90
    STAGE2_POLICY=none
    STAGE1_WATCHDOG_OWNER_MARKER=
    STAGE1_HANDOFF_PATH=
    STAGE2_WATCHDOG_OWNER_UNIT=
    STAGE2_WATCHDOG_STATE=
    STAGE2_WATCHDOG_EVIDENCE=
    STAGE2_SUCCESS_MARKER=
    validate_candidate
}

test_stage2_schema_requires_takeover_fields() {
    manifest=$TEST_ROOT/stage2-missing.manifest
    sed -e 's/^watchdog_profile=.*/watchdog_profile=initramfs-petter/' \
        -e 's/^acceptance_window_seconds=.*/acceptance_window_seconds=60/' \
        "$ROOT/research/p22-next-experiment.manifest" > "$manifest"
    printf '%s\n' \
        'stage2_policy=watchdog-takeover-required' \
        'expected_watchdog_identity=mtk-wdt' \
        'expected_watchdog_state=active' \
        'expected_watchdog_timeout=31' \
        'ssh_path_policy=both' \
        'power_preflight_policy=required' \
        'transaction_policy=observe-always-rollback' \
        'lease_seconds=90' >> "$manifest"
    set +e
    "$HARNESS" --manifest "$manifest" --dry-run \
        > "$TEST_ROOT/stage2-missing.log" 2>&1
    rc=$?
    set -e
    test "$rc" -eq 2
    grep -Fq 'manifest field is missing: stage1_watchdog_owner_marker' \
        "$TEST_ROOT/stage2-missing.log"
}

test_stage2_schema_requires_store_fields() {
    manifest=$TEST_ROOT/stage2-store-missing.manifest
    sed -e 's/^watchdog_profile=.*/watchdog_profile=initramfs-petter/' \
        -e 's/^acceptance_window_seconds=.*/acceptance_window_seconds=60/' \
        "$ROOT/research/p22-next-experiment.manifest" > "$manifest"
    printf '%s\n' \
        'stage2_policy=watchdog-takeover-required' \
        'expected_watchdog_identity=mtk-wdt' \
        'expected_watchdog_state=active' \
        'expected_watchdog_timeout=31' \
        'stage1_watchdog_owner_marker=watchdog=petting' \
        'stage1_handoff_path=/run/stage1-handoff' \
        'stage2_watchdog_owner_unit=gemini-watchdog.service' \
        'stage2_watchdog_state=active' \
        'stage2_watchdog_evidence=stage2=multi-user watchdog=petting acceptance=external' \
        'stage2_success_marker=/run/gemini-mainline-success' \
        'ssh_path_policy=both' \
        'power_preflight_policy=required' \
        'transaction_policy=observe-always-rollback' \
        'lease_seconds=90' >> "$manifest"
    set +e
    "$HARNESS" --manifest "$manifest" --dry-run \
        > "$TEST_ROOT/stage2-store-missing.log" 2>&1
    rc=$?
    set -e
    test "$rc" -eq 2
    grep -Fq 'manifest field is missing: stage2_store_source' \
        "$TEST_ROOT/stage2-store-missing.log"
}

test_stage2_schema_rejects_unsafe_store_target() {
    manifest=$TEST_ROOT/stage2-store-target.manifest
    sed -e 's/^watchdog_profile=.*/watchdog_profile=initramfs-petter/' \
        -e 's/^acceptance_window_seconds=.*/acceptance_window_seconds=60/' \
        "$ROOT/research/p22-next-experiment.manifest" > "$manifest"
    printf '%s\n' \
        'stage2_policy=watchdog-takeover-required' \
        'expected_watchdog_identity=mtk-wdt' \
        'expected_watchdog_state=active' \
        'expected_watchdog_timeout=31' \
        'stage1_watchdog_owner_marker=watchdog=petting' \
        'stage1_handoff_path=/run/stage1-handoff' \
        'stage2_watchdog_owner_unit=gemini-watchdog.service' \
        'stage2_watchdog_state=active' \
        'stage2_watchdog_evidence=stage2=multi-user watchdog=petting acceptance=external' \
        'stage2_success_marker=/run/gemini-mainline-success' \
        'stage2_store_source=/mnt/Home/src/stage2-test.squashfs' \
        'stage2_store_sha256=0000000000000000000000000000000000000000000000000000000000000000' \
        'stage2_store_size=1' \
        'stage2_store_target=/dev/mmcblk0p22' \
        'stage2_store_target_live=/gemian/nixos/next-mainline.squashfs' \
        'stage1_store_target=/gemian/nixos/mainline-nixos-connectivity-m0.squashfs' \
        'stage1_store_sha256=0000000000000000000000000000000000000000000000000000000000000000' \
        'stage1_store_size=1' \
        'ssh_path_policy=both' \
        'power_preflight_policy=required' \
        'transaction_policy=observe-always-rollback' \
        'lease_seconds=90' >> "$manifest"
    set +e
    "$HARNESS" --manifest "$manifest" --dry-run \
        > "$TEST_ROOT/stage2-store-target.log" 2>&1
    rc=$?
    set -e
    test "$rc" -eq 2
    grep -Fq 'stage2_store_target must be a unique /nixos/*.squashfs path' \
        "$TEST_ROOT/stage2-store-target.log"
}

test_stage2_store_staging_commands_are_safe_shell() {
    sed -n '/^provision_stage2_store() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/stage2-store-function.sh"
    # shellcheck disable=SC1090,SC1091
    . "$TEST_ROOT/stage2-store-function.sh"
    RUN_LOCAL=$TEST_ROOT/stage2-store-run
    mkdir -p "$RUN_LOCAL"
    n=0
    : > "$TEST_ROOT/stage2-test.squashfs"
    device_ssh_gadget() {
        n=$((n + 1))
        printf '%s\n' "$1" > "$RUN_LOCAL/store-command-$n.sh"
        case "$1" in
            *'test -f'*) return 1 ;;
            *'grep -Fqx'*) return 0 ;;
            *'cat >'*) cat > "$RUN_LOCAL/store-stream-$n"; return 0 ;;
            *) return 0 ;;
        esac
    }
    device_ssh_gadget_provision() { device_ssh_gadget "$@"; }
    STAGE2_POLICY=watchdog-takeover-required
    STAGE2_STORE_SOURCE=$TEST_ROOT/stage2-test.squashfs
    STAGE2_STORE_SIZE=1
    STAGE2_STORE_SHA=0000000000000000000000000000000000000000000000000000000000000000
    STAGE2_STORE_TARGET=/nixos/next-mainline.squashfs
    STAGE2_STORE_TARGET_LIVE=/gemian/nixos/next-mainline.squashfs
    STAGE1_STORE_TARGET=/gemian/nixos/mainline-nixos-connectivity-m0.squashfs
    STAGE1_STORE_SHA=0000000000000000000000000000000000000000000000000000000000000000
    STAGE1_STORE_SIZE=1
    provision_stage2_store
    for command in "$RUN_LOCAL"/store-command-*.sh; do sh -n "$command"; done
    grep -Fq 'cat >' "$RUN_LOCAL/store-command-4.sh"
    grep -Fq '/mnt/gemian/nixos/next-mainline.squashfs.provision.tmp' \
        "$RUN_LOCAL/store-command-4.sh"
    grep -Fq 'mv ' "$RUN_LOCAL/store-command-4.sh"
    grep -Fq 'sync' "$RUN_LOCAL/store-command-4.sh"
    grep -Fq '/run/store-provision.ready' "$RUN_LOCAL/store-command-4.sh"
    grep -Fq "test ! -L '/mnt/gemian/nixos/next-mainline.squashfs.provision.tmp'" \
        "$RUN_LOCAL/store-command-4.sh"
    grep -Fq 'store-provision=required target=/mnt/gemian/nixos/next-mainline.squashfs' \
        "$RUN_LOCAL/store-command-3.sh"
    ! grep -R -Fq 'device_scp' "$RUN_LOCAL" 2>/dev/null
}

test_stage2_exact_target_is_idempotent() {
    sed -n '/^provision_stage2_store() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/stage2-idempotent-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/stage2-idempotent-function.sh"
    RUN_LOCAL=$TEST_ROOT/stage2-idempotent-run
    mkdir -p "$RUN_LOCAL"
    calls=0
    device_ssh_gadget() {
        calls=$((calls + 1))
        case "$1" in
            *'test -f'*) return 0 ;;
            *) return 1 ;;
        esac
    }
    STAGE2_POLICY=watchdog-takeover-required
    STAGE2_STORE_SIZE=1
    STAGE2_STORE_SHA=0000000000000000000000000000000000000000000000000000000000000000
    STAGE2_STORE_TARGET_LIVE=/gemian/nixos/next-mainline.squashfs
    STAGE1_STORE_TARGET=/gemian/nixos/mainline-nixos-connectivity-m0.squashfs
    STAGE1_STORE_SIZE=1
    STAGE1_STORE_SHA=0000000000000000000000000000000000000000000000000000000000000000
    provision_stage2_store
    test "$calls" -eq 1
    test "$STAGE2_STORE_PROVISIONED" = yes
    calls=0
    STAGE2_STORE_PROVISIONED=no
    device_ssh_gadget() {
        calls=$((calls + 1))
        case "$calls" in
            1) return 1 ;;
            2) return 0 ;;
            *) return 1 ;;
        esac
    }
    provision_stage2_store
    test "$calls" -eq 2
    test "$STAGE2_STORE_PROVISIONED" = yes
}

test_stage2_rendered_validation_requires_handoff() {
    sed -n '/^validate_candidate_stage2() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/validate-stage2-function.sh"
    # shellcheck disable=SC1090,SC1091
    . "$TEST_ROOT/validate-stage2-function.sh"
    RUN_LOCAL=$TEST_ROOT/validate-stage2-run
    mkdir -p "$RUN_LOCAL"
    device_ssh() {
        printf '%s\n' "$1" > "$RUN_LOCAL/rendered-stage2.sh"
        sh -n -c "$1"
    }
    ACCEPTANCE_DEADLINE=2000000000
    CANDIDATE_SHA=0000000000000000000000000000000000000000000000000000000000000000
    ROOTFS_POLICY=nixos-stage2
    POWER_PREFLIGHT_POLICY=required
    EXPECTED_MODEL=MT6797X
    EXPECTED_COMPATIBLE=planet,gemini-pda
    EXPECTED_CMDLINE=maxcpus=8
    EXPECTED_CPU_ONLINE=0-7
    EXPECTED_GADGET_IP=10.15.19.82
    EXPECTED_ETHERNET_IP=192.168.23.70
    HOST_NET_POLICY=required
    EXPECTED_MARKER=gemini-mainline-success
    FEATURE_POLICY=allow-platform
    WATCHDOG_PROFILE=initramfs-petter
    EXPECTED_WATCHDOG_IDENTITY=mtk-wdt
    EXPECTED_WATCHDOG_STATE=active
    EXPECTED_WATCHDOG_TIMEOUT=31
    STAGE2_POLICY=watchdog-takeover-required
    LEASE_SECONDS=90
    STAGE1_WATCHDOG_OWNER_MARKER=watchdog=petting
    STAGE1_HANDOFF_PATH=/run/stage1-handoff
    STAGE2_WATCHDOG_OWNER_UNIT=gemini-watchdog.service
    STAGE2_WATCHDOG_STATE=active
    STAGE2_WATCHDOG_EVIDENCE='stage2=multi-user watchdog=petting acceptance=external'
    STAGE2_SUCCESS_MARKER=/run/gemini-mainline-success
    validate_candidate_stage2
    grep -Fq 'stage2_state=$(systemctl is-active' \
        "$RUN_LOCAL/rendered-stage2.sh"
    grep -Fq 'systemctl show -p MainPID --value' \
        "$RUN_LOCAL/rendered-stage2.sh"
    grep -Fq 'test "$success_first" = '\''mainline NixOS reached multi-user.target'\''' \
        "$RUN_LOCAL/rendered-stage2.sh"
    ! grep -Fq '/run/probe-status' "$RUN_LOCAL/rendered-stage2.sh"
    sed -n '/^validate_candidate_right_path_stage2() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/validate-stage2-right-function.sh"
    # shellcheck disable=SC1090,SC1091
    . "$TEST_ROOT/validate-stage2-right-function.sh"
    device_ssh_right() {
        printf '%s\n' "$1" > "$RUN_LOCAL/rendered-stage2-right.sh"
        sh -n -c "$1"
    }
    SSH_PATH_POLICY=both
    validate_candidate_right_path_stage2
    grep -Fq '/dev/mmcblk0p31' "$RUN_LOCAL/rendered-stage2-right.sh"
    grep -Fq 'idVendor' "$RUN_LOCAL/rendered-stage2-right.sh"
    grep -Fq 'watchdog-owner=$stage2_pid' "$RUN_LOCAL/rendered-stage2-right.sh"
    ! grep -Fq '/run/probe-status' "$RUN_LOCAL/rendered-stage2-right.sh"
}

test_stage2_lease_evidence_is_literal() {
    sed -n '/^verify_lease_expiry_evidence() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/verify-lease-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/verify-lease-function.sh"
    RUN_LOCAL=$TEST_ROOT/lease-proof
    mkdir -p "$RUN_LOCAL"
    cat > "$RUN_LOCAL/probe-status-proof.log" <<'EOF'
stage2-evidence
stage2=multi-user watchdog=petting acceptance=external
unattended_recovery=lease-expired watchdog_userspace=stopped
stage2-disconnected 2026-08-30T00:00:00Z
EOF
    STAGE2_POLICY=watchdog-takeover-required
    STAGE2_WATCHDOG_EVIDENCE='stage2=multi-user watchdog=petting acceptance=external'
    SUPERVISOR_STATE=$TEST_ROOT/supervisor.state
    printf '%s\n' 'supervisor_rollback_succeeded_rescue_verified 2026-08-30T00:00:00Z' > "$SUPERVISOR_STATE"
    trex_ssh() { grep -Fq 'supervisor_rollback_succeeded_rescue_verified ' "$SUPERVISOR_STATE"; }
    verify_lease_expiry_evidence
    sed -i '/unattended_recovery=lease-expired/d' "$RUN_LOCAL/probe-status-proof.log"
    set +e
    verify_lease_expiry_evidence
    rc=$?
    set -e
    test "$rc" -ne 0
}

test_stage2_policy_requires_observe_lease() {
    manifest=$TEST_ROOT/stage2-policy.manifest
    sed -e 's/^watchdog_profile=.*/watchdog_profile=initramfs-petter/' \
        -e 's/^acceptance_window_seconds=.*/acceptance_window_seconds=60/' \
        "$ROOT/research/p22-next-experiment.manifest" > "$manifest"
    printf '%s\n' \
        'stage2_policy=watchdog-takeover-required' \
        'expected_watchdog_identity=mtk-wdt' \
        'expected_watchdog_state=active' \
        'expected_watchdog_timeout=31' \
        'stage1_watchdog_owner_marker=watchdog=petting' \
        'stage1_handoff_path=/run/stage1-handoff' \
        'stage2_watchdog_owner_unit=gemini-watchdog.service' \
        'stage2_watchdog_state=active' \
        'stage2_watchdog_evidence=stage2=multi-user watchdog=petting acceptance=external' \
        'stage2_success_marker=/run/gemini-mainline-success' \
        'stage2_store_source=/mnt/Home/src/stage2-test.squashfs' \
        'stage2_store_sha256=0000000000000000000000000000000000000000000000000000000000000000' \
        'stage2_store_size=1' \
        'stage2_store_target=/nixos/next-mainline.squashfs' \
        'stage2_store_target_live=/gemian/nixos/next-mainline.squashfs' \
        'stage1_store_target=/gemian/nixos/mainline-nixos-connectivity-m0.squashfs' \
        'stage1_store_sha256=0000000000000000000000000000000000000000000000000000000000000000' \
        'stage1_store_size=1' \
        'ssh_path_policy=both' \
        'power_preflight_policy=required' \
        'transaction_policy=observe-always-rollback' \
        'lease_seconds=90' >> "$manifest"
    set +e
    "$HARNESS" --manifest "$manifest" --execute \
        > "$TEST_ROOT/stage2-policy.log" 2>&1
    rc=$?
    set -e
    test "$rc" -eq 2
    grep -Fq 'observe-always-rollback requires --proof-lease' \
        "$TEST_ROOT/stage2-policy.log"
}

test_wrapper_requires_transaction_owner_when_requested() {
    test_bin=$TEST_ROOT/owner-bin
    mkdir -p "$test_bin"
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$test_bin/timeout"
    chmod +x "$test_bin/timeout"
    state=$TEST_ROOT/owner.state
    set +e
    PATH="$test_bin:$PATH" "$WRAPPER" "$state" "$TEST_ROOT/owner.log" \
        unused.xml "$TEST_ROOT/owner.pid" "$TEST_ROOT/owner.pgid" \
        "$TEST_ROOT/owner.lock" "$TEST_ROOT/missing-owner"
    rc=$?
    set -e
    test "$rc" -eq 76
    grep -Fq 'flash_rc=76' "$state"
}

test_wrapper_rejects_stale_transaction_owner() {
    test_bin=$TEST_ROOT/stale-owner-bin
    mkdir -p "$test_bin"
    printf '%s\n' '#!/bin/sh' 'exit 0' > "$test_bin/timeout"
    chmod +x "$test_bin/timeout"
    owner=$TEST_ROOT/stale-owner
    printf '%s\n' 'owner=trex-transaction-holder pid=999999999 started=never' > "$owner"
    state=$TEST_ROOT/stale-owner.state
    set +e
    PATH="$test_bin:$PATH" "$WRAPPER" "$state" "$TEST_ROOT/stale-owner.log" \
        unused.xml "$TEST_ROOT/stale-owner.pid" "$TEST_ROOT/stale-owner.pgid" \
        "$TEST_ROOT/stale-owner.lock" "$owner"
    rc=$?
    set -e
    test "$rc" -eq 76
    grep -Fq 'transaction owner is stale' "$TEST_ROOT/stale-owner.log"
}

test_transaction_holder_removes_expired_owner() {
    lock=$TEST_ROOT/holder.lock
    owner=$TEST_ROOT/holder.owner
    timeout 5 "$ROOT/research/p22-trex-transaction-holder.sh" "$lock" "$owner" 1
    test ! -e "$owner"
}

test_ssh_timeout
test_duplicate_flash_tool_rejected
test_post_marker_failure_does_not_recover
test_stale_attempt_state_not_reused
test_observe_policy_disables_persistent_execute
test_wrapper_uses_per_attempt_pid_files
test_wrapper_lock_rejects_duplicate
test_wrapper_foreground_process_tree
test_sourced_stop_tool_kills_exact_session_after_leader_exit
test_stop_capture_does_not_trust_stale_diagnostic_pid
test_xml_is_attempt_unique_for_writer_and_supervisor
test_supervisor_fake_rollback
test_supervisor_rolls_back_failed_candidate
test_supervisor_records_unexpected_exit
test_supervisor_timeout_kills_only_owned_session
test_supervisor_stale_metadata_does_not_kill_foreign
test_harness_waits_for_nonterminal_supervisor_states
test_local_exit_preserves_active_supervisor
test_supervisor_is_trex_owned_and_bounded
test_recovery_ssh_window_covers_platform_gate
test_rendered_candidate_validation_is_valid_shell
test_wrapper_requires_transaction_owner_when_requested
test_wrapper_rejects_stale_transaction_owner
test_transaction_holder_removes_expired_owner
test_stage2_schema_requires_takeover_fields
test_stage2_schema_requires_store_fields
test_stage2_schema_rejects_unsafe_store_target
test_stage2_store_staging_commands_are_safe_shell
test_stage2_exact_target_is_idempotent
test_stage2_rendered_validation_requires_handoff
test_stage2_lease_evidence_is_literal
test_stage2_policy_requires_observe_lease
echo 'p22-recovery-harness tests: passed'
