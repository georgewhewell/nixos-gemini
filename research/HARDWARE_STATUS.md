# Gemini completion status, 2026-10-08

The objective remains complete hardware enablement and consolidation. Camera
and vibrator are excluded by the owner; hardware video is still unresolved,
not an additional exclusion. Historical milestone names are not completion
proof. The installed recovery system is M69 (configuration 3f8e9d5,
kernel c0dbf01b2bdaa). The default packaging now selects the combined maintained
Linux branch `gemini` at 70823e0a3c4c7, including watchdog/RTC fixes,
EFI/Nix support, desktop keyboard, zswap writeback, coupled A53/CCI voltage
scaling and native A72 shutdown/restart. Automatic A72 parking is enabled in
the candidate and has passed bounded hardware tests; the detailed evidence
and remaining limits are recorded below. The next A53 vendor points
(1.014/1.352GHz at1.04V) pass bounded hardware transition testing. FUSB301 role-switch and MT6797 USB3
PHY support are enabled, but no SuperSpeed link has been observed. Historical
profiles are isolated in the frozen
`recovery-packaging` input; local `legacy.nix` is removed. `recovery` retains
the exact M69 bundle. This
packaging consolidation does not itself update the installed device. The full
bundle and EFI files build successfully. Hardware settings live directly in
the Linux board DTS; 48 obsolete overlays and their build targets are removed.
`gemini_defconfig`
replaces the normal package's fragment assembly, and a small standalone Nix
kernel recipe replaces its historical profile builder. Native driver tests,
the full system/EFI/U-Boot builds and flake checks pass. A72 capability preparation
now uses board register expectations and architecture-collected system policy
without Nix rewriting source hashes or adding a DT record. The native DTB is
copied unchanged. The identity and fixture cleanup removed about 1,200 lines.
The subsequent CPU cleanup removed 7,245 lines of unused startup protocol
models, rollback hooks, temporary hotplug tracing and obsolete model metadata.
Generic CPU hotplug and idle code now match upstream Linux; the duplicated
readiness token is replaced by the existing capability receipt's ready state.
Live CPU register, topology, capability, mitigation, HWCAP and power checks
remain. The only additional config change removes the disabled P30 model
option. U-Boot a655c003 accepts both native and historical DTs in host tests.
Runtime driver startup services and other temporary diagnostics still need
consolidation.

Normal NixOS generation installation now uses a generic initramfs and the
persistent store at `/persist/nixos/nix`, with standard system-profile retention
and activation hooks. All 581 M69 paths were copied with Nix and all 26 ordinary
outputs independently checked. Linux CMDLINE_EXTEND now honors the generation's
init= path; test 12 passed all ten CPUs and desktop health after correcting stale
A72 assumptions about a forced command line. Test 13 restored the intended
cgroup-v2 default but panicked in allocator/object-cgroup code before healthy
SSH. Cause is unresolved; this generation has not been published or promoted.
Automatic rescue returned healthy M69 boot `1d3cfdd4-848c-4572-8da0-fe52a96d6f5f`,
with all retained outputs, protected storage and source checks passing and all
trial units stopped. The last complete passing EFI boot remains test 07.

The normal initramfs's unused squashfs, overlay and image-provisioning branches
are removed; frozen recovery imports its own implementation. The generated
boot commands are unchanged, and all other initramfs file bytes and permissions
match the previous build. The custom Nix database-seeding service is removed
in favor of the registered store and NixOS's existing booted-system GC root.
The storage provisioner now creates the normal `/persist/nixos/nix` layout;
host tests cover permissions, idempotence, retained data, symlink rejection and
the existing GPT-preservation cases. The runner checks the standard root for
the normal store and retains the original checks for M69. All 19 persistence/
runner tests and the five flake checks pass; the complete system bundle, EFI
files and U-Boot fallback package build successfully. These changes are not
deployed.

Workspace cleanup removed 82 obsolete, clean Linux worktrees without changing
any branch or tag references. The remaining 41 include the maintained tree,
the checkout holding the shared Git directory, detached heads, local edits and
ignored build artifacts; those were preserved.

U-Boot now uses `mt6797_gemini_defconfig` through a normal standalone recipe.
Startup initializes the real eMMC, console and keyboard drivers without the
old fixed GPT/boot-partition hashes, Debian version check, or embedded EFI
test apps. The former GPT hash rejected the current fixed-swap layout. The
manager launcher now reads the installed systemd-boot image, bounds its size,
records its actual digest and retains FIT fallback on failure. Its 18 host
test scripts and complete firmware/carrier builds pass. `bootloader` packages
the flashable image with the normal Linux fallback. Historical inputs and the
exact recovery bundle remain unchanged. This firmware passed the full device
test in `handoff/boot-test-07` using the normal installed EFI entry.

The normal system passed `handoff/boot-test-06` (candidate boot
`f8e3fb64-6a29-4fd6-b631-c223cbd64281`). It includes the unchanged Linux/DTB
from the successful CPU cleanup trial, the narrowed keyboard build inputs,
and a packaged `gemini-boot-install` command. The boot volume remains read-only
with its journal enabled; the installer briefly remounts it writable, publishes
immutable payloads, preserves the old loader default and selects the new entry
last. Recovery retains its exact original `noload` mount and bundle.

Runtime installation passed on hardware. Entry
`gemini-efd567ef400adac86ff7b6eb0ed5af82e03adbb64794f477a332ff17fd7764c8.conf`
and its matching store are installed and selected; independent readback passed
after restoring read-only and again after M69 recovery. Full Linux health,
real paging, an unprivileged Nix build, native RTC startup/UTC/awake alarms and
RTC-preserving automatic rescue all passed. The final locked audit retained
25 ordinary outputs, original home, previous EFI entries and protected storage,
and matched all 35 executed source files. M69 returned healthy as boot
`0b9f41cf-7477-4f68-9249-08f5d725405a`; the durable worker exited zero.
The old unused candidate cache was archived before replacement. All 25
installer/publisher tests, the normal system/EFI/bootloader builds and flake
checks pass.

