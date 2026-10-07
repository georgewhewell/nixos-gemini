# Power, PMIC, battery and DVFS

Current qualification is tracked in
[HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md) and
[POWER_QUALIFICATION.md](../research/POWER_QUALIFICATION.md). The accepted
baseline is M69; its October observations include charger status and fuel-gauge
current. Opt-in successors qualify real swap paging, watchdog expiry,
freezer/device diagnostics, guarded USB disconnection, awake RTC alarms and
firmware-compatible calendar read/write with retention through DA recovery.
Full suspend/wake, deep idle, hibernation and the complete lid policy remain
unfinished. Battery capacity/calibration, charging behavior and DVFS require
their own evidence; power/recovery tests do not establish them.

A fresh read-only observation during RTC startup recovery found
`cpufreq-dt`/`schedutil` policies 0 and 4, exposing 624–897 MHz and
1092–1209 MHz respectively. This disproves the historical absence of CPUFreq
interfaces, but is not a new transition, voltage, load or thermal test.
The charger reported online/Full and 4.284 V; `mt6351-fgadc` reported battery
current and Discharging, with no capacity attribute. No cpuidle driver was
published. Evidence: `handoff/power-rtc-startup-build/recovered-power-observation.stdout`.

## Historical Cycle18 observations

The following records the August probe configuration at `28c471502`, not the
currently selected kernel or runtime DT. Its disabled fuel-gauge child and
missing CPUFreq policy must not be carried forward as current observations.
At that point, BQ25896 was BOUND-UNVERIFIED, fuel-gauge preflight was read-only
and removed cleanly, and battery, charging policy and DVFS remained UNKNOWN
or IMPLEMENTED-INACTIVE.

That board source places the charger candidate at I2C0/0x6b and keeps
the VGPU/FAN candidates disabled (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:351-390,618-638). The live
full Stage2 image binds 3-006b to bq25890-charger, exposing TI
BQ25896, online=1, status=Not charging, and charge_type=N/A. This is a
read-only status observation, not proof of charging or battery operation.

Cycle18's second probe used gemini-live-fgadc with activate=N and reported:

> exact-active state ckpdn=0x1270 con0=0x29 osr=0x8, no child/power_supply, cleanly removed.

The exact evidence is
/mnt/Home/src/gemini-live-probe-cycle18-fg-preflight-20260830; its
`RESULT:1-3` has remote_rc=0 and its
`/mnt/Home/src/gemini-live-probe-cycle18-fg-preflight-20260830/dmesg-applied:1895-1901`
records clean overlay removal.
That full NixOS image intentionally composes InputObserve, not
DeviceActivation: the fuel-gauge child is disabled in the runtime DT.

The FG result does not establish battery capacity, voltage/current calibration,
CHR_STAT routing, charger control, or a safe charging policy. The exact BQ
variant beyond the compatible identity and the physical battery topology remain
could not determine. No raw PMIC or charger writes are authorized by this
evidence.

DVFSP handoff reaches state=ready and late_validation=passed in the live
dmesg, but no CPUFreq policy or OPP sysfs exists; classify DVFS as
IMPLEMENTED-INACTIVE. The next gates are a read-only charger/battery identity
record and a separately reviewed fixed-OPP DVFS test.
