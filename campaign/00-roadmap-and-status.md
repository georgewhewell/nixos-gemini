# Gemini PDA mainline campaign: evidence first

This is the front-page evidence ledger, not a promise that a source tree has
run on the device. It was audited on 2026-08-30 against
`nixos-gemini@8be6542d7a9015d46a4d4944da6bac65f78bbe40`,
`linux-gemini-platform@51895763654e9cf0a97f7676dba7816847e08048`, and the
retained hardware ledger. The Nix flake still pins Linux at
`1bb2a9863d9a1e6d59e513eddbec68e2866310cd` (`flake.nix:23-28`), **not**
platform HEAD. Consequently every Linux change after that commit is source
evidence only for current Nix outputs until the pin is deliberately updated and
the result is built again.

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

The last independently rechecked Gemini baseline was the read-only observation
at 02:30--02:41: model/compatible, CPUs 0--7, left USB gadget plus SSH, right
Ethernet, read-only p29/store, pstore, and p22/p30/p31 identities were observed
(`research/HARDWARE_TEST_LEDGER.md:32-58`). The Stage-A p22 transaction later
repeated that bounded boot acceptance and established that no CONSYS/BTIF/WMT
device or firmware request appeared (`research/HARDWARE_TEST_LEDGER.md:291-311`).

That is not the current-state claim. The latest authorized p22 transaction
flashed a candidate, failed its 60-second acceptance window, flashed the
recorded rollback, then stopped at `manual_reset_required_no_ssh`; the gadget
was enumerated but Trex's interface stayed down, so no post-rollback partition
readback was captured (`research/HARDWARE_TEST_LEDGER.md:645-674`). The current
physical partition state and SSH path therefore **could not be determined**
after that run. No new feature experiment is eligible until a fresh read-only
invariant check establishes them again.

## Front-page status matrix

| Area | Evidence that exists | What it does **not** prove / next falsifiable gate |
| --- | --- | --- |
| Recovery, serial, eMMC | DEVICE-TESTED only for the earlier baseline and Stage-A scope: model/CPU, p29 read-only root-store, p22/p30/p31 labels/hashes and left gadget/SSH (`research/HARDWARE_TEST_LEDGER.md:32-58,291-308`). | It does not establish the device's state after the latest transaction. Re-establish Trex link, SSH, pstore and all three read-only partition hashes before any write. |
| Left USB gadget and right host Ethernet | The baseline saw `usb0` and right-port `enu1`; Stage A again saw USB and Ethernet (`research/HARDWARE_TEST_LEDGER.md:44,297-300`). SOURCE EXISTS for the separate right-port host overlay (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:1-128`). | It does not prove Type-C PD, charging, dynamic role switching, or the newer RTL8156 adapter. Re-run one known cable/adapter after the invariant check and retain `ip`, dmesg and link-speed evidence. |
| Display | SOURCE EXISTS in the pinned kernel input for the opt-in display test sequence (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-display.dtso:3-121`); the shared display resources remain disabled absent that overlay (`arch/arm64/boot/dts/mediatek/mt6797.dtsi:851-1000`). | No Gemini pixels are recorded here. Gate: retain the exact composed-DT/build record, then one recovery-slot modeset and a physical panel observation. |
| Audio | SOURCE EXISTS in the pinned kernel input for an opt-in AFE/MT6351 smoke overlay, with no external amp/jack/UCM routing (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-audio.dtso:3-43`). | No Gemini playback/capture result. Gate: build the pinned source with the overlay, then capture one enumerated card and one recovery-tested stream; do not add amp GPIOs on inference. |
| Touch | The base client is explicitly disabled at I2C4/0x62 and records rising GPIO85/EINT8; its VTOUCH mapping is explicitly unresolved (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:388-430`). The pinned input contains a separate observer that enables only I2C4 and leaves the client disabled (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-touchscreen-observe.dtso:3-33`). | Reset polarity, regulator identity/voltage, and a safe activation sequence **could not be determined**. Run only the later read-only vendor-boot VTOUCH collector (`2fcd322947870d0375a8058069dc26d483111e5d`, not in the Nix pin) before an activation proposal. |
| Keyboard | The base I2C5/AW9523/matrix consumers are disabled (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:444-507`). The pinned input contains the separate 400 kHz, polling-only 8x7 overlay (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-keyboard.dtso:3-55`). | No current Gemini run is recorded. Gate: select/build the overlay, then test a bounded key subset; AW9120/LED/flash stay out of scope. |
| Charger, battery and PMIC | The pinned input contains an opt-in BQ2589x I2C0/0x6b no-write/no-IRQ observer (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-power-observe.dtso:3-33`). The overlay itself says the exact IC variant and CHR_STAT route are unknown. | No charger, fuel-gauge, battery capacity, charge control, or pre-init power safety result exists. Gate: build and boot the observer only after recovery is reverified; accept only identity/read-only sysfs/log evidence. |
| CONSYS, Bluetooth, GNSS, Wi-Fi and FM | SOURCE EXISTS for a dormant MT6797 WMT patch controller (`linux-gemini-platform@518957636:drivers/soc/mediatek/mt6797-consys-wmt-patch.c:1-27,225-303`), whose current code requires full STP before patch download. Stage A explicitly saw no WMT/BTIF/CONSYS device or firmware request (`research/HARDWARE_TEST_LEDGER.md:300-301`). | There is no live transport, identity read, firmware download, GNSS, Bluetooth, Wi-Fi or FM result. The next safe code gate is full STP validation; do not enable a radio client or release reset in a hardware test. |
| Watchdog / unattended recovery | An orderly reboot/preloader/gadget return was observed; the Linux watchdog was inactive and `nowayout=0` in that run (`research/HARDWARE_TEST_LEDGER.md:360-410`). The later chained transaction failed closed and issued no p30/p31 write, erase, format or firmware upgrade (`:645-674`). Exact current live p24/p25 reads are byte-identical and match the 98,304-byte ATF container in `research/ATF_WATCHDOG_HANDOFF.md`. | The exact live ATF dispatches `0x82000200` and has no direct WDT mode/length/disable write on that path; continuation of LK's nominal 10-second watchdog is an inference about timing/hardware state, not a runtime reset result (`research/ATF_WATCHDOG_HANDOFF.md`, binary offsets `0x9194-0x91a0`, `0x10950-0x10958`). A Linux p22 change cannot affect pre-handoff state, and no host watcher substitutes for a pre-init actuator. Gate: preserve exact candidate/rollback/readback and bounded recovery waits. |
| GPU, modem, cameras, sensors, MicroSD | Generic or vendor source may exist, but there is no accepted Gemini activation gate in this campaign. | UNKNOWN. Keep all disabled until the per-device rail, bus, identity and rollback evidence is collected. |

