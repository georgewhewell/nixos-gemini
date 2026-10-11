# NixOS on the Planet Computers Gemini PDA

The installed [accepted image](research/accepted-baseline.json) is Linux 7.2.9
with GNOME Wayland, 200% display scaling, a fixed bottom dock, NetworkManager,
ModemManager, Bluetooth, IPv6 and RAM-only LZ4 zram. GNOME Calls, Spacebar and
callaudiod are installed; the call daemon and SMS receiver run normally.
[Image 101](research/gnss-integration-20261011.json) passed installation,
changed desktop checks and its independent terminal audit. Its
[cross-runtime checks](research/gnss-integration-20261011.json)
passed 1,431 ARM64 ELF files and 124 scripts, including target Python/GI and the
telephony applications.

Wi-Fi automatically associates and passes traffic through NetworkManager;
selecting another SSID remains unqualified. Bluetooth is visible to GNOME and
bounded discovery passes; pairing and profiles remain unqualified. The native
modem reaches HS2, then fails with a watchdog interrupt. SIM/eSIM, cellular data,
SMS delivery and voice require further native driver bring-up. GNSS now exposes
the standard Linux endpoint and passes two power lifetime cycles, but receives
no data; receiver initialization and positioning remain unfinished. Native video
buffer allocation, export and Panfrost mapping pass on hardware; decoder completion,
rendering decoded surfaces and encoding remain unfinished. The
[current hardware status](research/HARDWARE_STATUS.md) records each feature's
accepted checks and remaining work; the [kernel baseline](research/KERNEL_BASELINE.md)
describes the maintained driver interfaces and exact installed revision.

Normal boot initializes devices and opens GNOME. GPU render, audio, Wi-Fi scan,
Weston and RTC qualification run explicitly when their behavior changes.
Measured graphical boot is about 95 seconds, including 51 seconds in the kernel
and initramfs. Paging uses RAM only: no eMMC/SD swap, zswap, zram writeback or
hibernation. The preserved [7.1.3 fallback](research/baselines/boot-test-76.json)
uses no swap and retains its completed
[hardware proof](research/ram-only-recovery-hardware-20261010.json).

## Build

On an x86_64 Linux host, cross-compile the complete system with:

```sh
nix build
cat result/MANIFEST
```

`nixosConfigurations.gemini` is the same system. The bundle contains the padded
p22 boot image, kernel, DTB, generic initramfs and system closure. Building does
not install or flash it.

```sh
nix build .#kernel         # Maintained Linux source and native board defconfig
nix build .#efiBootFiles   # Versioned systemd-boot entry and boot payloads
nix build .#uboot          # U-Boot with display, keyboard and EFI storage support
nix build .#bootloader     # Flashable U-Boot image with the normal Linux fallback
nix build .#mtkclient      # Open-source flashing tool with RTC preservation
nix build .#checks.x86_64-linux.gnome-cross-runtime
```

Packaging uses `master`; Linux uses one `gemini-7.2.9` branch for normal and media
work. [nix/gemini.nix](nix/gemini.nix) composes one kernel and one NixOS system.
Driver fixes belong in their native source trees. The Linux input is pinned to
our GitHub remote; the remaining local Git inputs, including U-Boot, require
their checkouts or explicit `--override-input` paths. Builds use the locked
Nixpkgs default ARM64 compiler, GCC 15.3.0 with binutils 2.46. Hardware settings
live in Linux's board DTS and `gemini_defconfig`; packaging copies the compiled
DTB unchanged.

The `mainlineNixosBundle` and component names remain aliases of the normal build.
Historical experiments and the vendor 3.18 system live under
`legacyPackages.x86_64-linux` and `legacyConfigurations`, loaded from the pinned
`recovery-packaging` input. Use each historical revision to reproduce its
recorded image; development continues in the default system.

## Install and update

NetworkManager owns Wi-Fi and Ethernet DHCP; the static USB rescue interface
stays unmanaged. GNOME Settings, `nmcli`, `nmtui` and `mmcli` are installed.
Saved profiles live in `/persist/NetworkManager/system-connections` with
root-only permissions. First boot imports automatic profiles from read-only
Gemian without overwriting profiles subsequently edited in GNOME. Opening the
desktop does not wait for an access point or a SIM.

Copy the system closure into the registered store before testing. Normal Linux
uses the usual local Nix store; the preserved 7.1.3 fallback accesses it as
`local?root=/persist/nixos`. [Storage documentation](research/PERSISTENCE.md)
explains the persistent home/store layout and initial provisioning. The reserved
p34 partition stays unused.

For a desktop/radio/audio change, use the focused supervised deployment:

```sh
python tools/test-network-audio-desktop.py --bundle result --out ../handoff/boot-test-$(date +%s) --observe-seconds 90 --execute
```

Omit `--execute` for read-only preflight, using a fresh output directory. The
supervisor checks the candidate and restores the accepted image afterwards.
Add `--keep` to leave a fully passing candidate installed; adopt its recorded
`promoted-baseline.json` after the independent terminal audit. Use
`tools/test-boot.py` when RTC startup/UTC/alarm behavior changes, and
`tools/test-media-boot.py` for temporary media-module observations. Test changed
behavior and unfinished acceptance checks; reuse proofs whose relevant inputs
are unchanged. See the [testing criteria](research/HARDWARE_STATUS.md#acceptance-and-testing).

Normal NixOS builds install through `system.build.installBootLoader`.
`nixos-rebuild boot` or `switch` installs the selected generation's kernel, DTB
and initramfs and selects its boot entry. The installer retains system-profile
generations, removes obsolete owned payloads after successful updates and
preserves independently owned recovery files. `gemini-boot-install --system
SYSTEM --check` verifies an installed default without writes. The current GNOME
image was installed through direct Linux boot; normal generation updates and
the U-Boot/EFI path retain their separate recorded qualification scope in
[boot and UEFI](research/BOOT_HANDOFF.md).
