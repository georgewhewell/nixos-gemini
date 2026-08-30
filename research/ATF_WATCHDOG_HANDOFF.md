# Gemini LK -> ATF -> Linux watchdog handoff

Status: 2026-08-30. This is the source-of-truth record for the exact live
TEE/ATF image and its watchdog handoff. The work was read-only: no block
device was mounted or written, and there was no reboot, flash, or harness
run.

## Exact live image identity

The live partition labels were resolved before reading:

```text
/dev/disk/by-partlabel/tee1 -> /dev/mmcblk0p24
/dev/disk/by-partlabel/tee2 -> /dev/mmcblk0p25
tee1 size = 5242880 bytes (10240 sectors)
tee2 size = 5242880 bytes (10240 sectors)
```

The exact read-only transaction was:

```sh
ssh -J trex -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  root@10.15.19.82 \
  'dd if=/dev/disk/by-partlabel/tee1 bs=4096 count=1280 iflag=fullblock status=none' \
  > /mnt/Home/src/nixos-gemini-atf-analysis/tee1-live.raw
ssh -J trex -i /home/grw/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  root@10.15.19.82 \
  'dd if=/dev/disk/by-partlabel/tee2 bs=4096 count=1280 iflag=fullblock status=none' \
  > /mnt/Home/src/nixos-gemini-atf-analysis/tee2-live.raw
```

Both reads produced 5,242,880 bytes and are byte-identical:

```text
tee1-live.raw SHA-256 = 82eb00d45057489a5964b14cfe534d883ed16b4ca335d80920c5e7e286160c32
tee2-live.raw SHA-256 = 82eb00d45057489a5964b14cfe534d883ed16b4ca335d80920c5e7e286160c32
```

The historical `2cd154f332ee72edb6dee431a68eb5f8b98b4dc05ee14e56591cfbffcf81a9b3`
value is not the current full-partition hash. It is retained historical
metadata in
`artifacts/ixoo-7199e822/experiments/2026-07-22-a72-firmware-power-contract/results/live-tee-identity-20260723.txt:9-17`.
The current live image is proven identical, through the complete 98,304-byte
ATF container, to the local
`firmware/gemini_x25_x27_base.zip` member `.../tee.img`:

```text
tee.img size = 98304 bytes
tee.img SHA-256 = 512d43a987c1659f4d9aecdff1436e5325ac314881e24926511be97e21d3d18e
cmp -n 98304 tee1-live.raw tee.img = identical
tee1-live.raw[0x18000..0x4fffff] = all zero bytes
```

The local copies and hashes are under
`/mnt/Home/src/nixos-gemini-atf-analysis/tee1-live.raw` and
`/mnt/Home/src/nixos-gemini-atf-analysis/tee2-live.raw`. The live header is
`88 16 88 58 00 7e 01 00 61 74 66` at binary offset `0x0`: magic
`0x58881688`, followed by the `atf` marker. The payload extent is
`0x1000..0x17dff`.

## ATF SMC path

The AArch64 disassembly uses the established analysis mapping base `0xff3c0`
(`artifacts/ixoo-a2f4a21/experiments/2026-08-21-mainline-secure-replay-epoch-audit/results/provenance-20260821.txt:11`).
On the exact live image, the dispatcher constructs and compares LK's SMC ID:

```text
VA 0x00108554 / file offset 0x9194: mov  w0, 0x200
VA 0x00108558 / file offset 0x9198: movk w0, 0x8200, lsl 16
VA 0x0010855c / file offset 0x919c: cmp  w5, w0
VA 0x00108560 / file offset 0x91a0: b.eq 0x108f78
```

The target at VA `0x108f78` (file offset `0x9bb8`) begins:

```text
0x00108f78  adrp x0, 0x117000
0x00108f7c  ldr  x0, [x0, 0x278]
0x00108f80  str  xzr, [x0]
0x00108f84  bl   0x104ca4
...
0x00108fc8  bl   0x109e3c
0x00108fd4  bl   0x10e448
0x00108fd8  bl   0x104cb4
0x00108fdc  b    0x109460
```

