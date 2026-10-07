# USB, Type-C and power delivery

The qualified left-port gadget and right-port host paths operate at USB2
high-speed. The left MTU3 controller is SuperSpeed-capable, but the selected
board DT enables only its USB2 PHY and caps it to high-speed. Physical
SuperSpeed routing/orientation and an actual 5 Gb/s link remain unqualified;
the right MUSB controller is USB2. Guarded software gadget disconnect/reconnect
and disconnected device-suspend diagnostics pass on the power/swap candidate.
Left-port OTG host behavior, PD and the remaining cable/role cases still need
qualification. See [HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md) for
source and live-speed evidence, and
[POWER_QUALIFICATION.md](../research/POWER_QUALIFICATION.md) for the bounded trials.

## Historical Cycle18 observations

These observations describe the August probe configuration at `28c471502`.
They establish only the listed cable/role setup and do not prove PD negotiation,
charging or SuperSpeed operation.

That full Stage2 runtime has a configured high-speed UDC using
g_ether, usb0=10.15.19.82/24, and SSH. The right MUSB host enumerates the
RTL8156 adapter 0bda:8156; enu1=192.168.23.70 is up with carrier. Cycle18
overlay probes kept both networks and the watchdog active during cleanup.

Runtime Type-C reports FUSB301A at 3-0025, power_role=[source],
data_role=[host], orientation normal, partner present, and
supports_usb_power_delivery=no, PD revision 0.0. This is a role
observation, not PD negotiation or charging evidence. The host overlay source
is explicit and host-only (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:5-34,91-129).

Next gate: test one declared cable/role at a time while preserving the left
gadget recovery path; retain Type-C state, VBUS, USB enumeration, and link
evidence. Do not write charger or CC-controller registers.