The subsequent `boot-test-07` booted that entry through consolidated U-Boot
and systemd-boot 261.2 (candidate `df50df1b-c288-4266-a2b9-694c8cde44aa`).
The manager's own EFI variables identify the expected entry and p29 volume,
with 9.818488 seconds between menu and execution. Linux verified 50 EFI
descriptors covering the full 4 GiB, LK reservations, native CPU readiness,
the selected CPU device tree and both online A72s. The historical console/MMC
test apps and generated CPU record were absent. Full Linux health, paging,
ordinary Nix, native RTC startup/UTC/awake alarms and automatic rescue passed.
M69 returned as `62173393-15e9-4d9f-bfe5-eaa5315d5a54`; the audit retained all
26 ordinary outputs, home, previous EFI entries and protected storage, with
35 executed source files unchanged. Host coverage includes 45 boot/recovery,
EFI, native DT and fallback-rejection tests. Permanent promotion remains
unfinished; the normal generation hooks implemented since this trial still
await a successful device test.

The first two attempts exposed host-tool issues. mtkclient now stops an idle USB
scan after 120 seconds, leaving transfer time inside its existing 180-second
outer limit; all 43 package tests pass, including a late connection crossing
the scan deadline. Hardware trials verified idle-scan retries and successful
automatic rescue. Memory checks now compare LK's live reservation nodes and
modem table while allowing regenerated phandle IDs. They follow the kernel
handoff provider: LK removes static modem reservations, so their obsolete
consumer phandles do not describe the live layout. Trial 01's host-assisted
recovery and trial 02's failed diagnostic result remain recorded separately.

## Fresh device observations

Initial read-only checks before the mtkclient trials are retained at workspace
`handoff/boot-consolidation-20261004/live-state.txt`:

- Boot ID fcce1f76-8617-480c-9dcb-5617e109cc7d; p22 matches M69; accepted healthy.
- Desktop, GPU, JPEG, Wi-Fi and audio services active; no failed units; CPUs 0-9 present.
- Charger reports Full; fuel gauge returns current. This is not a new codec,
  audio loopback, wireless traffic or battery-discharge qualification.
- Factory GPT verifies clean: p32 is 15.6 GiB and p34 does not exist.
- No swap is active. Stage 1 skips resume (no p34) and persistent storage
  (`layout missing=home`). The `/nix/store` is still the read-only squashfs.
- No cpuidle driver is published at `/sys/devices/system/cpu/cpuidle/current_driver`.

Subsequent storage work initialized the existing empty p32 filesystem without
changing GPT. Trial `handoff/data-persistence-02` then proved that home data and
a local fixed-output Nix build/database survive supervised reboot. Current
healthy M69 boot after the consolidated candidate's automatic recovery is
`2710f4b7-7b93-4cc8-b33a-417e154a3cba`, with `/persist`,
`/home`, `/nix/var` and the store overlay mounted. Fixed 5 GiB p34 swap is active.
Ordinary Nix builds revealed missing network namespaces and daemon units.
The opt-in correction passed `handoff/persistent-nix-01`: an unprivileged
daemon build ran in its own network namespace, both A72s and full health
passed, and its output/database survived recovery. `handoff/efi-nix-provision-01`
then installed its versioned EFI entry and switched the hash-pinned loader
default while retaining the previous configuration and payload.
`handoff/efi-nix-manager-01` qualified that entry through systemd-boot, including
an ordinary daemon build and retention of its output, GC root and database
through M69 recovery. `handoff/efi-nix-provision-02` also qualified reproducible
initramfs packaging and reuse of the installed boot files. Its final audit
retained all four ordinary build outputs from these trials and the earlier
direct Nix trial. Subsequent per-entry DT provisioning and manager trials
passed full EFI/Linux health, selected CPU provenance, ordinary builds and
automatic rescue. The cross-kernel manager trial then booted the newer entry
from the older carrier and passed the same full checks. Its final locked audit
retained seven ordinary outputs with free locks and no writer. The subsequent
native Unicode/modifier profile also passed full EFI/manager/entry-DT health,
an ordinary build and automatic M69 recovery in
`handoff/efi-key-events-manager-02`. The first attempt was rejected by a host
poll-counter ceiling; the corrected retry used identical firmware. All 416
compact-US key/Shift/Fn/Caps combinations match captured Gemian XKB in host
tests. The final locked audit retained all eight ordinary outputs and their
home GC roots/database identities, with free flash locks and no writer.
The later desktop candidate also passed full Linux health, an ordinary build
and automatic recovery in `handoff/desktop-keyboard-01`. Its final locked
audit retained all nine ordinary outputs and their database/GC-root proofs.
The subsequent power-kernel candidate passed normal-operation checks with
an identified patched kernel, owned active watchdog, full Linux health and
ordinary Nix build. Automatic M69 recovery and the final locked audit retained
all ten outputs in `handoff/power-kernel-01`. Sleep and hibernation were not
requested. See [POWER_QUALIFICATION.md](POWER_QUALIFICATION.md).
The subsequent `handoff/gpt-rewrite-01` trial rewrote both existing factory GPT
copies through mtkclient, verified independent readbacks and unchanged boot
partitions/flashinfo, then returned automatically to healthy M69. All ten Nix
outputs and the original persistence proof survived. The disk layout remains
unchanged in that trial; the later changed-layout result is recorded below.
See [STORAGE_QUALIFICATION.md](STORAGE_QUALIFICATION.md).
The offline data capture `handoff/data-backup-02` subsequently passed: a full
10.6 GiB raw image was preserved, journal replay in a separate host copy and
forced read-only fsck passed, and twelve known persistence proof files were
verified inside the recovered image. Linux returned healthy with all ten Nix
outputs retained. Fixed-swap trial `handoff/fixed-swap-01` then proved automatic
factory GPT/header restoration after a host-verifier failure. The corrected
`handoff/fixed-swap-02` passed installation, active 5 GiB swap, an ordinary
reboot and retention of all ten outputs, original home proof and EFI files.
The final locked audit found no writer and matched all thirteen executed
sources. The subsequent pressure trial exposed a cgroup OOM with zswap's
shrinker disabled. `handoff/swap-io-03` now passes a 128 MiB memory pattern
under a 64 MiB cgroup limit with the shrinker temporarily enabled, including
real p34 reads/writes, full health and all retained data. Its final audit
checks all fifteen sources and no active writer. The runtime setting was
restored afterward. The permanent correction subsequently passed normal boot,
the same paging test without runtime policy writes, an ordinary Nix build
and automatic M69 recovery in `handoff/power-swap-01`. The final locked audit
retained all eleven build outputs and matched all twenty-four executed
sources. A duplicate stop of already collected host services interrupted
the worker's final audit; a separately recorded completion performed the
unchanged live checks. The correction is included in the default build; hibernation is unqualified.
The subsequent `handoff/power-swap-02` trial also passed controlled Linux
watchdog expiry. The exact keepalive owner was stopped after all normal
candidate checks; independent USB observers measured reset after 25.3 seconds,
before the software fallback. Automatic M69 recovery, all twelve retained
build outputs and twenty-five executed source hashes passed the final audit.
The corrected cleanup completed automatically; all trial services are inactive.
Trial `handoff/power-swap-03` then passed the five-second freezer diagnostic,
unchanged watchdog ownership, a fresh GPU render and post-freezer health.
The device stage was rejected by the attached MTU3 recovery gadget with
`-EBUSY`, matching the driver's connected-device check and existing sleep
inhibitor policy. The combined profile remains failed. Automatic M69 recovery
and the final locked audit preserved all thirteen Nix outputs and matched
twenty-six executed sources. The subsequent guarded USB cycle passed in
`handoff/power-swap-05`: the gadget disappeared for 5.622 seconds, re-enumerated,
and returned to SSH and candidate health on the same boot. The independent
logind sleep inhibitor remained observed while the normal USB inhibitor
disappeared, and the latter returned before the guard was released. No sleep
was requested; watchdog ownership and suspend counters remained unchanged.
Automatic recovery and the final locked audit retained all fifteen Nix
outputs, matched twenty-seven executed sources and found no writer. The first
attempt (`power-swap-04`) was rejected by a reproduced host filename collision;
it also recovered and retained its build output. The corrected retry completed
automatically. Trial `power-swap-06` then passed freezer and device diagnostics
with the gadget disconnected, taking 5.25 and 6.55 seconds respectively. Both
restored the PM selection, retained the same watchdog owner and passed fresh
GPU rendering and candidate health. USB returned after 7.880 seconds under
the separate sleep inhibitor. Automatic M69 recovery retained all sixteen
Nix outputs, matched twenty-seven executed sources and found no writer;
the worker exited successfully and all trial services are inactive.
Awake RTC testing subsequently found that M69 still delivered a cancelled
alarm interrupt. The driver correction in `power-rtc-01` now passes delivery,
cancellation and delivery again (interrupt deltas 1, 0, 1). Automatic M69
recovery retained all seventeen ordinary build outputs, matched twenty-nine
executed sources and completed without a remaining writer. The correction
is included in the default build. The MT6351 calendar correction matches the firmware's
1968 year origin and passes native UTC write/read/ticking plus the same awake
alarm sequence. Trial `power-rtc-calendar-03` retained eighteen ordinary
outputs after automatic M69 recovery, but failed RTC retention because the
old download-agent exit explicitly requested RTC reset. With the opt-in
`mtkclientRtc` preservation option, `power-rtc-calendar-04` passes the complete
UTC/alarm/recovery sequence. The final firmware-decoded RTC agrees with host
UTC, all nineteen ordinary outputs survive, 33 executed sources match and
all five host units are inactive with no writer. Native M69 still reads the
wrong date; only the candidate has the calendar correction.
Periodic kernel clock updates are disabled; NixOS's existing shutdown
clock-save service is enabled and still writes the old encoding on M69.
The preserved initial candidate clock read 2094 before its explicit UTC write,
consistent with that old shutdown encoding. The subsequent
`power-rtc-startup-01` temporarily skipped the legacy writer and proved native
UTC startup, including the kernel's RTC_HCTOSYS timestamp before any explicit
clock write. UTC/alarm/recovery checks passed again; twenty ordinary outputs
and 35 executed sources passed the final locked audit. The original shutdown
policy is restored and all five trial services are inactive. Promotion of the
corrected kernel and clock policy remains.
The same calendar kernel then passed controlled watchdog expiry in
`power-rtc-startup-02`: independent observers measured reset after 31.798 and
31.803 s, before fallback. Automatic recovery retained twenty-one outputs,
matched 35 sources, preserved RTC UTC and restored the original clock policy.
A separate suspend-guard kernel now passes host/ARM64/full-build checks but
has not been installed; its opt-in counter-preservation mode is intended to
bound the next no-IRQ and RTC-wake trials.
Direct M69 remains installed. See
[PERSISTENCE.md](PERSISTENCE.md).

