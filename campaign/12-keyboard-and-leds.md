# Keyboard, notification LEDs and camera flash

Status: SOURCE EXISTS; GENERIC AW9523 pinctrl and gpio-matrix-keypad drivers
EXIST; MT6797 applicability for the expander is binding-level only; Gemini DT
consumers are disabled; DEVICE-TESTED **UNKNOWN**.

The mainline board DT describes an AW9523-compatible expander at I2C address
0x5b, GPIO87 interrupt, GPIO58 reset and an 8x7 matrix, but leaves both
expander and matrix disabled (`/home/grw/src/linux-gemini-push/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:366-483`). Vendor DTS confirms the legacy keyboard and AW9120 GPIO245 power-down pin (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:641-700`).

No current mainline AW9120 or LM3643 Gemini consumer is proven. Vendor LED
microcode, key maps, debounce behavior, chip IDs, flash currents and autonomous
breathing behavior are SOURCE EXISTS only. The former “PROVEN” key/LED/flash
claims and guessed compatible strings are removed.

Next validation: enable only the AW9523 node on a recoverable image, verify I2C
ID, reset/IRQ and a small key subset, then expand the matrix. Treat AW9120 and
flash as separate devices; verify rails and thermal timeout before any light
output.
