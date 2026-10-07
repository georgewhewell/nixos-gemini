# NixOS on the Planet Computers Gemini PDA

This repository packages Linux 7.1.3 and NixOS for the MT6797X Gemini.
The default build includes the tested EFI boot support, persistent Nix daemon,
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
the padded p22 boot image, kernel, DTB, initramfs and compressed Nix store.
Building does not install or flash it.

```sh
nix build .#kernel         # Linux, with fixes committed in its source tree
nix build .#efiBootFiles   # Versioned systemd-boot entry, kernel, DTB and initramfs
nix build .#uboot          # U-Boot with display, keyboard and EFI storage support
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
the compiled DTB unchanged. This passes the full device boot test. U-Boot's
host tests cover this DTB format and older kernels' DTs; its updated EFI path
still needs a device trial.
The flake currently uses local Git inputs for Linux and U-Boot; reproducing it
requires those checkouts, or explicit `--override-input` paths.

The `mainlineNixosBundle` and component names remain aliases of the normal
build. Historical experiments and the vendor 3.18 system are available under
`legacyPackages.x86_64-linux` and `legacyConfigurations`, defined in
[legacy.nix](legacy.nix). Their commands and device scripts describe their
recorded images and layouts. Use the matching historical revision when
reproducing an old trial; new features belong in the default system.

The existing device can test the normal bundle with automatic M69 recovery:

```sh
python tools/test-boot.py --bundle result --out ../handoff/boot-test-$(date +%s) --execute
```

Omit `--execute` for a read-only preflight, using a fresh output directory.
The command checks RTC startup/alarms, paging, an ordinary Nix build and retained
data before returning to recovery. It uses this device's fixed-swap layout and
existing host USB/SSH setup. If p29 is full, `--reclaim-cache /host/old.squashfs`
archives that image and removes its device cache only after checking that no
active loop device or installed EFI entry/initramfs uses it.

## Device status

The consolidated default boots both A72s without a generated build record.
It passes the complete supervised test: healthy Linux,
real swap paging, an unprivileged Nix build, native RTC startup, UTC write/read,
alarm delivery/cancellation/rearm and automatic M69 recovery. The final audit
retained home, EFI files and all 23 ordinary Nix outputs. The installed recovery
system remains M69; the current default EFI bundle has not yet had its own
boot-manager trial. mtkclient now ends idle USB scans before the outer transfer
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
