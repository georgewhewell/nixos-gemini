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

A second diagnostic boot, `fcc8068c-75da-4486-9eb5-2c60f99eefda`, verifies
short load and the expanded cooling control path on the same kernel. Eight
A53 workers completed1589 digest-checked PBKDF2 batches over10 seconds.
All10 load samples read897/1209 MHz under schedutil. Actual temperature rose
from42.0 C to a sampled peak53.7 C. Workers stopped before thermal emulation.

Synthetic86/88/90/92/94/96/98 C readings then exercised LL cooling states
1/2/3/4/5/6/6, capping and actually running the CPU at
806/715/624/481/338/221/221 MHz. L remained capped at1092 MHz. Clearing emulation
returned both cooling states to0 and limits/hardware frequencies to897/1209 MHz.
The rail stayed at1.00 V and initial/final CCI/A72 reads were unchanged.
Both schedutil governors and core parking were restored; the probe became
inactive/MainPID0, the system stayed running, and the captured kernel log
contained no clock-fencing, BUG, Oops, WARNING or CPUCLK_OBSERVE report.
The final actual temperature was41.2 C. Evidence:
`handoff/dvfs-thermal-trial-01/{dvfs.json,summary.json,after-probe.txt,kernel-error-check.json}`.
This establishes the emulated cooling control path and a short load test;
it does not establish operation at a physical98 C, sensor accuracy or long-term
thermal stability.

The maintained kernel now also enables L325/468/650/832/962 MHz using a
MAINPLL fallback for postdivider changes (Linux930feb4a2797c). Diagnostic boot
`eb21aebb-28a1-4fb2-b434-67b095e99a67` passed all49 LL and49 L ordered pairs,
including20 L transitions across the postdivider boundary. CPU and raw ARMPLL
rates matched;325/468 MHz used raw650/936 MHz with CKDIV2. Every PBKDF2 digest
passed and median CPU time decreased consistently as frequency increased.
The98 samples completed in23.671 seconds at36.7–40.7 C and a fixed1.00 V;
CCI remained629999328 Hz and A72 remained750 MHz. Both schedutil governors
were restored and the owned core-parking hold was removed. Follow-up found the probe
inactive/MainPID0 and system running; captured kernel logs had no fencing,
BUG, Oops, WARNING or CPUCLK_OBSERVE reports. Evidence:
`handoff/dvfs-postdivider-trial-01/{dvfs.json,summary.json,after-probe.txt,kernel-error-check.json}`.

The transition owns the TOPCKGEN shared setting through its provider lock,
prepares MAINPLL, protects/revalidates its rate, checks FHCTL ownership and
uses temporary CKDIV4. A failed PLL retune cannot switch back to that PLL;
faults fence further CPU clock changes and retain fallback rate protection.
Production host models cover196 L pairs across four saved fallback settings,
1040 postdivider failure cases and the original49 LL pairs/371 failures.
This is bounded diagnostic hardware acceptance; normal cgroup2 qualification
still requires validation.

A follow-up with the same kernel, boot `6f8ffc4b-dffa-4be4-a580-c8b921c0b9ab`,
also passes the expanded cooling path. Eight A53 workers completed1597 checked
PBKDF2 batches in10 seconds. All10 load samples reached897/1209 MHz, with
actual temperatures49.1–53.4 C. After workers stopped, synthetic86–98 C
readings drove both clusters through cooling states1–6: LL806/715/624/481/
338/221 MHz and L1092/962/832/650/468/325 MHz, with matching hardware reads.
Clearing emulation returned both states to0 and actual clocks to897/1209 MHz.
The rail stayed1.00 V; CCI/A72 initial/final clocks were unchanged. Both
schedutil governors and idle topology0,8–9 were restored; the probe was
inactive/MainPID0 and the system remained running. Captured kernel error
scan is empty. Final actual temperature40.8 C; total probe15.242 seconds.
Evidence: `handoff/dvfs-postdivider-thermal-trial-01/{dvfs.json,summary.json,after-probe.txt,kernel-error-check.json,parking-followup.txt}`.
This covers short load and emulated cooling, not prolonged load, physical
operation at98 C or temperature-sensor calibration.

