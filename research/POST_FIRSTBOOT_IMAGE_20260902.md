# Post-firstboot production image — 2026-09-02

This image is a successor to, not a replacement for, the frozen
`integration/production-image-20260902` candidate at `f25289e`. It pins the
kernel input to exact commit
`01c94807a09d6696d3c608fec7ed5a31b52b19a4` on
`integration/post-firstboot-next-20260902`.

## Build result

The single build command completed successfully:

```text
nix build --print-build-logs .#mainlineProductionNixosBundle \
  --out-link /home/grw/src/result-gemini-post-firstboot-image-20260902
```

Exact outputs:

```text
bundle=/nix/store/09qc1dk6zlyxwca2in52rprcb4s4k5sj-gemini-mainline-nixos-bundle
kernel=/nix/store/hj9216s0bm4dnh8fb0mgz55dsdmybk06-linux-gemini-production-7.1.3
system=/nix/store/wxpdsfnnhhffrrmj7q986vr5p0cdqx4g-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade
squashfs=/nix/store/wfyxzc0sgkr87n9hyjihwjyd08p72an1-mainline-production-nixos-zlib.squashfs size=106033152
initramfs=/nix/store/agyrgjj8zb0g59bjnaq6r3a2p3q8ph70-gemini-mainline-nixos-initramfs.cpio.gz size=1733107
boot-raw=/nix/store/k3xr53xkgx91ws05ky9crgwa1rkd9vsx-gemini-mainline-nixos.boot.img size=11980800
boot-padded=/nix/store/8lr6mgq1b2aj0vx3qbn806l7x25gkgdl-gemini-mainline-nixos-padded.img size=16777216
Image=/nix/store/hj9216s0bm4dnh8fb0mgz55dsdmybk06-linux-gemini-production-7.1.3/Image size=28002312
Image.gz=/nix/store/hj9216s0bm4dnh8fb0mgz55dsdmybk06-linux-gemini-production-7.1.3/Image.gz size=10198098
gemini.dtb=/nix/store/hj9216s0bm4dnh8fb0mgz55dsdmybk06-linux-gemini-production-7.1.3/gemini.dtb size=45616
```

No hardware was accessed. The bundle was not flashed or booted.

## Configuration evidence

The installed kernel config is module-free and contains:

```text
# CONFIG_MODULES is not set
CONFIG_DRM_MEDIATEK=y
CONFIG_DRM_PANEL_NOVATEK_NT36672E=y
CONFIG_MT6797_WIFI=y
CONFIG_BT_MTK6797_STP=y
CONFIG_GNSS_MTK_CONSYS=y
CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX=y
CONFIG_BMI160_I2C=y
CONFIG_INPUT_REGULATOR_HAPTIC=y
CONFIG_SND_SOC_MT6797=y
CONFIG_SND_SOC_MT6797_MT6351=y
CONFIG_VIDEO_HI556=y
CONFIG_VIDEO_MTK_MT6797_SENINF=y
CONFIG_VIDEO_MTK_MT6797_CAMSV=y
CONFIG_MTK_SCP=y
CONFIG_VIDEO_MEDIATEK_VCODEC=y
CONFIG_WATCHDOG_NOWAYOUT=y
CONFIG_MEDIATEK_WATCHDOG=y
CONFIG_USB_MTU3_GADGET=y
CONFIG_USB_ETH_RNDIS=y
CONFIG_USB_RTL8152=y
```

The command line retains `console=tty0`, early serial, eight CPUs, the Stage 1
`rdinit=/init`, verbose dmesg, rotated 16x32 framebuffer console and the
watchdog handoff policy. Stage 2 still enables root tty1 autologin, the
Gemini UK/Fn console map, `btop`, Wi-Fi tools, USB networking and key-only SSH.
The Stage 1 deadline and Stage 2 watchdog-takeover services remain enabled
with a 720-second lease and Stage-2-complete acceptance.

## Dormant hardware boundary

The built base DT reports `status = "disabled"` for haptics, Bluetooth, GNSS,
the GNSS LNA, BMI120, NT36772 touch, the MT6351 audio codec and sound card.
No MT6797 vcodec compatible is present in the base DT after the topology
quarantine. Thus their driver code is packaged without opting unproven nodes
into the default boot. Display, Wi-Fi, USB and the already accepted production
baseline retain their existing default composition.

The exact flake pin and successful semantic build checks are the artifact
identity. There is no revision-specific DT/image-content hash admission gate.
