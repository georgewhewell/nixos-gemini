# MT6797 connectivity implementation plan

Status: M0 merged, pinned, and booted; M1/M2 groundwork is next. This document records
merge order and safety gates. Hardware claims belong in the cited evidence
records; unsupported guesses do not become contracts by appearing here.

## Goal and first useful result

The immediate goal is raw GNSS data through the standard Linux GNSS API. The
installed MT6797 firmware exposes GNSS as STP task 2 inside the shared CONSYS
connectivity subsystem. It is not an independent MMIO receiver.

The minimum runtime path is:

```text
CONSYS power/reset/firmware owner
        |
        v
MT6797 BTIF + APDMA byte transport
        |
        v
STP framing and task multiplexer
        |                    |
        v                    v
WMT task 4             GNSS task 2
(boot/function control) (/dev/gnss0)
```

Bluetooth, Wi-Fi, FM, Android WMT character devices, the Android GNSS HAL,
SUPL, and assisted-location services are not required for the first result.
The shared layers must nevertheless be designed so Bluetooth and FM can become
additional STP clients without taking ownership away from CONSYS.

## Evidence baseline

The source and runtime baseline is preserved in
[`artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/`](../artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/).
In particular:

- the live capture proves the CONSYS and BTIF/APDMA resources, bound vendor
  owners, active BTIF DMA interrupts, firmware names and observed load order;
- the source design record traces the vendor CONSYS, BTIF, STP, WMT, and GPS
  call paths and compares them with Linux 7.1.3;
- [`vendor-kernel.config`](vendor-kernel.config) proves that normal Gemini GPS
  uses STP and that the optional `GPS_EMI`/`MNL.bin` path is disabled; and
- the extracted `WMT_SOC.cfg` and ROM patches are local evidence only. Their
  redistribution rights have not been established.

The active shared transport is BTIF/APDMA. SDIO remains relevant to the Wi-Fi
HIF and vendor initialization, but it is not a substitute for the captured
BTIF path carrying shared STP traffic.

## Stable internal boundaries

| Owner | Owns | Must not own |
| --- | --- | --- |
| CONSYS core | shared power state, reset, reserved EMI, firmware lifecycle, BGF/WDT recovery, function references | STP framing, GNSS ABI, HCI ABI |
| BTIF transport | BTIF registers, TX/RX APDMA rings, three transport IRQs, byte TX/RX, quiesce | WMT meanings, firmware selection, GNSS/HCI policy |
| STP core | mandatory/full framing, stream parser, task routing, sequence/ACK/window state, retry policy | clocks, DMA, firmware files, userspace ABI |
| WMT client | serialized task-4 transactions, exact response matching, boot/mode switch, function on/off | Android ioctl ABI, GNSS data path |
| GNSS client | function reference, task-2 TX/RX, `gnss_insert_raw()` | raw CONSYS MMIO, firmware boot, Bluetooth helpers |

No GNSS code may write CONSYS registers or call Bluetooth-owned `btmtk_*`
helpers. No function client may independently reset the shared subsystem.

## Worktree and merge discipline

Parallel agents work in isolated Linux worktrees based on the same integration
commit. Each worktree owns a bounded file set and produces follow-up commits;
agents do not amend, rebase, or merge one another's branches.

The orchestrator reviews each diff, reconciles the small shared Kconfig and
Makefile edits, builds the combined tree, and only then advances the integration
branch and Nix flake pin. New files must be Git-tracked before a Nix build.

Current first-wave branches:

| Branch | Worktree | Scope |
| --- | --- | --- |
| `gemini-consys-inventory` | `/home/grw/src/linux-gemini-consys` | disabled CONSYS schema/node and non-mutating resource validation |
| `gemini-stp-core` | `/home/grw/src/linux-gemini-stp` | hardware-free STP codec/mux and KUnit tests |
| `gemini-btif-inventory` | `/home/grw/src/linux-gemini-btif` | BTIF/APDMA schema and non-mutating resource validation |

The reviewed M0 series is integrated on `gemini-v7.1.3` and published at
Linux commit `6191785e643cb6397255eb417342ede9ed7fdc3f`. The flake enables the
three hardware-free foundations, while the CONSYS node remains disabled and no
BTIF node exists in the deployed Device Tree.

The 2026-08-30 default-slot boot test reached NixOS stage 2 and exposed SSH on
the left-port USB gadget. The 16 MiB p22 readback matched the flashed image at
SHA-256 `08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3`.
The live Device Tree reported CONSYS `disabled`, contained no BTIF node, and
the log showed driver registration without a CONSYS or BTIF hardware probe.

## Milestones and gates

### M0: protocol and inventory foundations

