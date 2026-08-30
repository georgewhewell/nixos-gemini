# Sensors, thermal and SCP

Status: GENERIC thermal, GPIO-key, and IMU drivers EXIST; MT6797 thermal
APPLICABILITY PROVEN; board sensor identity, SCP ownership and DT enablement
**UNKNOWN**; DEVICE-TESTED **NO**.

The current tree has the MT6797 thermal match
(`linux-gemini-platform@518957636:drivers/thermal/mediatek/auxadc_thermal.c:1748-1754`) and generic `st,lsm6ds3` I2C support. The Gemini board DT wires thermal calibration but leaves the BMI160 candidate disabled (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:333-346,503-506`).

Vendor DTS records a Hall input on GPIO66 and touch/keyboard-related GPIOs,
but the current board DT keeps the Hall gpio-keys node disabled and specifies a
64 ms debounce (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:536-551`). A vendor SCP directory is not proof that firmware, I2C ownership arbitration, wake sources, or step counting works.

The former thermal formulas, shared-zone explanations, “wakes AP” behavior, and
SCP deep-suspend claims are removed. Validate each assertion from a live trace.

Next validation: read the physically populated IMU ID over the correct bus,
capture calibrated thermal zones, and generate Hall open/close events on a
recoverable image. SCP tests require an identified firmware/ownership protocol.
