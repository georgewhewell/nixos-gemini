# Cycle 13 live hardware probes

Date: 2026-08-30. Target: running NixOS rescue kernel
`7.1.3-gemini-da921x-lkro` on the Gemini PDA. These tests used external
modules built from `linux-gemini-platform` with the exact live config and
runtime DT overlays; they did not reboot or flash the device.

## Touchscreen

- I2C4 appeared as `i2c-3` and the client bound at `3-0062`.
- The driver identified `NT36772` with trim bytes `00 00 03 72 66 03` and
  geometry `1080x2160`.
- `/dev/input/event1` and `Novatek NT36xxx touchscreen` appeared.
- Overlay and driver removal removed the client, adapter, and input device.
- No physical touch event was generated during this test.

## MicroSD

- A reversible PMIC helper changed VMCH from disabled/3.0 V to enabled/3.0 V
  and VMC from enabled/2.9 V to enabled/3.0 V.
- The live overlay instantiated `11240000.mmc` and `mmc1`; the driver probed
  successfully without the earlier regulator errors.
- GPIO67 was owned as card detect and read low. No `mmcblk1` appeared, which
  is consistent with the slot being empty under the active-high board wiring.
- No card was mounted or written.
- Teardown restored VMCH to disabled/3.0 V and VMC to enabled/2.9 V exactly.

## MT6351 FGADC

- Read-only regmap inspection found the bootloader-established vendor state:
  `TOP_CKPDN_CON2=0x1270`, `FGADC_CON0=0x0029`, and
  `FGADC_CON15=0x0008` (clocks enabled, control 0x29, OSR 8).
- A fail-closed child bridge accepted only that exact DT-authorized state,
  instantiated the active driver, and exposed `mt6351-fgadc` in the power
  supply class.
- One read each returned `CURRENT_NOW=0 uA` and
  `CHARGE_COUNTER=-106 uAh`. These are interface/transaction qualification
  values, not a capacity calibration claim.
- Child removal ran the driver's restore path. The three registers above
  matched their pre-probe values exactly afterward.
- A node-reference defect in the first lab bridge revision was observed and
  fixed. A final overlay apply/remove preflight produced no OF warnings,
  errors, refcount diagnostics, or memory-leak diagnostics.

## What still needs a boot

Runtime probing cannot replace code already built into the running kernel or
observe failures before userspace. The hardened MMSYS/IOMMU/SMI/display gate,
SCPSYS MFG default-off policy, bootloader handoff, and early boot ordering
therefore need one combined watchdog-supervised boot. Display activation can
then happen live through `activate_drm`; it does not need another image.
