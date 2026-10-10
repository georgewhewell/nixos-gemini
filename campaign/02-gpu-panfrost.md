# Mali-T880 / Panfrost

For the installed image and current integration, see [hardware status](../research/HARDWARE_STATUS.md). The observations below preserve the earlier bring-up baseline.

Status: GENERIC UPSTREAM DRIVER EXISTS; MT6797 APPLICABILITY PROVEN; DT ENABLED
**NO**; DEVICE-TESTED **UNKNOWN**.

Panfrost has an explicit `mediatek,mt6797-mali` match
(`linux-gemini-platform@518957636:drivers/gpu/drm/panfrost/panfrost_drv.c:1180-1184`). The SoC DT declares the Mali block at `0x13040000`, its three IRQs and four core power domains, but leaves it disabled (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797.dtsi:343-358`).

The Gemini board DT describes an RT5735 VGPU regulator at I2C address `0x1c`
but leaves that provider disabled (`linux-gemini-platform@518957636:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:353-369`). No local source proves a safe voltage/OPP table or a stable GPU power sequence. The vendor frequency/voltage table and a glmark2 score are not campaign evidence.

Next validation: prove the VGPU rail and MFG power-domain sequence at a fixed,
low OPP on a recoverable image; then capture Panfrost ID, fault counters, and a
deterministic render test. Do not enable DVFS as part of the first probe.