Remaining DVFS work includes CCI/shared-voltage and CPU LDO/Vsram coordination,
A72 control and sustained
load/physical thermal qualification. Battery capacity,
calibration, charging, deep idle and suspend remain separate unfinished work.

## Battery profile source for the remaining capacity work

The pinned vendor tree51e705e4 selects `CONFIG_MTK_HAFG_20=y` in its Gemini
configuration. `drivers/power/mediatek/Makefile` therefore selects
`battery_meter_fg_20.c`, whose `batt_meter_init_cust_data()` calls the header
initializer; the DT initializer call is commented out. Do not use the generic
`mt6797.dtsi` value `q_max_pos_25=2707` as the active Gemini capacity profile.

The selected MT6797 `mach/mt_battery_meter.h` defines `Q_MAX_POS_25=4268`
and high-current value4245, and leaves multi-battery-profile support disabled.
`mach/mt_battery_meter_table.h` supplies temperature-specific battery and
resistance tables copied by that initializer. Source is the pinned vendor
input `/nix/store/0km8xgjj4mjjsi7cljjl0bkjmpr1lwfz-source`; the header paths
are under `drivers/misc/mediatek/include/mt-plat/mt6797/include/`.

This identifies the vendor algorithm's inputs, not a calibrated capacity
measurement of the installed battery or a ready-to-use OCV table. The native
FGADC still exposes current and charge counter without capacity. Remaining
work must establish voltage/temperature inputs, counter calibration and
initial-state estimation before publishing a battery percentage.

Through Linux ae2f67c1f0182, the board used a118 percent current/coulomb multiplier. The same
vendor header defaults to115 on the MT6351 configuration, but the vendor
FG daemon can replace it with `FG_DAEMON_CMD_SET_CAR_TUNE_VALUE`
(`battery_meter_fg_20.c:4706`). Therefore the header default alone does not
justify changing the native multiplier. Its per-device calibration provenance
still needs checking. The original native overlay commit4cd4726d75b7c
explicitly took118 from the generic vendor DTS; it did not cite a measured
factory value. That DTS is not the selected vendor initializer described
above, so118 must not be described as an established per-device calibration.
Linux d76b7e4eff9fb corrects the board default to115 to match the selected
vendor header. This is a source-selection correction, not a new calibration
measurement or proof of a factory override. Vendor `get_hw_chip_diff_trim_value()` also hardcodes
trim index0, yielding1000 permille, in the selected source path.

## Battery measurement supplier integration

Linux ae2f67c1f0182 connects the native FGADC battery monitor to the board's
BQ25896 power supply through `power-supplies`. The battery's voltage and
temperature properties delegate to the charger; current and charge count
continue to use the PMIC gauge. Missing suppliers defer before changing gauge
hardware; malformed supplier lists reject. Boards without the optional link
retain the original property set. Charger notifications now propagate to the
battery device. The BQ25890 family driver publishes its firmware node so the
power-supply core can resolve the supplier relationship.

The voltage source is the charger's battery-terminal ADC; its temperature
conversion is the existing rough10K NTC lookup, not a new calibration result.
No capacity estimate or charging-policy changes are introduced. Host tests
exercise native/supplier routing, read errors, signed temperatures, missing
and malformed references, probe deferral, notifications and firmware-node
registration in normal and read-only charger modes. ARM64 gauge/charger
objects and Gemini DT compile; targeted binding validation passes. Both normal
and diagnostic bundles build with the same kernel and all packaged tests pass.

Diagnostic boot `ea2e7520-4e2a-4af3-b0aa-04f8833eaf24` verifies the actual
supplier phandle and all12 sequential battery/charger comparisons match
exactly:4.284 V and38.0 C over6.915 seconds. Battery uevents contain the new
voltage and temperature properties. Native current samples range from
-25.960 to-2.360 mA; charge counter remains0 during this short window.
The probe ends inactive/MainPID0 and the system remains running. Captured
kernel log has no gauge timeout, BUG, Oops, WARNING or clock-fencing report.
Evidence: `handoff/battery-supplier-trial-01/{battery.json,summary.json,after-probe.txt,kernel-error-check.json}`;
build/probe sources and calibration provenance are in
`handoff/battery-supplier-20261007`.

