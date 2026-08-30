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

test_ssh_timeout
test_duplicate_flash_tool_rejected
echo 'p22-recovery-harness tests: passed'
