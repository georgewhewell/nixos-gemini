# Cameras and ISP

Status: SOURCE EXISTS in vendor CAMSYS/sensor code; GENERIC V4L2 framework
EXISTS; MT6797 Gemini CAMSYS applicability and DT enablement **UNKNOWN**;
DEVICE-TESTED **NO**.

Vendor DTS records camera reset/power GPIOs: GPIO32/28 for one sensor,
GPIO33/29 for the other, and GPIO73/254 for candidate rails
(`vendor/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1103-1216`). This is a wiring record. The checked mainline tree has no Gemini camera nodes or MT6797 CAMSYS capture driver, so sensor names, I2C addresses, delays, CSI lanes, frame rates, chip IDs and libcamera graphs remain UNKNOWN.

The former “S5K4H8/HI551 detected”, MIPI lock, ISP feature, and frame-size
acceptance logs were invented examples and are removed.

Next validation: power exactly one physically identified sensor using a scoped,
reversible overlay; read its ID; then add a minimal CSI receiver and capture one
raw frame with timestamped media-bus configuration. Keep both sensor rails off
until that gate is reviewed.
