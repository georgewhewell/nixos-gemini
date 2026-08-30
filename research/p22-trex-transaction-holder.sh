#!/bin/sh
set -eu

# Trex-owned transaction lease. It prevents concurrent harnesses from
# staging or starting a transaction. The Flash Tool wrapper separately takes
# the global writer lock for each exact attempt.
LOCK_FILE=$1
OWNER_FILE=$2
LIFETIME=${3:-900}

case "$LIFETIME" in
    ''|*[!0-9]*) exit 2 ;;
esac

exec 9>"$LOCK_FILE"
flock -n 9 || exit 75
trap 'rm -f "$OWNER_FILE"' EXIT
trap 'exit 143' INT TERM
printf 'owner=trex-transaction-holder pid=%s started=%s\n' "$$" "$(date -Is)" > "$OWNER_FILE"
deadline=$(( $(date +%s) + LIFETIME ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    sleep 1
done
printf 'owner=trex-transaction-holder expired=%s\n' "$(date -Is)" > "$OWNER_FILE"
