# USB, Type-C and power delivery

Status: the earlier baseline DEVICE-TESTED the stated USB network paths; the
current physical state, Type-C roles, PD and charging are **UNKNOWN** pending a
fresh read-only recheck.

The independent baseline saw the left gadget at `usb0` with SSH and the
right-port Ethernet interface `enu1` (`research/HARDWARE_TEST_LEDGER.md:39-47`).
Stage A again reported USB and Ethernet after its p22 acceptance
(`:291-300`). The Nix-pinned input also contains the separate right-port
host-only FUSB301A/MUSB overlay (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:3-128`), and Nix's host profile
selects it (`nix/mainline.nix:47,68-71,383-390`). Those facts do not establish
PD, device/dual-role behaviour, charging, every cable or the RTL8156 adapter.

The last authorized p22 run ended with the gadget enumerated but the Trex
interface down, no SSH and no post-rollback hash capture
(`research/HARDWARE_TEST_LEDGER.md:655-674`). Thus the old text claiming that
the deployed image “currently” has both interfaces was stale.

First recover route/interface/SSH and capture pstore plus all partition hashes.
Only then test one known cable, port and role at a time, preserving the left
gadget as recovery. Pass a host test only with retained Type-C state, VBUS,
enumeration and link evidence; do not write charger or CC-controller registers.
