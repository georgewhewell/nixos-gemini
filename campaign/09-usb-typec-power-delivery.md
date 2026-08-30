# USB, Type-C and power delivery

Status: the observed USB paths are VERIFIED WORKING; Type-C source/host role
is observed; PD, dual-role behavior, and charging remain UNKNOWN.

The current full Stage2 runtime has a configured high-speed UDC using
g_ether, usb0=10.15.19.82/24, and SSH. The right MUSB host enumerates the
RTL8156 adapter 0bda:8156; enu1=192.168.23.70 is up with carrier. Cycle18
overlay probes kept both networks and the watchdog active during cleanup.

Runtime Type-C reports FUSB301A at 3-0025, power_role=[source],
data_role=[host], orientation normal, partner present, and
supports_usb_power_delivery=no, PD revision 0.0. This is a current role
observation, not PD negotiation or charging evidence. The host overlay source
is explicit and host-only (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:5-34,91-129).

Next gate: test one declared cable/role at a time while preserving the left
gadget recovery path; retain Type-C state, VBUS, USB enumeration, and link
evidence. Do not write charger or CC-controller registers.