- CONSYS and BTIF descriptions remain disabled by default.
- Resource probes perform no MMIO access, clock/regulator/reset operation, IRQ
  request, DMA allocation, firmware request, or reserved-memory mapping.
- STP mandatory/full framing is checked against vendor vectors and KUnit covers
  fragmented input, integrity failures, parser recovery, length limits, and
  task-2/task-4 isolation.
- ARM64 object builds, Gemini DTB, schema checks, `git diff --check`, and
  checkpatch pass before merge.

This milestone is boot-safe and does not justify claiming connectivity works.

### M1: passive resource probe

Enable only the non-mutating inventory nodes in a diagnostic image. Verify that
the resolved addresses, IRQs, clocks, reset, supplies, and 2 MiB no-map region
match the captured vendor system. The driver must still perform no hardware
operation. Disable the nodes again if any resource differs.

### M2: bounded CONSYS identity experiment

Before implementation, resolve these blockers with a passive vendor trace:

- three vendor implementations disagree on the CONN bus-protection mask;
- current mainline MT6797 SCPSYS lacks CONN and eagerly powers every registered
  domain during provider probe; and
- the required AFE writes and second WDT IRQ semantics remain unverified.

Add a lazy CONN power domain only after the protection mask is proven. The
first opt-in hardware transaction is limited to asserting reset, enabling the
minimum rail/domain, reading MCU chip ID `0x0279`, and unwinding in reverse.
It must not load firmware, touch AFE, enable BTIF, or request radio functions.

Gate: repeated cold-boot success, bounded polling, before/after register traces,
and a failure path that leaves reset asserted and all references released.

### M3: BTIF/APDMA local loopback

Implement coherent 8 KiB TX/RX rings, pointer/wrap handling, ordered WPT/RPT
updates, IRQ acknowledge/masking, and deferred RX delivery. Keep the transport
byte-only. Use the documented internal loopback mode before involving CONSYS
firmware.

Gate: at least 1000 deterministic wraparound transfers with exact data return,
no IRQ storm, no parser loss, clean close, and clean power unwind.

### M4: WMT bootstrap and firmware

Implement serialized task-4 transactions and exact event matching. Begin in
mandatory STP mode, run only the evidenced MT6797 initialization sequence,
switch to full mode, and then download the locally installed ROMv3 patches.
Use the normal firmware-class API; never reproduce Android's ueventd copy
fallback.

Gate each command on exact type, opcode, length, status, and timeout. Record a
bounded transcript without firmware contents. Any mismatch quiesces DMA,
releases CONSYS ownership, and leaves diagnostics available. File selection,
header validation, patch addresses, and the observed `1_1` then `1_0` order
must be independently proven before the first live download.

### M5: GNSS task 2

Add a GNSS-core client only after WMT bootstrap is repeatable:

- first open acquires the shared CONSYS function reference, performs verified
  GPS function-on, and registers STP task 2;
- `write_raw` frames task-2 payloads;
- task-2 RX calls `gnss_insert_raw()`;
- last close unregisters/drains the endpoint, performs function-off, and drops
  the reference; and
- shared reset sends a defined disconnect/error to open GNSS users before any
  recovery replay.

Start without GPS-LNA control. Although vendor code names GPIO69, the deployed
configuration and physical population/polarity do not yet prove a safe board
binding.

Gate: `/dev/gnss0` produces checksum-valid NMEA, repeated open/close powers the
function cleanly, malformed STP never reaches userspace, and recovery has no
stale data or use-after-free.

### M6: shared consumers and hardening

Only after GNSS works, add Bluetooth task 0 through the standard HCI API and
test GNSS/Bluetooth concurrency. FM task 1 and Wi-Fi are separate later tracks;
Wi-Fi requires its own firmware MAC/APDMA HIF and is not an `mt76` compatible
by family resemblance.

Add tracepoints and read-only counters for state transitions, BTIF IRQ/ring
state, STP frame metadata, retries, drops, WMT transactions, function votes,
and reset generations. Do not log payloads or firmware by default.

## Parallel implementation waves

1. M0 runs as the three independent branches listed above.
2. After their interfaces merge, three new branches may run concurrently:
   lazy CONN/identity, BTIF DMA/loopback, and WMT parser/state-machine tests.
3. WMT live bootstrap begins only after the first two hardware branches merge.
4. GNSS begins against the tested task-2 and function-control APIs; recovery
   and concurrency follow as separate branches.

The device's known-good default image remains unchanged through M0. Every live
milestone gets its own explicit enable commit, build artifact, expected log,
timeout, and rollback image. A compile pass is evidence of API correctness; it
is never reported as evidence of hardware function.
