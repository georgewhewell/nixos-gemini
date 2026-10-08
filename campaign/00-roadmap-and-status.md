# Gemini PDA mainline campaign: evidence first

Current status, 2026-10-08: use [the completion ledger](../research/HARDWARE_STATUS.md)
and the dated results in each campaign chapter. The maintained kernel pin is
`ca4b6d9b98e2b0dd3130eea37de405f680afa41d`; M69 remains the installed recovery
baseline. Automatic A72 parking has passed repeated hardware load/idle cycles and
service-stop restoration,
and coupled A53/CCI voltage scaling has passed bounded tests down to770mV.
These results do not qualify the normal cgroup2 generation: its allocator
failure remains unresolved. USB3 SuperSpeed and the other unfinished hardware
items are listed in the completion ledger. Camera and vibrator are excluded;
physical keyboard work is deferred.

## Historical August–September ledger

The remainder of this page preserves the earlier campaign baseline and its
requirements. Its statements about the current image, active drivers, missing
recovery, and next activation gates describe that earlier baseline. They must
not override later device evidence or the owner's current instructions.

This historical evidence ledger was corrected on 2026-08-30 against
`nixos-gemini@e118018605a8c5ded99973b2902e9f930fb88eff`,
`linux-gemini-platform@28c47150235be70cf5b19ea8d9ce7a5473ec23f2`, the
retained hardware ledger, and Cycle18 live probe artifacts. The Nix flake at that time pinned
that Linux revision; it is not the currently selected kernel.

The local 3.18 vendor checkout is currently a mutable worktree. Citations to
`vendor/gemini-linux-kernel-3.18/<path>:<line>` identify text inspected in that
tree; they do not assert an immutable vendor revision, a successful build, or
Gemini hardware behaviour. If a fact lacks a source, build, or device record,
this guide says **could not determine** rather than filling the gap.

| Label | Meaning |
| --- | --- |
| SOURCE EXISTS | A named source, DT description, or retained record exists. It says nothing about a build or device. |
| BUILD-TESTED | A named build record exists. It says nothing about device behaviour. |
| DEVICE-TESTED | A retained Gemini observation passed, within the scope stated. It does not transfer to another image, overlay, cable, or peripheral. |
| INERT / OPT-IN | The base DT keeps the consumer disabled, or a separate overlay enables it. Neither label is a device result. |
| UNKNOWN | No sufficient evidence. The next observation is stated explicitly. |

## Current milestone and device-state boundary

The current full NixOS Stage2 is running from p22. Its current SHA-256 is
`dddc5eb82952c8e597756c284c30558c2b78d6a41d3fc6357da71f4eb40084db`, and the
Cycle18 MANIFEST identifies Linux revision
`59d0d28adfcc3d25e98b3a82cb05bea85058290b`. Read-only live checks retain the
known-good gadget/SSH path, right-port RTL8156 Ethernet, pstore, and watchdog.
The image intentionally composes InputObserve, not DeviceActivation: the
touchscreen, MicroSD, and fuel-gauge child remain disabled in the running DT.

Cycle18 also performed two bounded live overlay probes. The touchscreen probe
bound `1-0062` to `novatek-nt36xxx`, detected NT36772 trim
`00 00 03 72 66 03` at `1080x2160`, created `event2`, and cleanly removed and
restored the client/adapter disabled status while both networks and the
watchdog stayed active. Its exact artifacts are
`/mnt/Home/src/gemini-live-probe-cycle18-touch-20260830`. A second read-only FG
preflight used `gemini-live-fgadc` with `activate=N` and reported exact-active
state `ckpdn=0x1270 con0=0x29 osr=0x8`, no child/power_supply, and clean removal;
its exact artifacts are
`/mnt/Home/src/gemini-live-probe-cycle18-fg-preflight-20260830`.

Neither probe is physical touch or charging evidence. No physical key, display,
audio, Hall, suspend, radio, modem, camera, GPU, or battery behavior is claimed
without a corresponding observation.

## Front-page status matrix

