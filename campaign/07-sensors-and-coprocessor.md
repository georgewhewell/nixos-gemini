# Sensors, thermal and SCP

For the installed image and current integration, see [hardware status](../research/HARDWARE_STATUS.md). The observations below preserve the earlier bring-up baseline.

Status: raw SoC thermal readout is VERIFIED WORKING; Hall and keyboard input
are BOUND-UNVERIFIED; IMU/SCP remain IMPLEMENTED-INACTIVE or UNKNOWN.

The live image exposes soc-thermal at about 46 C and binds the MT6797 thermal
driver. Dmesg says No trip points found, so this is a sensor readout, not a
validated cooling policy. The current board source wires calibration but keeps
the BMI160 candidate disabled (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:393-406,607-616).

The Hall gpio-keys node and keyboard matrix are present in the current runtime,
but no physical Hall transition or key press was retained. No IIO device is
present, and the SCP node has no bound remoteproc/firmware device. A vendor SCP
directory is not proof of ownership, wake, or sensor behavior.

Next gates: capture calibrated thermal readings under a known load, generate a
Hall open/close event on a recoverable image, and read the physically populated
IMU identity over the correct bus. Suspend/wake behavior remains untested.
