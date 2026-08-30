# Gemini Little Kernel audit

Status: 2026-08-29. Keep the working vendor LK. Rebuilding it is useful for
source-level diagnostics and binary comparison, but current upstream LK is not
a replacement for it.

## Source lineage

The public source family that almost certainly matches p20 is Planet's Android
8 [`gemini-lk-android8` at `f4988d7`](https://github.com/dguidipc/gemini-lk-android8/tree/f4988d74bb70a0a15d7f362f412afba7e7fcda46).
Its `k97v1_64_bsp` target specifies:

- MT6797 and `MEMBASE=0x46000000`;
- the exact two Gemini panel names;
- GPT/eMMC and Android image handling;
- FDT and 64-bit secure-monitor handoff;
- PMIC, charger, watchdog, verified boot, and fastboot.

The relevant source definitions are
[`k97v1_64_bsp.mk`](https://github.com/dguidipc/gemini-lk-android8/blob/f4988d74bb70a0a15d7f362f412afba7e7fcda46/lk/project/k97v1_64_bsp.mk#L261-L319)
and
[`rules.mk`](https://github.com/dguidipc/gemini-lk-android8/blob/f4988d74bb70a0a15d7f362f412afba7e7fcda46/lk/target/k97v1_64_bsp/rules.mk#L379-L444).

The p20 body independently matches that lineage: it is 430,856 bytes, loads at
`0x46000000`, contains MT6797 platform strings and both exact Gemini panel
names, and follows a standard 512-byte MediaTek LK header. This is near-certain
lineage, not a bit-identical reproduced build. The historical Android BSP,
generated inputs, vendor libraries, old ARM toolchain, and possibly signing
inputs still need recovery.

The vendor target reserves `0x03200000` (50 MiB) for kernel decompression,
consistent with the behavior recovered from p20.

## Watchdog and secure handoff

The retained p20 reverse-engineering record proves that the normal LK path
arms the MT6797 watchdog with timeout argument `10`, kicks
`0x10007008 = 0x1971` before handoff, and enters ATF with
`smc 0x82000200` (`artifacts/lk-analysis/REVERSE_ENGINEERING.md:7-18,47-65`).
The exact current live p24/p25 ATF image and its static trace are recorded in
[`ATF_WATCHDOG_HANDOFF.md`](ATF_WATCHDOG_HANDOFF.md): both labels resolve to
5,242,880-byte partitions with SHA-256
`82eb00d45057489a5964b14cfe534d883ed16b4ca335d80920c5e7e286160c32`, and
both are byte-identical to the local 98,304-byte `tee.img` container followed
by zero padding. Its normal `0x82000200` handler has no direct WDT mode,
length, or disable write; the only direct ATF WDT access is an EL3 exception
path restart kick at binary offsets `0x10950-0x10958`.

This proves the current ATF's direct register behavior, not the elapsed
SMC-to-Linux timing or a runtime reset. Continued counting of LK's nominal
watchdog until Linux probes is the bounded hardware-state inference; do not
promote it to DEVICE-TESTED recovery.

## Why not update to upstream LK

Current upstream LK has only
[basic generic MT6797 support](https://github.com/littlekernel/lk/tree/master/platform/mediatek/mt6797):
UART, timer, interrupt, GPT, watchdog, and simple memory initialization. It
lacks Gemini's eMMC boot path, Android image parser, FDT and secure handoff,
panels, PMIC, charger, and target definition.

Replacing vendor LK with upstream LK would therefore be a large new bootloader
port, not an update. It would add risk without helping the immediate kernel
bring-up.

## Recommended LK work

1. Preserve p20/p21 and continue booting both vendor and mainline kernels with
   the known-good LK.
2. Reconstruct an unmodified `k97v1_64_bsp` build using the historical
   toolchain and Android BSP inputs.
3. Compare header, size, load address, strings, symbols, and disassembly with
   the saved p20 image.
4. Use the source build for diagnostic-only instrumentation after comparison.

Do not flash a rebuilt LK merely because it compiles. A valid MediaTek header
does not prove that preloader/ATF authentication or signing requirements are
satisfied, and p20/p21 must not be treated as casually recoverable test slots.
