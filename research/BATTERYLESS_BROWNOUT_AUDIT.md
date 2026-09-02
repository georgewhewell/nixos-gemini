# Gemini USB-only batteryless brownout audit

Date: 2026-09-02  
Scope: offline source/configuration review only. No reset, flash, boot, cable,
power, or live hardware probe was performed.

## Inputs

The reviewed worktrees were clean at review time:

| Area | Worktree | Revision |
| --- | --- | --- |
| Linux/Nix low-power profile | `/home/grw/src/nixos-gemini-usb-only-low-power-20260902` | `73499c5` (`codex/usb-only-low-power-20260902`) |
| Linux power-survival overlay | `/home/grw/src/linux-gemini-usb-only-power-minimal-20260902` | `93aad395d` (`codex/usb-only-power-minimal-20260902`) |
| LK handoff | `/home/grw/src/gemini-lk-batteryless-handoff-20260902` | `75c802a` (`codex/batteryless-charger-handoff-20260902`) |
| Vendor Android LK/kernel reference | `/home/grw/src/gemini-lk-android8/lk`, `/home/grw/src/gemini-linux-kernel-3.18` | LK `f4988d7`; vendor kernel worktree as checked out |

The source/configuration inputs are evidence, not a claim that any binary was
run on the device.

## What is already the safe Linux minimum

The Nix profile explicitly says it retains only CPU0, eMMC, the left-port
gadget, SSH, and watchdog, while omitting display, right-port VBUS, and
peripheral overlays (`/home/grw/src/nixos-gemini-usb-only-low-power-20260902/flake.nix:746-764`).
It selects `maxCpus = 1` and the storage overlay, so this is one A53 plus the
diagnostic storage path, not an SMP bring-up.

The generated kernel command line makes that cap unconditional:
`/home/grw/src/nixos-gemini-usb-only-low-power-20260902/nix/mainline.nix:181-185`
(`maxcpus=${toString maxCpus}`, with `maxCpus = 1` above). The handoff and USB
diagnostic fragments independently retain both serial/earlycon and
`maxcpus=1` (`/home/grw/src/gemini-pda-mainline/configs/gemini-handoff.fragment:61-82`,
`/home/grw/src/gemini-pda-mainline/configs/gemini-usbdiag.fragment:1-5`).

The retained diagnostic interfaces are deliberately narrow:

* left-port MTU3 gadget only; no host, dual-role, VBUS source, USB3 PHY, or
  Type-C policy (`configs/gemini-usbdiag.fragment:66-76`);
* USB Ethernet/RNDIS, with mass-storage/configfs/multi-gadget disabled
  (`configs/gemini-usbdiag.fragment:115-121`);
* TTY and PTYs remain available for the serial shell
  (`configs/gemini-usbdiag.fragment:123-129`);
* eMMC is enabled only by the explicit development overlay, with PMIC wrapper,
  MT6397 MFD, MT6351 regulator, MMC block, and MTK MMC
  (`configs/gemini-emmc-development.fragment:1-15`).

The power-survival DT overlay does not add a new current request. It exposes the
LK-configured BQ25896, asks Linux to adopt firmware settings, and leaves the
charger node writable (`/home/grw/src/linux-gemini-usb-only-power-minimal-20260902/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb-power-survival.dtso:1-30`).
The Nix DT test requires the charger node to be `okay`, the adoption property to
be present, and `ti,read-only` to be absent, while also requiring GPU and CONSYS
to be disabled (`flake.nix:766-783`). This preserves power diagnostics without
introducing a Linux-side charger reset or reprogramming race.

## Where the early peak is likely coming from

### Preloader/LK boundary

The reviewed LK project enables eMMC, BQ25896, charger interface, and debug UART
(`lk/project/k97v1_64_bsp.mk:3-14,22-27`). It does not enable the existing
`MACH_FPGA_NO_DISPLAY` compile-time escape hatch: that line is commented out
(`lk/project/k97v1_64_bsp.mk:23-27`).

In normal boot, LK emits a PMIC vibrator pulse for 200 ms and waits another
400 ms (`lk/platform/mt6797/platform.c:597-604`). It then initializes the
framebuffer/display and updates a full panel-sized rectangle
(`lk/platform/mt6797/platform.c:679-712`), loads a boot logo
(`platform.c:731-739`), shows the boot logo and turns on the backlight
(`platform.c:845-857,864-884`). Those are the strongest source-level early
peak candidates: panel rails/backlight and logo traffic are before Linux has a
chance to apply its DT or `maxcpus=1` policy. eMMC initialization remains at
`platform.c:614-619` and must stay for the requested diagnostics.

LK also restarts its platform watchdog immediately before the kernel jump
(`lk/app/mt_boot/mt_boot.c:1806-1818`). The handoff branch now disables the BQ
watchdog in `platform_uninit()` immediately before the existing deinit path
(`lk/platform/mt6797/platform.c:913-922`). That is a handoff-correctness change,
not a peak-current reduction, and must not be replaced with an unverified
charger-current write.

### Charger settings

The vendor BQ driver initializes ICHG to 2048 mA and IINLIM to the maximum code
in LK (`lk/platform/mt6797/bq25890.c:766-799`), then uses lower values after
charger-type detection, including 500 mA input/charge for a host
(`bq25890.c:845-854`). The vendor Linux driver also starts with 500 mA input and
2048 mA charge (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/power/mt6797/bq25890.c:675-681`).
These are charger policy values, not a measured USB-source budget. Lowering
them in LK could starve the system; rewriting them in Linux would violate the
firmware-adoption handoff and could race the charger watchdog. No safe limit
change is justified by source evidence alone.

### Linux boundary

Linux cannot undo the pre-kernel panel/vibrator work. Once Linux starts, the
profile has already removed CPU concurrency (`maxcpus=1`), omitted CPU_FREQ and
CPU_IDLE from the minimal handoff fragment (`configs/gemini-handoff.fragment:173-188`),
and disabled GPU/CONSYS in the survival DT test (`flake.nix:775-783`). The
remaining eMMC and left-gadget probes are explicitly in scope, so removing them
would defeat the requested diagnostics. The broad vendor kernel illustrates why
this profile is materially smaller: it enables SMP/10 CPUs, CPU_FREQ, GPU/DVFS,
USB dual-role/host paths, vibrator, and eMMC CQ/cache
(`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/configs/aeon6797_6m_n_defconfig:23-25,45-51,186-197,273-292,447-471`).

## Decision

No additional behavioral patch is safe to commit offline.

The smallest defensible software envelope is the existing one: LK handoff with
the charger-watchdog fix; Linux `maxcpus=1`; GPU, CONSYS, display activation,
right-port host/VBUS, and unrelated peripheral overlays disabled; left USB
gadget, eMMC, and serial diagnostics retained; BQ firmware settings adopted
without new current writes.

The LK display/backlight/vibrator paths are worth a separately instrumented
hardware experiment, but introducing a new display-suppression macro or
changing BQ limits here would alter pre-kernel behavior without validation and
could remove the only useful handoff/diagnostic path. This audit therefore makes
no such change.

## Offline validation

On this worktree:

```text
git diff --check
nix-instantiate --parse nix/mainline.nix
git status --short --branch
```

The first two checks pass; the final status is clean after the audit commit.
