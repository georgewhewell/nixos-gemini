# Keyboard, notification LEDs and camera flash

Status: the base keyboard consumers are INERT; the Nix-pinned input contains an
OPT-IN polling keyboard overlay; DEVICE-TESTED keyboard, LEDs and flash are
**UNKNOWN**.

The base describes I2C5, AW9523 at 0x5b, GPIO58 reset, GPIO87/EINT10 facts and
an 8x7 matrix, but disables the expander and matrix
(`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:432-507`).
The polling overlay, present in the pinned input, enables I2C5 at 400 kHz and
uses the generic matrix path with 20 ms polling and 2 us column settling; it
deliberately omits the untested parent/row IRQ paths
(`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-keyboard.dtso:3-55`).

Its comment cites a retained prior run, but this campaign has no current
Gemini hardware acceptance for that exact Nix image/overlay. Vendor AW9120,
LED and flash source is not an activation contract. AW9120, LEDs, flash,
cameras and sensors remain outside the keyboard overlay’s scope.

After recovery revalidation, the first gate is a recovery-only keyboard image
with the polling overlay and a bounded, retained press/release subset. Do not
enable the AW9523 IRQ domain or any light output until its separate electrical
and safety evidence exists.
