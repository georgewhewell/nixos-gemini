# Gemini mtkclient qualification

Status, 2026-10-04: read/reboot, boot-only writes and supervised U-Boot
candidate/rescue cycles are working with the MT6797 packet-size fix. Software
reset, watchdog expiry, two full M69 FIT handoffs and one corrected EFI
application/FIT handoff have passed on hardware. Each trial restored healthy
direct M69 automatically.
Two corrected DA sessions read the primary GPT and complete boot partition,
then returned automatically to healthy M69 with matching hashes. A subsequent
boot-only write was acknowledged, read back in full and followed by another
fresh healthy M69 boot. The GPT and accepted boot contents remain unchanged.

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
replies. The packet-fix build passed 24 tests (8 reset, 7 write, 9 runner).

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
  --ssh-host 10.15.19.82 --ssh-host-key-alias 192.168.23.70 \
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
  --ssh-host 10.15.19.82 --ssh-host-key-alias 192.168.23.70 \
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

## Accepted-image write qualification

The hardware trial passed at workspace
`handoff/mtkclient-boot-write-20261004-01`. The patched DA acknowledged writing
all 32,768 sectors of `boot` starting at sector 362496. The complete 16 MiB
readback and subsequent Linux p22 hash both matched accepted M69; the primary
GPT and partition geometry were unchanged. Automatic reboot produced healthy
boot ID `74d10f78-c5e0-48fd-915d-9eea69e6b87b` after 194.7 seconds, with
no manual recovery.
Package: `/nix/store/vl6ynxsir46vp8w3445w342vdf0xm23b-mtkclient-gemini-2.1.4.1`;
canonical workspace root: `handoff/mtkclient-gemini`. The accepted image is
rooted at `handoff/accepted-m69/boot-padded-p22.img`.

The opt-in write mode rejects any image whose size is not 16 MiB or whose
SHA-256 differs from accepted M69. It stages a private copy, verifies that
copy again before starting the DA, and writes only the `boot` partition.
The command without `--execute` performs preflight and stages the image:

```sh
python3 tools/qualify-mtkclient.py \
  --mtk ../handoff/mtkclient-gemini/bin/mtk \
  --ssh-host 10.15.19.82 --ssh-host-key-alias 192.168.23.70 \
  --rewrite-accepted-boot ../handoff/accepted-m69/boot-padded-p22.img \
  --out ../handoff/mtkclient-write-preflight-new
```

Use a new output directory and add `--execute` for the supervised hardware
trial. Passing requires the patched client's acknowledgement of writing
sector 362496, count 32768, full readback, unchanged GPT and a fresh healthy
M69 boot. An identical-image readback alone is insufficient evidence of a
successful write. The image guard, absence of DA access during preflight,
and mandatory write acknowledgement are covered by four additional runner
tests; the complete package build now passes 28 tests.

A failed write stops `multi` before its reset command, so that failure may
require physical recovery. Keep the existing SP Flash Tool rescue available
while migrating the remaining recovery workflow. U-Boot carrier trials and
repartitioning require their own qualification; this accepted-image mode
does not allow arbitrary boot images or changes to the partition table.

## Durable candidate/rescue qualification

`tools/qualify-uboot-recovery.py` uses the existing transaction holder,
writer wrapper and rollback supervisor with the pinned mtkclient backend.
Its baseline hardware trial passed in workspace
`handoff/mtkclient-supervisor-baseline-02`. Both writes were to accepted M69;
both had DA write acknowledgements, complete readbacks and automatic reboots.
The intermediate healthy boot was `3b867164-e6a3-4753-9945-36b479b50a1d` and
the final healthy rescue boot was `dd0c674a-74cc-4b6d-bc3b-879bd55700a4`.
GPT, p22, p30, p31, factory geometry, system version and service health matched.
No physical recovery was needed. One device-free 180-second scan expired and
was retried before the deliberate second Linux reboot reached rescue.

The backend observes the physical USB port and device numbers from DA entry
through the first normal post-DA preloader's departure. Only then does it
report candidate success and arm rescue immediately. This prevents rescue
from catching the initial boot and falsely appearing to recover a candidate
that never executed. It also avoids the legacy 15-second delay, which could
miss an early U-Boot reset. Each attempt records the USB sequence and raw DA
log separately. A connected failure is terminal; only a timeout with no
observed MediaTek device or handshake evidence maps to a retryable scan miss.

Private staged images are bound to the candidate/rescue role and exact SHA.
The privileged client retains the writer lock through its stdin descriptor,
including if its host observer disappears. Host systemd services own the
bounded transaction, candidate writer, rescue supervisor and network watcher.
Selecting this backend never falls back to SP Flash Tool.

