# NixOS on the Planet Computers Gemini PDA

The accepted device baseline is **M69**, running Linux 7.1.3 and NixOS on the
MT6797X Gemini. Hardware enablement is still in progress. The maintained kernel
revision is `c0dbf01b2bdaa9cc741582ae0c88df3daac74285`; the accepted padded p22
image has SHA-256
`913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3`.

## Current state

The October 4 read-only checks found healthy M69, no failed units, all ten CPUs
present, and active desktop, GPU, JPEG, Wi-Fi and audio services. CPU parking
can offline cores at idle. These checks establish the current running state;
they do not replace physical peripheral, audio or power qualification.

The desktop uses Weston with Panfrost rendering and a terminal for `gemini`.
Display scanout currently bypasses IOMMU translation because translated
scanout stalled intermittently. JPEG encode/decode has prior hardware evidence;
hardware video codecs remain unfinished. The retained M51 record has successful
WPA3/PMF on-air data and reconnect tests; scanning while associated remains limited. Cellular registration/eSIM and weak
reception remain open.

Persistent home and the writable Nix layer survive supervised reboots, using
the existing p32 filesystem. The fixed 5 GiB p34 swap partition is now active
and survives an ordinary reboot. mtkclient installation and automatic factory
layout restoration have both passed on hardware, preserving the filesystem,
boot images and retained data. A candidate has passed
ordinary sandboxed Nix builds through the daemon as the unprivileged `gemini` user, retaining the
output through recovery. Installed M69 still lacks its network namespace and
daemon-unit fixes; normal NixOS generation updates remain unfinished. See
[storage evidence](research/PERSISTENCE.md).
A complete offline backup of the persistent filesystem now passes journal
recovery in a separate host copy, filesystem checks and retained-file proofs.
Paging under a memory-cgroup limit now passes with zswap writeback enabled
from boot in the corrected candidate. The trial verified a 128 MiB pattern
under a 64 MiB memory limit, an ordinary Nix build and automatic M69 recovery.
All eleven build outputs survived. Installed M69 retains its original policy;
the tested correction still needs promotion. Hibernation remains unqualified.
The hibernation-watchdog kernel correction has now passed a separate normal
boot/recovery trial, including an ordinary Nix build and data retention.
The successor candidate also passed controlled Linux watchdog expiry: stopping
its keepalive process caused a reset in 25.3 seconds and automatic M69 recovery,
with all twelve Nix build outputs retained.
The freezer diagnostic also passes, including a fresh GPU render afterward.
The device-suspend diagnostic currently stops at MTU3's deliberate refusal to
suspend an attached USB gadget; testing beyond it needs supervised USB
disconnection and restoration. Recovery retained all thirteen build outputs.
Hibernation, deep idle and the complete lid power policy are not qualified.
See [power evidence](research/POWER_QUALIFICATION.md) and the
[fixed-swap plan](research/STORAGE_QUALIFICATION.md).
Camera and vibrator are excluded from the owner's completion scope.

See [the completion inventory](research/HARDWARE_STATUS.md) for current evidence
and outstanding requirements. The [M37 desktop report](research/M37_DESKTOP.md)
records earlier implementation and hardware results; it is historical.

## Build the accepted Linux profile

The build host is x86_64-linux; the target is aarch64-linux.

```sh
nix build .#mainlineNixosBundle --out-link artifacts/mainline-nixos-bundle
cat artifacts/mainline-nixos-bundle/MANIFEST
```

The bundle contains the padded 16 MiB p22 image, kernel, composed DTB,
initramfs, and a uniquely named compressed Nix store image for p29. Builds do
not flash the device. The `linux-gemini` input pins an exact local Git commit;
reproducing this workspace requires the checkout paths declared in `flake.nix`.

Useful component builds:

```sh
nix build .#mainlineNixosKernel
nix build .#geminiDesktopWeston
nix build .#geminiDesktopBufferCheck
nix build .#geminiDesktopPresentationCheck
nix build .#geminiDesktopProtocolCheck
nix build .#mtkclient --out-link artifacts/mtkclient
```

The desktop protocol check uses native Weston fixtures. Hardware acceptance
also needs the real DSI output, input devices, presentation progress and
console/GPU restoration.

## Boot, recovery and mtkclient

The accepted path uses the existing boot firmware, an Android-format Linux
image, a watchdog-managed initramfs and NixOS stage 2. The Nix store squashfs
on p29 is mounted read-only. The [U-Boot profiles](research/BOOT_HANDOFF.md)
now qualify software reset, watchdog expiry, repeated Linux FIT handoff,
EFI application entry/return and full EFI Linux/ExitBootServices. The EFI
Linux trial retained the full 4 GiB memory map, passed service health and
automatically restored the accepted M69 image through mtkclient. GOP/text,
native keyboard polling and read-only native/EFI storage now pass. The distro
systemd-boot manager also boots the installed Linux entry after its unattended
menu timeout, with independent EFI-variable and file-hash evidence. Its new
versioned entry boots the Nix-enabled system and passes an ordinary sandboxed
daemon build as an unprivileged user, retaining its output and database through
automatic M69 recovery. Per-entry device trees now pass the same complete
boot and recovery checks, preserving the selected kernel's CPU identity and
LK's runtime reservations even when the carrier embeds an older kernel.
A further opt-in keyboard profile preserves native EFI modifiers and Unicode;
all 416 compact-US key/Shift/Fn/Caps combinations match the captured Gemian
XKB map in host tests, and real controller polling passes the complete
manager/boot/recovery trial. Physical menu selection, the separate power/Escape
input, desktop layout integration and normal NixOS generation updates remain.

The open-source [mtkclient workflow](research/MTKCLIENT.md) now builds from this
flake. Local patches expose `reset --bootmode reboot`, correct the MT6797
shutdown packet size, and propagate partition-write failures. Two corrected
October 4 sessions read GPT and the full M69 boot image with matching hashes
and returned automatically to healthy M69. A boot-only rewrite of the exact
accepted image also passed write acknowledgement, full readback and a fresh
healthy boot. The durable candidate/rescue supervisor has also passed a full
M69 baseline trial and restored M69 after the U-Boot trials using mtkclient.
The older general SP Flash Tool harness remains available; the new supervised
bootloader runner selects mtkclient explicitly with no automatic fallback.

Device trials need a fresh device/boot identity, the shared host locks, and
verification of the resulting boot and health. The installed fixed-swap layout
requires the dedicated two-layout recovery checks; historical factory-only
boot/power profiles must be adapted before reuse. Modem NV partitions can legitimately
change during modem operation and must not be treated as immutable hashes.

Current workspace observations are in `handoff/current-device.md`, alongside
transaction-specific evidence. Historical flashing scripts, scatter files and
health guards apply to their recorded image/layout and cannot establish the
current device state. Current U-Boot trials use the qualified mtkclient
supervisor and restore the accepted M69 image automatically.

The [vendor-era overview](research/VENDOR_README_LEGACY.md) retains historical
Linux 3.18 build and deployment details. The legacy `deploy` output still
belongs to that path; `mainlineNixosBundle` selects the mainline Linux profile.
