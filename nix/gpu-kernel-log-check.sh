#!/bin/sh
# Ignore only zero-fault address-space snapshots.
set -eu
source=${1:?kernel log required}
scoped=${2:?filtered output required}
# AS_STATUS_AS_ACTIVE is bit 0; it is not an MMU fault indication.
grep -Ev 'panfrost 13040000\.gpu: MT6797_GPU_DIAG event=submit as=[0-7] status=0000000[01] fault=00000000 tt_flags=[0-9a-f]{3} memattr=[0-9a-f]{16} transcfg=[0-9a-f]{16}$' "$source" > "$scoped" || test "$?" -eq 1
if grep -Ei '(panfrost|13040000\.gpu|mfg|rt5735|vgpu).*(fault|error|timeout|timed out|failed|stuck)|(^|[[:space:]])(BUG:|Oops:|Call trace:)' "$scoped"; then exit 1; fi
if grep -E 'GPULDO_FIRST_FAILURE|GPU_RENDER_FAIL|rcu.*detected stalls|Kernel panic|BUG:|Unable to handle kernel' "$source"; then exit 1; fi
