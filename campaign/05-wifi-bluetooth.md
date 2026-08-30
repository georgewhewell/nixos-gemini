# Connectivity: CONSYS, BTIF, Bluetooth, GNSS, Wi-Fi and FM

Status: SOURCE EXISTS; CONSYS and BTIF are INERT in the board DT; live
transport, identity, firmware download and every radio client are
DEVICE-TESTED **NO**.

The base board describes the CONSYS resources and supplies but marks it
disabled (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:219-235`). It also carries a disabled MT6797 BTIF transport
description whose comment names pads, firmware and CONSYS ownership as unknown
(`:240-262`). Stage-A hardware acceptance saw no WMT/BTIF/CONSYS device and no
firmware request (`research/HARDWARE_TEST_LEDGER.md:297-301`).

Later source work adds a dormant WMT patch controller which cannot acquire any
power, reset, pad, BTIF DMA, STP ownership or endpoint itself and requires full
STP before patch traffic (`linux-gemini-platform@518957636:drivers/soc/mediatek/mt6797-consys-wmt-patch.c:21-27,225-303`). This work is
after the Nix kernel pin (`flake.nix:23-28`); it is not proof that a Nix
artefact contains it or that the device can exchange a byte.
Vendor STP/WMT source can constrain a future protocol implementation, but it
does not close pad, reset, DMA, transport ownership or recovery safety.

The next implementation gate is full hardware-independent STP validation.
The next hardware gate, only after a separate review, is a bounded resource or
identity observation that keeps reset asserted. No firmware request, radio
function, GNSS task, Bluetooth HCI, Wi-Fi or FM activation follows from the
existing source.
