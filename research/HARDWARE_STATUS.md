# Gemini completion status, 2026-10-07

The objective remains complete hardware enablement and consolidation. Camera
and vibrator are excluded by the owner; hardware video is still unresolved,
not an additional exclusion. Historical milestone names are not completion
proof. The installed recovery system is M69 (configuration 3f8e9d5,
kernel c0dbf01b2bdaa). The default packaging now selects the combined maintained
Linux branch `gemini` at dc57eeca141b4, including the tested watchdog and RTC
fixes, EFI/Nix support, desktop keyboard and zswap writeback, plus host-tested
FUSB301 role-switch support. Historical profiles are isolated in the frozen
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
| USB speed and roles | The left MTU3 port is capped to USB2/high-speed in the selected board DT; only 480 Mb/s enumeration has been qualified. Vendor SuperSpeed support suggests further enablement is possible, but board wiring and a real 5 Gb/s connection remain to be verified (source notes below). Left-port OTG host operation is also unqualified. The right port uses the separate USB2 controller |
| Cellular / eSIM | Resolve weak reception and registration; qualify applicable SIM/eSIM use. The October 1 record says stock Gemian also failed registration with the same SIM at the same location; a comparable stock operator scan/signal measurement remains outstanding. On October 7 the owner offered a new eSIM on their existing Sunrise contract and confirmed it includes calls, SMS and data. Confirm this device's provisioning path before activation, then test registration and all three services; no new profile has been installed or tested |
| Wi-Fi / Bluetooth / GNSS | The September 30 M51 record reports WPA3-SAE/PMF data and three successful reconnects; older summaries calling all on-air testing absent are stale. Associated Wi-Fi scanning remains a recorded gap. Bluetooth LE discovery passed on M45; pairing, profiles and sustained coexistence remain unqualified. GNSS has source/transport work but no retained successful location-fix evidence |
| Peripherals | microSD, wired headset and RTC alarm power-on need hands-on qualification; check retained evidence for other interfaces |
| Battery / DVFS | Fresh read-only M69 observations expose charger status/voltage, fuel-gauge current and CPUFreq policies 0/4 using cpufreq-dt/schedutil. The fuel gauge publishes no capacity attribute, and no cpuidle driver is present. Reconcile prior DVFS transition/load evidence; qualify battery calibration/capacity, charging behavior and remaining frequency/thermal cases. Status observations do not prove those behaviors; see campaign/08-power-pmic-battery-dvfs.md |
| Display IOMMU | Resolve intermittent translated scanout stalls; current M69 display bypasses translation |
| Media | JPEG was hardware-tested historically; video encode/decode remains unimplemented and requires further vendor investigation |
| Consolidation | Merge qualified work, reconcile stale docs and stranded branches, and preserve reproducible source/artifacts |

### USB SuperSpeed evidence

The selected `mt6797-gemini-pda.dts` uses only `u2port0` and explicitly sets
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
while the right controller at I2C0 address 0x25 uses GPIO64/EINT3. Linux still
only enables the latter. The current host connection and device UDC both
report high-speed (480 Mb/s); the host's paired SuperSpeed root hub is present,
but cable lane capability and the Gemini's physical routing remain unverified.

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
