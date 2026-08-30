#!/bin/sh
set -eu

# Host-only regressions for the bounded transaction.  These tests deliberately
# replace ssh; they never contact trex or the Gemini and never invoke a writer.
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
HARNESS=$ROOT/research/p22-recovery-harness.sh
RUNNER=$ROOT/research/p22-chained-recovery-runner.sh
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

test_ssh_timeout
test_duplicate_flash_tool_rejected
test_post_marker_failure_does_not_recover
test_stale_attempt_state_not_reused
test_observe_policy_disables_persistent_execute
echo 'p22-recovery-harness tests: passed'