The exact live-image disassembly contains no direct WDT register write in
this normal `0x82000200` target path.

LK's side of this boundary is documented at
`artifacts/lk-analysis/REVERSE_ENGINEERING.md:7-18,47-65`: the early setup
passes timeout value `10`, the final normal handoff kicks the restart register,
and the AArch32 routine loads `0x82000200` before `smc 0`.

## WDT register access in exact live ATF

The vendor register definitions are
`vendor/gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/common/mt_wdt.h:19-24,51-52`:

```c
#define MTK_WDT_MODE       (MTK_WDT_BASE+0x0000)
#define MTK_WDT_LENGTH     (MTK_WDT_BASE+0x0004)
#define MTK_WDT_RESTART    (MTK_WDT_BASE+0x0008)
#define MTK_WDT_STATUS     (MTK_WDT_BASE+0x000C)
#define MTK_WDT_INTERVAL   (MTK_WDT_BASE+0x0010)
#define MTK_WDT_SWRST      (MTK_WDT_BASE+0x0014)
#define MTK_WDT_RESTART_KEY (0x1971)
```

The complete exact live image has one direct reference to the TOPRGU restart
register, in the EL3 exception path:

```text
VA 0x0010fd10 / file offset 0x10950: ldr x0, 0x10fff8 ; [0x10fff8:8] = 0x10007008
VA 0x0010fd14 / file offset 0x10954: ldr x1, 0x110000 ; [0x110000:8] = 0x1971
VA 0x0010fd18 / file offset 0x10958: str x1, [x0]
```

The literal scan found no direct references to `0x10007000`, `0x10007004`,
`0x1000700c`, `0x10007010`, or `0x10007014`. The restart write is reached by
the unhandled EL3 exception/interrupt handlers; it is not on the normal SMC
handler path. This excludes direct literal-address writes, not every possible
computed or undocumented secure alias.

## Linux boundary and experiment consequence

The legacy vendor Linux probe sets timeout 30, kicks, and then configures the
mode at
`vendor/gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/mt6797/mtk_wdt.c:758-787`.
The newer mainline driver first reads `WDT_MODE` and records handoff state at
`/home/grw/src/linux-gemini-platform/drivers/watchdog/mtk_wdt.c:323-345`, then
probes and conditionally starts the device at `:511-515`.

Consequently, a p22 kernel/DT/cmdline change cannot alter the LK/ATF state
before Linux starts. A userspace watchdog petter cannot cover a hang before
the Linux watchdog driver probes. Current exact ATF evidence removes the
former uncertainty about a direct ATF disable/reconfiguration: the normal
SMC path does not perform one. P22 experiments must still use bounded waits
and the existing rollback/lease discipline; they must not claim that a
userspace watchdog proves recovery from a pre-probe hang.

## Proof, inference, and unknowns

Proven:

- Current p24 and p25 resolve to `tee1`/`tee2`, are 5,242,880 bytes, and are
  byte-identical.
- The current live bytes are the local `tee.img` container plus zero padding.
- LK constructs the normal handoff SMC ID `0x82000200`.
- Exact live ATF dispatches that ID and has no direct WDT mode/length/disable
  write on that handler path.
- Exact live ATF has an exception-path restart kick of `0x10007008` with
  `0x1971`.

Inference:

- The LK-armed nominal 10-second watchdog remains counting through normal ATF
  handoff until Linux takes ownership, assuming the documented TOPRGU mapping
  and no separate reset-domain side effect.

Unknown:

- The exact elapsed SMC-to-Linux-probe time and the resulting watchdog margin.
- Whether any computed secure alias or hardware reset-domain behavior can
  affect TOPRGU without a direct `0x10007000`-range reference.
- Whether the historical full-partition hash `2cd154…` represented a prior
  image/padding state; it is not the current live partition hash.