This qualifies property routing and available readings under the diagnostic
configuration. It does not calibrate the analog inputs or establish capacity.
In that build, the separate native status read still followed instantaneous
gauge-current sign: it toggled Charging/Discharging/Not charging while the
charger remained online/Full. Those sequential readings are not atomic.
The subsequent charger-backed status change is described below.

The diagnostic completed observation and failed the expected cgroup2 check.
Automatic recovery returned healthy M69 boot
`e5a684af-8877-4534-a5cf-34bcc64f0915`. The worker is terminal, with no writer,
35 matching source hashes and26 retained outputs. No default was promoted.

## Charger-backed battery status

Linux a01c00222dfa8 also delegates battery status to the configured charger,
which owns termination and input state. Gauge-current sign no longer turns
Full into Charging/Discharging/Not charging near zero. Supplier errors are
returned instead of silently reverting to the noisy current sign. Boards
without the optional charger link retain the existing native status behavior.
Host tests cover all five supplier states despite gauge sign changes and
latch failures, error propagation, and the supplier-free path.

The new conversion test exercises production current and counter decoding:
37 coherent samples cover positive/negative values, both zero codes, reserved
CAR bits,115/118/unity gain, board slope, trim, micro-unit scaling, and capture
failures that must not publish partial results. Both tests are normal Nix
kernel checks. ARM64 builds, binding validation and normal/diagnostic Nix
builds pass; both bundles use the same kernel.

Diagnostic boot `b1026674-79a7-4e5c-9e67-508f8327ba67` passes all12 battery/
charger status comparisons over7.004 seconds. Both statuses remain Full while
instantaneous gauge current ranges from-34.5 to+6.9 mA. The live DT reports
115 percent and every current sample is a multiple of2300 uA, as expected
from the existing conversion with the corrected multiplier. Voltage/rough
temperature remain4.284 V/38.0 C and match the supplier. The probe ends
inactive/MainPID0, system running, topology0,8–9, with no gauge timeout,
BUG, Oops, WARNING or clock-fencing report in the captured log. Evidence:
`handoff/battery-status-trial-01/{battery.json,summary.json,after-probe.txt,kernel-error-check.json}`.
This validates status routing under the observed Full state and numerical
configuration, not physical current calibration or unplugged/charging-cycle
behavior. Capacity remains absent.

The four active vendor battery curves each contain96 entries. Discharge
percentage is nondecreasing, voltage is nonincreasing, and each curve spans
0–100 percent discharge; the matching resistance tables also contain96
entries at the same voltages. Repeated end-of-discharge entries require
handling before conversion to an OCV lookup table. These are source-profile
properties, not installed-battery capacity or calibration evidence. Shape
analysis is in `handoff/battery-status-20261007/vendor-profile-shape.json`.

The battery-status trial completed automatic recovery to healthy M69 boot
`a8d32ece-2bd2-47a3-8cf5-fe9d92c18659`. The worker is terminal, and the
final audit confirms no writer, both locks acquired, all 35 source hashes
unchanged and all 26 ordinary outputs retained. The diagnostic remains
unqualified for normal cgroup2 operation; no default was promoted. Final
evidence: `handoff/battery-status-trial-01/final-idle-check.json` and
`handoff/battery-status-20261007/completion.json`.

## Original-pack voltage profiles (October 7)

Linux `eb2d529cd4684` adds the four original-pack zero-current voltage
profiles through a standard `simple-battery` node referenced by FGADC's
`monitored-battery`. The active HAFG_20 header initializer supplies these
same arrays to the vendor fuel-gauge daemon; its voltage lookup calls them
ZCV profiles. The vendor generic DTS and the inactive `battery_meter.c`
algorithm are not the source of this data.

The importer pins the SHA256 of `mt_battery_meter_table.h` from vendor
revision `51e705e4e7b1e52a31a79985f7fbbc9e98b59c8c`, converts mV to uV
and depth of discharge to remaining percent, and removes only identical
consecutive points. The four 96-entry arrays become 94, 87, 87 and 85
strictly descending voltage tables at -10, 0, 25 and 50 degrees Celsius.
The header's `TEMPERATURE_T0=110` is a selector, not 110 degrees Celsius.
Different percentages at the same voltage, malformed input and nonmonotonic
data are rejected. No Qmax value is relabelled as design capacity, and no
charge limits or charger reference are added to this battery node.

