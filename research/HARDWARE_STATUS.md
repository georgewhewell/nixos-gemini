# Gemini completion status, 2026-10-04

The objective remains complete hardware enablement and consolidation. Camera
and vibrator are excluded by the owner; hardware video is still unresolved,
not an additional exclusion. Historical milestone names are not completion
proof. Current direct-Linux baseline is M69 (baseline configuration 3f8e9d5,
kernel c0dbf01b2bdaa).

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
healthy M69 boot after fixed-swap installation and an ordinary reboot is
`f48ecf05-1772-49e7-898a-ce9bd3740c5e`, with `/persist`,
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
restored afterward. The permanent correction builds as an opt-in power
candidate; its boot and hibernation remain unqualified.
Direct M69 remains installed. See
[PERSISTENCE.md](PERSISTENCE.md).

## Remaining work

| Area | Required evidence |
|---|---|
| Recovery / mtkclient | Read/reboot, boot-only candidate/rollback ownership, software-reset rescue, watchdog rescue, factory-GPT write/readback and fixed-swap installation/restoration now pass. General harness migration and adapting older factory-only boot/power profiles to the installed swap layout remain |
| U-Boot / UEFI | Reset/watchdog recovery, FIT and full EFI Linux handoff, owner-confirmed GOP/text, native keyboard polling, native eMMC and EFI filesystem reads pass. systemd-boot now loads the versioned Nix-enabled entry after its unattended menu timeout, with its own EFI variables and exact boot-file hashes verified. Native Unicode/modifier behavior passes host tests and its actual EFI polling passes the complete device trial. Physical key selection, the separate power/Escape input, promotion of the tested desktop layout, persistent EFI settings and normal NixOS generation management remain. Per-entry DT fixup now preserves selected CPU provenance and LK reservations on hardware; a newer kernel/DT also boots successfully from a carrier embedding the older kernel/DT. See BOOT_HANDOFF.md |
| Persistence and fixed-size swap | Home and Nix storage/database survive reboots and the fixed-swap transition. Ordinary unprivileged daemon builds pass direct boot and the distro-manager path. Offline backup, fixed 5 GiB swap installation, automatic factory restoration, activation and reboot persistence pass. Real paging under a 64 MiB cgroup limit passes with zswap writeback temporarily enabled; booting/promoting that policy correction and normal generation updates remain |
| Power | The hibernation-watchdog kernel fix passes normal boot, exact runtime identity, ordinary builds and automatic recovery. Its successor also enables zswap writeback by default and builds successfully, but has not booted on the device. Hardware expiry, suspend/wake, deep idle, hibernation save/restore and the 24-hour policy remain |
| Cellular / eSIM | Resolve weak reception and registration; qualify applicable SIM/eSIM use. The October 1 record says stock Gemian also failed registration with the same SIM at the same location; a comparable stock operator scan/signal measurement remains outstanding |
| Wi-Fi / Bluetooth / GNSS | The September 30 M51 record reports WPA3-SAE/PMF data and three successful reconnects; older summaries calling all on-air testing absent are stale. Associated Wi-Fi scanning remains a recorded gap. Bluetooth LE discovery passed on M45; pairing, profiles and sustained coexistence remain unqualified. GNSS has source/transport work but no retained successful location-fix evidence |
| Peripherals | microSD, wired headset and RTC alarm power-on need hands-on qualification; check retained evidence for other interfaces |
| Display IOMMU | Resolve intermittent translated scanout stalls; current M69 display bypasses translation |
| Media | JPEG was hardware-tested historically; video encode/decode remains unimplemented and requires further vendor investigation |
| Consolidation | Merge qualified work, reconcile stale docs and stranded branches, and preserve reproducible source/artifacts |

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
