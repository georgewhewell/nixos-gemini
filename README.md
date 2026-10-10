# NixOS on the Planet Computers Gemini PDA

The installed system is Linux 7.2.9 with GNOME Wayland, 200% display scaling,
a fixed bottom dock, NetworkManager, ModemManager, Bluetooth, IPv6 and LZ4 zram.
[Trial 88](research/desktop-responsiveness-20261011.json)
passed the supervised installation and independent terminal audit, and was
kept as the [accepted baseline](research/accepted-baseline.json).
Native RTC startup, UTC read/write, alarm delivery/cancellation/rearming,
128 MiB of actual zram paging, an ordinary Nix build and retained storage pass.
The cross-built desktop and networking runtime check passes 1,224 ARM64 ELF
files and 124 script checks, including service entrypoints, target Python and
GI libraries. Both managers run, the onboard modem is detected and wired DHCP
works. Saved Wi-Fi profiles are imported; Wi-Fi association and cellular data
remain unqualified on this image. Bluetooth registers and powers on at boot;
the GNOME document portal has built-in FUSE support. GPU DVFS now uses seven
operating points from 238 to 900 MHz, with verified voltage/clock readbacks and
pixel rendering in both directions. The [integration audit](research/integration-audit-20261011.json)
records the retained device support and the gaps corrected in this image.

Normal boot initializes devices and opens GNOME. GPU render tests, audio
playback/capture tests, Wi-Fi scan loops and Weston qualification are explicit
diagnostics; they no longer run before the desktop. Measured graphical boot
is about 95 seconds, including 51 seconds in kernel/initramfs. The installer's
observation, RTC, paging and retention checks run during an explicit trial.

Normal paging uses RAM only: no eMMC or SD swap, zswap, zram writeback or
hibernation. Actual paging tests verified exact data and zero flash-swap writes.
Historical disk-backed paging results describe retired images. The preserved
[7.1.3 fallback](research/baselines/boot-test-76.json) now has no swap or disk
resume and has its own completed [hardware proof](research/ram-only-recovery-hardware-20261010.json).

Packaging development uses `master`; Linux development uses one
`gemini-7.2.9` branch for normal and media work. Both duplicate development
branches are retired locally and remotely. The default build includes EFI
support, a persistent Nix daemon, Gemini keyboard layout, watchdog and MT6351
RTC fixes. See the [kernel baseline](research/KERNEL_BASELINE.md) and
[current hardware status](research/HARDWARE_STATUS.md). Decoder IRQ completion,
shared hardware surfaces and video encoding remain unfinished. Camera and
vibrator are outside the owner's completion scope.

## Build

On an x86_64-linux host, cross-compile the complete system with:

```sh
nix build
cat result/MANIFEST
```

`nixosConfigurations.gemini` is the same mainline system. The bundle contains
the padded p22 boot image, kernel, DTB, generic initramfs and system closure.
Building does not install or flash it.

NetworkManager manages Wi-Fi and Ethernet DHCP in the default GNOME image;
ModemManager manages modem discovery. `nmcli`, `nmtui` and `mmcli` are installed,
and the `gemini` user can change connections from GNOME Settings. Saved profiles
live in `/persist/NetworkManager/system-connections` with root-only permissions.
The first boot imports automatic Wi-Fi profiles from the read-only Gemian
filesystem without overwriting profiles subsequently edited in GNOME. The
static USB rescue interface stays unmanaged, and startup does not wait for an
access point or a SIM. The old Wi-Fi worker and standalone DHCP service are
absent from the default image.

```sh
nix build .#kernel         # Linux, with fixes committed in its source tree
nix build .#efiBootFiles   # Versioned systemd-boot entry, kernel, DTB and initramfs
nix build .#uboot          # U-Boot with display, keyboard and EFI storage support
nix build .#bootloader     # Flashable U-Boot image with the normal Linux fallback
nix build .#mtkclient      # Open-source flashing tool, including RTC preservation
nix build .#checks.x86_64-linux.gnome-cross-runtime # Installed ARM64 runtime paths
```