## Remaining work

| Area | Required evidence |
|---|---|
| Recovery / mtkclient | Read/reboot, boot-only candidate/rollback ownership, software-reset rescue, watchdog rescue, factory-GPT write/readback and fixed-swap installation/restoration now pass. The new power/swap boot profile also preserves and verifies the installed swap layout. General harness migration and adaptation of older factory-only profiles remain |
| U-Boot / UEFI | Reset/watchdog recovery, FIT and full EFI Linux handoff, owner-confirmed GOP/text, native keyboard polling, native eMMC and EFI filesystem reads pass. Consolidated U-Boot boots the normal installed NixOS entry through systemd-boot, with real EFI variables, memory map, native CPU DT and boot-file readback verified. Native Unicode/modifier behavior passes host tests; actual EFI polling passed the earlier complete device trial. Physical key selection, the separate power/Escape input, persistent EFI settings, permanent promotion and normal NixOS generation management remain. Per-entry DT fixup preserves LK reservations and both native and historical CPU trees; an older carrier also boots a newer kernel/DT. See BOOT_HANDOFF.md |
| Persistence and fixed-size swap | Home and Nix storage/database survive reboots and the fixed-swap transition. Ordinary unprivileged daemon builds pass direct boot and the distro-manager path. Offline backup, fixed 5 GiB swap installation, automatic factory restoration, activation and reboot persistence pass. Real paging under a 64 MiB cgroup limit now passes with the candidate's default zswap writeback policy; installation of the consolidated default and normal generation updates remain |
| Power | The hibernation-watchdog and default zswap writeback fixes pass normal boot, exact runtime identity, real paging, ordinary builds and automatic recovery. Freezer/device diagnostics pass on the power/swap kernel with guarded USB disconnection and fresh GPU rendering. The calendar kernel passes native UTC startup/write/read/ticking, awake delivery/cancellation/rearm, RTC-preserving recovery and controlled watchdog expiry. A separate bounded-suspend guard is built but not hardware-qualified. Kernel/clock-policy promotion, selected-kernel USB/PM checks, wake-source validation, noirq, full suspend/wake, deep idle, hibernation save/restore and the 24-hour policy remain |
| USB speed and roles | The maintained left MTU3 DT enables both PHYs and SuperSpeed, with connector-driven peripheral VBUS. The maintained kernel now enumerates at 480 Mb/s without a diagnostic VBUS patch and passes connector-driver unbind/rebind. Recovery M69 remains capped to USB2. Board lane routing and a real 5 Gb/s connection remain unverified (source notes below). Left-port OTG host operation is also unqualified. The right port uses the separate USB2 controller |
| Cellular / eSIM | Resolve weak reception and registration; qualify applicable SIM/eSIM use. The October 1 record says stock Gemian also failed registration with the same SIM at the same location; a comparable stock operator scan/signal measurement remains outstanding. On October 7 the owner offered a new eSIM on their existing Sunrise contract and confirmed it includes calls, SMS and data. Confirm this device's provisioning path before activation, then test registration and all three services; no new profile has been installed or tested |
| Wi-Fi / Bluetooth / GNSS | The September 30 M51 record reports WPA3-SAE/PMF data and three successful reconnects; older summaries calling all on-air testing absent are stale. An October 7 M69 passive scan while associated with WPA2-PSK/CCMP returned 13 BSSs across both bands, retained the same association/IP and passed all 30 concurrent gateway pings; WPA3/5GHz-associated scans and sustained coexistence remain unqualified. Bluetooth LE discovery passed on M45; pairing, profiles and sustained coexistence remain unqualified. GNSS has source/transport work but no retained successful location-fix evidence |
| Peripherals | microSD, wired headset and RTC alarm power-on need hands-on qualification; check retained evidence for other interfaces |
| Battery / DVFS | October M69 test passes 12 up/down measurements across all six enabled A53 frequencies, with matching hardware reads and workload scaling at a fixed 1.00 V; governors and core parking restored. Historical M42c also covers schedutil load, emulated cooling and hotplug. Maintained Linux also passes a bounded diagnostic test of all49 LL frequency pairs across221–897 MHz and4 L pairs, with matching CPU/raw-PLL reads and fixed1.00V. A second diagnostic passes10 seconds of load on all8 A53 cores and all6 emulated LL cooling states down to221 MHz, then clears the limits. The next maintained diagnostic passes all98 LL/L ordered pairs, including20 postdivider transitions, enabling L325–1209 MHz at fixed1.00V with matching clock reads and checked computation. A follow-up passes10 seconds of eight-core load and all6 cooling states on both clusters down to221/325 MHz, then restores limits and idle topology. CCI clock transactions pass host tests and the native runtime diagnostic now passes all16 ordered pairs among416/481/533/611 MHz at fixed1.00V. The native CPU SRAM regulator binds and passes1,003 configured-voltage reads at inherited1.10V during all98 A53 frequency pairs at fixed1.00V, with no kernel errors and verified M69 recovery. DA9214 forward-write and rollback settling now pass98,304 host selector pairs plus fault cases and ARM64 compilation. The pure CPU/SRAM planner passes11,528 starting-pair/target combinations and26,656 intermediate writes. The regulator-framework adapter now passes11,528 paths and156,336 injected failures, with shared votes and permanent fault fencing. The initial coupled DT held the rail at1.00V. The coupled adoption trial passes all98 A53 frequency pairs with1,017 concurrent SRAM reads at1.10V, no kernel errors, restored governors and verified M69 recovery. The CCI policy/vote core passes5,376 CPU combinations,512 ordered paths,6,388 injected failures and704 boot states; the native runtime consumer and governor are now implemented with host-tested hotplug, PM and failure cleanup, and were first enabled in the candidate DT at fixed1.00V. The runtime diagnostic passes all98 A53 pairs with1,633 SRAM reads at1.10V, restored governors, no kernel errors and verified M69 recovery. The startup ownership guard now passes11,528 inherited-pair/target cases and prevents a CPU request from lowering Vproc before the CCI vote exists. The candidate enables BUCKA0.77–1.20V, preserves existing A53 frequency limits and avoids noisy late-OPP lookups. Normal and diagnostic builds pass. The coupled-voltage diagnostic passes all98 A53 pairs and all16 ordered transitions among CPU/SRAM0.90/1.00,0.94/1.05,0.97/1.075 and1.00/1.10V, with1,586 SRAM samples, no kernel errors, restored governors and verified M69 recovery. Native CPU8/9 hotplug and warm power/clock/SRAM lifecycle calls are now connected in Linux8061e213868e5. The first physical trial starts both A72s and correctly refuses wrong-order CPU8 removal, but CPU9 post-shutdown verification fails and fences re-add; full cluster shutdown/restart remains unverified. M69 recovery and final audits pass. A new shutdown core passes two ordered sequences,24 call failures and62 corrupt readbacks, and the clock provider now supplies serialized MP2 sync-DCM control plus retained-PLL validation. Clock API failure/locking tests and normal/diagnostic builds pass. The SRAM provider now supports one restart per recorded shutdown, with independent cluster-off checks and permanent failure protection; six host cycles and fault cases pass, as do normal/diagnostic builds. The next diagnostic confirms primary CPU9 power acknowledgment clears while secondary status remains unchanged, causing the false failure. Linuxdef0029470b6c corrects both power-owner and SRAM checks to the primary bits used by ATF; exact-sample replay, independent-secondary regressions, fault tests and ARM64 compilation pass. Corrected normal/diagnostic bundle builds pass and share the same kernel/unchanged DTB. Trial03 verifies CPU9 off/on and a checked workload on the restarted core with no kernel errors, but a missing taskset command stops the probe before cluster shutdown; cleanup succeeds. Trial04 reaches full cluster shutdown with BUCKB disabled and SRAM at its reset selector, but the zeroed MP2 PLL words expose an overly strict retained-clock check and restart is refused. Linuxa2ad78e32f349 admits the observed complete PLL reset only with the existing shutdown record and unchanged mux/divider contract; 58,539 clock-core assertions, native API tests and ARM64 compilation pass. Trial05 confirms MP2 reads26MHz after full shutdown with the clock fix, but CPU8 preparation now returns EUCLEAN before CPU_ON. Low-voltage testing is withheld; M69 recovery and final audits pass. Trial06 diagnostics locate the failure in SRAM precheck: power-off reads0/0, while re-powering exposes0x00400ff9/0. Linuxca4b6d9b98e2b records a stable powered baseline before the first successful initialization and permits restart only with two matching samples equal to that baseline or the recorded off state; one-use authorization and permanent failure protection remain. Provider fault tests, 238 SRAM KUnit assertions and ARM64 compilation pass. Trial07 passes CPU9-only off/on and three full-cluster shutdown/restart cycles with checked A72 execution, rail-off/26MHz verification and no kernel errors. Its follow-up passes all98 A53 pairs with both A72s off, all49 ordered CCI pairs across169–611MHz, CPU rails770–1000mV and1,420 concurrent SRAM reads; cleanup restores both cores and schedutil. The candidate enables automatic A72 parking and its real daemon passes three schedutil load/idle cycles in22.52 seconds, followed by six cycles plus service-stop/restart restoration in47.99 seconds: all10 CPUs under load, checked execution on each A72, and BUCKB-off/MP2-26MHz after load removal. Service stop restores all10 CPUs and restart resumes parking; no daemon or kernel errors occur. The next1.04V step passes128 ordered A53 pairs and64 CCI/voltage pairs, reaching LL1.014GHz/L1.352GHz, CCI676MHz and SRAM1.15V, with1,709 SRAM reads and no kernel errors; governors and both A72s are restored. Higher operating points and sustained voltage/load testing remain unfinished, as do normal cgroup2 qualification, sustained load/physical thermal testing and A72 frequency control. Native battery voltage/rough temperature now forward the charger readings, with12 exact on-device comparisons; current and charge count remain gauge-backed. Charger-backed status now stays Full across12 samples spanning-34.5 to+6.9mA; the native gauge default is corrected to115 percent from the active vendor header. The maintained native gauge now implements capacity and estimated OCV using original-pack voltage/resistance/Qmax models, charge-counter tracking and explicit continuity/anchor rules. Normal and diagnostic builds and arithmetic/lifecycle tests pass. A diagnostic passes32 samples over66.1 seconds at100 percent/Full, with11 distinct estimated-OCV updates and no kernel errors; discharge integration and percentage accuracy remain unverified. Physical calibration, aging and charging/discharging remain unqualified. No cpuidle driver is present. See campaign/08-power-pmic-battery-dvfs.md |
| Display IOMMU | Resolve intermittent translated scanout stalls; current M69 display bypasses translation |
| Media | JPEG was hardware-tested historically; video encode/decode remains unimplemented and requires further vendor investigation |
| Consolidation | Merge qualified work, reconcile stale docs and stranded branches, and preserve reproducible source/artifacts |

