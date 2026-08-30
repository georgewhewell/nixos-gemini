# Display and DRM/KMS

Status: SOURCE EXISTS; DT is INERT by default; an OPT-IN display overlay is in
the Nix-pinned input; BUILD-TESTED only where a named build manifest says so;
DEVICE-TESTED **UNKNOWN**.

The base board DT does not apply the display overlay. The overlay is explicitly
described as recovery-slot-only and not device-tested
(`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-display.dtso:3-10`);
it supplies the I2C bias device, GPIO60/GPIO251 enables, display blocks, panel,
and GPIO180 reset (`:17-121`). Nix defines a `mainlinePlatformSmoke` output
which selects display and audio overlays (`flake.nix:396-415`) and validates
their composed-DT properties (`nix/mainline.nix:560-577`). Those are source and
composition facts, not pixels.

Vendor panel wiring text remains useful only as source evidence:
`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1043-1102`
and its LCM driver. It does not establish a safe current panel power sequence,
mode, backlight, or display-device result.

No retained Gemini display mode-set or physical image is cited by the hardware
ledger. The gate is therefore: retain a build manifest and composed DT for the
exact image; recover the read-only baseline first; then boot the opt-in overlay
through the recovery procedure and capture component binding, regulator/clock
errors, `modetest`, and a physical panel observation. A successful probe alone
is not DEVICE-TESTED.