Packaging development uses `master`; its former `gemini-7.2.9` alias is retired.
The maintained Linux source is branch `gemini-7.2.9`, pinned by `flake.lock`.
The port uses a separate worktree while the original `../linux` checkout keeps
its uncommitted diagnostics. [nix/gemini.nix](nix/gemini.nix) composes one kernel and one NixOS
system; driver fixes belong in Linux, rather than new package variants.
The hardware settings now live in Linux's board DTS and `gemini_defconfig`;
the default build no longer applies hardware overlays or edits DT properties.
A72 capability preparation now belongs entirely to Linux: native Kbuild uses
the board register expectations and live system policy, and packaging copies
the compiled DTB unchanged. This passes both direct boot and the complete
U-Boot/systemd-boot device test. U-Boot's host tests also cover older kernels' DTs.
Unused CPU startup models, rollback hooks and temporary hotplug tracing have
been removed. Generic CPU hotplug and idle code now match upstream Linux;
the working A72 power and capability checks remain in the board support.
U-Boot likewise uses a native `mt6797_gemini_defconfig`. Normal startup loads
the installed systemd-boot image without the former fixed disk hashes or
embedded display/storage test apps. Its flashable image includes the normal
Linux fallback. The keyboard build depends only on its keymap and input header,
so unrelated firmware changes no longer rebuild the userspace image.
The active Linux input points to the pinned commit in our GitHub kernel remote.
The remaining local Git inputs, including U-Boot, still require their checkouts
or explicit `--override-input` paths.

The `mainlineNixosBundle` and component names remain aliases of the normal
build. Historical experiments and the vendor 3.18 system are available under
`legacyPackages.x86_64-linux` and `legacyConfigurations`, loaded from the pinned
`recovery-packaging` input. Their commands and device scripts describe their
recorded images and layouts. Use the matching historical revision when
reproducing an old trial; new features belong in the default system.

Normal boot trials use the durable supervisor and the accepted RAM-only image:

```sh
python tools/test-boot.py --bundle result --out ../handoff/boot-test-$(date +%s) --observe-seconds 90 --execute
```

Omit `--execute` for a read-only preflight, using a fresh output directory.
The supervisor checks the candidate and restores the accepted image afterwards.
Add `--keep` to leave a fully passing candidate installed; adopt its recorded
`promoted-baseline.json` after the independent terminal audit. Trial 88 did this
for the current GNOME image. The unchanged accepted image needs no new baseline
cycle. Test changed behavior and unmet acceptance checks using the
[current testing criteria](research/HARDWARE_STATUS.md).

Copy the system closure into the registered store before testing. From the
preserved 7.1.3 fallback, Nix accesses that store as `local?root=/persist/nixos`;
from normal Linux it is the usual local store. Normal candidates require zram,
and the supervisor rejects a fallback with physical swap. The existing p34
partition stays unused. Retention checks protect fixed data/build fixtures and
the accepted trial's Nix build; archived outputs no longer expand admission.
`usb-link.json` records both sides' negotiated USB speed. Completed observation
alone does not qualify a candidate.

Normal builds install through NixOS's `system.build.installBootLoader` hook.
After the initial installation, `nixos-rebuild boot` or `switch` installs the
selected generation's kernel, DTB and generic initramfs, then selects its boot
entry. Boot entries pass the standard `init=/nix/store/.../init` option; system
updates use the registered store on p32 and do not create new squashfs images.
The normal initramfs has only this storage path; the frozen recovery input
keeps its own image-based implementation. `gemini-storage-provision` prepares
home and the normal Nix layout on p32. With p32 mounted at `/persist`, copy the
system closure with Nix into `local?root=/persist/nixos` before booting it.
NixOS maintains its usual booted-system GC root.
The retained Android loader reads only the first 512-byte command-line field.
Initial boot images keep their options short; Linux appends the board defaults.
The installer retains entries for system profile generations and removes its
obsolete entries and payloads after a successful update. On a full boot volume
it first reclaims obsolete generations, preserving the current default until
the new entry is installed. Recovery files remain independently owned.
It briefly remounts the boot volume writable and restores it read-only, with
the ext4 journal enabled throughout. Recovery retains its original `noload`
mount and cannot run this installer. `gemini-boot-install --system SYSTEM
--check` verifies an installed default without writes. These generation changes
have host coverage and earlier device evidence for their recorded images. The
current GNOME image was installed through the direct Linux boot path. To test
an already installed EFI generation, use `tools/test-boot.py` with matching
`--bootloader` and `--efi-files` outputs. See [boot and UEFI](research/BOOT_HANDOFF.md)
for the historical installation proofs.

## Device status

[Current hardware status](research/HARDWARE_STATUS.md) records accepted features,
their exact proof scope and unfinished work. GNOME, HiDPI, the dock, IPv6 over
USB and RAM-only zram are qualified for their recorded checks. Earlier proofs
cover touch, ten CPUs, Wi-Fi, audio, USB host/gadget, eMMC and persistent storage
on their stated builds. Display scanout still bypasses IOMMU translation; USB
has been observed at USB2 speeds.

Remaining work includes hardware video, suspend/wake, battery capacity and
power policy, cellular/eSIM calls/SMS/data, GNSS, Bluetooth profiles, USB3 and
normal NixOS boot-generation updates. See [storage](research/PERSISTENCE.md),
[power](research/POWER_QUALIFICATION.md) and [mtkclient](research/MTKCLIENT.md)
for the underlying results. Workspace state is in `../handoff/current-device.md`.