### USB SuperSpeed evidence

The recovery M69 board configuration uses only `u2port0` and explicitly sets
`maximum-speed = "high-speed"` on the left MTU3 port. The SoC DT also describes
`u3port0`, but its presence alone does not establish physical lane routing.
The actual controller capability check logs `IP version 0x0(U3 IP)` followed
by `max_speed: high-speed` in `power-swap-06/usb-pm-devices/pm-kernel.stdout`:
USB3 controller capability is observed, while the configured link remains USB2.
The clean Gemian vendor source at commit
`8cfe6596a503612e3332d9c26e292a19525a7f07` enables `CONFIG_USB_MU3D_DRV` in
`aeon6797_6m_n_defconfig`; its selected MU3D header defines `SUPPORT_U3`, and
the gadget driver therefore advertises `USB_SPEED_SUPER`. The board DTS also
contains FUSB340 switch and redriver names, but these do not establish active
Gemini wiring. In the pinned vendor source `51e705e4e7b1e52a31a79985f7fbbc9e98b59c8c`,
the FUSB340 enable pinctrl entries are empty/commented out: GPIO251 actually
enables the display's negative-bias supply. GPIO252 and redriver GPIO196/197
remain named in the DWS/DT, but the selected FUSB301 drivers do not consume
those switch states. The GPIO70/71 switching in the other Type-C driver is
the right port's HDMI path, not evidence of left-port SuperSpeed routing.

