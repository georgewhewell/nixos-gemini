# Power, PMIC, battery and DVFS

Status: SOURCE EXISTS; the BQ2589x observer is OPT-IN and no-write; battery,
fuel-gauge, charging policy, DVFS and DEVICE-TESTED power management are
**UNKNOWN**.

The board DWS routes `SW_CHARGER` to I2C0/0x6b
(`vendor/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:3679-3683`),
and the retained vendor capture reports a bound `bq25890` at that address while
explicitly not logging the exact part number
(`research/mt6797-bq25896-routing-evidence/README.md:138-151`). The Nix-pinned
kernel input contains a BQ25896/BQ25890-compatible overlay which exposes only
I2C0, the address and `ti,read-only`, with no IRQ, charge limits, battery,
regulator or OTG control (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-power-observe.dtso:3-33`).

Nix defines, but does not thereby hardware-prove, a platform recovery output
that selects this overlay (`flake.nix:417-436`); the composed-DT check confirms
the no-IRQ/read-only shape (`nix/mainline.nix:584-598`). Exact BQ variant,
CHR_STAT routing, fuel-gauge device, battery electrical parameters and safe
charge policy could not be determined.

The next gate is after recovery revalidation: boot only the no-write observer,
retain its I2C/driver errors and exposed read-only values, and stop. No raw PMIC
or charger writes, regulator control, OTG, battery reporting or DVFS change is
authorized by this evidence.