| Area | Evidence that exists | What it does **not** prove / next falsifiable gate |
| --- | --- | --- |
| Recovery, serial, eMMC | Current p22 is `dddc5eb8…84db`; Cycle18 MANIFEST identifies Linux `59d0d28a…58290b`; full Stage2, pstore, gadget/SSH, and p22/p30/p31 reads are live evidence. | It does not prove write safety, alternate-slot selection, or unattended recovery. Recheck all hashes before any write. |
| Left USB gadget and right host Ethernet | Current live UDC is configured high-speed `g_ether`; `usb0=10.15.19.82`; right MUSB host enumerates RTL8156 `0bda:8156` and `enu1=192.168.23.70`; Cycle18 kept both nets active during overlay removal. | It does not prove PD, dynamic roles, charging, or other cables/adapters. |
| Display | Current live DRM has connected/enabled DSI-1 at `1080x2160` and fb0; dmesg binds the display components. | BOUND-UNVERIFIED: no physical pixels/image observation. Gate: one recovery-slot modeset plus physical panel observation. |
| Audio | Current live ALSA card is `mt6797mt6351` with playback/capture nodes; AFE and machine-card probes succeed. | BOUND-UNVERIFIED: no physical playback/capture, jack, amp, or UCM result. |
| Touch | Current InputObserve image keeps I2C4/client disabled. Cycle18 read-only activation nevertheless bound `1-0062`, detected `NT36772 trim 00 00 03 72 66 03 detected (1080x2160)`, created event2, and cleanly removed/restored disabled status (`/mnt/Home/src/gemini-live-probe-cycle18-touch-20260830/dmesg-applied:1885-1894`). | This proves identity/probe cleanup only, not physical touch. Keep normal image inactive pending a separately reviewed activation gate. |
| Keyboard | Current matrix input0 is present and polling at 20 ms. User observation on 2026-09-02: ordinary physical keyboard use works, but the `Fn` modifier does not. | LOW-PRIORITY FUNCTIONAL GAP. Gate: bounded `evtest`/scan-code capture comparing `Fn` alone and `Fn` chords, then determine whether the loss is in the matrix driver, keymap, or userspace translation. LEDs/flash remain out of scope. |
| UEFI and boot UX | WISHLIST, IMPLEMENTATION CHOSEN: keep stock LK/ATF, chainload U-Boot from p22, and use U-Boot's EFI loader, GOP and console input to run `systemd-bootaa64.efi`. | extlinux is only an early diagnostic fallback; EDK2 and upstream LK are not parallel ports. Gates include reliable display/GOP output, pre-boot keyboard input including modifiers, EFI-variable and ESP storage, deterministic DT/UKI handoff, and repeated `ExitBootServices()` plus recovery testing. |
| Charger, battery and PMIC | BQ25896 observer is bound at `3-006b`, `online=1`, `Not charging` (`/mnt/Home/src/gemini-live-probe-cycle18-fg-preflight-20260830/dmesg-applied:1763-1770`); Cycle18 FG preflight with `activate=N` reported `ckpdn=0x1270 con0=0x29 osr=0x8`, no child/power_supply, and clean removal (`/mnt/Home/src/gemini-live-probe-cycle18-fg-preflight-20260830/dmesg-applied:1895-1901`). | BOUND-UNVERIFIED observer only. Battery capacity, charge control, CHR_STAT, and safe policy remain could not determine. |
| CONSYS, Bluetooth, GNSS, Wi-Fi and FM | SOURCE EXISTS for a dormant MT6797 WMT patch controller (`linux-gemini-platform@28c471502:drivers/soc/mediatek/mt6797-consys-wmt-patch.c:1-42,398-464`), whose current code requires a private full-STP lease before patch download. Stage A explicitly saw no WMT/BTIF/CONSYS device or firmware request (`research/HARDWARE_TEST_LEDGER.md:300-301`). | There is no live transport, identity read, firmware download, GNSS, Bluetooth, Wi-Fi or FM result. The next safe code gate is full STP validation; do not enable a radio client or release reset in a hardware test. |
| Cellular, SIM and eSIM | WISHLIST: the stock Gemian oracle exposes the vendor MD1/CCCI, oFono and ConnMan control plane, but the installed physical SIM is reported by the owner as expired and cancelled. Registration failure or absent data on that profile is therefore not a modem-driver verdict. | The target flow is mainline-only CLI eSIM/eUICC inventory, active-SIM selection, profile download/enable and later registration/data validation with a live profile. Do not provision an eSIM under Android/Gemian or make a one-time Android setup boot a prerequisite; identify and implement the underlying SIM-mux, persistent-state and eUICC operations in the open stack. |
| Watchdog / unattended recovery | Current live `/dev/watchdog0` is an active `mtk-wdt` with timeout 31 seconds and `nowayout=1`; boot dmesg and userspace petting are present, and Cycle18 overlay cleanup retained watchdog continuity. | This proves an active Linux watchdog path, not that a deliberate hang resets and recovers the device. Pre-init margin, reset observation, and unattended recovery remain could not determine; preserve exact candidate/rollback/readback and bounded recovery waits before any write. |
| GPU, modem, cameras, sensors, MicroSD | GPU, BMI160, modem, camera, and MicroSD consumers remain inactive or absent in the current DT/runtime. Thermal raw SoC readout exists; no physical external sensor result. | UNKNOWN / IMPLEMENTED-INACTIVE. Keep disabled until per-device rail, bus, identity, and rollback evidence exists. |

