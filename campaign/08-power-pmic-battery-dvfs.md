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

## Fixed-voltage A53 DVFS evidence

On October 7, recovered M69 boot
`488faade-81bc-485e-b673-8a98c449739a` passed an ascending and descending
walk of all six enabled frequencies (12 measurements). CPU0 ran at
624/715/806/897 MHz and CPU4 at 1092/1209 MHz. Every hardware frequency
read matched the request. A pinned PBKDF2 workload produced the expected
digest at every step; mean CPU time fell from 2642 to 1805 ms on CPU0 and
1444 to 1301 ms on CPU4, consistent with the frequency changes.

The shared little/CCI rail remained at 1.00 V. CCI stayed at 629999328 Hz
and A72 at 750 MHz. Measured temperatures ranged from 35.8 to 38.6 C.
The probe used the existing core-parking hold to bring CPUs0–9 online,
then restored both governors to schedutil and removed its own hold.
Core parking returned to CPUs0,8–9 online, the system remained running,
and the test unit ended inactive with MainPID=0. Policy4 returning EBUSY
while CPUs4–7 are parked is not a frequency-transition failure.
Evidence: `handoff/dvfs-current-20261007/{probe.py,result.json,analysis.json,final-health.txt,kernel-check.txt}`.

Historical `handoff/m42c-test-dvfs.txt` also proves the six-frequency walk,
schedutil reaching both policy maxima under load, emulated thermal cooling
states and their release, hotplug, and the unchanged 1.00 V rail. Those
thermal-emulation and load checks were not repeated in the October walk.
The failed M41 test predates the M42 CPU8 OPP-sharing fix; it is not evidence
of a current missing CPUFreq interface.

The clock provider, core/header, cpufreq-dt/platform glue and OPP OF code
are byte-identical between M69's `c0dbf01b2bdaa` and maintained Linux
`d25a82d67956d` (`source-comparison.json` in the October evidence directory).
That source comparison does not qualify the maintained kernel as a whole;
normal cgroup2 allocator stability remains unresolved.

## Low LL frequencies enabled and exercised

Maintained Linux `cad55d85bcfe0` now coordinates ARMPLL and CKDIV as a single
clock transaction and enables LL 221/338/481 MHz alongside 624–897 MHz.
The raw PLL clocks remain read-only observation points; compound
`mt6797_mp[01]_armpll_div` clocks own rate changes. DCM is lowered for the
minimum intermediate CPU rate, division increases before the PLL hop and
decreases afterward, and final DCM/readback completes the transaction.
Failures after writes begin fence further changes. The shared rail remains
fixed at 1.00 V; this adds frequency scaling, not voltage scaling.

Diagnostic boot `e69c5c64-db70-4d28-9b2c-57053312ddb1` passed all49 ordered
pairs among the seven LL frequencies plus all4 pairs among the two L
frequencies in15.24 seconds. Each step checks the CPU rate, divided clock,
raw PLL rate, fixed rail, unchanged CCI/A72 and a pinned PBKDF2 digest.
The low points read PLL884/676/962 MHz for CPU221/338/481 MHz respectively.
Temperatures were37.1–41.8 C. Both governors returned to schedutil, the owned
parking hold was removed, and the probe unit became inactive/MainPID0.
The collected kernel log contains no clock-fencing, BUG, Oops, WARNING or
CPUCLK_OBSERVE report. Evidence:
`handoff/dvfs-divider-trial-01/{dvfs.json,analysis.json,after-probe.txt,candidate-kernel.log,kernel-error-check.json}`.

The normal kernel and both normal/diagnostic bundles build successfully and
share the identical kernel. Host tests execute production planning/callback/
transaction code:49 pairs, all32 initial DCM selectors,371 injected write
failures, stale plans, readback errors and fenced retries. These models cover
software sequencing; the device test above establishes bounded hardware
acceptance. The diagnostic still fails the unchanged cgroup2 memory-controller
qualification check and is not promoted.

Remaining DVFS work includes postdivider transitions, lower L points,
CCI/shared-voltage and CPU LDO/Vsram coordination, A72 control, sustained load
and thermal cooling qualification across the expanded range. Battery capacity,
calibration, charging, deep idle and suspend remain separate unfinished work.

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