## Blocking facts, not workarounds

1. **Recoverability is not yet unattended.** A host can observe BROM and Flash
   Tool, but no remote reset/power actuator is evidenced. Exact current ATF
   static analysis makes a pre-probe watchdog reset plausible, but the elapsed
   margin and reset observation remain unknown; a dead device still requires
   the bounded/manual recovery path (`research/ATF_WATCHDOG_HANDOFF.md`).
2. **The artefact boundary is real.** Nix consumes `1bb2a9863`, whereas the
   reviewed source work is at `518957636` (`flake.nix:23-28`). Calling a later
   overlay “in the Nix image” would be false until a new pin and build manifest
   are recorded.
3. **Touch activation is blocked on electrical identity, not driver appetite.**
   VTOUCH and reset are unresolved by the base-DT evidence; the observer is
   intentionally transfer-free (`mt6797-gemini-pda-touchscreen-observe.dtso:5-21`).
4. **Battery/charging is observational only.** BQ variant, CHR_STAT route,
   fuel-gauge path and safe charging policy could not be determined; do not
   turn the observer into a control plane.

## Next parallel gates

1. **Hardware owner -- recover evidence before features.** Restore the Trex
   interface or manually reset as required, then perform the ledger's
   read-only invariant check: route/interface, SSH, pstore capture, and full
   p22/p30/p31 hashes. Passing criterion: all values are captured and the
   intended known-good image is identified. Failure criterion: stop at the
   recovery boundary; do not guess which partition booted.
2. **Build/integration owner -- close the pin gap.** Rebase the desired,
   reviewed platform commits onto the immutable Nix input, make an explicit
   `flake.nix` revision change, and retain config/DTBO/composed-DT/image
   manifests. Passing criterion: those named artefacts build. This remains
   BUILD-TESTED, not DEVICE-TESTED.
3. **Touch/power research -- collect, do not activate.** Use the VTOUCH
   collector in vendor boot and identify the exact live regulator phandle,
   properties and reset behaviour. For BQ, retain only no-write probe logs.
   Passing criterion: an exact regulator/charger identity and route; otherwise
   leave each client disabled.
4. **Connectivity implementation -- finish transport before radio.** Keep
   the WMT controller dormant and complete full STP protocol validation. No
   CONSYS reset release, firmware, GNSS, Bluetooth, Wi-Fi or FM hardware trial
   is justified until a bounded transport/identity gate is separately reviewed.

Every hardware handoff must name the immutable source/input revisions, exact
image and DT overlay, target partition, expected log, acceptance timeout,
rollback image and evidence location. A source diff, a cross-build, a DTBO
composition or KUnit result is never promoted to DEVICE-TESTED by prose.
