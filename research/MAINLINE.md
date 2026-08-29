# Mainline Linux on MT6797 and Gemini

Status: 2026-08-29. MT6797 is upstream enough to start a headless Gemini port,
but upstream alone cannot yet provide storage or USB networking on this board.
An active Gemini-specific project now reports the desired minimal feature set
locally, so reproducing and auditing that work is the shortest path.

## What happened to the historical patches

The remembered LKML effort was principally the 96Boards X20 port, not Planet
Gemini. It did not simply disappear:

- basic MT6797 DTS and EVB support landed in
  [`464c510`](https://github.com/torvalds/linux/commit/464c510f60c6016d92cc67e7548413f85a78c1c5);
- the X20 board DTS landed in
  [`a873996`](https://github.com/torvalds/linux/commit/a873996921296ad74941017bf00884f14e10dffd);
- basic pinctrl landed in
  [`f969b7a`](https://github.com/torvalds/linux/commit/f969b7aac980a26d3b5d126947989d4b072f27b4);
- I2C nodes and X20 board enables landed in
  [`d3c8429`](https://github.com/torvalds/linux/commit/d3c84299f2088e3927bcbe36a458744a3b804d6d)
  and
  [`1f3f873`](https://github.com/torvalds/linux/commit/1f3f87305ed6ae5fcf5f638fa1c3846e07c32829).

Review deliberately scoped MT6797 pinctrl to GPIO and mux. Advanced drive and
pin configuration were deferred, not rejected.

Gemini-specific 4.19 work reached a serial BusyBox shell. Its notes identify
three concrete problems: disabling critical clocks corrupted memory, SCPSYS
could not represent domain gaps, and PWRAP needed an infracfg reset. See
[`gemini-pda-buildroot`](https://github.com/Jasu/gemini-pda-buildroot/blob/master/README.md#L147-L168).
The related SCPSYS Patchwork series remains "Action Required," rather than
merged.

## Current upstream boundary

Current upstream
[`mt6797.dtsi`](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/mediatek/mt6797.dtsi)
contains PSCI, ten CPU descriptions, timer, GICv3, clocks, basic GPIO/pinmux,
SCPSYS, watchdog, four UARTs, and I2C controllers.

It contains no Planet Gemini board and no usable MT6797 eMMC, USB,
PMIC-wrapper/MT6351 board integration, RTC, thermal, EINT, charger, or board
power description. Basic UART Linux is plausible from upstream; a useful
headless system still needs board enablement.

## Active Gemini work

The strongest current lead is
[`ixoo/gemini-pda-mainline`](https://github.com/ixoo/gemini-pda-mainline).
Its 2026-08-25
[hardware matrix](https://github.com/ixoo/gemini-pda-mainline/blob/main/docs/HARDWARE_SUPPORT.md)
reports a local Linux 7.1.3 integration that boots `/init` from `boot2` and has:

- USB gadget Ethernet and a network shell;
- watchdog takeover and native reboot;
- guarded eMMC development access;
- keyboard polling;
- a read-only PMIC/regulator provider;
- A53 CPU0-7.

The project labels these features **local**. This is a concrete and unusually
well-documented codebase to reproduce and audit, not independent proof and not
upstream support.

## Pinned Nix reproduction

The flake now integrates the smallest hardware-proven ixoo serviceability
baseline as separate outputs. It does not update LK and it does not change the
default vendor-kernel `bootImg`.

| Input | Pin or identity |
|-------|-----------------|
| ixoo kernel source/profile | `7199e8229c6a805a941e33a6862956949dfebd3a` |
| frozen candidate/DT tooling | `a24b2d264844ee2bb50e77dc7aceaa6b902c7b6a` |
| named profile | `da921x-lk-clock-readonly-provider` |
| Linux source | 7.1.3, SHA-256 `be41c068e88f5242a19bccdbffbe077b18c47b45f627e2325504b4fab79dd1dc` |
| compiler | Nix cross GCC 12.2.0 |
| canonical patch series | 271 patches, ixoo SHA-256 `ac1e5da43d6694178058c8a623405b2c53d8bd2782d5f1d3a23e05368dc18ae8` |

The profile fragment list is read from ixoo's pinned `kernel/manifest.json`,
not duplicated in the flake. The build rejects the wrong local version,
missing read-only NVMEM/provider gates, enabled A72/resource-owner paths, a
command line without `maxcpus=8`, a changed base DTB, or a Nix store path in
the kernel image. It also rejects any remaining Nix hardening-wrapper policy;
Kbuild alone owns kernel compiler hardening.

Ixoo later recorded one attributable hardware pass for this exact source and
profile: CPUs 0-7, USB gadget/netcat, I2C5/AW9523 keyboard, watchdog/native
reboot, and read-only LK-devinfo/DVFSP/I2C6/DA921x observation all passed. It
kept CPUs 8-9 closed and reported zero DA921x register-data writes. The proven
Buildbox identities were:

- `Image`: `c5d73e077165f0f22b0d8ff109661edc29763c12f4ed6fbd64b2d0fef910e1cc`
- `Image.gz`: `086d109464533194abed2c19fa56e647033edd957dafb2ee2512acd3100ed9f1`
- base DTB: `380205e0546c1b87f4ce6b4c34fcd734a22dc42e3b1c3145044d396a16e00709`
- serviceability DTB: `d7dba05efa272c8264c8ea15c776fb88c21a0012603214b49dfd9e2893e87d48`

The original serviceability ramdisk is identified by hash in ixoo's record but
is not published as a source artifact. This flake therefore builds a new,
deterministic static-BusyBox initramfs. It neither probes nor mounts a block
device. It configures `usb0` as `10.15.19.82/24`, retains a tty1 shell, and
offers an unauthenticated root shell on TCP 2323 over the direct USB link. It
also mounts pstore read-only and reports watchdog, UDC, cmdline, retained-record,
and dmesg-tail state without opening the watchdog.

The first Nix-built candidate boot-looped from p30 and produced no mainline USB
identity. Its raw ARM64 entry-ledger slots were empty after Gemian recovery,
but ixoo's own positive control could also return empty slots, so that result
does not locate the failure.

The build now provides two explicit variants. The config control retains
ixoo's exact selected config while disabling every Nix wrapper-hardening flag.
Its `Image` is still byte-for-byte the failed Nix image
`c3df398ebdbd6703e0385267c40c4f276a0aed1fa73d43463ee74a23d63dab38`.
That rules out the remaining wrapper-hardening environment as the cause; it
does not make this a Buildbox replay. The default diagnostic variant then
makes only the observability changes: `console=tty0`, ordinary ramoops instead
of the mutually exclusive raw entry ledger, and ixoo's post-ramoops marker.
Its `Image` is
`92339e8bf4b664652f3babfeb74455fa22101872cc23ca011680b2523cebb9b0`.
Both use GNU binutils 2.40 and both retain exact ixoo DTB hashes. Matching
GCC's version number is not a byte-reproducible match for the complete
Buildbox toolchain.

Build it with:

```sh
nix build .#mainlineBundle --out-link artifacts/mainline-bundle
cat artifacts/mainline-bundle/MANIFEST

# Optional failed-config control; not the preferred next attempt.
nix build .#mainlineConfigControlBundle \
  --out-link artifacts/mainline-config-control-bundle
```

The diagnostic build has:

- initramfs `83a7efe138e527e617cdd569569420d196aa3609f39c22c83207425891955b70`;
- raw Android-v0 image `4f755ef05beae390fa936ad97040b45636565e2e7fccbb288fc4eb2d6ef89a45`;
- padded p30 image `122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`.

Ixoo's own serializer enforces the retained Planet-LK contract: Android header
v0, 2048-byte pages, kernel `0x40200000`, ramdisk `0x45000000`, second
`0x40f00000`, tags `0x44000000`, exact ARM64 flags `0x0a`, gzip plus appended
DTB, and only `bootopt=64S3,32N2,64N2` in the Android header. A generic
`mkbootimg` was deliberately rejected because it zeroed the unused second
address. The padded output is exactly 16 MiB.

Its storage work found that MT6797 needs a dedicated MMC variant: borrowing the
MT6779 variant changes the wrong block-length register. The safe first storage
contract is 8-bit eMMC at 25 MHz, not HS200/HS400. See the
[MSDC findings](https://github.com/ixoo/gemini-pda-mainline/blob/main/experiments/2026-07-12-mt6797-msdc-recovery/README.md#L91-L110).
The PMIC investigation confirms that upstream has PWRAP transport data but
lacks the DTS node and mandatory MT6797 reset-controller integration; see
[PMIC recovery](https://github.com/ixoo/gemini-pda-mainline/blob/main/experiments/2026-07-11-mt6351-pmic-recovery/README.md#L135-L165).

## Live mainline NixOS milestone (2026-08-29)

The Nix-built Linux 7.1.3 image now boots from default p22, enumerates eMMC,
mounts p29 read-only with journal replay disabled, loop-mounts the distinct
gzip SquashFS payload, and reaches NixOS stage 2. The left MTU3 gadget remains
reachable at `10.15.19.82`; p31 remains the untouched Gemian recovery slot.

The right Type-C port is also a proven debug-network path:

- FUSB301A reports source/host and controls the GPIO94 5 V regulator.
- USB11 MUSB enumerates RTL8156 `0bda:8156` at 480 Mb/s and binds `r8152`.
- `rtl8156b-2.fw` version `v3 10/20/23` loads from the early initramfs.
- `CONFIG_PACKET=y` permits dhcpcd to acquire `192.168.23.70/24`; OpenSSH
  listens on `0.0.0.0:22`, and direct SSH from `192.168.23.8` succeeds.

The decisive controller fix is `patches/mt6797-usb11-multipoint.patch`.
Vendor `musbfsh_start()` unconditionally sets `is_multipoint = 1`; without the
same setting, mainline uses `MUSB_FADDR` instead of MT6797's per-endpoint target
address registers and descriptor traffic fails after address assignment with
`-EPROTO`. The Type-C/VBUS work was already correct at that point.

The current host path is deliberately `CONFIG_MUSB_PIO_ONLY=y`. Iperf3 against
trex measured 70.2 Mb/s transmit with zero retransmits and 57.8 Mb/s receive;
the latter produced 2,741 RTL8156 `rx_missed` events and CPU0 softnet time
squeeze. That is adequate for recovery and development. DMA/IRQ/RPS performance
work is separate from basic boot and network correctness.

The deployed p22 image SHA-256 is
`195a179824c092a64d1693c837be93db88b9458d6b1804a48eb40b58e6895867`.
Its initramfs includes `USB_MON`, dynamic debug, and the exact RTL8156 firmware
SHA-256 `5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f`.

## Minimal headless target

| Subsystem | Current basis | Work or constraint |
|-----------|---------------|--------------------|
| Entry/PSCI/timer/GIC | upstream | validate CPU0, then A53s; keep A72 offline |
| UART | upstream driver | Gemini mux and `ttyS*` command line |
| GPIO/pinmux | basic upstream | no EINT, pulls, or full pinconf yet |
| Watchdog/reboot | upstream fallback | prove LK watchdog takeover and native reset |
| USB gadget | local Gemini work | proven: MTU3 gadget, static recovery network |
| PWRAP/MT6351 | transport pieces plus local work | reset, MFD, regulator, IRQ integration |
| eMMC | local dedicated variant | proven at 25 MHz; p29 remains read-only |
| Thermal/power safety | incomplete | required before A72, DVFS, or sustained load |
| USB host Ethernet | local MT6797 work | proven FUSB301/VBUS/MUSB/RTL8156; PIO performance remains |

The vendor 3.18 tree is a hardware specification, not code to merge wholesale.
Use it for register maps, reset IDs, wiring, rail topology, clocks, and tested
constraints. Implement missing support through current kernel frameworks.

## Execution order

1. Boot the diagnostic Nix reproduction once from live-GPT-resolved
   p30/`boot2`. Require a framebuffer/initramfs marker, USB gadget shell, or a
   retained ramoops marker. If it fails, recover immediately and capture
   pstore before repeating or changing the profile.
2. Reproduce watchdog takeover and USB gadget Ethernet. Gadget networking is
   the first mainline debug plane; host USB networking comes later.
3. Audit/add MT6797 reset and PWRAP, minimal MT6351 VEMC/VIO18 regulators, then
   the dedicated MMC variant at 25 MHz. Start with read-only GPT/eMMC access.
4. Add thermal and regulator safety, then A53 SMP. Keep A72, DVFS, charging,
   and eMMC high-speed modes disabled until the safety layers are proven.
5. Add USB host, PHY, role switching, and Type-C control before relying on the
   external USB Ethernet adapter.
6. Split clean SoC, binding, driver, and Gemini DTS changes for upstream rather
   than sending a monolithic vendor-code port.

Display, GPU, Wi-Fi/BT/GNSS, modem, cameras, audio routing, and polished power
management are deliberately deferred. None is required for a stable,
network-reachable headless Linux system.
