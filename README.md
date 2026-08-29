# NixOS on the Planet Computers Gemini PDA

A minimal, cross-compiled NixOS image for the MT6797X Gemini PDA. The repository
retains the vendor Linux 3.18 recovery/deployment path and now also builds a
booted Linux 7.1 mainline headless system; the build host is x86_64-linux.

## Current status

- The best-supported Gemian-derived 3.18.41 source is pinned. Its known-good
  130745-byte device tree is appended unchanged. A p22 test proved that the
  GCC 8 rebuilt payload entered the final `machine_restart` loop before
  initramfs. The flake now provides a one-variable GCC 8/GCC 6 diagnostic
  matrix with the exact live config; see
  [research/VENDOR_KERNEL.md](research/VENDOR_KERNEL.md).
- The deploy image therefore uses the byte-for-byte known-good Gemian kernel
  and appended DTB while retaining the new NixOS initramfs and userspace.
- The NixOS system, initramfs, Android-format `boot.img`, and XZ SquashFS build
  successfully with `nix build .#deploy`.
- The current boot image is 9.23 MiB and fits a 16 MiB Gemini boot slot. The
  SquashFS is 60.12 MiB.
- Stage 2, D-Bus, logind, ConnMan, OpenSSH, the RNDIS gadget, and its DHCP
  server have been verified on the live Gemini 3.18.41 kernel. The paired
  SquashFS lives at `/nixos/nixos.squashfs` on p29, so later userspace-only
  updates do not require a boot-partition write.
- As of 2026-08-29, Linux 7.1.3 and a read-only mainline NixOS userspace boot
  from the default p22 slot. The known-good p31 Gemian recovery slot remains
  untouched. The left USB-C port provides gadget Ethernet at
  `10.15.19.82/24`; OpenSSH listens on every IPv4 interface.
- The physical right USB-C port now detects its FUSB301A source/host role,
  enables the board's GPIO94 5 V rail and USB route, and enumerates an RTL8156
  (`0bda:8156`) through USB11 MUSB. Its pinned `rtl8156b-2.fw` is embedded in
  the early initramfs. The live adapter negotiated 1 Gb/s, acquired
  `192.168.23.70/24` by DHCP, and accepted direct SSH.
- The USB11 enumeration failure was not a generic upstream-driver failure. The
  MT6797 vendor driver forces MUSB multipoint target addressing, while the ixoo
  mainline glue selected non-multipoint mode. The local patch restores that
  hardware contract. `CONFIG_USB_MON` and dynamic debug are retained for
  protocol-level diagnosis.
- USB Ethernet is currently a serviceability path, not a performance result:
  MUSB is intentionally PIO-only and the right port enumerates at USB 2.0 high
  speed. Measured iperf3 throughput to trex is 70.2 Mb/s transmit and
  57.8 Mb/s receive; the receive run exposed packet-processing pressure.

Wi-Fi is currently unavailable. The display, audio, Bluetooth, modem, suspend,
and power-management experience are not yet validated under NixOS userspace.

## Image design

The boot path has two deliberately small stages:

1. An Android v0 boot image contains the exact known-good Gemian kernel plus
   appended DTB and a static AArch64 BusyBox initramfs.
2. The initramfs mounts p29 at `/gemian`, loop-mounts
   `/gemian/nixos/nixos.squashfs` directly at `/nix/store`, creates a tmpfs
   root, and starts the NixOS toplevel named by the squashfs's
   `.gemini-system` pointer.

The pointer and its complete closure are replaced together with the squashfs.
Once this generic initramfs is installed, userspace-only NixOS updates require
replacing p29's `nixos.squashfs`; p22 only changes when the kernel, DTB,
initramfs, or embedded early firmware changes.

The Nix store is immutable and XZ-compressed. Runtime state, ConnMan Wi-Fi
credentials, SSH host keys, and the durable boot log remain on p29. Android is
not started. The existing Android `system.img` is mounted read-only so the two
small Bionic MediaTek WMT helpers can be studied without changing it. The
opt-in diagnostic copies the launcher to `/run` and hash-checks it before a
one-instruction patch skips its dependency on Android's property service; the
original in `system.img` remains untouched.

Wi-Fi and the WMT launcher are not started automatically. The patched launcher
cannot complete vendor patch discovery by itself, never creates `wlan0`, and
leaves a kernel worker blocked. The stock Gemian host eventually writes `1` to
`/dev/wmtWifi` after starting its Android container; doing that from the
Android-free NixOS environment reproducibly panics the 3.18 vendor kernel, even
with `nvcfg` and `nvdata` mounted. Firmware and an opt-in `gemini-wmt.service`
are retained for diagnosis, while RNDIS remains the stable recovery link.

## Kernel drivers, USB, and firmware

This kernel is monolithic: `CONFIG_MODULES` is disabled. There are no `.ko`
files to copy and no module load order. The relevant drivers are built in:

- MediaTek connectivity/Wi-Fi: `CONFIG_MTK_COMBO_WIFI=y`
- Legacy left-port gadget: `CONFIG_USB_G_ANDROID=y`
- Realtek USB Ethernet: `CONFIG_USB_RTL8150=y` and `CONFIG_USB_RTL8152=y`
- The separately available rebuilt kernel additionally enables generic USB
  networking and CDC-NCM for other adapters. Those options are not present in
  the currently deployed known-good kernel.