## Blocking facts, not workarounds

1. **Recoverability is not yet unattended.** The current Linux watchdog is
   active (`/dev/watchdog0`, 31-second timeout, `nowayout=1`) and was kept alive
   through Cycle18 cleanup, but no deliberate hang/reset/recovery observation
   exists. A host can observe BROM and Flash Tool, but no remote reset/power
   actuator is evidenced; a dead device still requires the bounded/manual
   recovery path (`research/ATF_WATCHDOG_HANDOFF.md`).
2. **The artefact boundary is current and explicit.** Nix pins
   `28c471502` (`flake.nix:23-28`). Current full NixOS intentionally composes
   InputObserve, not DeviceActivation; source overlays alone do not change that
   image.
3. **Touch identity is now observed, activation is not.** Cycle18 detected the
   exact NT36772 trim and removed/restored the client cleanly, but retained no
   physical touch events; normal image activation remains a separate gate.
4. **Battery/charging is observational only.** BQ variant, CHR_STAT route,
   fuel-gauge path and safe charging policy could not be determined; do not
   turn the observer into a control plane.

## Next eight falsifiable gates, ranked by impact and independence

1. **Recovery invariant (highest impact).** Recheck p22
   `dddc5eb8…84db`, p30/p31 hashes, pstore, SSH, gadget, and the Cycle18
   MANIFEST. Pass only if every identity is captured; otherwise stop before any
   write or overlay experiment.
2. **Display pixels.** In a recovery-slot image, run one declared modeset and
   retain DRM state, regulator errors, and a physical panel observation. Driver
   binding alone fails this gate.
3. **Touch event.** Preserve the Cycle18 NT36772 identity/cleanup result, then
   separately capture a physical press/coordinate event with network and
   watchdog continuity. Keep normal InputObserve composition unchanged until
   pass.
4. **Keyboard/Hall events.** Capture bounded matrix press/release, `Fn` alone,
   representative `Fn` chords, and one Hall transition, with no LED or flash
   activation. Preserve raw scan codes before changing a keymap; a present input
   node is not a physical event.
5. **Power and fuel gauge.** Repeat the `activate=N`,
   `ckpdn=0x1270 con0=0x29 osr=0x8`, no-child/power_supply preflight; only a
   separately reviewed read-only battery/charger identity may follow. No
   charging or fuel-gauge ownership transition is implied.
6. **Storage lineage and MicroSD.** Re-audit 11230000/11240000 pin, rail and
   card-detect lineage, insert a known card, and capture read-only CID/size/I/O.
   Pass requires controller lineage, not an `mmcblkN` number; current evidence
   proves no MicroSD card.
7. **Audio and suspend.** Independently capture one bounded playback/capture
   stream and one suspend/resume wake path, retaining pstore and watchdog
   continuity. ALSA nodes and an empty suspend-state interface are not passes.
8. **Connectivity and dormant devices.** Complete hardware-independent full-STP
   validation, then separately observe radio identity with reset asserted; GPU,
   camera, modem, IMU and SCP remain disabled until their own rail/bus/identity
   gates exist. No radio firmware or reset release follows from source alone.

Every hardware handoff must name the immutable source/input revisions, exact
image and DT overlay, target partition, expected log, acceptance timeout,
rollback image and evidence location. A source diff, a cross-build, a DTBO
composition or KUnit result is never promoted to DEVICE-TESTED by prose.
