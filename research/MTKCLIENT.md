# Gemini mtkclient qualification

Status, 2026-10-04: the supervised hardware trial read the primary GPT and
complete boot partition correctly. The DA acknowledged the patched reboot
request and mtkclient exited zero, but healthy Linux did **not** return within
three minutes. USB remained at the MediaTek preloader and the owner reported
a black screen. Read/reboot qualification failed; boot-only writes remain
unqualified.

## October 4 read/reboot trial

Evidence: workspace `handoff/mtkclient-read-reboot-20261004-01`.
The owner was available for physical recovery. Starting from healthy M69,
the runner performed one normal Linux reboot and one DA session, with no
eMMC write commands:

- The 32,768-byte primary GPT read matched preflight SHA-256
  `6addff62cc67f5b5fac9bd87194b6643f4029262251c51c1e43e1b5b64cb887d`.
- The 16,777,216-byte boot read matched accepted M69 SHA-256
  `913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3`.
- `reset --bootmode reboot` was acknowledged; the client exited zero.
- At approximately 120 seconds after client exit, USB was still
  `0e8d:2000`, `MT65xx Preloader`, on port `3-2`; SSH did not return during
  the full 180-second observation window. This does not establish why the
  DA reboot failed to reach Linux.

The runner also exposed a host-side permissions bug: the privileged client
created readback files owned by root with mode 0600. Ownership of the two
completed readbacks was corrected locally so their hashes could be checked.
The runner now creates these files exclusively as the invoking user before
launching the client. No second DA attempt or fallback flash was started.
Manual recovery observations are recorded separately from the failed trial.
The owner subsequently confirmed a force restart. USB on the same port
changed to `0fce:7169` (`GNU/Linux Device`), the known vendor-kernel gadget
identity. This is consistent with the owner's expectation of Gemian; the OS
was not authenticated over SSH, and healthy M69 was not observed. See
`manual-recovery-usb.json` in the evidence directory. Manual recovery does
not convert the automatic read/reboot trial into a pass.

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
failed DA sessions, and readback file ownership). These are host tests, not
hardware evidence.

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
