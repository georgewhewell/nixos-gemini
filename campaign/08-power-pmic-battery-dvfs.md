# Power, PMIC, battery and DVFS

Status: SOURCE EXISTS; GENERIC PWRAP/MT6351, regulator, charger and cpufreq
drivers EXIST; MT6797 Gemini rail/PMIC applicability **PARTIAL**; DT ENABLED
only for limited read-only providers; DEVICE-TESTED **UNKNOWN**.

The shared DT declares the MT6797 PWRAP and MT6351 child devices
(`/home/grw/src/linux-gemini-push/arch/arm64/boot/dts/mediatek/mt6797.dtsi:372-398`). The Gemini board enables only VEMC/VIO18 descriptions and a read-only DVFS handoff; it leaves the GPU regulator disabled (`mt6797-gemini-pda.dts:190-204,314-330`).

Vendor PMIC and SPM sources are useful for register names and candidate rails,
not proof of safe suspend, Pump Express, battery capacity, coulomb compensation,
or a CPU OPP table. The former exact voltages, current limits, sleep current,
wake masks and “PROVEN” suspend/charging claims are removed.

Next validation: preserve the working recovery image; prove PWRAP reset and
read-only register access; add one regulator at a time with scope/current
limits; then test thermal-safe fixed-frequency CPU operation. Suspend, charging,
FGADC and DVFS each need their own captured device gate.
