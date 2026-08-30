# Cellular modem (MD1, CCCI and CLDMA)

Status: SOURCE EXISTS in the vendor tree; GENERIC UPSTREAM WWAN is not a
drop-in CCCI driver; MT6797 applicability and DT enablement **UNKNOWN**;
DEVICE-TESTED **NO**.

Vendor DTS/source describe an MD1 reserved-memory area, CLDMA and CCIF resources,
and VSIM rails. The CLDMA/CCIF resource declaration is explicit in
`vendor/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:1782-1806`.
The relevant declarations are in
`vendor/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi` and
`drivers/misc/mediatek/eccci/mt6797/cldma_reg.h`. They establish a source
contract, not a safe Linux modem boot. The current Gemini DT only reserves
generic CCCI memory (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:108-122`) and has no modem consumer.

The former claims about a 161 MiB fixed address, signatures, boot-status values,
SIM debounce, CCCI channel semantics, or ModemManager compatibility are removed:
the checked sources do not prove those details for this board. No modem firmware
may be loaded merely because a blob or register header exists.

Next validation: identify the physically populated modem and exact reserved
memory from a live vendor boot; document firmware ownership and MPU permissions;
then implement a fail-closed CLDMA/CCIF probe with bounded reset and teardown.
Only a captured modem boot handshake and AT/data exchange may become
DEVICE-TESTED.
