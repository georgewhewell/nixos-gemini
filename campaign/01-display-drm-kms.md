# Display and DRM/KMS

For the installed image and current integration, see [hardware status](../research/HARDWARE_STATUS.md). The observations below preserve the earlier bring-up baseline.

Status: display pipeline is BOUND-UNVERIFIED; physical pixels remain
UNKNOWN.

The current full Stage2 runtime exposes /dev/dri/card0, connector DSI-1
with status=connected, enabled=enabled, and mode 1080x2160; fb0 is
mediatekdrmfb with 1080x2160 virtual size. Live dmesg binds the Mediatek
components and creates fb0
(`/mnt/Home/src/gemini-live-probe-cycle18-touch-20260830/dmesg-applied:1847-1877`; the normal live capture has the same result).

The reviewed pipeline and panel are in the current pinned source overlay
(linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-display.dtso:3-14,44-180).
Those runtime and source facts prove driver binding and connector state only.
No physical image, backlight observation, or user-visible modeset result is
retained. Do not claim display DEVICE-TESTED.

Next gate: one recovery-slot modeset with exact image/DT manifest, captured DRM
and regulator errors, and an explicit physical panel observation.