The left controller at I2C1 address 0x25 also lacks a valid vendor interrupt
assignment: the retained July 14 vendor capture reports IRQ 0 / -EINVAL,
while the right controller at I2C0 address 0x25 uses GPIO64/EINT3. The recovered M69 kernel enables only the latter. Its host connection and
device UDC report high-speed (480 Mb/s). The owner has confirmed a known
SuperSpeed cable and host port; Gemini routing remains unverified.

The maintained FUSB301 driver now consumes an optional connector-graph USB
role switch, selects host/device on attach, and stops data plus source power
on detach. Provider failures unwind the connection, and remove releases the
threaded IRQ before destroying the port. ARM64 object builds pass with role
support built in, modular and disabled. The full normal `nix build .#kernel`
passes, including its new regression test for roles, orientations, detach,
failure cleanup and IRQ teardown. The result is
`/nix/store/zzpnw1x55rs7qm1w685vlr5dr7zjs2f5-linux-gemini-7.1.3`.
This is driver support; the left connector/PHY remain unchanged and no 5 Gb/s
link has been demonstrated. The new kernel has not been deployed.
The [FUSB301 datasheet](https://www.onsemi.com/pdf/datasheet/fusb301-d.pdf)
describes its autonomous SS_SW output for driving a SuperSpeed lane switch.
Consequently, the missing processor GPIO/IRQ setup does not by itself rule out
working lane selection. Whether Gemini connects SS_SW to its switch still
needs a schematic or a successful test in both cable orientations.

Further comparison with the pinned vendor MT6797 PHY implementation identified
the missing `RG_SSUSB_VUSB10_ON` sequence: enable VA10 at 0.95 V, wait 50 us,
then assert the bit; clear it and wait 10 us before removing the supply.
The live M69 rail reports enabled at 950000 uV with no Linux consumer, so its
state is inherited from firmware. Linux 98ed7e2 adds the USB3 power-ready
sequence through the normal PHY power callbacks, restricted to MT6797.
Its host regression runs the actual PHY core and driver callbacks and covers
failed startup, nested power references, shared supply retention, repeated
cycles, unrelated register bits and other PHY types. The ARM64 object and full
normal kernel builds pass, including the driver checks. Output:
`/nix/store/jxfll4n280y2nwgpssrl5lznqpvjz3cl-linux-gemini-7.1.3`.
The DTB and configuration match the preceding kernel byte for byte; recovery
is unchanged and nothing was deployed. Board supply ownership, remaining PHY
tuning and SuperSpeed enablement are still pending; this change does not raise
the current USB2 speed limit.

USB3 board integration now enables the left SuperSpeed PHY and a 0.95 V VA10
supply shared with its USB2 fallback PHY. The driver applies the MT6797 vendor
signal settings after analog power-up, using the three calibration fields from
LK devinfo word 37 with vendor defaults for unprogrammed fields. Linux commits
1e514531dbcf8, 02c9ad67268ad and 8482b753c5143 contain the binding, driver and
board changes. Both bindings and the compiled board's relevant schemas validate;
the ARM64 W=1 object/DTB build and calibration/power callback regression pass.
Existing unrelated DT address warnings remain. This is a device-mode candidate;
left-port host role switching is still disabled. Full kernel, system bundle, EFI
files and bootloader builds pass, including the packaged driver regressions.
SuperSpeed negotiation has not succeeded. The normal
boot runner now records actual USB speed from the device and the exact host
network interface, with tests covering USB2/USB3 bus changes and mismatched
speeds. The owner confirmed a known SuperSpeed cable and host port. Device trials now show the controller initializes for SuperSpeed but fails
to attach. The normal cgroup-v2 generation still panics during systemd startup.

The left FUSB301 now has a native sink/device-only connector node. With no
verified IRQ assignment it polls attachment and orientation every 500 ms on
the freezable workqueue; source-capable polling is rejected. Removal waits for
polling to stop before releasing the port. Linux commits 5d1512b3bc9fa,
d9878cfd22dc6 and 4c2b238f72cfe include the binding, driver and board changes.
Host regressions, ARM64 object/DTB build and targeted schema validation pass.
Normal packaging pins these changes. Full kernel/system/EFI/bootloader builds
and packaged DTB schema validation pass. The system closure is copied to the
persistent store without activation. Device validation remains outstanding.
The normal boot runner also records Type-C orientation, roles and partner
attachment with full controller paths, avoiding dependence on probe-order port
numbers. Read-only capture on M69 shows the right controller in reverse
orientation with a partner attached; M69 does not expose the new left port.

A temporary cgroup-v1 diagnostic with the same USB kernel and redzone checks
remained accessible over right-port Ethernet through 344 seconds. Left FUSB301
reported reverse orientation, sink/device and 1.5 A. PHY calibration readback
matched the vendor defaults (intr 45, RX 15, TX 16), but the UDC stayed
unattached even after a standard gadget disconnect/reconnect. This isolates the
USB failure from the early allocator crash; it does not qualify the normal
generation, which remains cgroup v2. A later PHY trial reported normal
orientation with the same failure; no physical connector transition was witnessed.
Controller snapshots show USB3 enabled, LTSSM disabled, automatic USB2 switching
enabled, both device ports powered, reference-clock control 0x1f and no VBUS
override. A read-only powered-PHY register dump now exposes routing/reset and
analog controls for further diagnosis. All supervised trials recovered M69
with complete retention audits; no candidate was promoted.

Linux a3b50ebb47cfb adds software USB2 fallback for MT6797, matching the active
vendor `mu3d/` driver: automatic switching off, SS.Disable interrupt enabled,
and explicit fallback disconnect. Host regressions, ARM64 W=1 and full packages
pass. The temporary cgroup-v1 trial reads back USB2_TEST_MODE=0 and
LTSSM_INTR_ENABLE=0x2432, but still reports LTSSM Disable, SOFT_CONN clear and
UDC not attached through 143 seconds. This change alone does not restore the
link. M69 recovery and final retention audit passed; no promotion. Evidence:
`handoff/usb3-fallback-trial-02` and `handoff/usb3-link-diagnostic/fallback-ethernet-capture.txt`
in the workspace. Grok's allocator instrumentation is unchanged.

The following read-only monitor trial (Linux6615ac9fcf7f4) reports no receiver
attempts in LTSSM_INFO, no PHY RXPLL lock or CDR/PLL calibration completion,
and completed TX/RX impedance calibration without receiver detection. Controller
IRQ count is zero. Clock framework reports enabled 26MHz reference, 124.8MHz
system and 156MHz bus clocks; VA10 is 950mV. These software observations do not
prove analog clock delivery, nor distinguish missing clock from a controller
that never requests PHY startup. Evidence: `handoff/usb3-monitor-trial-01`.
Candidate still did not enumerate; complete M69 recovery audit passed.

An export-only diagnostic forcing MAC VBUS sense (MISC_CTRL bits1:0) restores
left USB enumeration: device configured/high-speed and host480Mb/s, with the
same candidate verified over both left USB and right Ethernet. LTSSM_INFO changes
to0x300 and SOFT_CONN becomes set. This establishes that the MAC sense override
unblocks startup/fallback despite IPPC already indicating VBUS valid. It does
not establish SuperSpeed. PHYD_MON2 remains0xb0 after fallback, so that final
reading alone cannot diagnose absent clock delivery. A production policy must
track real attachment; the unconditional override remains diagnostic-only.
Evidence: `handoff/usb3-mac-vbus-trial-01`. Normal cgroup-v2 qualification rejected
the temporary cgroup-v1 setup as expected; automatic M69 recovery and full audit
passed. No promotion or allocator change.

Ftrace is now enabled in the maintained Gemini configuration (Linux24f1216912361),
including dynamic function, function-graph and event tracing. The diagnostic
boots with the standard MTU3 LTSSM event enabled and records three SS.Disable
interrupts at2.401188,2.567750,2.744113s, with3/3 retained events and USB2 fallback.
The event reports masked interrupt status, not every hardware transition.
Available tracers on hardware include function/function_graph. Evidence:
`handoff/usb3-ftrace-trial-01`. Full normal/diagnostic builds and complete recovery
audit passed; normal cgroup-v2 stability and SuperSpeed remain unresolved.

Repeating that same diagnostic with the paired host USB3 root hub held active
(power/control=on, runtime_status=active) gives the same three SS.Disable events
and480Mb/s link. Host autosuspend in this setup is therefore not the cause.
Original auto policy was restored and recovery retention audit passed.
Evidence: `handoff/usb3-host-awake-trial-01`.

PHY-monitor decode caveat: vendor MT6797 u3_loop_back_test and its header disagree
on PHYD_MON5 loopback bit positions. Earlier calibration/PLL interpretations are
header-derived, not independently confirmed for this revision. Retain raw MON2
and MON5 values; these do not establish a PHY clock fault. MAC traces and paired
host/device negotiated speeds are unaffected by this header inconsistency.

The vendor's `CONFIG_U3_PHY_SMT_LOOP_BACK_SUPPORT` is enabled in the retained
config and exposes `smt_err_count` through MU3D debugfs. Its Kconfig describes
checking connector mounting by sending a pattern on TX1/2 and receiving it on
RX1/2. This is not evidence of a self-contained internal PHY test that can be
interpreted with an ordinary host attached. The helper also changes shared
power controls and VA10 selection. No loopback test has been transplanted or
run; a failure in the current connection would not establish a PHY fault.

The maintained MT6797 USB3 tuning was also compared with the vendor's active
`usb_phy_recover()` writes, including absolute bank offsets and masks: RX/TX
impedance, IEXT, 3.5 dB drive/de-emphasis, CDR, equalizer steps, XTAL and CHIP
settings agree. Vendor comments contain different TX impedance and drive
values from the executed code; the maintained driver follows the code. The
vendor USB2 EOP adjustment at U2PHY+0x70 is separate and is not evidence of a
SuperSpeed tuning mismatch.

Linux 516b58a0a53eb extends the LTSSM event with raw status and interrupt-enable
mask, preserving the handled-status field and existing acknowledgement and
interrupt behavior. This can expose latched masked events at handler entry;
it cannot timestamp every transition or make masked events trigger an IRQ.
The real-function fake-MMIO test verifies raw/masked trace values and that
masked status remains pending. The ARM64 MTU3 object build passes.

The subsequent full build and `usb3-raw-trace-trial-01` capture verify this on
hardware: three events retain raw=0x8002, enabled=0x2432 and handled=0x2. VBUS
rise and SS disable are present; receiver-detection-success and U0 entry are
not pending at these handler entries. The host and device still report
480 Mb/s/high-speed. This focuses further investigation on receiver detection
and the lane/PHY path, without distinguishing wiring from PHY setup. It does
not rely on the disputed PHY monitor decoding. The diagnostic still fails
the normal cgroup-v2 memory-controller check; it is not a qualified generation.
Automatic recovery passed its complete health and retention audit: 35 source
hashes matched, 26 ordinary outputs retained, both locks available, no writer.

Peripheral VBUS integration is now in the maintained kernel (d951c0cadafbb).
FUSB301 requests device role only when an attached source reports VBUS valid,
and disconnects on read errors or a missing partner type. MTU3 peripheral mode
registers the connector role provider, rejects host requests, drives its MAC
VBUS sense from those reports, gates pull-up/fallback on attachment, and reports
powered/not-attached state to the UDC. The left connector graph connects these
drivers. Gadget-only and dual-role ARM64 builds and real-function regression
tests pass, including PM failures, stale fallback IRQs and reconnects.

`usb-connector-vbus-trial-01` uses exactly the normal kernel output. Its system
retains temporary cgroup v1 and diagnostic tracing/capture. The always-on diagnostic
VBUS patch was removed. Initial USB2 enumeration succeeds. Unbinding only the
left FUSB301 driver over independent right-port Ethernet changes MISC_CTRL
3→1, USB3_CONFIG 1→0 and POWER_MANAGEMENT 0x64f1→0x64a0, with UDC state
not-attached. Rebinding restores configured/high-speed, MISC_CTRL=3 and left
USB SSH; host speed is 480 Mb/s. This tests connector-driver detach/reprobe,
not a physical cable removal. SuperSpeed remains unresolved, and this does
not qualify the normal cgroup-v2 generation.
Automatic M69 recovery and the full retention audit passed (35 source hashes,
26 retained outputs, both locks and no writer); no generation was promoted.

The [FUSB340 datasheet](https://www.onsemi.com/download/data-sheet/pdf/fusb340-d.pdf)
identifies it as a SuperSpeed lane switch. [Planet's port guide](https://support.planetcom.co.uk/index.php/Troubleshooting)
describes the ports' roles without data rates. Preserve the current working
USB2 recovery path while establishing the board routing, orientation control
and actual SuperSpeed link. Host USB bus numbering is not a speed measurement.

## Storage and recovery correction

The distro-manager files have now been installed additively on the existing
p29 ext4 filesystem in `handoff/uboot-efi-provision-01`. All five hashes and
both existing squashfs stores were checked, p29 was returned to read-only,
candidate Linux passed full health and automatic rescue restored healthy
M69 `49655993-d7c5-42a1-adc7-9f12935076bc`. The later systemd-boot trial 10
passed all candidate checks; normal NixOS generation updates remain unqualified.
That EFI provisioning performed no formatting, GPT change or persistent
writable-store enablement. The later p32 initialization and reboot evidence
are recorded separately in PERSISTENCE.md.

The first six systemd-boot launch trials failed before the manager started.
Trial 06 captured the exact U-Boot exception while traversing the EFI event
list. A returning RAM application's temporary device path remained in global
boot state after being freed; later cleanup could free a replacement event
allocated at the same address. A regression reproduces that lifetime error
and passes with the fix. Trials 07 and 08 then reached fully healthy Linux
through the manager, with its own variables confirming systemd-boot 261.2 and
the selected entry. The factory disk GUID is zero but p29's partition GUID
is valid; U-Boot omitted that partition identity from the device path. A
failing-then-passing regression supports the correction, and trials 09/10
reported the correct p29 UUID. After correcting module lookup, device-path
text rendering and UUID case handling in the host verifier, trial 10 passed
the complete candidate profile, including a 9.48-second menu-to-launch interval
and all five installed-file hashes.
The earlier UTF-16 alignment fix also has a failing-then-passing sanitizer
regression, but did not resolve the device failure. Every trial automatically
restored healthy M69 with protected hashes unchanged. Trial 10 completed with
the manager profile qualified and final M69 boot
`99e02757-9dfe-4e5b-8bb6-7b94d030ce17`. Physical menu input was not observed;
automatic selection and boot are now proven. Direct M69 remains installed.
See BOOT_HANDOFF.md for artifacts and trial results.

The September 29 note claiming p34 was provisioned is historical. Claude later
restored the factory GPT after SP Flash Tool refused the modified layout with
error 8502. The fixed-size LVM alternative was proposed, but is not implemented
on the live system. Do not repartition from the earlier note.

The mtkclient logs (`handoff/mtkclient-test/printgpt.log`, `multi.log`) show two
successful GPT reads, including the then-existing swap partition. Subsequent
return to Linux was not demonstrated. Claims that the whole DA/read sequence
failed at USB speed switching are not supported by these logs. The successful
M69 flashing transaction at the start of this work used SP Flash Tool. The
owner then prioritised making mtkclient work; the qualified boot-only trials
below now use it without a vendor-tool fallback.

The patched mtkclient package and supervised read/reboot runner are described
in [MTKCLIENT.md](MTKCLIENT.md). The initial October 4 trial read the primary
GPT and full M69 boot partition with matching hashes. The DA acknowledged
reboot, but Linux did not return within three minutes; USB remained at the
preloader and the owner reported a black screen. The read/reboot trial failed,
and boot-only writes had not yet been tested. No eMMC writes were issued in
that initial trial.
After the owner's force restart, the vendor Linux USB gadget returned
(`0fce:7169`). SSH via `gemini@gemini` confirmed Gemian / Debian 9, kernel
`3.18.41+`, fresh boot ID `1508c791-df3f-4384-b4fd-5704338ef3ca`, and unchanged
p22/GPT hashes and partition geometry. Manual recovery succeeded; this is
not a new healthy M69 observation.

After correcting the MT6797 DA shutdown payload from 32 to 28 bytes, two
sessions returned automatically to healthy M69 with unchanged GPT/p22 hashes.
The full repeat runner passed in 194.4 seconds using its corrected six-minute
health deadline, returning boot ID
`6b1b01f6-cd4b-462f-8b5a-3de4b73c909a`.
Detailed evidence and the packet-size diagnosis are in MTKCLIENT.md.

The following boot-only write trial also passed: the DA acknowledged writing
the exact accepted M69 image, full readback matched, and it rebooted
automatically to healthy M69. That trial returned boot ID
`74d10f78-c5e0-48fd-915d-9eea69e6b87b`; GPT/p22 hashes and geometry remain
unchanged. Evidence: `handoff/mtkclient-boot-write-20261004-01`.

The durable candidate/rescue baseline subsequently passed, followed by
hardware-qualified U-Boot software-reset and 31-second watchdog-expiry tests.
Removing an unmapped post-MMU framebuffer probe resolved the early U-Boot
failure. Two plain U-Boot FIT handoffs then reached fully healthy M69
with its Linux-visible marker, full RAM bank and unchanged modem reservations.
The supervised trial restored direct M69 afterward. Details and exact
artifacts are in [BOOT_HANDOFF.md](BOOT_HANDOFF.md); these boot tests do not
qualify EFI Linux, writable persistence, fixed swap or hibernation.

The EFI smoke retry also passed after deferring the EFI dispatcher until
SMBIOS initialization completed. Linux exposed both EFI-success and FIT
handoff markers and passed full M69 health and LK-memory checks. Its
supervised rescue returned healthy direct M69 boot
`7f567308-9b27-4719-af29-edf5c6f8496e`, with unchanged GPT and all boot
partitions. This proves EFI application entry/return; M69's kernel still has
EFI disabled, so the full EFI Linux trial uses a separate kernel and system.

The full EFI profile subsequently passed in `handoff/uboot-efi-linux-04`
and repeated in `handoff/uboot-efi-linux-05`.
It required removing stale LK carrier initrd properties and rebinding the
DT's CPU provenance to the actual EFI kernel. Linux verified its runtime
identity, brought up both A72 cores, initialized EFI and its initrd table,
retained all 4 GiB and LK reservations, and passed full service health.
The matching content-addressed squashfs was installed separately on p29;
the accepted M69 squashfs was verified before and after installation.
Automatic mtkclient rescue restored healthy M69 boot
`57d9effa-69ba-4f0f-bbc6-1c085f031b2b`, then
`b01b9b87-d724-4f1d-9cc3-583eae64617e`, with unchanged GPT and boot partitions.
The two EFI boots had identical memory maps and LK handoff data; neither
needed physical recovery.
The exact artifacts and failed-trial diagnoses are recorded in
[BOOT_HANDOFF.md](BOOT_HANDOFF.md). This qualifies EFI Linux handoff, while
the inherited EFI console now also passes in `handoff/uboot-efi-console-01`,
with owner visual confirmation. Keyboard, storage and boot-manager paths
remain unfinished. The console trial automatically restored healthy M69
boot `75f4fd80-c07f-4575-8949-55ec2a2a0a5d`.


The native EFI keyboard trial `handoff/uboot-efi-keyboard-01` subsequently
passed 1,402 real AW9523 matrix scans with zero errors, full EFI Linux health
and automatic rescue to healthy M69 boot
`8b6fd83e-f611-4545-a5eb-8c25c403c905`. Its compiled matrix matches live Linux
byte-for-byte. Host simulations cover arrows/Enter, Shift/Ctrl, debounce,
repeat and bus failures. Physical key presses and full Fn/Alt semantics are
not yet qualified. Gemian's installed XKB definitions identify LWIN as its
third-level/Fn modifier; implementation can proceed from that source.

The source-backed Fn follow-up now passes host tests and a complete firmware
build: Fn+arrows, Fn+Shift+number function keys, and Shift+Backspace/Delete.
It has not been separately flashed. Full Fn text-symbol parity and Alt/Meta
semantics remain unfinished; the pinned hardware-qualified keyboard carrier
is retained by the trial runner.


The native eMMC trial `handoff/uboot-efi-mmc-01` also passed on October 4.
It read and hashed the primary GPT, all three 16 MiB boot partitions and
an existing p29 ext4 file in U-Boot, with all hashes matching. EFI Linux
passed full health, 43 EFI descriptors covering 4 GiB and 1,402 keyboard
scans without error. Automatic rescue restored healthy M69 boot
`992b64b9-c885-4b69-a071-462272ab3b4d` with unchanged GPT/p22/p30/p31. Native firmware
storage writes remain disabled; EFI filesystem access and the distro
picker are subsequent milestones. See BOOT_HANDOFF.md for artifact pins.


EFI storage protocol trial `handoff/uboot-efi-storage-02` passed after fixing
EFI `Read()` EOF/zero-length semantics. A real EFI application checked p29
Block I/O, Simple File System metadata, exact file bytes, seeking, EOF and
directory enumeration, with write capability correctly reported absent.
It then reached fully healthy EFI Linux and automatically restored healthy
M69 `d811a8ba-9180-4f07-9316-3f37f619419d`. Protected hashes remained unchanged.
The systemd-boot file bundle is being prepared on the host; it has not been
published or booted, and normal NixOS generation updates remain unfinished.
