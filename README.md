# NixOS on the Planet Computers Gemini PDA

This repository packages Linux 7.1.3 and NixOS for the MT6797X Gemini.
The default build includes EFI boot support, a persistent Nix daemon,
desktop keyboard layout, zswap writeback, watchdog and MT6351 RTC fixes.
Hardware enablement is still in progress; see [hardware status](research/HARDWARE_STATUS.md).
Camera and vibrator are outside the owner's completion scope.

## Build

On an x86_64-linux host, cross-compile the complete system with:

```sh
nix build
cat result/MANIFEST
```

`nixosConfigurations.gemini` is the same mainline system. The bundle contains
the padded p22 boot image, kernel, DTB, generic initramfs and system closure.
Building does not install or flash it.

```sh
nix build .#kernel         # Linux, with fixes committed in its source tree
nix build .#efiBootFiles   # Versioned systemd-boot entry, kernel, DTB and initramfs
nix build .#uboot          # U-Boot with display, keyboard and EFI storage support
nix build .#bootloader     # Flashable U-Boot image with the normal Linux fallback
nix build .#mtkclient      # Open-source flashing tool, including RTC preservation
nix build .#recovery       # Exact installed M69 recovery bundle
```

The maintained Linux checkout is `../linux`, branch `gemini`, pinned by
`flake.lock`. [nix/gemini.nix](nix/gemini.nix) composes one kernel and one NixOS
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
The flake currently uses local Git inputs for Linux and U-Boot; reproducing it
requires those checkouts, or explicit `--override-input` paths.

The `mainlineNixosBundle` and component names remain aliases of the normal
build. Historical experiments and the vendor 3.18 system are available under
`legacyPackages.x86_64-linux` and `legacyConfigurations`, loaded from the pinned
`recovery-packaging` input. Their commands and device scripts describe their
recorded images and layouts. Use the matching historical revision when
reproducing an old trial; new features belong in the default system.

The existing device can test the normal bundle with automatic M69 recovery:

```sh
python tools/test-boot.py --bundle result --out ../handoff/boot-test-$(date +%s) --execute
```

Omit `--execute` for a read-only preflight, using a fresh output directory.
The command checks RTC startup/alarms, paging, an ordinary Nix build and retained
data before returning to recovery. It uses this device's fixed-swap layout and
existing host USB/SSH setup. Copy the system closure into the installed Nix
store before testing. From recovery, that store is accessible to Nix as
`local?root=/persist/nixos`; its database and files are separate from recovery's
overlay. Historical image trials still accept `--reclaim-cache`.

Normal builds install through NixOS's `system.build.installBootLoader` hook.
After the initial installation, `nixos-rebuild boot` or `switch` installs the
selected generation's kernel, DTB and generic initramfs, then selects its boot
entry. Boot entries pass the standard `init=/nix/store/.../init` option; system
updates use the registered store on p32 and do not create new squashfs images.
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
have passed host builds/tests; the device migration is being tested.

To exercise installation during the supervised boot test, add
`--install-efi /path/to/efiBootFiles`. For normal generations the runner invokes
NixOS's `switch-to-configuration boot` after Linux passes its health checks;
it checks the new files and retained older entries again after M69 returns.

Once installed, test that entry through U-Boot using the same command with
`--bootloader /path/to/bootloader --efi-files /path/to/efiBootFiles`.
It checks the actual EFI memory map, systemd-boot's selected entry and volume,
the native CPU device tree, Linux health and automatic M69 recovery.

## Device status

The maintained Linux kernel boots both A72s without a generated build record or
the retired CPU startup models and tracing.
The normal system passed runtime EFI installation in `boot-test-06`, followed
by the complete consolidated U-Boot/systemd-boot test in `boot-test-07`.
The manager selected the installed entry after its unattended menu timeout;
Linux verified the native CPU tree, both A72s, the full 4 GiB EFI memory map
and LK reservations. Linux health, real paging, an unprivileged Nix build,
native RTC startup/UTC/awake alarms and automatic M69 recovery all passed.
The final audit retained home, previous EFI entries and all 26 ordinary Nix
outputs. The installed recovery system remains M69. Permanent promotion and
normal `nixos-rebuild` generation installation remain unfinished.
mtkclient now ends idle USB scans before the outer transfer
deadline, preserving time for a late-arriving device to finish.

Working paths include the Weston/Panfrost desktop, touch, ten CPUs, Wi-Fi,
audio, USB host/gadget, eMMC, persistent home/Nix storage and fixed 5 GiB swap.
Native RTC startup, UTC write/read, awake alarms and hardware watchdog recovery
pass. Display scanout still bypasses IOMMU translation. USB is currently
configured and observed at USB2 speeds.

Remaining work includes suspend/wake and hibernation, battery capacity and
power policy, cellular/eSIM calls/SMS/data, GNSS, Bluetooth profiles, hardware
video, USB3, and normal NixOS boot-generation updates. The separate suspend
guard is an untested experiment and is excluded from the default kernel.

See [boot and UEFI](research/BOOT_HANDOFF.md),
[storage](research/PERSISTENCE.md), [power](research/POWER_QUALIFICATION.md)
and [mtkclient](research/MTKCLIENT.md) for implementation and hardware results.
Current workspace state is recorded in `../handoff/current-device.md`.