```sh
python3 tools/qualify-uboot-recovery.py --profile baseline \
  --out ../handoff/mtkclient-supervisor-preflight-new
```

Use a fresh directory and add `--execute` to run the complete baseline trial.
The separate `reset` and `watchdog` profiles select only the pinned M69 U-Boot
carriers in `BOOT_HANDOFF.md`. They always restore M69, and a successful
recovery alone does not prove which code initiated the candidate reset.
The older general recovery harness retains its existing backend selection;
this runner qualifies the shared supervisor path for the bootloader trials.

Host validation: 15 backend evidence/order tests, the full recovery-harness
suite, self-accept supervisor tests (including immediate mtkclient arming and
no retry on connected failure), shellcheck, and real host checks of privileged
lock inheritance and systemd session lifetime. The first baseline attempt,
`handoff/mtkclient-supervisor-baseline-01`, stopped before reboot or DA access:
`setsid` forked under systemd and its parent exited. `setsid --wait` fixes that
lifetime; the original failed evidence and unchanged-device check are retained.

The optional `--capture-boot-phase` read-only diagnostic reads exactly four
bytes from TOPRGU NONRST_REG2 (`0x10007024`) using `da peek`, followed by the
same GPT/boot reads, acknowledged reboot and full M69 health check. Hardware
qualification passed in `handoff/mtkclient-phase-read-01`, with no eMMC writes,
199.0 seconds to healthy M69 and boot ID
`15d76bb0-5d91-498e-8727-e047d6f5088b`. It read zero after a normal Linux reboot;
this does not establish whether a U-Boot phase survives a direct rescue path.
The candidate/rescue backend now records that same fixed register before
each write. `handoff/uboot-watchdog-mtkclient-03` captured a fresh U-Boot
`board_init` marker during rescue; see `BOOT_HANDOFF.md` for the failure
interval. The backend/phase/Linux-handoff evidence suite now has 26 passing
host tests, including rejection of stale, missing and unknown execution
markers, inconsistent reset timing, wrong candidate images and lost LK data.

After removing U-Boot's unmapped framebuffer probe, both intended recovery
branches passed on hardware: `handoff/uboot-watchdog-fbfix-01` reached the
watchdog WFI marker and returned after 40.110 seconds; `handoff/uboot-reset-fbfix-01`
reached the software-reset marker and returned after 9.064 seconds. Both
restored fully healthy M69 with unchanged GPT and all boot partitions,
without physical recovery. The same supervisor now supports observing
Linux handoff before a deliberate reboot into rescue; see `BOOT_HANDOFF.md`.

## Capturing a failure log before flash access

`qualify-mtkclient.py --capture-ramoops` reads the fixed Gemini ramoops region
at `0x44410000`, length `0xe0000`, before GPT/boot reads. The read-only hardware
trial `handoff/mtkclient-ramoops-read-01` returned healthy M69 after 195.1 seconds
with unchanged GPT/boot hashes and no eMMC writes. Its captured ring contains
the preceding M69 shutdown. Reading pstore after a DA flash/reboot instead
showed invalid buffers; that later view cannot recover this evidence.

The boot-only candidate/rescue backend now saves the same bounded RAM read
before its flash operations and requires the full byte count. Use
`python3 tools/parse-gemini-ramoops.py RAMOOPS_BIN NEW_DIRECTORY` to decode the
DT's fixed record and console rings. Header, extent and ring chronology
checks reject invalid data; valid bytes alone do not establish which boot
produced a log. The second EFI Linux trial's fresh phase and captured kernel
panic together identify its failed initramfs handoff. Device-specific RAM
capture remains separate from any GPT-write qualification.

## Factory GPT write qualification

The separate `mtkclientGpt` package and `tools/qualify-gpt-rewrite.py` passed
`handoff/gpt-rewrite-01`. One DA session admitted the exact factory GPT and
protected boot images, rewrote the backup and primary in that order, verified
each write independently, reread the complete GPT/protected data, and
acknowledged reboot. Fresh healthy M69 returned automatically as boot
`2c468de5-5249-43a0-ab38-6be1cf570603`; all ten retained ordinary Nix outputs,
the original persistence proof and published EFI files passed subsequent checks.

This package accepts only the original factory bytes. The existing boot-only
package and recovery backend are unchanged. The disk still has 33 partitions
and no swap. Host tests cover partial-write/restoration failures; provisioning
a changed layout and recovering it on hardware remain separate work. See
[STORAGE_QUALIFICATION.md](STORAGE_QUALIFICATION.md) for exact bounds, artifacts
and the fixed-swap prerequisites.
