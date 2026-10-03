# Gemini mtkclient qualification

Status, 2026-10-04: patched host package and regression tests pass; read-only
SSH preflight passes on accepted M69. The patched DA reboot has **not** been
tested on hardware. Boot-only writes are not yet qualified.

## What failed previously

The September 29 logs in `handoff/mtkclient-test/{printgpt,multi}.log` both show
successful DA upload and GPT reads. The unresolved part was returning to Linux.
They do not show a stage-2 speed-switch failure.

The pinned upstream mtkclient 2.1.4.1 `reset` command always selects shutdown
mode 0. XFlash defines mode 1 as HOME_SCREEN, but the CLI did not expose it.
It also discarded the shutdown result and reported success unconditionally.
After the shutdown acknowledgement it attempted a host USB reset, which can
race the departing device. These are plausible causes of the old behaviour;
hardware qualification is still required.

The local patch adds `reset --bootmode reboot` (mode 1), retains shutdown as
the default, checks acknowledgement, and avoids the redundant host USB reset
after acknowledgement. Failed requests retain the DA state file and return
nonzero. The shared legacy backend now returns its acknowledgement correctly
and compares ACK bytes correctly, so stricter failure reporting also works
there. The Gemini's historical session used XFlash.

The upstream partition-write command had the same exit-status problem: a DA
write failure printed an error but allowed `multi` to continue and exit zero.
The second local patch returns failure from partition writes and exits nonzero,
stopping later commands in that session. It rejects missing/empty inputs and
oversized partition images before submitting that write, and closes image files
on XFlash transfer failure. This matters when qualifying an identical M69
rewrite: matching readback alone cannot distinguish a successful write from
a failed write that left the old bytes intact.

## Build and preflight

From this flake:

```sh
nix build .#mtkclient --out-link ../handoff/mtkclient-gemini
../handoff/mtkclient-gemini/bin/mtk reset --help
python3 tools/qualify-mtkclient.py \
  --mtk ../handoff/mtkclient-gemini/bin/mtk \
  --out ../handoff/mtkclient-preflight-new
```

The last command only checks the local CLI and reads Linux state through SSH.
It does not reboot or connect to the DA. Evidence directories must be new.
The actual initial preflight is `handoff/mtkclient-preflight-20261004`:
boot ID `fcce1f76-8617-480c-9dcb-5617e109cc7d`, healthy accepted M69,
p22 SHA-256 `913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3`.

The package build runs source-level reset tests (CLI including a multi-command
session, mode-to-packet mapping, acknowledgement/failure handling, legacy ACKs)
partition-write tests (real XFlash command/packet/final-status failures reaching
CLI exit status, bounds, and stopping multi-command dispatch), and
qualification-runner tests (fresh boot, image integrity, preflight isolation,
and failed DA sessions). These are host tests, not hardware evidence.

## Supervised read/reboot trial

Run this when someone can force-restart the Gemini if the DA leaves it hung:

```sh
python3 tools/qualify-mtkclient.py \
  --mtk ../handoff/mtkclient-gemini/bin/mtk \
  --out ../handoff/mtkclient-read-reboot-new --execute
```

The runner holds the existing transaction/writer locks, checks accepted M69
and the factory partition geometry, starts one bounded mtkclient process, waits
until it is ready, then requests a normal Linux reboot. In that single DA
session it prints GPT, reads the first 32 KiB of the disk and all of `boot`
(p22), then requests normal boot. It issues no eMMC writes.

Passing requires complete reads matching the preflight hashes, an acknowledged
DA reboot, a new Linux boot ID, unchanged GPT/p22/system, and healthy services.
Exit code zero from mtkclient alone is insufficient. Logs and snapshots remain
in the evidence directory. There are no automatic retries or fallback flashes;
an incomplete session can require physical recovery.

After repeatable read/reboot passes, qualify a write of the already accepted
M69 image to `boot` only, with full readback and a fresh healthy Linux boot.
Require an acknowledged write as well as matching readback. A failed write
stops `multi` before its reset command, so that failure may require physical
recovery; it must never be reported as a passing write/reboot trial.
Keep the existing SP Flash Tool rescue available until this sequence works.
U-Boot carrier trials and repartitioning follow that qualification.