The left USB-C port uses the vendor kernel's legacy Android gadget sysfs API,
not configfs. NixOS configures an RNDIS recovery link at `10.15.19.82/24` and
runs a small DHCP server. This gives SSH a deterministic fallback even if
Wi-Fi and the right-port NIC do not come up.

Ten board firmware files are embedded, with their canonical uncompressed
filenames, in both the initramfs and the NixOS firmware aggregate. The build has
been checked byte-for-byte against `blobs/`; Linux 3.18 cannot consume modern
`.xz` firmware names.

## Build

```sh
nix build .#deploy --out-link artifacts/nixos-deploy
cat artifacts/nixos-deploy/MANIFEST
```

Useful individual outputs are:

```sh
nix build .#kernel
nix build .#bootImg
nix build .#rebuiltBootImg
nix build .#initramfs
nix build .#squashfs
nix build .#probeBootImg
nix build .#diagnosticKernelBundle \
  --out-link artifacts/vendor-kernel-diagnostic-matrix
nix build .#mainlineBundle --out-link artifacts/mainline-bundle
nix build .#mainlineConfigControlBundle \
  --out-link artifacts/mainline-config-control-bundle
nix build .#mainlineNixosBundle \
  --out-link artifacts/mainline-nixos-bundle
```

The diagnostic bundle contains tiny probe images for exact-config GCC 8,
GCC 8 with wrapper hardening retained, GCC 6.5, and a staged GCC 8 USB-NCM
variant. Each kernel output also retains its config, config diff, symbols, and
a build manifest. It is a test bundle, not the deploy default; `bootImg`
remains the byte-for-byte known-good kernel.

The mainline bundle pins ixoo's kernel commit, profile manifest, candidate DT
transform, and Android-v0/LK serializer. It contains the Nix-built kernel,
exact serviceability DTB, storage-free initramfs, raw candidate, padded 16 MiB
`boot2` payload, and their hashes. See [research/MAINLINE.md](research/MAINLINE.md)
for provenance and [research/BOOT_PROBE.md](research/BOOT_PROBE.md) for the
guarded p30-only procedure.

The main deploy bundle contains:

```text
boot.img          Android boot image for a 16 MiB boot partition
nixos.squashfs    complete cross-compiled NixOS store closure
MANIFEST          exact toplevel path and SHA-256 hashes
```

## Stage the paired store image

Do this while Gemian is running, before changing any boot slot:

```sh
scp artifacts/nixos-deploy/nixos.squashfs gemini@gemini:nixos.squashfs.new
ssh gemini@gemini '
  sudo install -d -m 0755 /nixos
  sudo mv "$HOME/nixos.squashfs.new" /nixos/nixos.squashfs
  sudo chown root:root /nixos/nixos.squashfs
  sudo chmod 0444 /nixos/nixos.squashfs
  sha256sum /nixos/nixos.squashfs
'
```

Compare that hash with `MANIFEST` before proceeding.

## Flash the default p22 slot

Do **not** use `dd` from Gemian for p22. The bootloader applies power-on eMMC
write protection to the 8 MiB groups covering p10 through p26. The vendor
kernel logs `R1_WP_VIOLATION` but then clears the I/O error, so `dd` can report
success while the partition remains byte-for-byte unchanged.

Use Planet's MediaTek Flash Tool over the **left USB-C port**:

```sh
nix build .#flash-tool --out-link artifacts/mtk-flash-tool
artifacts/mtk-flash-tool/bin/mtk-flash-tool
```

Use the device's exact custom scatter file. In Flash Tool:

1. Select `MTK_AllInOne_DA.bin` from the built Flash Tool directory.
2. Load the custom scatter and select **only** the `boot` entry at
   `0xb100000`, size `0x1000000`.
3. Point that entry at `artifacts/nixos-deploy/boot.img`.
4. Select **Download Only**, click Download, connect the powered-off/restarting
   Gemini to the left USB-C port, and wait for completion.

Never choose **Format All + Download**. Do not choose **Firmware Upgrade** for
this one-partition update. Preserve an NVRAM/IMEI backup and the original p22
image first. These restrictions follow Planet's own flashing guidance.

On the inspected device, normal power-on selects p22, the side button selects
p30/`boot2`, and Esc plus the side button selects p31/`boot3`. p30 is the
designated experiment slot. p22 and p31 currently contain the same known-good
Gemian image; neither mainline nor vendor-kernel experiments may write p31.

## First-boot observation and recovery

NixOS writes stage-1 progress and the stage-2 success marker to:

```text
/nixos-boot.log
```

If a future default NixOS installation does not become reachable, boot the
known-good p31 Gemian path and inspect that file. The NixOS recovery paths are:

- the left-port RNDIS gadget at `10.15.19.82`
- a right-port RTL8150/RTL8152 USB Ethernet adapter supported by the deployed
  known-good kernel

See [research/BOOT_PROBE.md](research/BOOT_PROBE.md) for the partition map and
probe procedure, [research/HARDWARE.md](research/HARDWARE.md) for the hardware
inventory, [research/LK.md](research/LK.md) for the vendor/upstream LK audit,
and [research/MAINLINE.md](research/MAINLINE.md) for the MT6797 mainline state
and staged headless bring-up plan.

## Source layout

```text
blobs/       firmware and known-good kernel/DTB material
nixos/       minimal target configuration and firmware package
patches/     old-vendor-kernel build fixes
pkgs/        Planet MediaTek Flash Tool packaging
research/    device, partition, and boot-chain notes
vendor/      local reference checkout (the flake input is the build authority)
```
