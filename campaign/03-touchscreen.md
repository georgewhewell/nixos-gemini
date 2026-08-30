# Touchscreen

Status: SOURCE EXISTS; the base NT36xxx client and its bus are INERT; the
Nix-pinned input contains an OPT-IN bus observer; safe client activation and
DEVICE-TESTED **UNKNOWN**.

The current base describes an NT36xxx client at I2C4/0x62, rising GPIO85/EINT8,
and vendor-derived X/Y transforms, but deliberately leaves both adapter and
client disabled. Its comment explicitly records the unresolved physical
VTOUCH regulator mapping (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:388-412`).
The pinned observer only enables I2C4; it leaves the client disabled and
therefore makes no touch I2C transfer or EINT request
(`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-touchscreen-observe.dtso:3-33`).

Vendor DTS text records GPIO85/EINT8 and a selectable GPIO68 reset state
(`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:579-638`).
It does not determine reset polarity/timing, VTOUCH regulator identity or
voltage, controller revision, or a safe read transaction. The later read-only
VTOUCH collector exists at `linux-gemini-platform@2fcd32294`, but it is not in
the Nix pin (`flake.nix:23-28`).

The next gate is vendor-boot collection of the actual VTOUCH phandle and
regulator properties, without I2C/GPIO/PMIC writes. Only an exact rail and
reset contract can justify a separately selectable recovery-only client
overlay. Until then, no address scan, polling substitute, or IRQ activation is
permitted.