`tools/gemini/test-gemini-battery-profile-host.py` verifies original-data
hashes and runs production Linux OCV lookup and fixed-point interpolation
against 7,307 exact rational voltage cases, 161 temperature selections and
missing-table behavior under undefined-behavior sanitization. Linux's helper
selects the nearest temperature table, with the colder table winning ties;
this is not a claim that the vendor daemon used that same selection policy.
The importer regenerates the checked-in DTSI byte for byte. The ARM64 DTB
build and battery/FGADC schema validation pass; the build still reports the
existing MTU3 empty-ranges address/size-cell warnings.

This supplies estimator inputs, not a complete estimator: `CAPACITY` remains
absent. Load/temperature compensation, initial state, counter reset/wrap and
suspend behavior, full/empty anchors, aging and charge/discharge validation
still need implementation or qualification. In particular, the current
vendor-compatible counter decoding discards portions of the CAR register;
those ignored bits must not be assumed to prove the hardware's wrap modulus.
The normal kernel and deployment bundle build and all packaged checks pass.
The packaged DTB is byte-identical to the schema-validated DTB; its source
manifest names the committed revision. Build artifacts, kernel check log and
verification record are in `handoff/battery-profile-20261007/`. The profile
change has not been booted on the device. M69 remains the recovered runtime,
and the allocator files remain unchanged by this work.

## Native percentage estimator (October 7)

Linux `7e59616b85be4` implements optional software capacity and estimated OCV
in the native FGADC supply. Gemini supplies the active vendor's four
voltage-dependent resistance tables and temperature/Qmax pairs through the
new documented model properties. Both source headers are hash-pinned by the
importer. Qmax remains an internal model input; the driver does not expose it
as measured aged capacity or design capacity, and makes no charger-policy
writes.

The estimator interpolates resistance, Qmax and OCV-derived remaining charge
between the bracketing temperatures. It solves the loaded-voltage equation
on the combined resistance-table segments, rejecting multiple electrical
solutions or values outside the 2–5 V calculation range. Such ambiguity
prevents a voltage anchor but does not discard an already established,
continuous coulomb estimate. A charger Full indication anchors 100 percent;
a compensated empty voltage anchors zero during discharge. Otherwise gauge
counter differences update the accumulated charge. A temperature excursion
cannot discard charge merely because the model Qmax temporarily decreases.

A zeroed counter, a step larger than 5 percent of model Qmax, a backwards
clock, a gap over 60 seconds or suspend loses continuity and requires a new
voltage/full anchor. The implementation does not guess a CAR wrap modulus.
A reset to a small nonzero value is not reliably distinguishable from a real
charge delta; physical counter retention and discharge testing remain
necessary. After 10 minutes below C/50 while neither Charging nor Full,
compensated voltage can correct drift. These are explicit estimator rules,
not a port of the vendor userspace daemon or a claim of calibrated accuracy.

A freezable worker samples every 5 seconds, with a 1-second refresh request
on supplier changes. Model locking serializes capture/publication and work
scheduling; cancellation completes before supply removal or hardware restore.
Suspend stops work and invalidates continuity. Getters reject sensor errors
and readings older than 60 seconds. Older DTs without the optional model
retain the existing properties and behavior.

