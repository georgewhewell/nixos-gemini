# Gemini mtkclient qualification

Status, 2026-10-04: read/reboot is working with the MT6797 packet-size fix.
Two corrected DA sessions read the primary GPT and complete boot partition,
then returned automatically to healthy M69 with matching hashes. Boot-only
writes remain unqualified.

## Corrected hardware trials

Both use the same seven-word shutdown payload, explicit normal reboot, fresh
DA state, shared host locks, and USB SSH with the existing M69 host key.
No eMMC writes or manual recovery were needed.

| Workspace evidence | Result |
|---|---|
| `handoff/mtkclient-read-reboot-20261004-02` | Automatic M69 return confirmed, boot ID `bb58cca9-dfbe-4d41-98b6-8cf9aa67ff15`. The original 180-second health deadline expired during startup checks; a separate observation verified full health and both hashes at 252 seconds after DA exit. The original failed result is retained alongside `extended-result.json`. |
| `handoff/mtkclient-read-reboot-20261004-03` | Full runner pass in 194.4 seconds, boot ID `6b1b01f6-cd4b-462f-8b5a-3de4b73c909a`, using a 360-second health deadline. GPT, p22, NixOS system and service health all matched preflight. |

The repeat used package
`/nix/store/d2arl80i2c18na36dg74g1ssjz02m0yl-mtkclient-gemini-2.1.4.1`.
M69 runs cellular, GPU, audio, connectivity and desktop checks before
self-acceptance; the runner now allows six minutes for that complete
sequence. It retains partial SSH output when a health check is still pending.

## Initial October 4 read/reboot failure

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
identity. The owner supplied the working recovery SSH target, `gemini@gemini`.
That connection confirmed Gemian / Debian 9 (stretch), kernel `3.18.41+`,
fresh boot ID `1508c791-df3f-4384-b4fd-5704338ef3ca`, and boot reason
`power_key`. Read-only checks from Gemian verified that p22 and the primary
GPT still matched both preflight hashes, with the original partition geometry
and no p34. See `after-manual-recovery.json` and `manual-recovery-ssh.txt`.
Manual recovery to Gemian succeeded; it does not convert the automatic
read/reboot trial into a pass or establish a fresh healthy M69 boot.

A subsequent normal reboot from Gemian restored healthy M69, boot ID
`bcdf57d3-47fb-4b5d-9284-990608709454`, with both storage hashes unchanged.
Wired SSH was unavailable, so this was verified over `root@10.15.19.82`,
retaining the known M69 host key through `HostKeyAlias=192.168.23.70`.
The runner accepts `--ssh-host` and `--ssh-host-key-alias` for this path.

## MT6797 shutdown packet defect

Offline inspection of the actual bundled `MTK_DA_V5.bin` identified a packet
size mismatch. Its MT6797 entry (DA code `0x6797`, entry 30, region 2) has
SHA-256 `e7ad09de8ef025b9416ac4eca1c85938d3303c1aea462e5cfaa7c15721a1c45b`.
At load address `0x40000000`:

- `cmd_shutdown` starts at `0x400066d0`. At `0x400066d6` it sets receive
  capacity to `0x1c` (28 bytes), covering seven 32-bit fields.
- Its read callback goes through `0x4000c7f0` to `0x40008030`. The capacity
  check at `0x400080a6` rejects a larger packet with `0xc0010006` before
  reading the payload into the caller's buffer.
- The shutdown handler ignores that return value at `0x4000670a` and sends
  its independently initialized zero status at `0x40006716`. The success
  status therefore does not prove the parameters were accepted.

mtkclient sent eight words (32 bytes), including a final reserved zero. Patch
`0003-mt6797-shutdown-packet-size.patch` omits that word for MT6797; other
DA codes retain the existing packet size. The regression test reads the
capacity instruction from the checksum-guarded bundled DA and exercises
the rejected old packet and accepted new packet despite identical status
replies. All 24 package tests pass (8 reset, 7 write, 9 runner).

The first trial's host USB log also shows no disconnect/re-enumeration
between DA acknowledgement and manual recovery. The persistent
`MT65xx Preloader` descriptor alone did not establish that a reset occurred.
Extraction metadata, disassembly, packet-contract evidence and USB events
are in workspace `handoff/mtkclient-da-reboot-analysis`.

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
