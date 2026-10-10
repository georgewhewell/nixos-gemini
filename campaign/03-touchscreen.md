# Touchscreen

For the installed image and current integration, see [hardware status](../research/HARDWARE_STATUS.md). The observations below preserve the earlier bring-up baseline.

Status: SOURCE EXISTS; the normal full NixOS image keeps the client INACTIVE;
Cycle18 established the NT36772 identity and clean overlay teardown;
physical touch behavior remains UNKNOWN.

The current board DT describes the NT36xxx client at I2C4/0x62, rising
GPIO85/EINT8, and the vendor-derived transforms, but deliberately leaves both
adapter and client disabled (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:409-436). The current image
is the InputObserve composition, not DeviceActivation, so runtime
/i2c@11011000/touchscreen@62/status=disabled is expected.

Cycle18's read-only/live overlay result is authoritative for identity only:

> bound 1-0062 to novatek-nt36xxx, detected NT36772 trim 00 00 03 72 66 03 1080x2160, created event2, and cleanly removed/restored disabled status while both nets/watchdog stayed active.

The exact evidence is in
/mnt/Home/src/gemini-live-probe-cycle18-touch-20260830; its `RESULT:1-3` has
remote_rc=0, and its
`/mnt/Home/src/gemini-live-probe-cycle18-touch-20260830/dmesg-applied:1889-1890`
records the input and trim. This
does not prove a finger event, coordinates, calibration, reset polarity, or
VTOUCH regulator behavior. No physical touch observation is claimed.

The next gate is a separately reviewed recovery-only activation retaining the
identity, event stream, cleanup, and network/watchdog continuity, followed by a
physical touch test. Do not promote the probe to normal-image activation or
DEVICE-TESTED touch behavior.
