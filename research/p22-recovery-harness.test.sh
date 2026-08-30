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

test_harness_waits_for_nonterminal_supervisor_states() {
    sed -n '/^wait_supervisor_rollback() {/,/^}/p' "$HARNESS" \
        > "$TEST_ROOT/wait-supervisor-function.sh"
    # shellcheck disable=SC1091
    . "$TEST_ROOT/wait-supervisor-function.sh"
    state_file=$TEST_ROOT/wait-supervisor.state
    printf '%s\n' 'supervisor_waiting_candidate now' > "$state_file"
    (sleep 1; printf '%s\n' 'supervisor_rollback_armed now' > "$state_file"; sleep 1; printf '%s\n' 'supervisor_rollback_succeeded_rescue_verified now' > "$state_file") &
    SUPERVISOR_STATE=$state_file
    SUPERVISOR_UNIT=unused
    SUPERVISOR_KEEP=yes
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
    ! grep -Fq 'systemctl --user stop' "$stop_log"
    ! grep -Fq 'kill' "$stop_log"
}

test_supervisor_is_trex_owned_and_bounded() {
    grep -Fq 'systemd-run --user --unit=' "$HARNESS"
    grep -Fq 'p22-proof-supervisor.sh' "$HARNESS"
    grep -Fq 'FLASH_LOCK_FILE=$TREX_CAPTURE_ROOT/.p22-flash-writer.lock' "$HARNESS"
    grep -Fq 'TRANSACTION_LOCK_FILE=$TREX_CAPTURE_ROOT/.p22-transaction.lock' "$HARNESS"
    ! grep -Fq 'flash-attempt-$attempt_tag.lock' "$HARNESS"
    grep -Fq 'transaction_policy=observe-always-rollback' "$ROOT/research/p22-unattended-recovery-power-preflight-v1.manifest"
    grep -Fq 'LIFETIME=${3:-900}' "$ROOT/research/p22-trex-transaction-holder.sh"
    grep -Fq 'SUPERVISOR_KEEP=yes' "$HARNESS"
    grep -Fq 'if [ "$SUPERVISOR_KEEP" != yes ]; then' "$HARNESS"
    grep -Fq 'supervisor_waiting_candidate' "$ROOT/research/p22-proof-supervisor.sh"
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
test_supervisor_fake_rollback
test_supervisor_rolls_back_failed_candidate
test_supervisor_records_unexpected_exit
test_harness_waits_for_nonterminal_supervisor_states
test_local_exit_preserves_active_supervisor
test_supervisor_is_trex_owned_and_bounded
test_wrapper_requires_transaction_owner_when_requested
test_wrapper_rejects_stale_transaction_owner
test_transaction_holder_removes_expired_owner
echo 'p22-recovery-harness tests: passed'
