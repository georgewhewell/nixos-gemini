# Storage: eMMC and MicroSD

Status: eMMC is VERIFIED WORKING for bounded read-only access; MicroSD is
IMPLEMENTED-INACTIVE in the current image and remains UNKNOWN.

Current live eMMC is DF4064, 58.2 GiB, with p22/p30/p31 readable and
/gemian mounted read-only. The current p22 SHA-256 is
dddc5eb82952c8e597756c284c30558c2b78d6a41d3fc6357da71f4eb40084db; p30 is
122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159; p31 is
1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513. Debug
MMC reports 25 MHz, 8-bit, legacy timing, and zero recorded errors. This does
not prove high-speed modes, tuning, or write safety.

The current normal image intentionally does not compose DeviceActivation;
runtime /mmc@11240000/status=disabled and no MicroSD card/I/O are present.
The opt-in source overlay constrains a proposed controller to 4-bit, 25 MHz,
3.0 V, no-1.8-V operation (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-microsd-bringup.dtso:3-10,90-104).
Cycle13 did show the proposed `11240000.mmc` acquiring a CD GPIO
(`/mnt/Home/src/nixos-gemini-cycle13-device-activation-export/run-output/candidate-dmesg-full:1339`) and both MMC hosts completing probe
(`/mnt/Home/src/nixos-gemini-cycle13-device-activation-export/run-output/candidate-dmesg-full:1377-1379`), but its later `mmc1` result is the same
Samsung DF4064 58.2-GiB eMMC with p1--p33, boot0/boot1 and RPMB
(`/mnt/Home/src/nixos-gemini-cycle13-device-activation-export/run-output/candidate-dmesg-full:1431-1460`). MMC host numbering is dynamic, so an
`mmcblkN` name cannot identify controller lineage; no retained result proves a
MicroSD card or card I/O.

Next gate: re-audit controller/pin/rail lineage, insert a known card, and
retain card-detect plus read-only identification/I/O evidence. Do not promote
the DeviceActivation overlay or any mmcblkN inference to MicroSD support.
