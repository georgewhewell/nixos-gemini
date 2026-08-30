# USB, Type-C and power delivery

Status: GENERIC UPSTREAM MTU3, MUSB, PHY and FUSB301 drivers EXIST; MT6797
APPLICABILITY PROVEN for declared USB nodes; DEVICE-TESTED **YES only for the
specific network paths recorded in `research/MAINLINE.md`**; role/PD/charging
coverage **UNKNOWN**.

The mainline board DT declares the left SSUSB peripheral resources and
`dr_mode = "peripheral"` (`/home/grw/src/linux-gemini-push/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:485-501`). `research/MAINLINE.md` records a deployed MTU3 gadget and a right-port MUSB/RTL8156 development path. Those results do not prove every cable, speed, role, VBUS, or charging transition.

The read-only 2026-08-30 snapshot in `research/HARDWARE_TEST_LEDGER.md`
confirms that the deployed p22 image currently has both `usb0` at
`10.15.19.82/24` and right-port `enu1` at `192.168.23.70/24`. This is a
repeatable network/debug baseline, not broader Type-C or power-delivery proof.

The vendor tree contains FUSB301 control GPIOs and USB power-switch descriptions
(`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon_gpio.dtsi:1-52`). Exact dual-port conflict behavior, current limits, PD negotiation and
safe OTG boost behavior are UNKNOWN. Never use raw I2C writes to charger or CC
controllers during a hardware test.

Next validation: retain the left gadget as the recovery path, test one port and
one role at a time, record Type-C state, VBUS/current and USB enumeration, and
exercise unplug/fault rollback before enabling dynamic role switching.
