#!/bin/sh
# shellcheck disable=SC1007
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SUPERVISOR=$ROOT/research/p22-proof-supervisor.sh
WORK=$(mktemp -d /mnt/Home/src/p22-self-accept-supervisor-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT INT TERM

make_run() {
    name=$1
    run=$WORK/$name
    mkdir "$run"
    truncate -s 16777216 "$run/rescue.img"
    cp "$run/rescue.img" "$run/stage.img"
    sha256sum "$run/rescue.img" | cut -d' ' -f1 > "$run/rescue.sha"
    printf 'flash_rc=0 test\n' > "$run/candidate.state"
    : > "$run/flash.lock"
    : > "$run/transaction-owner"
    printf '%s\n' "$run"
}

run_supervisor() {
    run=$1
    wrapper=$2
    accept_path=$3
    candidate_sha=$4
    P22_SUPERVISOR_ARM_DELAY=0 \
    P22_SUPERVISOR_ROLLBACK_TIMEOUT=10 \
        sh "$SUPERVISOR" "$run" "$run/candidate.state" \
        "$run/rescue.img" "$(cat "$run/rescue.sha")" "$run/stage.img" \
        "$run/download.xml" "$run/flash.lock" 4 "$wrapper" \
        "$run/rollback.state" "$run/rollback.log" "$run/supervisor.state" \
        8 "$accept_path" "$candidate_sha"
}

CANDIDATE_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

# A commit already visible at the first quiescent point starts no writer.
run=$(make_run accepted-before-scan)
wrapper=$run/wrapper.sh
cat > "$wrapper" <<'EOF'
#!/bin/sh
touch "$1.wrapper-ran"
exit 1
EOF
chmod +x "$wrapper"
accept=$run/candidate-self-accepted
printf 'candidate_self_accepted sha256=%s\n' "$CANDIDATE_SHA" > "$accept"
run_supervisor "$run" "$wrapper" "$accept" "$CANDIDATE_SHA"
grep -Fq 'supervisor_candidate_self_accepted ' "$run/supervisor.state"
test ! -e "$run/rollback.state.wrapper-ran"

# A commit arriving during a BROM scan is consumed only after that scan has
# ended normally with rc=1.  The supervisor never kills an active scanner.
run=$(make_run accepted-after-scan-timeout)
wrapper=$run/wrapper.sh
cat > "$wrapper" <<'EOF'
#!/bin/sh
state=$1
touch "$state.wrapper-running"
sleep 1
printf 'flash_rc=1 bounded-scan-timeout\n' > "$state"
exit 1
EOF
chmod +x "$wrapper"
accept=$run/candidate-self-accepted
run_supervisor "$run" "$wrapper" "$accept" "$CANDIDATE_SHA" &
supervisor_pid=$!
deadline=$(( $(date +%s) + 5 ))
while [ ! -e "$run/rollback.state.wrapper-running" ]; do
    [ "$(date +%s)" -lt "$deadline" ] || exit 1
    sleep 0.1
done
printf 'candidate_self_accepted sha256=%s\n' "$CANDIDATE_SHA" > "$accept"
wait "$supervisor_pid"
grep -Fq 'supervisor_candidate_self_accepted ' "$run/supervisor.state"
grep -Fqx 'flash_rc=1 bounded-scan-timeout' "$run/rollback.state"

# Preloader/DA success wins the race even if acceptance appears while the
# wrapper is active: exact Stage-A rollback is the safer terminal outcome.
run=$(make_run rollback-wins-race)
wrapper=$run/wrapper.sh
cat > "$wrapper" <<'EOF'
#!/bin/sh
state=$1
touch "$state.wrapper-running"
sleep 1
printf 'flash_rc=0 exact-rescue-written\n' > "$state"
exit 0
EOF
chmod +x "$wrapper"
accept=$run/candidate-self-accepted
run_supervisor "$run" "$wrapper" "$accept" "$CANDIDATE_SHA" &
supervisor_pid=$!
deadline=$(( $(date +%s) + 5 ))
while [ ! -e "$run/rollback.state.wrapper-running" ]; do
    [ "$(date +%s)" -lt "$deadline" ] || exit 1
    sleep 0.1
done
printf 'candidate_self_accepted sha256=%s\n' "$CANDIDATE_SHA" > "$accept"
wait "$supervisor_pid"
grep -Fq 'supervisor_rollback_succeeded_rescue_verified ' "$run/supervisor.state"

# Wrong-SHA, symlink and multiply-linked records cannot cancel recovery.
reject_record() {
    kind=$1
    run=$(make_run "reject-$kind")
    wrapper=$run/wrapper.sh
    cat > "$wrapper" <<'EOF'
#!/bin/sh
printf 'flash_rc=0 exact-rescue-written\n' > "$1"
exit 0
EOF
    chmod +x "$wrapper"
    accept=$run/candidate-self-accepted
    case "$kind" in
        wrong-sha)
            printf 'candidate_self_accepted sha256=%064d\n' 0 > "$accept"
            ;;
        symlink)
            printf 'candidate_self_accepted sha256=%s\n' "$CANDIDATE_SHA" > "$run/record"
            ln -s "$run/record" "$accept"
            ;;
        hardlink)
            printf 'candidate_self_accepted sha256=%s\n' "$CANDIDATE_SHA" > "$run/record"
            ln "$run/record" "$accept"
            ;;
    esac
    run_supervisor "$run" "$wrapper" "$accept" "$CANDIDATE_SHA"
    grep -Fq 'supervisor_rollback_succeeded_rescue_verified ' "$run/supervisor.state"
}
reject_record wrong-sha
reject_record symlink
reject_record hardlink

# The supervisor rejects an acceptance path outside its private run.
run=$(make_run invalid-path)
wrapper=$run/wrapper.sh
printf '#!/bin/sh\nexit 1\n' > "$wrapper"
chmod +x "$wrapper"
if run_supervisor "$run" "$wrapper" "$WORK/outside" "$CANDIDATE_SHA"; then
    exit 1
fi
grep -Fq 'supervisor_blocked_bad_self_accept_path ' "$run/supervisor.state"

echo 'p22 self-accept supervisor tests: passed'
