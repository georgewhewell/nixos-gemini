#!/bin/sh
# SPDX-License-Identifier: MIT
# Host-only tests for the self-accept watcher. No hardware paths are opened.
# shellcheck disable=SC1007 # zsh/NixOS-compatible scoped CDPATH assignment
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d /mnt/Home/src/nixos-gemini-self-accept-watch-test.XXXXXX)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

fail() { echo "test-unattended-recovery-self-accept-watch: $*" >&2; exit 1; }

make_fixture() {
  d=$1
  mkdir -p "$d/run" "$d/proc" "$d/bin"
  printf '%s\n' '300.50 0.00' > "$d/proc/uptime"
  cat > "$d/bin/fake-busybox" <<'BUSYBOX'
#!/bin/sh
exec "$@"
BUSYBOX
  cat > "$d/bin/systemctl" <<'SYSTEMCTL'
#!/bin/sh
case "$*" in
  is-system-running) echo degraded; exit 1 ;;
  "show -p ActiveState --value gemini-baseline-self-accept.service") echo inactive ;;
  "show -p SubState --value gemini-baseline-self-accept.service") echo dead ;;
  "show -p Result --value gemini-baseline-self-accept.service") echo success ;;
  "show -p NRestarts --value gemini-baseline-self-accept.service") echo 0 ;;
  "show -p "*) echo x ;;
  "--failed --no-legend --plain") echo 'gemini-connectivity.service loaded failed failed Wi-Fi' ;;
  "list-jobs --no-legend --plain") ;;
  *) exit 2 ;;
esac
SYSTEMCTL
  cat > "$d/bin/journalctl" <<'JOURNALCTL'
#!/bin/sh
echo "journal $*"
JOURNALCTL
  chmod 0755 "$d/bin/fake-busybox" "$d/bin/systemctl" "$d/bin/journalctl"
}

run_fixture() {
  d=$1
  GEMINI_SELF_ACCEPT_WATCH_BUSYBOX="$d/bin/fake-busybox" \
  GEMINI_SELF_ACCEPT_WATCH_SYSTEMCTL="$d/bin/systemctl" \
  GEMINI_SELF_ACCEPT_WATCH_JOURNALCTL="$d/bin/journalctl" \
  GEMINI_SELF_ACCEPT_WATCH_RUN_ROOT="$d/run" \
  GEMINI_SELF_ACCEPT_WATCH_PROC_ROOT="$d/proc" \
  GEMINI_SELF_ACCEPT_WATCH_KMSG_FILE="$d/kmsg" \
  GEMINI_SELF_ACCEPT_WATCH_PMSG_FILE="$d/pmsg" \
  GEMINI_SELF_ACCEPT_WATCH_INTERVAL=0 \
  GEMINI_SELF_ACCEPT_WATCH_MAX_ROUNDS=3 \
    sh "$ROOT/nix/unattended-recovery-self-accept-watch.sh"
}

waiting=$WORK/waiting
make_fixture "$waiting"
run_fixture "$waiting" || fail 'watcher exited non-zero'
test ! -e "$waiting/run/unattended-recovery.accepted"
# One line for three identical rounds.
test "$(grep -c 'self_accept_watch waiting' "$waiting/kmsg")" = 1 || fail 'repeated identical summary'
grep -Fq 'system=degraded gate=inactive/dead/success/restarts=0 last_reason=none failed=gemini-connectivity.service jobs=none' \
  "$waiting/pmsg"
grep -Fq 'journal -b -u gemini-connectivity.service -n 40 --no-pager' \
  "$waiting/run/gemini-baseline-self-accept.watch"

accepted=$WORK/accepted
make_fixture "$accepted"
printf '%s\n' unattended_recovery=healthy > "$accepted/run/unattended-recovery.accepted"
printf '%s\n' 'result=accepted' 'reason=health-exact' > "$accepted/run/gemini-baseline-self-accept.status"
run_fixture "$accepted" || fail 'watcher exited non-zero'
grep -Fq 'self_accept_watch accepted uptime=300.50' "$accepted/pmsg"
grep -Fq 'last_reason=health-exact' "$accepted/pmsg"

echo 'test-unattended-recovery-self-accept-watch: PASS'