Production arithmetic tests cover full/empty/relaxed anchors, counter updates,
resets, discontinuities, gaps, time reversal, temperature excursions and
invalid inputs. The board sweep checks 23,935 usable roots and 1,040
ambiguous/out-of-range cases with undefined-behavior sanitization. Separate
production-function tests cover parser/allocation errors, battery matching,
partial sensor reads, error propagation, stale data, notifications and
start/stop/suspend/resume callbacks. ARM64 object/DT builds and binding/DT
schema checks pass. Normal and diagnostic image builds and all packaged
checks pass and use the same kernel. Diagnostic boot
`b32cb972-2ec5-46ac-a8cf-62fc14187e74` passes 32 samples over 66.101 seconds,
with the last sample after 63.981 seconds. Capacity remains 100 while battery
and charger status remain Full. Estimated OCV ranges from 4.281317 to
4.285338 V across 11 distinct values; terminal voltage remains 4.284 V and
rough temperature 38.0 C. Instantaneous current spans -16.1 to +34.5 mA and
the counter remains zero. The live model pairs and battery/charger phandles
match the built data. The probe ends inactive/MainPID 0, system running,
schedutil selected, with no captured gauge timeout, clock fence, BUG, Oops
or WARNING. CPU topology at that snapshot is 0–1,8–9 under automatic core
parking; the probe never overrides it.

This verifies the new properties, continued estimate updates beyond the
60-second stale-data limit, and the observed Full anchor. It does not verify
discharge integration or physical percentage accuracy. The 90.504-second
observation completes; the diagnostic still fails the normal cgroup2 memory
controller gate as expected. Automatic recovery completes to healthy M69 boot
`ed1feaea-5f15-4859-aa30-5e9216db5723`. The worker is terminal and the final
audit confirms no writer, both locks acquired, all 35 source hashes unchanged
and all 26 ordinary outputs retained. No default is promoted. Physical
aging, current/temperature calibration and complete charging/discharging
qualification remain outstanding. Build/probe sources are recorded in
`handoff/battery-estimator-20261007/`; on-device measurements and the kernel
error check are in `handoff/battery-estimator-trial-01/`.

## CPU rail admission and remaining voltage control

Maintained Linux `2db1ca9770760` corrects a units error in calibrated-DVFS
admission. Vendor `mt_cpufreq.c` expresses voltages in 10 microvolt units:
the nominal SRAM offset is 100 mV, the maximum offset is 300 mV, and the
SRAM range is 1.0–1.2 V. Its runtime checks allow equal CPU/SRAM voltages
at the upper ceiling. The old 10–30 mV admission window rejected valid
vendor operating points. EEM table construction, handoff admission and
snapshot matching now share the same overflow-safe rail check. Snapshot
matching also enforces the SRAM absolute range.

The production admission paths pass 733 host cases under UBSan, covering
boundary values, DA9214 selectors, SRAM rounding and unsigned overflow.
The three affected ARM64 driver objects and the adjusted calibrated-provider
KUnit object compile. The host test substitutes unrelated provenance and
EEM voltage conversion; it does not exercise physical rail transitions.
The normal kernel package now runs this regression test.
The full normal kernel build and its complete check phase pass, producing
`/nix/store/vdgk5l0gvddcarcnak5nnkpypla48qcp-linux-gemini-7.1.3`.
The source manifest, build/check logs and retained output are recorded in
`handoff/cpu-rail-admission-20261008/`. No device trial was started for this
admission-only change.

Voltage scaling is still inactive. The production tree has no caller of
`mt6797_dvfsp_vendor_owner_bind()`, so the calibrated-provider plumbing is
not an active voltage controller. The active CPU clock planner accepts
MP0/MP1 transitions only; CCI remains observational. BUCKA is constrained
to 1.00 V and supplies both A53 clusters and CCI. Implementing scaling
requires shared voltage votes, CCI frequency control, and ownership of the
eight CPU SRAM LDOs at INFRACFG offsets 0xf98/0xf9c/0xfa0. The vendor sets
both four-lane SRAM registers together in 25 mV steps, raises SRAM before
CPU voltage and lowers CPU voltage before SRAM, with bounded intermediate
rail differences and settling delays. These operations need readback and
failure handling coordinated with the existing DVFSP hardware lease.
The PMIC `vsram-proc` regulator must not be assumed to represent these LDOs.
CCI also needs its own DCM sequence: vendor `set_cur_freq()` selects zero
before a CCI downshift, unlike the A53 target-frequency calculation;
`sync_dcm_set_cci_freq()` updates selector bits 5:1 and its toggle in the
shared MCUCFG DCM register. Extending the MP0/MP1 transition code by merely
adding a CCI rate table would omit this domain-specific behavior.
No operating-point voltage or device runtime setting changes in this fix.

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
