# Cycle 13 device activation result

Cycle 13 is the first unattended p22 hardware cycle that reached the
mainline NixOS candidate and stayed up after the watchdog lease was accepted.
The exact image was \`b0e982daf729be7b76da95490e37d3c0f2c11269b74e43f684c78f910a1545a7\`
(16 MiB); only p22 was written. Rescue p30/p31 remained intact.

The candidate proved the board-level bring-up needed for the next display
experiment: \`mtk-wdt\` ownership and petting, gadget SSH, the right-port
RTL8156 Ethernet path and DHCP, eMMC enumeration, AW9523/input devices,
NT36772 and FGADC read-only probes. Storage was not mounted writable and
the DRM/display gate remained deferred; \`activate_drm\` was not written.

Evidence is retained outside the repository under
\`/mnt/Home/src/nixos-gemini-cycle13-device-activation-export/run-output/\`,
including \`candidate-accepted-baseline.log\`, \`candidate-live-baseline.log\`,
\`candidate-dmesg-full\`, \`candidate-console-ramoops-0\`, and the Trex flash
record. The acceptance failure before the manual lease write exposed a
harness bug: Linux names this board's eMMC \`mmcblk1\`, not always \`mmcblk0\`.
The harness and both generated targets now resolve the device through the
board's \`11230000.mmc\` sysfs lineage and fail closed on ambiguity.
