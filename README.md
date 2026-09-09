# NixOS on the Planet Computers Gemini PDA

M37 boots Linux 7.1.3 and NixOS on the MT6797X Gemini with a GPU-accelerated
Weston desktop and terminal. The September 9, 2026 hardware trial passed two
desktop starts and full device health; the supervised p22 transaction accepted
the image. Bring-up is still in progress.

## Verified M37 state

- All ten CPUs online, with an active hardware watchdog and verified stage 1
  to NixOS watchdog handoff.
- Panfrost rendering on the Mali-T880, mediatek-drm scanout, and three
  progressing VSync presentations on each desktop start.
- A terminal running as the normal user `gemini`; the root console remains
  ready on tty1. Stopping the desktop restores tty1/fbcon and switches off all
  six GPU power domains before the next start.
- Both USB network paths reachable by SSH: left gadget 10.15.19.82 and the
  right RTL8156 adapter. The test network assigned 192.168.23.70 to the adapter.
- WLAN association and IPv4 using WPA2-PSK/CCMP, a default fq_codel queue, and
  read-only transmit timing diagnostics. M37 performance measurements are
  separate from boot acceptance.
- Cellular kernel/services restoration and audio playback/capture, ALSA/UCM
  routing, speaker/headphone isolation and shared-USB-rail restoration checks.
  Physical cellular service/eSIM and acoustic validation remain open.
- Exact eMMC identity and all seven guarded partition hashes preserved across
  acceptance.

The desktop requests landscape 1080×540 logical pixels from the native
1080×2160 output, scale 2 and rotate 270. Physical visibility, orientation,
keyboard interaction and touch alignment still need observation. Its home and
caches are volatile in the current read-only NixOS system model.

See [M37 desktop implementation and evidence](research/M37_DESKTOP.md) for the
source pins, allocation fix, acceptance checks and hardware results.

## Build the accepted profile

The build host is x86_64-linux; the target is aarch64-linux.

```sh
nix build .#mainlineNixosBundle --out-link artifacts/mainline-nixos-bundle
cat artifacts/mainline-nixos-bundle/MANIFEST
```

The bundle contains a padded 16 MiB p22 boot image, the kernel and composed DTB,
initramfs, and a uniquely named compressed Nix store image. The current
`linux-gemini` input pins a local Git checkout and exact commit; reproducing
this workspace requires that source checkout at the path declared in
`flake.nix`. The accepted source revision and artifact hashes are recorded in
the M37 report. Builds do not flash the device.

Useful component builds:

```sh
nix build .#mainlineNixosKernel
nix build .#geminiDesktopWeston
nix build .#geminiDesktopBufferCheck
nix build .#geminiDesktopPresentationCheck
nix build .#geminiDesktopProtocolCheck
```

The protocol check runs the real presentation client against native Weston
fixtures and rejects invalid geometry and unsuitable evidence. The physical
boot separately requires the real DSI output, input capabilities and VSync
progress.

## Boot and recovery

The accepted path uses the existing boot firmware, an Android-format Linux
boot image, a watchdog-managed initramfs, and NixOS stage 2. It mounts the
unique Nix store image from p29 read-only. UEFI, GOP and systemd-boot are still
unfinished.

Hardware trials use an exact-current-boot health guard and the supervised
p22-only recovery harness in the workspace handoff directory. The supervisor
must prove its rescue scanner is live before reboot, and host acceptance must
verify both USB paths and the candidate's full health. M37 additionally
requires the active desktop on tty7 plus recorded console/GPU restoration;
tty1 must retain its root shell. A build result alone is insufficient for
hardware acceptance.

The accepted M37 procedure and results are under
`handoff/m37-oneboot-r2/` in the bring-up workspace. Current device identity and
its exact health guard are in `handoff/current-device.md` and
`handoff/current-device-health.sh`. These runtime artifacts are separate from
the Git source tree. Flashing instructions from archived experiments are tied
to their historical profiles and partition policies.

## Remaining work

Physical display/input and acoustic verification, normal desktop/power policy,
suspend/wake and remaining peripherals, eSIM service, persistent user state,
and the UEFI boot chain remain open. WPA3/SAE/PMF remains disabled in the
current radio implementation. Boot acceptance does not establish these
features or overall bring-up completion.

The [archived vendor-era overview](research/VENDOR_README_LEGACY.md) retains
historical Linux 3.18 build and deployment details. The legacy `deploy` output
still belongs to that path; `mainlineNixosBundle` selects the accepted M37
mainline profile.
