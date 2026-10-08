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
not an active voltage controller. At that revision the CPU clock planner
accepted MP0/MP1 transitions only. BUCKA is constrained
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

Maintained Linux `527849181352c` subsequently adds CCI clock transactions
through the same CSPM lease, hardware semaphore and fault fencing as A53
transitions. It implements all 16 CPU_LEVEL_1 vendor frequencies from
169 to 988 MHz, with the vendor /2 and /4 path dividers at low rates,
FHCTL channel 2, and the CCI DCM downshift behavior described above.
CCF registers a separate CCI PLL/divider branch; A72 remains observational.
No consumer or devfreq policy is added and no voltage constraint is relaxed.

Host tests execute all 256 ordered CCI frequency pairs and 1,836 injected
write failures, including a postdivider handoff from an alternate inherited
PLL configuration. They check sibling register preservation, zero DCM on
downshifts, rejection of stale plans, channel-2 ownership and fencing.
Production CCF registration is tested for all seven registration failure
positions and for correct A72 isolation. Existing A53 tests pass;
the affected ARM64 objects compile. These are software tests, not physical
CCI qualification. The generic `mtk-cci-devfreq` driver currently reparents
CCI explicitly through an intermediate clock; it cannot be enabled unchanged
against this provider, which owns the complete rate transaction and rejects
external CCI parent changes. A voltage-aware consumer and the shared-rail
controller remain required, followed by device qualification.

The vendor CCI policy considers all available CPU clusters, including A72:
`_calc_new_cci_opp_idx()` first requests half the fastest CPU frequency,
looks up its CCI voltage, then takes the maximum of that voltage and both
A53 voltage votes. It finally selects the highest CCI point supported by
that shared voltage. With A72 still fixed at 750 MHz, the frequency-derived
CCI floor rounds up to 416 MHz. A device test of 169/234/325 MHz therefore
needs the A72 cluster offline and appropriately reduced A53 rates; testing
every CCI point while all CPUs stay at their maximum clocks would not follow
the vendor policy. A read-only check still finds healthy M69 boot
`ed1feaea-5f15-4859-aa30-5e9216db5723`, online CPUs `0,8-9`, and CCI/its PLL
both at 629999328 Hz. Follow-up Linux test commit `676c564d691c4` exercises
the first transition from that non-table firmware rate to 611 MHz.
The normal package selects that follow-up revision. Its full kernel build
and complete check phase pass, producing
`/nix/store/b1mckzz0fp9hv8n79iq21p6c1rfm2ykc-linux-gemini-7.1.3`.
Build/check logs, source manifest and the retained output are recorded in
`handoff/cci-clock-20261008/`. No device trial has started for this driver.

## Native A53 SRAM regulator

Linux binding `7d785d4872e76` and driver `2dd12edcf765b` add the eight
INFRACFG CPU SRAM LDOs as `vsram-a53-cci`. The provider supports 1.0–1.2 V
in 25 mV steps and recognizes code zero as the alternate 1.05 V encoding.
It requires all eight lanes enabled and at the same decoded voltage,
preserves reserved bits, leaves the enable register untouched, and verifies
each bank write plus a stable final snapshot. Per-bank delays use the vendor
settling formulas. Any uncertain write or semaphore release returns EUCLEAN
through the actual handoff gate, which fences later CSPM/I2C access.

The hardware semaphore implementation is shared with the CPU clock driver.
The regulator prepares its interface clock before entering the CSPM gate
and releases it afterward, avoiding a CCF/CSPM lock inversion. Board
constraints cover the supported range and keep the rail always on; probe
adopts an in-range firmware setting without changing it. BUCKA remains
fixed at 1.00 V. A coupled CPU/SRAM voltage policy is not yet installed.

The production regulator callbacks, semaphore helpers and handoff access
gate pass 81 voltage pairs and 1,206 injected I/O failures under UBSan,
plus lane/enable/alias checks, unstable reads, clock and semaphore failures,
and rejection after global fencing. Existing CPU clock tests pass. The
binding and packaged board DTB validate; packaged and local DTBs match.
Normal and diagnostic bundles build with the new regulator enabled, and
the complete normal kernel check phase passes. The shared kernel is
`/nix/store/9cn7dsjlp2fbb2647xw29id6a5w831yf-linux-gemini-7.1.3`.
Builds, checks and the bounded adoption/concurrent-read probe are retained
in `handoff/cpu-sram-20261008/`. Physical SRAM transitions remain untested.

The adoption trial `handoff/cpu-sram-adoption-trial-01/` subsequently passes
on candidate boot `7ed34ff9-9e45-4e1c-ac7d-f3af57bab599`. The provider binds
after the handoff supplier becomes ready. Its 1,003 concurrent voltage reads
span 23.816 seconds and all report the inherited 1.10 V setting while all
98 ordered A53 frequency pairs pass at fixed 1.00 V CPU voltage. The probe
finishes in 24.223 seconds, restores both schedutil governors and removes
its core-parking hold. Its service is inactive with PID zero; the kernel
error scan is empty. CCI and A72 stay at their inherited frequencies. This
proves configured-voltage readback and bounded concurrent access, not an
analog voltage measurement, SRAM transitions or coupled voltage scaling.

The diagnostic observation completes in 94.876 seconds and fails the
expected normal cgroup2 memory-controller gate. No default is promoted.
Automatic recovery returns healthy M69 boot
`bd5a9a61-8f84-4c53-a7c8-924961042005`. The durable worker is terminal and
the final audit confirms no writer, both locks acquired, all 35 source
hashes unchanged and all 26 ordinary outputs retained. Full results are in
`handoff/cpu-sram-20261008/completion.json`. Next voltage work needs the
CPU/SRAM coupler, explicit DA9214 settling and a CCI voltage vote that
accounts for the still-fixed A72 clock before relaxing BUCKA constraints.

## DA9214 settling before coupled voltage scaling (2026-10-08)

Kernel commit `6c4fbe6238a22fb177e72a227230979bdcb9c56a` adds the
vendor DA9214 delay inside the voltage transaction: one microsecond per
10 mV selector step, with a 25 microsecond minimum. Both the forward write
and rollback settle before readback, including writes that return an error
but may have taken effect. The chip mutex covers the complete transaction.
No-op requests and enable-register writes add no delay. DA9213 and DA9215
keep their existing behavior because this timing comes from the MT6797
DA9214 vendor policy.

The production callbacks pass 98,304 selector pairs across both bucks and
all three variants under UBSan. Fault cases cover failed reads, effective
and ineffective failed writes, ignored writes, and uncertain rollback.
Both the driver and existing transaction KUnit object compile for ARM64;
checkpatch reports no errors or warnings. The host test is now part of the
normal Nix kernel checks. The full normal kernel check phase and deployment
bundle build pass. The resulting kernel is
`/nix/store/xjgk8z2z5xxjrkp9994snwxfqh2gjw6k-linux-gemini-7.1.3`, and the
bundle is `/nix/store/2cm02k7qnxyy945406b1r3b48wis6m2y-gemini-mainline-nixos-bundle`.
Build logs and GC roots are retained under
`handoff/da9214-settling-20261008/`; a new device voltage-transition trial has
not yet run.

Current A53 OPP entries already use voltage triplets with a 1.2 V maximum,
so they can tolerate another shared-rail consumer requesting a higher
voltage. They do not need conversion from scalar values. The remaining
work is the CPU/SRAM coupler and CCI consumer policy, including the fixed
A72 contribution, before relaxing BUCKA's fixed 1.00 V constraint. The
existing MediaTek GPU coupler is not applicable: it only registers on other
SoCs and programs SRAM before the other rail in both directions.

## Discrete CPU/SRAM transition planner (2026-10-08)

Kernel commit `9e44cb208280aa0a3e1313748f157e10463e964b` adds
`mt6797-cpu-rail-plan.h`, the sequencing arithmetic for the forthcoming
CPU/SRAM coupler. It admits exact DA9214 selectors from 770 mV to 1.2 V
in 10 mV steps and SRAM selectors from 1.0 V to 1.2 V in 25 mV steps.
The target uses the nominal 100 mV offset, clamped to SRAM's range and
rounded upward to an actual SRAM selector. Intermediate steps retain the
vendor's 275 mV margin and nominal offset where the limits allow it.
Each step changes one rail; higher CPU voltage first needs sufficient
SRAM voltage, and lower SRAM voltage first needs sufficiently low CPU
voltage. Valid inherited pairs need not start at the nominal offset.

The host test executes the production header over all 11,528 admitted
starting-pair/CPU-target combinations: 26,656 writes, at most six steps.
It independently checks exact selectors, strict progress, no reversal,
the final nominal target, and the electrical envelope along each write.
Golden full-range cases check the 1.025 V initial SRAM step when raising
770 mV CPU voltage and the 930 mV initial CPU step when lowering from
1.2 V. Invalid input tests verify that the proposed output remains intact.
UBSan and checkpatch pass. This test is part of the normal Nix check phase.
The full normal kernel checks and deployment build pass. The kernel is
`/nix/store/6k5xijrxa60f48bkd75v69cf8xpwyjmc-linux-gemini-7.1.3`; the bundle is
`/nix/store/65ynmd90i2vx361ypqjn61pa7r0sqxqf-gemini-mainline-nixos-bundle`.
Logs, result metadata and GC roots are retained in
`handoff/cpu-rail-plan-20261008/`.

This is the pure planner, not an installed regulator coupler. The next
adapter must aggregate consumer votes, validate machine constraints and
both final rails before writing, hold the regulator framework's coupled
consumer locks, and execute each exact selector through the existing
settling/readback providers. It must stop and fence subsequent clock
access on uncertain writes or reads after a write; it must not blindly
restore CPU voltage after a partial SRAM update. CSPM must not be held
across the DA9214 I2C call, which acquires that gate itself. OF matching
must identify CPU SRAM and DA9214 BUCKA, rather than matching arbitrary
regulator names. CCI voting and the fixed A72 contribution remain required
before BUCKA constraints can be relaxed. No device voltages change from
adding this planner.

## CPU/SRAM regulator coupler (2026-10-08)

Kernel commit `9421a191779447b89c1628949a3a126e39511cd4` installs the
MT6797 CPU/SRAM regulator-framework adapter. It matches CPU SRAM and
DA9214 BUCKA by OF identity and reciprocal coupling links, merges all
consumer requests through the regulator core, and checks every planned
intermediate step against machine constraints before writing. Each write
uses the existing settling/readback providers and is followed by a read
of both rails. No consumer vote retains the inherited CPU voltage; fixed
voltage adoption needs no write permission. SRAM minimum requests can
raise the selected CPU target within the aggregated CPU maximum so the
nominal SRAM relationship is satisfied.

After any write error or failed post-write verification, the coupler
stops without a blind rollback, marks itself faulted, and permanently
fences CSPM clock/I2C access. The new owner rail-fault entry works even
while access is temporarily blocked, preventing resume from reopening a
faulted owner. The existing owner fault-state and atomic permission
implementations are exercised in the host test, including rejection of
subsequent transitions and attempted permission reopening. Suspend-state
voltage programming is explicitly unsupported by this coupler.

Tests execute the production adapter, planner, regulator consumer/machine
constraint helpers, and owner fault helpers: all 11,528 admitted paths and
156,336 injected read/write failures pass under UBSan. Additional cases
cover three concurrent A53/CCI requests, incompatible votes, SRAM votes,
fixed-rail adoption, unavailable write permission, reciprocal OF matching,
probe deferral, detach, and PM-blocked fault fencing. The existing SRAM
provider suite still passes 81 pairs and 1,206 injected I/O failures. ARM64
compilation caught and fixed a collision with the kernel's `current` macro
in the previously pure planner; the host tests now also define that macro.
Both ARM64 objects compile and checkpatch passes. The coupled DTB validates
against the CPU SRAM, DA921x and base regulator schemas.

The normal Gemini configuration builds the coupler, and the board DT links
both regulators with the 300 mV maximum spread. BUCKA remains fixed at
1.00 V: CCI voting, the fixed A72 contribution and physical voltage scaling
are still unfinished. The normal and diagnostic bundles build successfully with the full kernel
check suite passing. The coupler is enabled in the packaged kernel config,
and the packaged DTB is byte-identical to the validated local DTB. The
shared kernel is `/nix/store/hv72jnrj9bw51if9b67gd07xq66ik27k-linux-gemini-7.1.3`.
The diagnostic candidate is
`/nix/store/lr5bp3xaimyc0i99zc9ry9vddpl9vmhg-gemini-mainline-nixos-bundle`.
The subsequent hardware adoption trial is recorded below. Build logs,
result metadata and GC roots are retained in `handoff/cpu-coupler-20261008/`.

## Coupled regulator adoption trial (2026-10-08)

`handoff/cpu-coupler-adoption-trial-01/` passes on candidate boot
`b4766304-89f6-4573-9ea6-e3b89eadbc13`. CPU SRAM binds after the handoff
supplier becomes ready, and CPUFreq then binds successfully. The live
regulator OF nodes expose the reciprocal BUCKA/CPU-SRAM coupling links
and the 300 mV maximum spread. All 98 ordered A53 frequency pairs pass at
fixed 1.00 V CPU voltage, with 1,017 concurrent SRAM reads reporting the
inherited 1.10 V across 23.824 seconds. The probe finishes in 24.283 seconds;
sampled temperatures span 36.6–41.0 C. Both schedutil governors are restored,
the probe's core-parking hold is removed, its service is inactive with
PID zero, and the kernel error scan is empty. CCI remains 629999328 Hz and
A72 remains 750 MHz. This proves coupled configuration adoption and the
fixed-voltage frequency regression, not physical rail transitions or
runtime fault injection.

Observation completes in 91.516 seconds. The diagnostic profile fails the
expected normal cgroup2 memory-controller qualification gate and is not
promoted. The supervisor restores healthy M69 boot
`446184d2-fe63-4ff2-be86-1da4f5d17ddf`. Its worker is inactive/dead with PID
zero and exit status zero; the CLI returns one for the expected profile
qualification failure. The final audit confirms no writer, both locks
acquired, all 35 source hashes unchanged, and all 26 ordinary outputs
retained. Build, probe and recovery metadata are consolidated in
`handoff/cpu-coupler-20261008/completion.json`. Next work is CCI voltage
voting, including the fixed A72 contribution, before relaxing BUCKA's
fixed voltage and testing physical rail transitions.

## CCI policy and ordered vote core (2026-10-08)

Kernel commit `545ebf4313147e21cf4f97348ee16b7bcb158db9` adds the
CCI policy/transaction core in `mt6797-cci-policy.h`. Its 16 frequency and
voltage points come from the vendor CPU_LEVEL_1/SB table. The policy takes
half the fastest available LL/L/A72 frequency, saturates at the highest
CCI point, and then selects the highest CCI point supported by the maximum
of that minimum CCI voltage and the two A53 voltage requirements. A72's
separate rail voltage is excluded. At the lowest A53 rates, an available
750 MHz A72 therefore requires 416 MHz CCI at 900 mV; without A72, the
lowest case can use 169 MHz at 770 mV.

The transaction core raises its own voltage vote and checks the actual
shared voltage before raising CCI frequency. It lowers frequency and
verifies it before reducing the voltage vote. Other consumers may retain
a higher actual voltage. Write errors, mismatched readbacks and terminal
read errors fence the transaction without a blind rollback. Firmware
adoption holds the measured voltage, moves to a supported rate no higher
than the inherited clock and supported by that voltage, then releases
any excess vote. The inherited 629999328 Hz at 1.00 V maps to 611 MHz.

The production header passes 5,376 CPU-policy combinations from the actual
board A53 OPPs, all 512 ordered CCI paths with sole/shared votes, 6,388
injected failures, and 704 inherited frequency/voltage combinations under
UBSan. Golden cases cover the A72 floor, voltage-dominated selection,
maximum-rate saturation and the off-table boot rate. ARM64 header
compilation and checkpatch pass. The test is included in normal kernel
checks. The complete normal kernel checks and deployment build pass.
The kernel is `/nix/store/kb1vz3xgzns7jgwflggdxx2j2hnr2cvf-linux-gemini-7.1.3`, and
the bundle is `/nix/store/fzyaciwbainfl3z4gwm9ff2dsml3rvw9-gemini-mainline-nixos-bundle`.
Logs, result metadata and GC roots are retained in
`handoff/cci-policy-20261008/`.

This core is not yet connected to a runtime CCI consumer. The generic
MediaTek CCI driver reparents the raw PLL and cannot directly drive the
native compound clock provider. The generic CPUFreq passive governor also
currently requires a CPUFreq policy for every possible CPU, including the
still-unmanaged A72s. The vendor changes CPU frequency before CCI while
holding sufficient voltage, so post-CPU-change CCI updates can retain
that ordering; integration must handle unmanaged CPUs, hotplug, consumer
lifetime and failure propagation. BUCKA remains fixed at 1.00 V and no
new hardware clock or voltage transition has run for this core.

## Native CCI runtime consumer (2026-10-08)

Kernel commit `ecf9cc95a71a22dc5dadd189f01e1e36b3677848` adds the built-in
MT6797 devfreq consumer and immutable CCI governor. The SoC node names the
native CCI and three CPU cluster clocks plus the DVFSP handoff supplier;
Gemini supplies the shared BUCKA regulator and all 16 SB CCI OPPs. Probe
checks those OPPs against the policy table, holds a regulator vote, adopts
the inherited clock through the tested sequence, and retains an enabled
regulator reference for the running CCI. It drives only the compound
clock provider; no raw PLL reparenting is used.

CPUFreq post-change and CPU hotplug callbacks queue work. The worker
samples active cluster clocks and A53 OPP voltages, includes A72 frequency
without requiring an A72 CPUFreq policy, then applies the tested vote/clock
sequence. Clock identity maps possible CPUs to clusters. The CPU hotplug
read lock covers target sampling and execution; hotplug callbacks never
wait on devfreq while holding the hotplug write lock. OPP registration
and stale target samples retry while retaining the existing CCI vote.
Frequency limits and regulator support are checked before hardware writes.
A managed CPU policy removal fences clock/rail access because unmanaged
CPU clocks could outlive their removed voltage votes.

Cleanup stops new notifications, unregisters both CPUFreq notifiers and
hotplug callbacks, drains queued work, and fences before releasing the
live CCI supply reference. Nested global/device suspend events retain the
vote and suppress work until the final resume event. These lifecycle rules
are host-tested, not proof of physical suspend or resume support.

The production runtime callbacks and probe unwind pass UBSan tests covering
native clock/vote calls, A72 inclusion and removal, hotplug, late OPP
registration, stale targets, unsupported frequency/voltage limits, nested
PM, policy removal, eight post-adoption failure positions and five
preflight failures. The policy-core suite still passes 5,376 combinations,
512 ordered paths, 6,388 injected failures and 704 boot states. The board
CCI table matches the policy table exactly. ARM64 compilation, checkpatch,
DT binding validation and the built board DTB validation pass. Normal and
diagnostic bundle builds pass with the full kernel check suite. The
packaged kernel enables the runtime driver, and its DTB matches the
validated local DTB. The shared kernel is
`/nix/store/mh5z6a6qfsj2nh7pnq2jrh0hpmgfx5p6-linux-gemini-7.1.3`, and the diagnostic
candidate is `/nix/store/x025hcn6q01g5yqgmnx4lhgjiwkkn3n0-gemini-mainline-nixos-bundle`.
Build logs, result metadata and GC roots are retained in
`handoff/cci-runtime-20261008/`.

The driver and DT node are enabled in the candidate configuration. The
October 8 runtime trial `handoff/cci-runtime-trial-01` booted candidate
`2b25c776-156c-4845-ac08-7fff5f5f7c48` and adopted CCI at 611 MHz. It passed
all 98 A53 ordered frequency pairs and all 16 ordered CCI pairs among
416, 481, 533 and 611 MHz, checking devfreq, branch and raw PLL readings.
BUCKA remained fixed at 1.00 V; all 1,633 concurrent SRAM readings were
1.10 V over 43.40 seconds. The probe completed in 43.85 seconds with sample
temperatures 37.5–43.0 C, restored both schedutil governors, removed its
parking hold and exited. The follow-up found a running system, an inactive
probe service and no matching kernel errors. Startup did emit repeated
OPP-table-not-found messages before cpufreq registered; the retry needs
quiet handling.

The 95.49-second observation completed. This diagnostic cgroup1 profile
failed the normal cgroup2 memory-controller gate as expected; it is not a
qualified normal generation and was not promoted. Automatic recovery
returned healthy M69 `fbc7adf3-97b1-4a4c-958e-1f1573aaa43d`. The worker is
terminal with no writer, both locks acquired, all 35 source hashes matching
and 26 ordinary outputs retained in the final audit.

This proves physical CCI transitions over the four tested rates. A72 was
online at its fixed 750 MHz, so lower CCI rates and deliberate A72 hotplug
remain untested. Before relaxing BUCKA's constraints, startup must guarantee
a CCI voltage floor until its consumer has established ownership;
dependency timing observed in one boot is insufficient. Physical coupled
rail transitions and normal cgroup2 qualification also remain outstanding.

## CCI startup ownership and coupled voltage enablement, October 8

Linux `e4ab5bf89d728` adds a one-way CCI ownership contract to the existing
DVFSP handoff owner. The coupler preserves measured Vproc until ownership
is published, so an earlier CPU regulator request cannot lower the rail
under the inherited CCI clock. Publication follows verified CCI adoption,
an enabled voltage vote, and registered lifetime cleanup. It serializes
with the CSPM admission/fault gate and rejects duplicate or blocked claims.
Consumer cleanup permanently fences the owner before releasing its vote;
there is no unfenced ownership release. The coupler rejects a blocked or
faulted owner before reading or changing rails. The public status accessor
avoids acquiring the owner mutex under regulator locks.

The board now permits the supported 0.77–1.20 V BUCKA range with reciprocal
CPU/SRAM coupling. Existing A53 frequency limits remain. Normal regulator
constraint application preserves the measured boot voltage when it is in
this range; subsequent requests pass through the coupler. CCI startup also
checks OPP availability before frequency lookups, avoiding the repeated
late-table messages found in the previous hardware trial.

Host tests execute the production ownership callbacks and coupler through
11,528 inherited-pair/target combinations before and after ownership,
including a consumer vote that must survive lower CPU requests. Duplicate
claims, conflicting maxima, blocked/faulted ownership and permanent fencing
are covered. The original 11,528 coupled paths and 156,336 injected failures
still pass. Runtime tests check ownership ordering, nine post-adoption
failure positions, five preflight failures, and voltage-enabled high/low
votes in addition to fixed-rail rejection. The policy regression passes;
ARM64 objects, board DTB, CCI schema validation and checkpatch pass. Normal and
diagnostic bundle builds pass with the full kernel check suite; the packaged
DTB matches the validated local DTB. The shared kernel is
`/nix/store/1jbvv8bahp2xxsg6ksvdmi5qjr7rgbx9-linux-gemini-7.1.3`, and the diagnostic
bundle is `/nix/store/2dll060k52khn8sv838jc6cq6zzyx8gh-gemini-mainline-nixos-bundle`.
Builds, probe and completion metadata are in `handoff/cci-ownership-20261008/`.

The physical trial `handoff/coupled-voltage-trial-01` booted
`0c171d7e-ba1d-445e-8bbe-0dee885c543d` and passed all 98 A53 ordered frequency
pairs and all 16 ordered transitions among CPU/SRAM pairs 0.90/1.00,
0.94/1.05, 0.97/1.075 and 1.00/1.10 V. The probe checked settled regulator
readback, CCI/CPU branch and raw PLL clocks, and a pinned computation digest.
CCI covered 416, 481, 533 and 611 MHz. A concurrent reader took 1,586 SRAM
samples over 41.50 seconds; these include all four expected SRAM levels.
The probe completed in 42.03 seconds at sample temperatures 35.9–38.8 C.
Both schedutil governors were restored, the parking hold was removed, the
probe service exited and the system remained running. Kernel error scanning
was empty, including the previously noisy missing-OPP lookup pattern.

The 95.50-second observation completed, followed by the expected normal
cgroup2 gate failure in this diagnostic cgroup1 profile. Automatic recovery
returned healthy M69 `95e8a653-14da-4624-8edb-52cc11443cfe`. The worker is
terminal; the final audit acquired both locks, found no writer, verified
all 35 executed source hashes and retained 26 ordinary outputs. No normal
generation was qualified or promoted.

This proves real coordinated CPU/SRAM voltage changes over the four tested
levels. A72 stayed online at 750 MHz, keeping the minimum CPU rail at
0.90 V. A72-offline low-voltage operation, higher A53/CCI operating points,
A72 frequency control, sustained load/thermal validation and full PM remain
unfinished. The concurrent reads are not analog transient measurements;
provider settling and the intermediate-step envelope remain backed by the
implementation and host fault tests rather than oscilloscope evidence.

## A72 shutdown lifecycle prerequisite, October 8

The following prerequisite entries describe successive implementation stages.
Native callbacks are now connected; the first hardware trial and its failure
are recorded below under “Native A72 lifecycle trial.”

The planned A72-offline low-voltage trial cannot run on the current CPU
operations. `arch/arm64/kernel/mt6797_psci.c` deliberately returns `-EPERM`
for CPU8/9 disable and provides neither `cpu_die` nor `cpu_kill`. The native
power owner and SRAM preparation also accept only the first cold CPU8
start. The existing hotplug attribute test explicitly verifies that refusal.
Generic ARM64 hotplug matching upstream does not mean this platform's A72
shutdown lifecycle is implemented. No unplug was attempted on the device.
This also blocks the nonboot-CPU teardown needed by full system sleep.

The frozen vendor kernel at `51e705e4e7b1` provides the required order in
`arch/arm64/kernel/psci.c`: last-core MP2 sync DCM off, PSCI AFFINITY_INFO
completion, then BUCKB disable. `BigiDVFSSRAMLDODisable()` in
`drivers/misc/mediatek/base/power/mt6797/mt_idvfs.c` is a no-op; its name is
not evidence for an additional SRAM register write. The retained ATF
source `artifacts/atf-1.0-x20/services/std_svc/psci/psci_main.c` confirms
that AFFINITY_INFO actively invokes `power_off_big()`. It must only be
called by a surviving CPU after the target has left Linux, never as a live
CPU health query. `plat/mt6797/power.c` performs core/cluster power-off,
coherency teardown, PLL deselection/disable and external isolation.

Linux `8f945dc45d722` adds the shutdown transaction core to the existing A72
power implementation. CPU9 removal requires CPU8 to remain online and
powered, with the rail retained. CPU8 removal requires both A72s logically
offline. After firmware completion, both SPM status words must confirm the
expected core/cluster power state. Last-core removal additionally requires
external isolation, reset asserted and clock-disable set before BUCKB can
be disabled. Two further samples verify the rail is off. Unexpected state
or I/O failure permanently fences the transaction, with no rollback or
restart of a CPU that already left Linux. An enabled iDVFS controller is
rejected. Other clusters' status bits are ignored.

The host test runs the production core, checking the two exact operation
sequences, 24 failure cases over 12 I/O positions, 62 corrupt-readback cases,
live-target refusal, unrelated status bits and permanent fencing. The
existing cold-start suite passes all 14 cases and 721 assertions. ARM64
core/adapter compilation and checkpatch pass. The shutdown test is included
in the normal kernel recipe. Normal and diagnostic bundles pass with the
full kernel check suite and share kernel
`/nix/store/pdlsigq9s5mm8s2k9n9w08cfx4mg2cpn-linux-gemini-7.1.3`. The DTB is
byte-identical to the voltage-tested candidate. Build evidence, completion
metadata and GC roots are retained in `handoff/a72-lifecycle-20261008/`.
No new device boot occurred; healthy M69 remains
`95e8a653-14da-4624-8edb-52cc11443cfe`.

This is a tested core, not enabled A72 unplug. Remaining work is native
CPU-hotplug admission/cancellation and firmware-kill callbacks, serialized
MP2 sync-DCM control through the clock owner, and a restart contract covering
retained PLL/SRAM state. The cold clock validator currently requires both
PLL words to be zero, while firmware shutdown only deselects and disables
the PLL. SRAM's first-start attempt latch must not simply be cleared; a
verified shutdown receipt must authorize each subsequent start. A refused
unplug must also be able to unwind CPU-hotplug callbacks without being
misclassified as a new cold start. These pieces must be integrated before
A72-offline voltage or full shutdown/restart hardware qualification.

Linux `a89f2e0eb96f3` adds the clock portion of that restart contract:
`mt6797_cpuclk_validate_stopped_mp2()` compares a saved running observation
against the stopped state. The running PLL must be enabled, selected and
decodable. The stopped MP2 must select 26 MHz, retain its divider and both
PLL words exactly except for the cleared PLL-enable bit. This matches the
retained ATF `power_off_cl3()` sequence; it does not assume a new cold tuple
or a hard-coded retained rate. Other clusters' fields may change. The cold
validator remains unchanged. This helper alone neither proves cluster power
is off nor authorizes CPU_ON: native integration must bind the saved snapshot
to a successful shutdown and validate SRAM state separately.

The production clock-core host suite passes 15 cases and 58,357 assertions,
including 128 single-bit stopped-state mutations and invalid running
observations. Both clock core and KUnit objects compile for ARM64;
checkpatch reports no warnings or errors. This commit is not yet selected
by the bundle recipe and has not been booted. MP2 DCM control, native hotplug
callbacks and SRAM restart handling remain outstanding.


Linux `0f4521b48adff` adds the native clock-provider MP2 sync-DCM API. It
validates the A72 power consumer's exact MP2 handle, holds the supplier
against removal, enables the interface clock before the observer/CSPM
locks, and uses the raw hardware semaphore inside the transaction. The
existing cold-boot API now uses the same lock ordering. DCM changes require
an enabled, selected MP2 PLL and two equal initial DCM reads. The secure
MCUSYS-write service updates only bits 6:0 of `0x10222274`, preserving all
other bits; enable selects divide-by-four, with toggle high then low as in
vendor `dcm_mcusys_mp2_sync_dcm()`. Each write is read back. Any failure after
a dispatched write, or hardware-semaphore release failure, permanently
fences both clock observer and shared handoff. Full-width SMC errors are
rejected. No DCM call has yet been connected to the A72 power owner.

The production API/transaction host test covers lookup failures, lock order,
both toggle sequences, 36 injected I/O failures, eight readback corruptions,
high-word SMC errors, preserved upper bits and no I/O after fencing. The
clock-core suite now passes 15 cases and 58,361 assertions. All clock host
suites, ARM64 provider/core/KUnit compilation and checkpatch pass. Normal
and diagnostic bundles both complete successfully with the full kernel
checks and share kernel
`/nix/store/zc563d6av8wgapxl77b53vwhiydc8gc2-linux-gemini-7.1.3`; the DTB is
unchanged. Recipes and lockfiles now select this commit. Evidence and GC
roots are in `handoff/a72-mp2-clock-20261008/`. No hardware trial or promotion
occurred; M69 boot `95e8a653-14da-4624-8edb-52cc11443cfe` was rechecked healthy.
The next integration must connect the native CPU-hotplug callbacks, bind
saved clock state to completed shutdown, and authorize SRAM restart without
clearing permanent failure state.


Linux `eecfc28abc66b` adds the SRAM provider restart path. The exclusive A72
power owner may call `mt6797_sram_record_cpu8_off()` after verifying BUCKB
shutdown. The provider requires both CPUs logically offline, both SPM status
words clear for MP2, external isolation set, reset asserted and clock-disable
set, sampling these conditions twice. It does not query AFFINITY_INFO.
Two full SRAM samples must match and must either retain the last committed
control/calibration words or both be zero. A successful record authorizes
one restart. Restart consumes authorization before reading hardware, checks
two fresh samples against the recorded state, then reruns the full vendor
SRAM service, calibration verification and settling sequence. Any uncertain
restart permanently faults the provider. The physical boot-attempt latch
remains set across all cycles and provider reprobe; ordinary voltage setters
remain excluded. Actual SRAM retention through physical shutdown has not
yet been measured.

The actual provider/core host test passes six restart cycles (retained and
zeroed samples), 13 invalid shutdowns, 12 shutdown I/O failures and 17 restart
failures, alongside existing ownership, first-start and ordinary-setter
checks. ARM64 provider/KUnit/A72-owner objects compile; checkpatch passes.
Normal and diagnostic bundles pass the full kernel checks and share kernel
`/nix/store/6nqfv4zanhql9ybndn9gza7hgw648bcz-linux-gemini-7.1.3`. The DTB is
unchanged. Evidence and GC roots are in `handoff/a72-sram-restart-20261008/`.
No hardware trial or promotion occurred, and M69 boot
`95e8a653-14da-4624-8edb-52cc11443cfe` was rechecked healthy.

The power owner still needs the native hotplug admission/cancellation and
firmware-kill callbacks, a saved running MP2 clock observation checked via
the provider at restart, and warm power-transaction admission tied to its
completed shutdown. Its current transaction admission still requires cold
SRAM words. The new SRAM shutdown-record API must be called only after the
last-core shutdown core verifies BUCKB off. These connections remain necessary
before enabling unplug or conducting the physical off/on trial.


Linux `071c10bcb0025` adds warm transaction admission and the public clock
restart check. A successful MP2 DCM disable saves the running clock snapshot
inside the clock provider; duplicate disable is refused without replacing it.
The restart check compares fresh stopped clocks against that observation.
Successful DCM enable invalidates the saved observation. These clock checks
alone do not prove power-off: the native power owner must also retain the
completed last-core shutdown record.

`mt6797_a72_transaction_restart()` requires that completed, nonfaulted
cluster-off record plus a saved post-shutdown resource snapshot. A fresh
snapshot must retain the recorded MP2 power control, disabled BUCKB vote,
voltage and full SRAM state. Both snapshots require isolation, no online A72,
no reset/transaction in progress, and valid voltage limits. SRAM must be the
complete cold tuple or the initialized 1.10 V tuple. The cold entry point
keeps its original strict admission. Both entry points use the same startup
sequence and rollback/fault boundaries. The native owner must capture these
records after firmware/rail shutdown and recheck physical shutdown state
before dispatching restart; those lifecycle calls are not yet connected.

The power-core suite passes 15 cases and 2,088 assertions, including 30
invalid restart admissions, both warm SRAM shapes and 108 injected step
failures across cold/reset-SRAM/retained-SRAM starts. Clock API and transition
regressions, ARM64 clock/power-core/KUnit compilation and checkpatch pass.
Evidence is in `handoff/a72-warm-admission-20261008/`. No bundle rebuild or
hardware trial was performed for this commit; packaging remains on the
previous fully built SRAM-provider commit `eecfc28abc66b`. The next work is
the native hotplug admission/cancellation, CPU_OFF/firmware-kill callbacks
and power-owner lifecycle calls, followed by the complete off/on trial.

## Native A72 lifecycle trial, October 8

Linux `8061e213868e5` connects CPU8/9 admission, CPU_OFF and surviving-CPU
firmware completion to the native power, clock and SRAM owners. CPU9 must
leave before CPU8; cancellation clears the pending shutdown without replaying
startup. Successful last-core shutdown records the stopped resources, and
restart checks fresh clock, power and SRAM state before consuming its
authorization. Faults permanently prevent further lifecycle operations.
Automatic parking still retains both A72s pending hardware qualification.

Normal and diagnostic bundles build with the same kernel and unchanged DTB.
The production callback host test covers cold/warm cycles, CPU9 re-add,
cancellation and errors before/after effects at 41 CPU8-shutdown, 19
CPU9-shutdown and 34 warm-start I/O boundaries. These tests used matching
primary/secondary SPM acknowledgment words, an assumption now contradicted
by hardware observation.

Diagnostic boot `52dc0135-4192-46a6-ae78-37fb71ebda46` successfully starts
both A72s and enables MP2 sync DCM. With A53 rates and shared rails fixed at
their previously tested maxima, wrong-order CPU8 removal correctly returns
EBUSY. CPU9 removal returns success in 41.2 ms and firmware reports it killed,
but the native post-shutdown check faults with EUCLEAN. CPU9 re-add and probe
cleanup are consequently refused. No full cluster shutdown or restart was
attempted. This is a failed qualification, not successful A72 hotplug.

The boot worker restores healthy M69 boot
`51f5beca-7346-466c-a12e-fb84382fe74d`; terminal-worker and source/output audits
pass. Evidence is in `handoff/a72-native-trial-01/` and
`handoff/a72-native-lifecycle-20261008/completion.json`.

Linux `24820f78a5629` adds failure-only logging of the existing shutdown
samples without changing admission or hardware operations. Normal and
diagnostic builds pass; build evidence is in
`handoff/a72-shutdown-diagnostics-20261008/`. A read-only M69 observation
finds primary CPU power status `0x003b80c8` and secondary `0x003980ff` while
both A72s are online: the secondary cluster bit is clear even though the
cluster is running. ATF `power_off_big()` and `power_off_cl3()` poll the
primary status word, not that secondary word. The next diagnostic trial
captures the precise failed post-shutdown state before changing verification.

Diagnostic boot `11eaa14c-68ce-444e-a168-c6dda88ed73f` confirms the mismatch.
CPU9 shutdown changes primary status from `0x003fc0c8` to `0x003fc088`,
clearing precisely CPU9's bit 6. Secondary status remains `0x003dc0ff`.
Primary masked by `0x200c0` equals the required CPU8-plus-cluster `0x20080`;
secondary does not. MP2 power control is `0x00010127`, isolation and iDVFS
control are zero, and BUCKB is enabled: every other CPU9-off check passes.
The unchanged verifier faults and refuses re-add as before. Evidence:
`handoff/a72-native-trial-02/kernel-after-probe.txt` and
`handoff/a72-primary-ack-20261008/diagnosis.json`.

Linux `def0029470b6c` corrects power-owner and SRAM restart checks to use
the primary MP2 acknowledgment bits polled by ATF. The owner retains the
secondary word for failure diagnostics. Repeated primary readings, peer
ordering, iDVFS exclusion, reset/clock/isolation checks, rail checks and
permanent fault protection remain enforced. Tests now keep the secondary
word independent of MP2 transitions and replay the exact hardware sample;
the regression fails against the old verifier. Both shutdown sequences,
24 I/O failures, 64 corrupt samples, native hotplug fault cases, SRAM restart
tests and all 15 power-core cases/2,088 assertions pass. ARM64 compilation
and checkpatch pass. Normal and diagnostic bundles pass all kernel checks
and share kernel `/nix/store/sp049jpi7ymbxjbkyrbgvgrm000y1w0z-linux-gemini-7.1.3`,
with unchanged DTB. Build logs and GC roots are retained in
`handoff/a72-primary-ack-20261008/`. Trial03 is running; physical restart
qualification remains pending. Trial02 completed M69 recovery as boot
`19fecbdd-1dbb-4899-9405-567ac0998e67`, with terminal worker, all 35 source
hashes matching and all 26 tracked outputs retained.

Trial03 boot `15a7d905-0591-4c8c-9170-dfa6ecc7065a` verifies the correction:
CPU9 powers off in 62.0 ms and restarts in 49.1 ms, with unchanged peer
clock/rails and no collected kernel errors. The probe then fails to locate
`taskset` in its service environment. Its cleanup restores both governors
and removes its hold/pause. A separate Python-affinity workload on the same
restarted CPU9 passes. Full-cluster shutdown was not reached. Evidence:
`handoff/a72-native-trial-03/{a72.json,cpu9-execution-check.json,analysis.json}`.
The replacement probe in `handoff/a72-affinity-probe-20261008/` sets and
checks affinity through Python directly. A bounded retry did not fit the
remaining observation window and was not launched; a fresh trial is required.

Trial04 boot `426a1970-e102-42da-879e-d289c9556c2c` passes CPU9 off/on and
the pinned workload, then powers off CPU9 and CPU8. CPU8 removal takes
54.8 ms. The stopped system has CPUs0–7 online, BUCKB disabled at a stored
1.00 V setting, and big SRAM reporting its reset selector's 1.05 V.
No native shutdown-verification error is logged. This reaches successful
last-core shutdown and the SRAM shutdown record, but not restart.

The next snapshot exposes a second incorrect assumption: MP2 PLL words are
both zero after rail removal, with mux `0x54` and divider `0x42108`. The
clock observer returns zero/error because its zero-PLL decoding exception
requires the original cold divider 0, whereas the retained MP2 divider is 8.
The restart validator separately refuses the reset PLL pair because it
requires retained programming. The probe therefore fails its expected
26 MHz path-rate check, and cleanup CPU8 restart returns EBUSY. Evidence:
`handoff/a72-native-trial-04/{a72.json,kernel-after-probe.txt,stopped-state.txt,stopped-rails.txt}`.

Linux `a2ad78e32f349` decodes an unselected, fully reset MP2 PLL with any
valid divider, without relaxing cold-start admission. Restart still needs
the saved running clock record, reference mux selection and exact retained
divider, and now permits either exact retained PLL programming or both
PLL words zero. Partial resets and changed mux/divider bits remain rejected.
The power owner still independently verifies the completed shutdown receipt,
logical CPU state, primary power acknowledgments, isolation and disabled
rail before invoking this clock check. Regression tests fail against the
previous decoder; 15 clock-core cases/58,539 assertions, native clock API
tests, ARM64 compilation and checkpatch pass. Both normal and diagnostic
bundles pass the full kernel checks and share kernel
`/nix/store/wr0kgandrdn32csj23qa3j21zcpyjmm6-linux-gemini-7.1.3`, with unchanged
DTB. Build logs and GC roots are in `handoff/a72-reset-clock-20261008/`;
physical restart qualification remains pending. Trial04 recovery returned
healthy M69 boot `3374baff-83db-4a92-858c-39d064f08c4e`. The worker is terminal
and final source/output audits pass.

Trial05 boot `3501052e-5501-4903-8fc9-d9bd9b30cfd8` verifies the clock fix:
after CPU9 and CPU8 shutdown, BUCKB is disabled and MP2 correctly reads
26 MHz, with no collected clock/kernel errors. CPU8 restart now returns
EUCLEAN during preparation, before another CPU_ON commit. Cleanup is also
refused. This is a further preparation failure, not a qualified restart.
The conditional low-voltage probe records `admitted=false` and does not run.
Evidence is in `handoff/a72-native-trial-05/` and
`handoff/a72-reset-clock-20261008/completion.json`.

Recovery returns healthy M69 boot `a4bf6f77-3ea3-410d-8f15-d8a1bd3f8132`;
the worker is terminal and final audits pass for 35 source hashes and 26
retained outputs. Linux `d8cc8df95225e` adds failure-only diagnostics of the
power transaction's applied step count and initial resources, plus the SRAM
restart phase, underlying error, recorded shutdown sample and observed
samples. It adds no hardware reads and changes no admission rule. Native
hotplug and SRAM host tests, ARM64 compilation and checkpatch pass. Normal
and diagnostic builds pass the complete kernel checks, sharing kernel
`/nix/store/lw7sjsd0khvmkcv71k6iay8kzxpq0fz9-linux-gemini-7.1.3` and unchanged
DTB. Build evidence and GC roots are in
`handoff/a72-restart-diagnostics-20261008/`; diagnostic hardware testing
remains pending.

Trial06 boot `2a7af4c7-fd4f-48c3-af4e-e7e03e14c4f0` locates the failure
at applied step 11, inside the SRAM restart precheck, before its initialization
SMC. The recorded powered-off sample is control/calibration `0/0`; after
the Linux buck/isolation sequence, the first powered sample is
`0x00400ff9/0`. The check incorrectly requires these different power states
to match. The first mismatch stops sampling, so this diagnostic does not
establish a stable pair of powered samples. M69 recovery returns boot
`74622d50-f765-4570-a9d7-1509713d0347`; terminal-worker and final source/output
audits pass. Evidence: `handoff/a72-native-trial-06/` and
`handoff/a72-restart-diagnostics-20261008/completion.json`.

Linux `ca4b6d9b98e2b` records two matching powered SRAM samples before the
first successful vendor initialization. That original baseline survives
every restart. Restart consumes its shutdown authorization, then requires
two matching samples equal either to the recorded shutdown state or to
that original powered baseline, before invoking the same initialization,
calibration verification and settling sequence. A changing pair, partial
match, unrelated value, I/O failure or failed initialization still faults
the provider permanently. There is no hard-coded acceptance of `0x00400ff9`.
The existing boot-attempt latch and exclusive native ownership remain intact.

Tests execute the real provider, covering six powered-baseline cycles with
reset/retained shutdown samples, 64 single-bit corruptions, two mixed
observations, nine initial I/O failures and two unstable initial samples,
alongside the previous shutdown/restart fault cases. All 14 SRAM KUnit
cases/238 assertions and native hotplug fault tests pass. ARM64 provider
and test compilation and checkpatch pass. Normal and diagnostic bundles
pass all kernel checks and share kernel
`/nix/store/j4dc3d1qrih52bdx2jr8x1zsg837paq5-linux-gemini-7.1.3`, with unchanged
DTB. Build evidence and GC roots are in
`handoff/a72-sram-powered-baseline-20261008/`. Hardware restart qualification
remains pending.

Trial07 (`92339179-b34f-432c-b75a-d384c8c9b429`) passes CPU9-only
shutdown/restart and three full A72 cluster shutdown/restart cycles in
4.09 seconds. Wrong-order CPU8 removal is refused, every restarted core
executes a checked workload, BUCKB is disabled and MP2 reads26MHz while
the cluster is off, and both cores return at750MHz. The captured original
powered SRAM baseline is`0x00400ff9/0`. No kernel errors occur; cleanup
restores schedutil and removes the test hold/pause.

The chained low-voltage probe passes all98 A53 ordered frequency pairs
with both A72s off, all49 ordered CCI pairs across169/234/325/416/481/533/
611MHz, CPU rails770–1000mV and1,420 concurrent SRAM reads in44.53 seconds.
Checked computations pass, kernel errors are absent, and cleanup restores
both A72s and schedutil. Evidence: `handoff/a72-native-trial-07/`, including
its`low-voltage/` child directory. These are bounded diagnostic hardware
results; normal cgroup2 qualification remains unresolved.

The maintained candidate now removes the CPU8/9 parking exclusion while
preserving CPU4→CPU8→CPU9 startup dependencies. Service-stop cleanup also
restores CPU8/9. Both packaging variants build with unchanged kernel/DTB.
The actual daemon passes three load/idle cycles on candidate boot
`6b06926a-a9ab-4367-beec-c95a952bf376` in22.52 seconds, with schedutil
active throughout. Twelve load processes bring all ten CPUs online;
checked workloads execute on CPU8 and CPU9 in every cycle. Removing load
lets the daemon shut down CPU9 then CPU8, disable BUCKB and return MP2 to
26MHz each time. Loaded snapshots peak at47.7°C; kernel error checks and
post-probe health checks pass. The host simulation also passes three
all-core idle/load cycles, dependency ordering and service-stop restoration.
A separate hardware service-stop check was withheld before execution because
only21 seconds remained in the observation window; that particular cleanup
path is host-tested only. Evidence: `handoff/a72-automatic-parking-trial-01/`
and `handoff/a72-automatic-parking-20261008/`. Sustained stress and normal
cgroup2 qualification are separate outstanding requirements. The trial returns
to healthy M69 boot`b4177a75-b3d4-413d-a2e7-0720bdc9577d`. The worker exits
successfully; the final audit verifies no writer, both locks, all35 executed
source hashes and26 retained outputs. The overall diagnostic profile still
fails its expected cgroup2 memory-controller requirement. No default is
promoted. Final evidence: `handoff/a72-automatic-parking-20261008/completion.json`.

Boot qualification must distinguish successful A72 startup from their later
parking state. The native first-start service already checks each online
transition, both kernel commit messages, the active MP2 clock, and all ten
online CPUs before writing its final`a72_startup=pass` record. The post-boot
EFI check now verifies that completed service and record for the current
boot, then records the present online bits separately. Host tests reject
failed/incomplete service evidence, missing startup records and changed boot
identity while accepting subsequent parking.

On candidate boot`8ab215b1-2e33-4b19-9168-2ff5b0574d84`, this read-only check
passes with both CPU8 and CPU9 currently offline. Evidence:
`handoff/a72-parking-soak-trial-01/native-startup-check.json`. The larger
six-cycle probe stops before load because its systemd PATH lacks`sh`; it
records no completed cycles. Kernel and follow-up health checks are clean.
A retry is withheld for insufficient observation time. The corrected probe
uses the verified absolute shell path and is prepared in
`handoff/a72-parking-soak-fixed-20261008/`. Six-cycle and hardware service-stop
restoration results remain pending; the previous three-cycle success stands.
The trial returns to healthy M69 boot`5479167c-24dc-4c34-873e-fc5493fc42e8`;
terminal-worker and final source/output audits pass. The same read-only
startup script is now shared by EFI and ordinary Nix-build qualification;
its contents exactly match the successful device check. Historical kernels
retain their online-CPU/runtime-identity requirements. All16 boot-runner and
five persistent-Nix tests pass. Final evidence:
`handoff/a72-parking-soak-20261008/completion.json`.

The corrected probe passes on candidate boot
`3c480f98-6dda-48d6-bb3a-b5178a284751`. Six schedutil load/idle cycles
bring all ten CPUs online, execute checked workloads on both A72s, then
power the A72 cluster off with BUCKB disabled and MP2 at26MHz. Stopping the
parking service restores all ten CPUs, enables BUCKB and returns MP2 to
750MHz; restarting the service resumes ordered A72 parking. The native
startup-record check also passes while both A72s are parked. Total probe
time is47.99 seconds. Daemon error records and kernel error checks are empty;
post-probe service and system health checks pass. Evidence:
`handoff/a72-parking-soak-trial-03/`. This extends the bounded lifecycle
coverage; it is not sustained thermal or endurance qualification.

Before this boot, trial02 stopped in preflight without a reboot or candidate
writer because a duplicated admission block referenced an undefined variable
in retained-output verification. Commit`3b8199f` removes the two unintended
copies. The regression test now exercises the complete mocked build/proof/
retention sequence and independent post-recovery retention, alongside the
startup rejection tests; all22 tests pass. Trial03's real preflight also
passes. Its corrected probe sets the system command path explicitly.
The completed trial returns to healthy M69 boot
`19538208-778e-4177-8248-9712eceea415`. The worker is terminal with exit0;
the final audit verifies no writer, both locks, all35 source hashes and26
retained outputs. The diagnostic still fails the normal cgroup2 requirement,
so no default is promoted. Final record:
`handoff/a72-parking-soak-fixed-20261008/completion.json`.

## Next A53 voltage step: 1.04 V, October 8

Linux`70823e0a3c4c7` enables the next SB-table operating point for each
A53 cluster: LL1.014GHz and L1.352GHz at1.04V. The vendor definitions are
`CPU_DVFS_FREQ8_LL_SB`, `CPU_DVFS_FREQ8_L_SB` and
`CPU_DVFS_VOLT8_VPROC1_SB` in`mt_cpufreq.c`; the inspected source revision
and content hash are retained in`handoff/a53-1040mv-20261008/source-evidence.json`.
The existing clock provider supports both rates. CCI follows the shared
budget to676MHz, and the CPU/SRAM coupler rounds the1.14V nominal SRAM
target to its1.15V selector. Thermal trips and cooling maps remain unchanged.

The production runtime-consumer host test now verifies each new CPU point
raises CCI to676MHz/1.04V and releases that vote on return to low rates.
It passes under UBSan. ARM64 DTB compilation passes; decoded-DTB comparison
shows exactly the two removed disabled properties and no other change.
Normal and diagnostic bundle builds pass their full kernel checks and use
the same kernel. Build identities and GC roots are retained in
`handoff/a53-1040mv-20261008/`. Bounded hardware results follow below. The prepared probe covers128 ordered A53
pairs and64 ordered CCI/voltage pairs with A72s off, concurrent SRAM reads,
checked computation, and governor/core restoration.

Trial01 passes on candidate boot`c2d5cccf-28f4-47af-bc24-6e7c5b5bcde5`:
all128 A53 ordered frequency pairs and all64 ordered CCI/voltage pairs,
including LL1.014GHz, L1.352GHz, CCI676MHz, CPU1.04V and SRAM1.15V.
All checked computations pass. The53.28-second probe retains1,709 concurrent
SRAM readings; sampled temperature peaks at37.5°C. No kernel errors occur.
Cleanup restores both A72s, schedutil, and automatic parking, and removes its
hold/pause files. Post-probe health checks pass. Evidence:
`handoff/a53-1040mv-trial-01/`. These results establish bounded transition
coverage at the new points; sustained stress and physical thermal response
remain outstanding. M69 returns healthy as
`f7968825-e132-48ab-a3e9-01419e0d209c`; the worker exits0 and the final audit
passes all35 source hashes,26 retained outputs, no-writer and lock checks.
No default is promoted while normal cgroup2 qualification remains unresolved.
Final record:`handoff/a53-1040mv-20261008/completion.json`.
The next load/cooling probe is prepared in
`handoff/a53-1040mv-load-cooling-20261008/`.

That probe passes on boot`aa336a57-bc1e-40e2-99a5-e34f24dfdf8b`. Eight
CPU-affined workers each complete30 seconds of checked PBKDF2 computation;
load snapshots reach both new frequency maxima and real temperature peaks
at59.8°C. After all workers exit, synthetic temperature steps exercise all
seven CPUFreq cooling states on both clusters, down to221/325MHz. Clearing
emulation restores1.014/1.352GHz limits and zero cooling state; cleanup
restores schedutil and parking. The final real reading is43.2°C. Total probe
time is35.81 seconds, with no kernel errors and passing post-probe health.
This verifies software cooling response, not physical overtemperature,
long-term stability or endurance. Evidence:
`handoff/a53-1040mv-load-cooling-trial-01/`.
All5,355 checked workloads pass. M69 returns healthy as
`afe0fc55-49d1-4cb9-8b19-c3ad286e3f9e`; the worker exits0. Final audits
verify no writer, both locks,35 source hashes and26 retained outputs.
Final record:`handoff/a53-1040mv-load-cooling-20261008/completion.json`.
No default is promoted; normal cgroup2 qualification remains unresolved.

The next LL point crosses an ARMPLL postdivider boundary. Test-only Linux
`2ed10202112a9` expands native clock callback coverage to both LL and L,
ten rates per domain and four inherited fallback settings:800 successful
pairs and4,256 injected postdivider failures pass under UBSan. Every
intermediate write checks sibling mux/divider/DCM/PLL preservation. LL221MHz
already uses the temporary /4 divider, so identical-value refused writes are
accepted only when the required register state is already present; refused
state changes still test failure fencing. The existing256 CCI pairs/1,836
failures and49 lower-LL pairs/371 failures also pass. No additional operating
point or production driver changes in this test commit. Evidence:
`handoff/a53-upper-divider-20261008/`.

## A53 points through 1.10 V, October 8

Linux`7fe1d8055ed94` enables LL1.118/1.222GHz and L1.495/1.625GHz
using the vendor SB OPP7/OPP6 voltages1.07/1.10V. CCI follows to754/819MHz
and SRAM to1.175/1.20V. Existing thermal limits and voltage ceilings remain
unchanged. Source hashes and the decoded-DTB comparison are retained in
`handoff/a53-1100mv-20261008/`; only four OPP enable flags differ from the
qualified1.04V DTB. The comparison scopes nodes to their CPU cluster because
1.495GHz also appears in the higher, still-disabled LL table.

The runtime-consumer host test checks all six upper CPU points independently
raise and release the correct CCI vote. It passes under UBSan, as do the
expanded800 LL/L transition pairs and4,256 postdivider failure cases. DTB
compilation passes. Both bundles pass full kernel checks and share the same
kernel/DTB; identities and GC roots are retained in the evidence directory.
Physical transition results follow below.
The device probe covers200 ordered A53 pairs,100 CCI/voltage pairs,
and82 target transitions crossing the PLL postdivider boundary. Each pair
executes a checked5,000-iteration PBKDF2 workload; separate sustained-load
qualification remains necessary.

Trial01 passes on boot`c2bbc244-5de8-4184-b757-223e1d46ac41`: all200
ordered A53 frequency pairs and100 ordered CCI/voltage pairs, reaching
LL1.222GHz/L1.625GHz, CCI819MHz, CPU1.10V and SRAM1.20V. Target transitions
include32 LL and50 L postdivider crossings. The64.37-second probe retains
1,928 concurrent SRAM reads, and all checked workloads pass. Sampled real
temperature peaks at41.8°C; kernel errors are absent. Cleanup restores both
A72s, schedutil and automatic parking, removes hold/pause, and passes
post-probe health checks. Evidence:`handoff/a53-1100mv-trial-01/`.
The follow-up load/cooling trial below covers this ceiling. Physical thermal
response and endurance remain unqualified.
M69 recovery returns healthy boot`2907e8a6-f8dd-4d48-bff3-280800b8575e`;
the worker is terminal with exit0. The final audit verifies no writer, both
locks,35 source hashes and26 retained outputs. The overall diagnostic still
fails the normal cgroup2 memory-controller requirement; no default is promoted.
Final record:`handoff/a53-1100mv-20261008/completion.json`.

## A53 1.10V load and cooling — 2026-10-08

The unchanged Linux 7fe1d8055ed94 diagnostic passes a 30-second checked
PBKDF2 workload on CPU 0–7, with 6,466 successful computations and 30 samples.
Both clusters reach their 1.222/1.625 GHz limits at 1.10 V. Real temperature
peaks at 70.6°C; this bounded run does not establish endurance or physical
thermal throttling.

After load exits, synthetic temperatures exercise all nine cooling states
on both clusters, down to 221/325 MHz. Clearing emulation restores both maximum
frequencies and cooling state 0. Cleanup restores schedutil, removes the probe
hold and resumes automatic parking; the probe is inactive and the system is
healthy. Kernel error checks are empty. Total probe time is 37.01 seconds.
Candidate boot: `9a751836-a6d2-431b-b4f1-a58d1abf677d`.
Evidence: `handoff/a53-1100mv-load-cooling-trial-01/`; scripts:
`handoff/a53-1100mv-load-cooling-20261008/`.
Recovery returns healthy M69 boot `451692c1-6b66-4a56-95ae-368783ef6d23`.
The worker is inactive with MainPID 0 and exit 0. The final audit passes:
no writer, both locks acquired, 35 matching executed sources and 26 retained
outputs. The CLI exits 1 because the diagnostic lacks the normal cgroup2
memory controller. No default is promoted.
Final record: `handoff/a53-1100mv-load-cooling-20261008/completion.json`.

## Full A53 clock table prerequisite — 2026-10-08

Linux `108f859dc137d` adds the missing vendor SB clock rates:
LL 1.443/1.495/1.547 GHz and L 2.002 GHz, all with unity PLL/path dividers.
The vendor `mt_cpufreq.c` SB frequency and FP divider tables supply these
values. This completes clock-provider coverage of the existing A53 DT OPP
tables; it does not enable the disabled operating points.

The production clock transition host test now covers all 16 rates per
cluster: 2,048 ordered pairs across four saved MAINPLL settings, 12,344
postdivider fault injections and 127,933 intermediate checks, with UBSan.
Sibling register preservation, failure fencing and fallback restoration
remain checked. All 58,539 clock-core assertions, registration tests and
ARM64 clock-core compilation pass. Evidence and source hash:
`handoff/a53-full-clock-table-20261008/completion.json` and adjacent logs.

Packaging remains pinned to the physically tested `7fe1d8055ed94` kernel.
Higher voltage points still require coupled-rail/runtime tests and physical
qualification; no new candidate was flashed for this clock-table change.

## A53 points through 1.15 V — 2026-10-08

Linux `0d44f0f59b6a0` enables LL 1.274/1.339/1.391 GHz and
L 1.703/1.755/1.820 GHz at nominal 1.13/1.14/1.15 V, using the vendor
SB frequency/voltage tables. SRAM remains capped at 1.20 V. The compiled
DTB differs from the 1.10 V image only by six removed disabled flags.
Normal and diagnostic images build successfully with the full kernel checks
and identical kernel/DTB. Both packaging inputs select this commit.

The native CCI runtime test now covers all upper SB CPU points through
1.20 V with exact mock OPP tables. It verifies rail votes and their release.
L 1.703 GHz selects CCI 884 MHz/1.14 V rather than 845 MHz/1.13 V because
of the half-rate floor; L 1.885 GHz similarly selects 975 MHz/1.19 V.
These are expected governor decisions, not new driver behavior. UBSan
runtime tests and all 5,376 policy combinations, 512 ordered paths, 6,388
fault cases and 704 boot states pass.

Physical probes are prepared separately for LL and L: 169 ordered CPU pairs
each, 80 target postdivider crossings each, 169 LL and 121 L CCI/voltage
pairs. Each uses the existing bounded systemd cleanup and recovery workflow;
the LL result is recorded below and the L trial is pending. All higher points above
1.15 V remain disabled. M69 remains the default and normal cgroup2 remains
unqualified. Build identities, source hash, full build logs and DTB diff:
`handoff/a53-1150mv-20261008/`. Probe scripts and expected mappings:
`handoff/a53-1150mv-ll-20261008/` and `handoff/a53-1150mv-l-20261008/`.

## A53 1.15 V LL transition trial — 2026-10-08

Candidate boot `eada5a22-a5b7-435b-9404-46714bb4925c` passes all 169
ordered LL CPU pairs and 169 ordered CCI/voltage pairs. The test reaches
LL 1.391 GHz, CCI 910 MHz, CPU 1.15 V and SRAM 1.20 V, including 80 target
postdivider crossings. All checked computations and 1,749 concurrent SRAM
reads pass. Sampled temperature peaks at 38.8°C; duration is 56.65 seconds.
The L cluster stays at its minimum during measurement, so this does not
qualify its upper transitions. Startup and cleanup use both cluster maxima.

Both A72s are off during measurement; cleanup restores them, schedutil and
automatic parking, and removes hold/pause. Follow-up health checks pass and
kernel errors are absent. Evidence: `handoff/a53-1150mv-ll-trial-01/`.
M69 recovery returns healthy boot `6aa3d496-f0eb-488c-8d5b-1fd754399c5a`.
The worker is inactive with MainPID 0 and exit 0. The final audit confirms
no writer, both locks acquired, 35 source hashes and 26 retained outputs.
The CLI exits 1 because this diagnostic lacks the normal cgroup2 memory
controller. No default is promoted. Final record:
`handoff/a53-1150mv-ll-20261008/completion.json`.

The separate L transition probe remains prepared. A follow-up 30-second
eight-core load and twelve-state cooling probe is also prepared in
`handoff/a53-1150mv-load-cooling-20261008/`, with the existing 75°C physical
temperature bound and cleanup. Neither has run at this ceiling yet.

## A53 1.15 V L trial 01 — 2026-10-08

Candidate boot `9eb7766b-dba8-4507-97a7-452c41ec4f24` reaches the healthy
observation window, but the observer SSH command times out after 85 seconds
without returning a probe result. A concurrent runner storage-verification
command times out after 25 seconds. No L transition pair is qualified by
this trial. The same supervisor successfully writes/readbacks M69 and
returns healthy boot `e4c5fa50-2dea-46d6-84e8-2cb49c308438`. The terminal
worker has MainPID 0 and exit 0; final audit passes with no writer, both
locks, 35 matching sources and 26 retained outputs. No default is promoted.

The retained current-candidate console shows healthy acceptance around
uptime 157 seconds, a Wi-Fi HIF -75 fault/restart around 164 seconds, and
ends after CPU4–7 reactivation around 166 seconds. It does not establish
why contact was lost or whether a frequency transition was reached.
Separate retained dmesg-ramoops records contain a memcg panic at uptime 57;
these are not evidence of this accepted diagnostic boot's failure.
Evidence: `handoff/a53-1150mv-l-trial-01/recovery-console.txt`, observer log,
and `handoff/a53-1150mv-l-20261008/trial-01-result.json`.

A separate diagnostic probe in `handoff/a53-1150mv-l-trace-20261008/` adds
boot-tagged kernel markers before/after core activation, matrix operations
and cleanup, plus preservation of partial SSH output on timeout. Original
trial sources are retained. No retry or load/cooling trial has run yet.

## A53 1.15 V L traced trial 02 — 2026-10-08

The unchanged kernel passes the traced repeat on boot
`126657c3-fe9e-4387-882f-16c3eaa6778e`: all 169 ordered L CPU pairs,
121 CCI/voltage pairs and 80 target postdivider crossings. It reaches
L 1.820 GHz, CCI 910 MHz and CPU/SRAM 1.15/1.20 V. Every sample at
L 1.703 GHz confirms CCI 884 MHz with the raised 1.14 V CPU vote.
All checked computations and 1,114 concurrent SRAM reads pass. Sampled
temperature peaks at 42.3°C; duration is 37.59 seconds.

Boot-tagged markers show successful all-core activation, ordered A72
shutdown, the complete matrix and cleanup. Both A72s and schedutil are
restored, hold/pause removed, and automatic parking resumes. Post-probe
health passes, with no kernel errors or Wi-Fi HIF fault in the captured log.
The first trial's loss of contact did not reproduce and remains unexplained;
this result establishes bounded transition behavior, not endurance.
Evidence: `handoff/a53-1150mv-l-trial-02/`.
Recovery returns healthy M69 boot `f9e958ea-50a6-4543-8c8e-55c0d1ba0846`.
The worker is inactive with MainPID 0 and exit 0. The final audit verifies
no writer, both locks, 35 source hashes and 26 retained outputs. CLI exit 1
is the expected diagnostic cgroup2 memory-controller qualification failure.
Final record: `handoff/a53-1150mv-l-trace-20261008/completion.json`.
Load/cooling remains pending. No default is promoted.

## A53 1.15 V load stop at 75°C — 2026-10-08

Candidate boot `e01e1e7f-e24e-48b3-9bea-314e1704513f` reaches both
1.391/1.820 GHz limits under eight-core load, but stops after about ten
seconds when the physical sensor reaches 75.5°C, exceeding the probe's
75°C bound. Nine preceding samples are retained; the last is 74.3°C at
9.50 seconds. The planned 30-second checked workload does not complete,
and cooling emulation is not reached. This is a bounded-test stop, not
proof of CPU instability or successful load qualification.

The probe terminates the workers, restores schedutil, removes its hold and
resumes automatic parking. Final temperature is 73.7°C; the transient unit
is inactive, the system remains healthy, and kernel error checks are empty.
Evidence: `handoff/a53-1150mv-load-cooling-trial-01/`.
Recovery returns healthy M69 boot `13f9d8e6-071e-4e63-b065-4d0c21ee84f7`.
The worker is terminal with MainPID0/exit0; final audit verifies no writer,
both locks,35 source hashes and26 retained outputs. No default is promoted.
Final record: `handoff/a53-1150mv-load-cooling-20261008/completion.json`.

The selected board's first passive trip is 85°C, second passive trip 95°C,
and critical trip 117°C. A separate probe is prepared in
`handoff/a53-1150mv-thermal-response-20261008/`: first all twelve emulated
cooling states, then up to45 seconds of checked eight-core load with real
temperature sampling every quarter second and a90°C stop bound. It checks
trip identity, retains raw frequency/cooling readings, and reports actual
physical throttling separately from bounded workload success. The device
service deadline remains70 seconds within the90-second recovery observation
window. It has not run; the aborted75°C test remains recorded as failed.

## A53 1.15 V physical thermal response — 2026-10-08

The separate thermal-response trial passes on boot
`83bc7780-e6d0-445f-b6bf-8a0df1031d8e`. All twelve emulated cooling states
on both clusters map to the expected frequency limits and clear before
real load starts. Eight A53 cores then complete 10,936 checked PBKDF2
computations over45 seconds, retaining173 real-temperature samples.

Real temperature peaks at85.4°C. The first sampled crossing is at45.255s
from probe start; by45.516s both clusters have cooling state1, limits and
actual rates1.339/1.755GHz, and the shared rail has dropped from1.15 to1.14V.
Both clusters exercise states1 and2 during real load. The final load sample
is83.8°C with state0 and restored1.391/1.820GHz limits. This demonstrates
bounded physical throttling and release around the85°C passive trip; it
does not establish endurance or operation at the95°C/117°C trips.

Total probe time is53.80 seconds. Cleanup restores schedutil and parking,
removes the hold, and leaves the system healthy with the transient unit
inactive. Final temperature is74.3°C. Kernel checks and the Wi-Fi HIF fault
search are empty. Recovery returns healthy M69 boot
`f48185ac-3a2a-4cd7-aee8-8c7847a225be`. The worker is inactive with MainPID0
and exit0; final audit passes with no writer, both locks,35 source hashes
and26 retained outputs. CLI exit1 remains the expected diagnostic cgroup2
memory-controller qualification failure. No default is promoted.
Final record: `handoff/a53-1150mv-thermal-response-20261008/completion.json`.
Evidence: `handoff/a53-1150mv-thermal-response-trial-01/`, including the
raw JSON, kernel log and `thermal-timeline.csv`. The earlier75°C-bound
abort remains a separate failed test; its threshold was not changed.

## Full vendor A53 table through 1.20 V — 2026-10-08

Linux `814f83792871a` enables the remaining six SB OPPs:
LL 1.443/1.495/1.547 GHz and L 1.885/1.950/2.002 GHz, at nominal
1.17/1.19/1.20 V. Both A53 clusters now expose all16 vendor points in the
candidate. SRAM remains capped at1.20 V; the vendor rail code explicitly
permits SRAM equal to CPU voltage at the upper ceiling. L1.885 GHz needs
CCI975MHz/1.19V; L2.002 GHz uses the vendor CCI saturation at988MHz/1.20V.

Normal and diagnostic bundles build successfully with the full kernel
checks and identical kernel/DTB. The DTB differs from the1.15V image only
by six OPP enable flags. Clock-host UBSan tests pass2,048 A53 pairs,
12,344 postdivider failures and127,933 intermediate checks; the runtime
CCI test already covers these upper points and passes unchanged.
Both packaging inputs select this commit. No default is promoted.

The prepared hardware probe covers every pair with at least one newly
enabled rate:87 pairs per cluster,174 CPU pairs total,87 CCI pairs, and
48LL/30L target postdivider crossings. These disjoint pairs plus the two
qualified13x13 lower matrices cover all512 ordered CPU pairs. This is a
coverage plan, not a claim of new hardware qualification. It retains
boot-tagged progress markers, concurrent SRAM reads, checked computation,
65-second guard and70-second service deadline. Builds, source hashes,
DTB diff, expected mappings and probe scripts are in
`handoff/a53-1200mv-20261008/`. Transition and load/thermal qualification
of the1.20V ceiling remain pending.

## A53 1.20 V transition trial 01 — 2026-10-08

Candidate boot `c24ad825-17da-47a3-ba23-bffcf3a371bc` passes all174 added
CPU pairs and87 CCI pairs, with48LL/30L target postdivider crossings,
1,037 concurrent SRAM reads and checked computation. It reaches
LL1.547/L2.002GHz, CCI988MHz, and CPU/SRAM1.20/1.20V. L1.885GHz correctly
selects CCI975MHz/1.19V. Sampled temperature peaks at43.6°C; duration is
33.28 seconds. Both A72s and schedutil are restored, hold/pause removed,
automatic parking resumes and post-probe health passes.

One kernel diagnostic is retained at uptime169.036834:
`CPUCLK_OBSERVE callback=path-rate domain=1 stage=snapshot status=-11`.
It occurs during CPU8 activation, before all-cpus-online at169.299857 and
matrix-start at169.520318. The clock observer requires stable snapshots;
its path-rate callback returns zero when sampling fails. This is not a
failed matrix pair, but it remains an unresolved observation issue and the
kernel-error check is not clean. No Wi-Fi HIF fault appears in this log.

Independent coverage audit verifies that these174 new pairs and the two
prior169-pair matrices are disjoint and cover all512 ordered pairs across
both16-point tables. This is aggregate evidence across consecutive kernels
differing only by six OPP enable flags, not a single512-pair run.
Evidence: `handoff/a53-1200mv-trial-01/`, including `coverage-audit.json`.
Recovery returns healthy M69 boot `8dbf28fc-451e-4750-aa1a-3cbf607952cd`.
The worker is inactive with MainPID0/exit0; final audit verifies no writer,
both locks,35 source hashes and26 retained outputs. CLI exit1 remains the
expected diagnostic cgroup2 memory-controller qualification failure. No
default is promoted. Final record:
`handoff/a53-1200mv-20261008/trial-01-result.json`.

The full-ceiling load/thermal probe is prepared in
`handoff/a53-1200mv-thermal-response-20261008/`: fifteen emulated cooling
states, then45 seconds of checked eight-core load, with real throttling
reported separately and a90°C stop bound. It has not run yet.

## Clock observations during A72 startup — 2026-10-08

Linux `eb64c46a953ef` separates read-only domain observation from the
full snapshot used by transition planning, execution, startup admission and
power lifecycle checks. Previously a read of the L clock compared every
sampled register, including firmware-owned A72 PLL words. The full-table
trial's path-rate snapshot EAGAIN coincides with CPU8 startup; unrelated
A72 register changes are a plausible cause, though the original log did
not capture the differing words.

Read-only callbacks now compare only the requested domain's PLL words,
mux and divider fields, under the existing mutex and CSPM lease. They still
take exactly two samples and reject requested-domain instability or I/O
failure. No retry, stale-rate substitution or diagnostic suppression is
introduced. All transition and lifecycle paths retain strict full snapshots;
lease-release errors still fence the provider.

The production observation/lease path passes1,152 single-bit change cases
and25 injected errors under UBSan. Every full-snapshot comparison remains
strict, while unrelated changes no longer invalidate a requested-domain
read. Existing callback semantics,58,539 core assertions,2,048 A53 pairs,
12,344 postdivider failures and native A72 lifecycle tests pass. ARM64
compilation and both full image builds pass; the new regression is part of
both packaging check suites. Kernel and DTB match between bundles, and the
DTB is unchanged from the full-table candidate.

A physical regression is prepared: continuous A53 rate reads during three
complete A72 power cycles with checked work on each restarted core, followed
by the174 upper transition pairs. The first attempt is recorded below. Evidence, builds and
scripts: `handoff/clock-domain-observation-20261008/`. Both packaging inputs
select this commit; no default is promoted.

## 2026-10-08: observation trial interrupted before CPU8 startup completed

Trial `clock-domain-observation-trial-01` booted kernel `eb64c46a953ef`
(candidate boot `5c453107-d099-4568-bdad-b833bf4b0f96`). The probe created
its parking hold at 163.792 seconds with CPUs0–3 online. CPUs4–7 then
started; the console ends at 163.997 seconds after CPU7. No CPU8 online,
all-CPUs-ready, observation regression or transition-matrix marker follows.
The observer timed out after85 seconds and produced no measurement result.
This does not qualify or disprove the domain-scoped observation fix.

There is no Wi-Fi HIF fault in the current candidate console. The older
memcg panic in separate pstore records predates this healthy candidate and
must not be attributed to this interruption. The earlier1.15V L trial also
ended after CPU7 startup, but its coincident Wi-Fi fault is not necessary
for this observed pattern. Neither capture identifies the blocking call.

The CCI driver samples only online clusters and queues its update from
`CPUHP_AP_ONLINE_DYN`; the A72 power driver's prepare callback has no CCI
floor acquisition. A missing startup vote is a hypothesis, not a measured
cause. Instrumentation must distinguish prepare entry, off-state checks,
clock restart validation, rail transaction and PSCI CPU_ON. A synchronous
devfreq update from prepare cannot simply be added: existing updates hold
the devfreq mutex while acquiring the CPU hotplug read lock, whereas prepare
runs under the hotplug write lock. Any startup vote needs a consistent lock
order and lifetime through failure/unwind and the last-core shutdown.

Recovery boot `16976c24-8d3a-45a7-97d1-65596b5043aa` passed the final audit:
swap layout, no writer, locks acquired, all35 source hashes matching and
all26 ordinary outputs retained. The worker is inactive with MainPID0.
No default was promoted. Evidence: `handoff/clock-domain-observation-trial-01/`
and `handoff/clock-domain-observation-20261008/trial-01-result.json`.

## 2026-10-08: traced warm startup stops in VPROC enable

Diagnostic-only kernel `3c9e22b10f1ee` adds dynamic-debug preparation stages
and host-harness logging plumbing. Full image build and packaged tests pass;
the DTB is identical to `eb64c46a953ef`. Normal packaging remains at `eb64`.
The traced trial boot `9a65254e-7c9c-40b6-896e-81aa08079626` reached healthy
userspace and the probe's cold-start trace check passed before creating its
parking hold. Warm CPU8 startup reached both off samples, clock restart
validation, transaction admission, guard entry, SPM reset update, IDVFS
fence and PWRAP reset assertion. Their verify stages completed.

The final console marker at164.014728 seconds enters action4,
`MT6797_A72_VPROC_ENABLE`. No action4 verify or prepare-complete marker
follows. This localizes the observed interruption to the enable action,
which calls `regulator_enable(preflight->vproc_big)` when a vote is needed;
it does not identify whether regulator-core locking, provider I/O, hardware
response, or another concurrent failure is responsible. CPU_ON has not been
reached by this prepare callback. The CCI startup vote hypothesis remains
unproven and should not be treated as the cause. The next trace should
separate regulator-core entry, DA9213 provider entry and its I2C transaction.
The observation regression and upper transition matrix never started.

The observer timed out after85 seconds. Automatic recovery returned M69
`bf4283d8-6dc1-4c29-8079-d1f71f300cbd`; the final locked audit passed all35
source hashes and retained all26 outputs. Worker inactive, MainPID0.
Evidence: `handoff/a72-startup-trace-trial-01/recovery-console.txt` and
`handoff/a72-startup-trace-20261008/trial-01-result.json`. No default promoted.

## 2026-10-08: regulator trace boot-argument limit

The next diagnostic (`a028500f1517b`) adds regulator dependency-lock,
DA9214 provider and BUCKB I2C entry/return markers. ARM64 compilation,
98,304 selector-pair/settling/rollback cases and the full packaged build pass.
Trial `a72-regulator-trace-trial-01` reached SSH but never healthy acceptance:
its expanded dynamic-debug argument filled the command line to2047 bytes
(excluding newline), truncating the baseline lease capability token. The
self-accept service repeatedly failed and the regression never started.
This trial supplies no new evidence about the warm-start regulator stall.

The runner restored healthy M69 `01fc7e2f-ef5d-42b6-a5a5-f105f2003fb6`.
Its final audit passed:35 source hashes,26 retained outputs, swap layout,
no writer and locks acquired. Worker inactive, MainPID0. Evidence lives in
`handoff/a72-regulator-trace-trial-01/` and the corresponding dated
`trial-01-result.json`.

The corrected bundle uses the previous shorter A72-only debug boot argument
and enables the extra regulator callsites through dynamic-debug control when
the probe starts, after health acceptance. It builds with the same kernel;
see `handoff/a72-regulator-trace-runtime-20261008/`. Its physical trial is
pending. Normal packaging and the installed default have not changed.

## 2026-10-08: BUCKB enable completes; trace ends at following delay

The shortened-argument candidate boot `f9396084-2651-433c-b47e-1e35217f201d`
passed healthy acceptance. The probe enabled the additional dynamic-debug
callsites at165.518 seconds before creating the parking hold. Warm CPU8
startup again reached VPROC_ENABLE, but this capture shows both regulator
core dependency locks and the DA9214 mutex acquired, the control-register
write and readback returning2 (the expected transfer count), and the
regulator enable sequence returning0 at165.842684 seconds. Action4 verify
also completed successfully.

The final marker at165.846512 enters action5 with value0x3e8: the1ms delay
before isolation release. No delay verify follows. Thus the prior trace's
last enable-entry marker did not establish a regulator lock or I2C stall;
this attempt completed that entire path. Logging changes timing, and neither
capture proves the root cause. The observation regression never started.
Further investigation must consider concurrency while PWRAP reset is held,
scheduling during the delay, and power/clock conditions, without assuming
the delay itself is faulty or substituting a busy wait without evidence.

Recovery returned healthy M69 `5a212a80-cfec-4ad1-b985-3a7d46cfdfd0`.
The worker is inactive with MainPID0; the final locked audit confirms all35
source hashes and26 retained outputs, swap layout and no writer. Evidence:
`handoff/a72-regulator-trace-runtime-trial-01/recovery-console.txt` and
`handoff/a72-regulator-trace-runtime-20261008/trial-01-result.json`.
No default promoted.

## 2026-10-08: vendor reset-held delay does not resolve warm startup

Vendor `arch/arm64/kernel/psci.c:525–550` uses `udelay(1000)` between BUCKB
enable and isolation release while PWRAP reset is latched. Diagnostic kernel
`e7314b974124e` matches that busy wait for the guarded interval, retaining
sleeping delays after reset release. Core/lifecycle fault tests, ARM64 and
full packaged builds pass. The lifecycle harness now rejects sleeping while
reset is asserted and checks the guarded1ms busy delay. This change neither
disables interrupts nor excludes other CPUs' hardware accesses.

Trial `a72-reset-settle-trial-01`, boot
`d12f8f10-c8ce-40cf-bc6b-a505cdbd9476`, reached healthy acceptance and started
the same traced probe. Warm preparation completed off-state samples, clock
validation, SPM reset and IDVFS fence. The last marker at168.618853 enters
PWRAP reset assertion (action3); its verify marker is absent. The changed
delay was not reached. The interruption therefore persists and this candidate
is not qualified. No observation regression or transition matrix ran.

The trace also records VMC/VMCH regulator activity shortly before reset
assertion; this is concurrent activity, not proof of a conflicting access.
The reset identifier matches the vendor bit11 (0x800). Next investigation
should examine coordination between this reset window and PMIC-wrapper
clients, rather than infer a timer fault from the earlier delay-entry marker.

Recovery M69 `690d7ffc-92fc-4b70-a3c0-c6d957987b05` passed the final locked
audit:35 source hashes,26 retained outputs, swap layout and no writer.
Worker inactive, MainPID0. Evidence: `handoff/a72-reset-settle-trial-01/`
and `handoff/a72-reset-settle-20261008/trial-01-result.json`. Normal packaging
remains at `eb64c46a953ef`; no default promoted.

## 2026-10-08: fixed startup passes once; concurrent observation still fails

Trial `a72-fixed-startup-trial-01`, kernel `e7314b974124e`, boot
`4a8980b5-5f4f-453c-a3cd-d34d08143b36`, froze parking and set LL806/L1092MHz,
CCI611MHz and CPU1.000V with readback before releasing the hold. Both A72
cores then started successfully and all CPUs were online at164.840 seconds.
The recorded state before fixing the clocks was already CPU1.20V/CCI988MHz;
therefore this run does not establish that the earlier failures were caused
by a low voltage or CCI floor.

The probe then selected the qualified maximum A53 points and started its
continuous A53 clock-rate reader. In cycle0, CPU9 and CPU8 went offline.
The first CPU8 re-add stopped at VPROC_ENABLE entry at165.088392 seconds,
after PWRAP reset assertion/verification. No regulator-core entry follows.
No full cycle completed and the174 transition matrix never began. The fixed
operating point is not a sufficient fix; timing and concurrent clock access
remain variables. The failed probe produced no measurement JSON.

Source inspection identifies a remaining observation coupling:
`mt6797_cpuclk_read_observation()` still calls the full `read_once()` twice,
including secure MP2 register reads, even for A53/CCI rate callbacks. The
`eb64` fix only scopes equality. Narrowing the actual register reads is the
next investigation; this source fact does not prove a secure-monitor hang.

Healthy M69 recovery `79e049cf-c608-4f85-9b7b-f793aac31692` passed the final
locked audit (35 source hashes,26 retained outputs, swap layout, no writer).
Worker inactive, MainPID0. Evidence: `handoff/a72-fixed-startup-trial-01/`
and `handoff/a72-fixed-startup-20261008/trial-01-result.json`. No default
promoted and normal packaging remains unchanged.

## 2026-10-08: domain-specific reads pass concurrent A72 regression

Diagnostic kernel `1844e1afbb318` changes actual observation accesses: each
A53/CCI read samples only its PLL, mux and divider twice, without MP2 secure
reads. MP2 observation still samples its two secure PLL words; transition
and lifecycle full snapshots are unchanged. Host tests execute the domain
reader and assert exact access footprints across1,152 bit-change cases,
zero A53/CCI secure calls,23 error cases and lease ownership. Existing
58,539 core assertions, callback checks, ARM64 and full image builds pass.

Trial `clock-domain-reads-trial-01`, boot
`43070076-e93f-43b7-b0e6-283a4c5fb0a1`, passed the same fixed-startup
comparison that failed on `e7314b974124e`. Initial restoration at
LL806/L1092MHz,CCI611MHz/CPU1.00V succeeded. At maximum A53 rates the probe
completed three full A72 cycles with558 paired rate reads and six checked
workloads on restarted A72 cores. All174 upper transition pairs passed,
including48 LL/30 L postdivider crossings and1,083 SRAM reads. Elapsed
36.232 seconds; peak sampled temperature43.9°C. Both schedutil governors,
parking and hold/pause cleanup were restored. The captured kernel has no
matched clock, rail, lifecycle, BUG/Oops/WARNING or Wi-Fi HIF errors.

This is bounded evidence for the domain-read change, not proof of a secure
monitor root cause or ordinary autonomous startup qualification. The next
prepared probe removes fixed-startup conditioning. Full-ceiling thermal and
endurance checks remain pending. Normal packaging remains at `eb64`.

The runner's general profile check failed at the expected cgroup-v2 memory
controller gate on this cgroup-v1 diagnostic image; the hardware probe itself
returned0. M69 recovery `14dc830a-7f25-48ac-a052-db8c866928cb` passed the final
locked audit:35 matching source hashes,26 retained outputs, no writer and
swap layout. Worker inactive, MainPID0. Evidence:
`handoff/clock-domain-reads-20261008/completion.json` and
`handoff/clock-domain-reads-trial-01/`. No default promoted.

## 2026-10-08: ordinary startup remains unresolved after scoped observations

Trial `clock-domain-reads-idle-trial-01` used the same `1844e1afbb318` bundle
as the passing fixed-startup regression, but created its hold directly from
autonomous parking with CPUs0–3 online and without changing governors first.
Boot `2b3bbc3a-4204-4e58-b943-f7ff72395a61` reached healthy acceptance. Warm
CPU8 preparation completed its off samples, clock checks, transaction
admission, SPM reset update and IDVFS fence. The last marker at163.943664
enters PWRAP reset verification; no VPROC_ENABLE marker follows. The observer
timed out without a result, before the observation stress or matrix began.
The scoped-observation fix therefore has bounded passing evidence under
fixed-clock conditioning, but ordinary startup is not qualified.

The next source audit concerns full snapshots still used by A53/CCI
frequency transitions and parent changes. These include secure MP2 reads,
unlike the now-scoped read-only callbacks. A future change must preserve
all shared mux/divider/DCM checks and strict native A72 admission; do not
merely weaken snapshot comparisons or assume the secure call is proven to
hang. Reset/PMIC access coordination remains another unproven possibility.

Healthy M69 recovery `3da89774-2ac5-45ac-adf2-7f5a4bd58025` passed the final
locked audit:35 source hashes,26 retained outputs, swap layout and no writer.
Worker inactive, MainPID0. Evidence: `handoff/clock-domain-reads-idle-trial-01/`
and `handoff/clock-domain-reads-idle-20261008/trial-01-result.json`.
Normal packaging remains unchanged; no default promoted.

## 2026-10-08: AP snapshots pass ordinary startup and clock stress

Diagnostic kernel `7c94d629970b5` uses AP-only snapshots for A53/CCI
transactions and parent changes. These retain both complete shared mux and
divider words, all three AP PLL words and SYNC_DCM. Native A72 transactions
and initial admission retain full snapshots, including secure MP2 reads.
Host checks cover 288 AP snapshot bit changes in addition to 1152 domain
observation cases; transition and native A72 checks and the full build pass.

Trial `clock-ap-snapshot-trial-01`, boot
`c1fb9e5f-d07b-4e47-92e4-68a1d52f8c93`, started from CPUs0–3 with ordinary
governors and no fixed-clock conditioning. It passed three A72 cycles,
586 paired A53 rate reads, six checked A72 workloads, 174 upper transition
pairs and 1063 SRAM samples in36.016 seconds, peaking at45.4°C. Both governors
returned to schedutil, hold/pause were removed and parking remained active.
The kernel error scan and follow-up passed. This supports the access-scope
fix, but does not prove which firmware operation caused earlier hangs.

Healthy M69 recovery `14dd17b4-d551-43d0-9f46-db225f93db61` passed the final
locked audit:35 matching source hashes,26 retained outputs, swap layout and
no writer. Worker inactive, MainPID0. The general profile remains unqualified
because this diagnostic uses cgroup1; the normal memory-controller gate
fails as expected. No installed/default generation was promoted. Evidence:
`handoff/clock-ap-snapshot-20261008/completion.json` and
`handoff/clock-ap-snapshot-trial-01/`. A repeat without extra driver tracing
passed its physical probe in `clock-ap-untraced-trial-01`: boot
`c08eda15-c702-4827-bb18-30c109002235`, three A72 cycles,480 paired reads,
six checked workloads,174 transitions,1046 SRAM samples,34.816 seconds
and43.6°C peak. Cleanup and kernel checks pass. The boot command line has
no dyndbg argument. M69 recovery `104bbd44-031f-4073-b961-bd3aa67111d1`
and final locked audit pass:35 matching sources,26 retained outputs, swap
layout and no writer. The worker is terminal. Evidence is in
`handoff/clock-ap-untraced-20261008/completion.json`. Full-ceiling thermal
qualification is next.

## 2026-10-08: A72 frequency-control source entry points

A72 frequency control remains unfinished at the fixed750MHz operating point.
The local vendor tree's
`drivers/misc/mediatek/base/power/mt6797/mt_cpufreq.c:3178` implements the
iDVFS request path, selecting percentage tables by CPU date code and segment.
`mt_idvfs.c:917` converts the percentage into a fixed-point SWREQ and invokes
`SEC_BIGIDVFS_SWREQ`; low-frequency requests also change the clock divider.
This is not the same transaction as the maintained AP clock planner.

The vendor also provides a non-iDVFS path in `mt_cpufreq.c:3044`:
`adjust_armpll_dds()` raises the B rail to its fallback requirement when
needed, switches to MAINPLL, calls `BigiDVFSPllSetFreq()` in MHz, waits for
PLL settling, switches back to ARMPLL and restores voltage. The wrapper in
`mt_idvfs.h:118` invokes the dedicated firmware PLL-set-frequency call.
These are source entry points, not evidence that either interface is safe
or supported by the device's current firmware state. Next implementation
work must establish firmware admission, voltage/SRAM and CCI ordering,
shared-register serialization, failure handling and hotplug restoration
before adding an A72 OPP policy. No A72 frequency writes were attempted.

The retained newer live capture was independently checked on the host:
SHA-256 `82eb00d45057489a5964b14cfe534d883ed16b4ca335d80920c5e7e286160c32`
(the identity documented in `research/ATF_WATCHDOG_HANDOFF.md`). At mapping
base0xff3c0, the AArch64 dispatcher compares0xc20003b8 at0x108db4 and
routes through0x109164 to the PLL handler at0x106450. The handler starts by
disabling the PLL at0x102224a0, matching the retained vendor implementation.
This validates the entry point against that captured firmware, not a new
live reread or an operational frequency-change test. Host evidence is in
`handoff/a72-frequency-audit-20261008/`; private payload bytes remain local.

## 2026-10-08: full-ceiling thermal guard and minimum cooling level

`a53-1200mv-thermal-response-trial-01` passed all15 cooling states under
emulation, cleared emulation and reached both full rates during real load.
It stopped after about32 seconds of load at the90°C guard (90.7°C reading).
The120 retained load samples show cooling states0–3 above85°C, with repeated
returns to state2 (1.443/1.885GHz,1.19V) near90°C. Cleanup restored governors
and parking; kernel and follow-up checks pass. M69 recovery
`f620de92-a764-4b96-9cec-dc9d04a14c6f` and final audit pass:35 matching
sources,26 retained outputs, swap layout and no writer. Worker inactive,
MainPID0. Evidence: `handoff/a53-1200mv-thermal-response-20261008/completion.json`.

`gov_step_wise.c:get_target_state()` permits reducing cooling on a falling
sample even while above the trip. With the expanded sixteen-point tables,
the previous unrestricted map admits the three newly added hot OPPs during
passive cooling. Diagnostic commit `085d69c3f2945` sets the85°C map minimum
to state3, capping LL/L at1.391/1.820GHz and1.15V while cooling is requested.
The governor may throttle further; full rates remain available after cooling
releases. The95°C and117°C trips are unchanged. DTB compilation passes;
full packaging and a repeated bounded hardware load are pending. This is
a board thermal-policy adjustment, not a claim that the governor is faulty.
The repeated synthetic test expects the policy's reachable states3–15;
the original trial already verified frequency mapping for states1–15.

## 2026-10-08: cooling release exposes slow normal polling

`a53-thermal-floor-trial-01` verifies reachable synthetic states3–15 and
the real state3 frequency cap, but still stops at90.4°C. Near the end,
temperature falls through84.2,83.5,83.2°C with state3 and1.15V. Cooling then
releases: samples at35.202,35.462 and35.722 seconds show full1.547/2.002GHz,
1.20V and85.4,88.2,89.9°C, respectively. The normal one-second polling
interval permits rapid reheating after passive cooling releases. This is
a distinct boundary from the overly weak cooling levels in the first trial.
Cleanup and kernel checks pass. M69 recovery `eb109d18-9545-48d4-9c5c-f28da6b6b3e4`
and final audit pass:35 matching source hashes,26 retained outputs, swap
layout and no writer; worker inactive with MainPID0. Evidence:
`handoff/a53-thermal-floor-20261008/probe-result.json` and the raw trial.

Diagnostic `b62fc653f754f` reduces normal thermal polling from1000 to100ms,
retaining40ms passive polling, the state3 floor and all trip temperatures.
DTB and full packaging builds pass. Packaged DTB polling, floor and trip
checks pass. Hardware verification remains pending;
neither thermal diagnostic has qualified the full-ceiling load yet.

## 2026-10-08: full-ceiling thermal response passes with faster polling

Kernel `b62fc653f754f`, trial `a53-thermal-poll-trial-01`, boot
`69044188-1cfe-4faf-adb3-d98e2547aa76`, passes the bounded thermal probe.
The live DT verifies100ms normal polling,40ms passive polling and the state3
cooling floor. All reachable synthetic states3–15 map correctly and clear
before the physical load. Eight A53 cores complete45 seconds and11,156
checked PBKDF2 computations, with173 real-temperature samples. Both full
rates are observed; peak temperature is88.1°C. Both clusters exercise
states0,3,4,5, and the last load sample is84.2°C at1.274/1.703GHz.

Total probe time is55.766 seconds. Cleanup restores both schedutil governors,
removes the hold and retains active parking; final temperature is75.8°C.
Kernel and follow-up checks pass. Healthy M69 recovery
`d0177459-b374-47cd-a18e-85faf4df2311` passes the final locked audit:
35 matching sources,26 retained outputs, swap layout and no writer. Worker
inactive, MainPID0. Final record: `handoff/a53-thermal-poll-20261008/completion.json`.
This qualifies
the bounded response, not endurance or normal cgroup2 operation, and does
not promote the installed/default generation. Evidence:
`handoff/a53-thermal-poll-20261008/probe-result.json` and raw trial files.

## 2026-10-08: live A72 table selection and SRAM ownership prerequisite

After verified recovery, read-only M69 capture of `/chosen/atag,devinfo`
(boot `d0177459-b374-47cd-a18e-85faf4df2311`) reports word61=0x003f00c0
and word22=0x00000004. Applying the pinned vendor's date/segment functions
selects date0119, CPU_LEVEL_1, TT segment. Its nominal B table is SB0119
with the TT overrides at the first two points (2.587/2.431GHz); this is
source selection evidence, not a qualified operating range. The extracted
sixteen-point nominal table is in
`handoff/a72-frequency-audit-20261008/live-table-selection.json`.
Calibration and hardware qualification are still required.

The maintained SRAM regulator's ordinary setter rejects changes after
`mt6797_sram_boot_attempted` is set (`mt6797-bigidvfs-sram.c:601`). Existing
A72 hotplug uses an explicit lifecycle transaction instead. A future A72
DVFS implementation must extend coordinated ownership rather than attaching
an OPP table to a setter that is intentionally unavailable after startup.
No regulator or frequency writes were made in this capture.

## 2026-10-08: A72 firmware PLL expected-state planner

Linux `43b04fd6748ea` adds a pure expected-readback planner for the audited
0xc20003b8 PLL service. It accepts only the26MHz reference and integral-MHz
requests within the vendor API's250–3000MHz bounds, models post-divider
selection and Q24 PCW truncation, preserves unrelated snapshot/register bits,
and expects PLL enable with the PCW latch clear. This API range does not
qualify any board OPP. No firmware write callback or CPUFreq policy is added.

The production-core host suite passes16 cases and73,581 assertions, including
all2751 integral-MHz requests, boundary constants,32-bit preservation cases,
invalid arguments and unchanged output on failure. ARM64 core-object build
passes. Evidence: `handoff/a72-frequency-audit-20261008/pll-plan-tests.log`.
Normal packaging remains at the physically tested `b62fc653f754f`.
Remaining implementation includes OPP/voltage admission, SRAM/power ownership,
safe-parent/DCM sequencing, strict readback and hotplug restoration.

## 2026-10-08: A72 DVFS integration route and lock ordering

Source review rules out assigning a second regulator owner: the native A72
power provider holds exclusive VPROC and SRAM handles. A separate CPUFreq
driver would also conflict with the existing cpufreq-dt registration.
`dev_pm_opp_config.config_clks` offers a candidate integration route: the
existing cpufreq-dt target calls `dev_pm_opp_set_rate()`, and the OPP core
invokes this callback with the selected OPP. The A72 owner can retain rail
ownership and execute voltage/clock coordination inside that callback.
OPP voltage metadata can be parsed without giving the OPP core a second
regulator handle; registration must precede CPUFreq table discovery.
This is an implementation route, not a tested callback integration yet.

Both native A72 commit/teardown and CPUFreq use CPUHP_AP_ONLINE_DYN. Native
power is built in; `nixos/core-parking.nix` loads cpufreq-dt later. That
registration order puts A72 startup commit before CPUFreq online and reverses
on teardown, allowing CPUFreq to stop before native shutdown. Registration
order must be enforced/verified, not inferred merely from callback names.
A72 frequency operations must serialize through the existing power owner;
CCF prepare precedes clock-observer/CSPM locks. Do not introduce a nested
CPU hotplug read lock in a callback that can run under the hotplug writer,
or query firmware AFFINITY_INFO on a running A72. Future tests must include
CPUFreq initial policy, restart, teardown veto and partial clock/rail failure.

## 2026-10-08: bounded A72 clock handoff planning

Linux `d6763b2d4fa27` adds the clock-only MP2 transition plan: divide the
running PLL path by4, select MAINPLL, program the disconnected MP2 PLL,
return to MP2 at /4 and restore the target path divider. The338MHz vendor
point uses a676MHz PLL with /2. Other selected points use unity division;
equivalent existing unity encodings are preserved. The plan rejects disabled
or latched PLL state, non-PLL source, unsupported dividers, wrong reference
and a fallback rate exceeding the greater endpoint. It records the minimum
intermediate rate for the executor's DCM handling and full expected snapshots.

The production-core suite passes18 cases and115,279 assertions. The new
matrix covers1156 combinations (17 points including startup750MHz, squared,
across four unity encodings), checks every intermediate rate and unrelated
snapshot fields, and includes rejected-admission/output-preservation cases.
ARM64 core-object compilation passes. Evidence:
`handoff/a72-frequency-audit-20261008/transition-plan-tests.log`.
No firmware executor, OPP policy or voltage ownership change is enabled;
normal packaging remains at hardware-tested `b62fc653f754f`.

## 2026-10-08: strict A72 clock-plan executor

Linux `1e6071c7f2f3e` adds the callback-based clock executor. It reconstructs
the plan using the caller's independently measured/pinned MAINPLL rate,
rejects altered plans and stale initial state before mutation, and requires
MP2 DCM to be quiesced. All five writes require exact full-snapshot and DCM
readback. Any uncertain write or subsequent readback error sets a sticky
fault and stops I/O; it does not attempt a speculative rollback. The future
power owner must retain sufficient voltage after such a fault.

Host production-core checks pass19 cases and121,859 assertions, including
six read and five write error boundaries,1728 snapshot bit corruptions,
160 DCM corruptions, enabled-DCM refusal, plan mutation and sticky-fault
re-entry. ARM64 object compilation and existing AP transition/native A72
boot API regressions pass. Logs are in
`handoff/a72-frequency-audit-20261008/executor-tests.log` and
`executor-regression.log`. Hardware callbacks, owner serialization and OPP
integration are still pending; no runtime frequency-write path is enabled.
Normal packaging remains at `b62fc653f754f`.

## 2026-10-08: inherited MP2 PCW latch is valid startup state

Before wiring hardware callbacks, the admission check was corrected:
firmware `power.c:221` explicitly expects MP2 CON1=0xB9B13B14 at startup,
also used by existing native A72 fixtures. Bit31 is the PCW latch strobe,
not an independently established busy indication. Rejecting it would reject
the actual750MHz startup state. The planner now accepts either inherited
bit value; its firmware-write result still requires bit31 clear, matching
the audited PLL setter. No post-write equality checks were weakened.

The transition matrix now covers2312 combinations across both latch states.
The real executor fixture starts at0xB9B13B14. All19 core cases and163,542
assertions pass, along with native A72 boot API tests and ARM64 compilation.
Evidence: `handoff/a72-frequency-audit-20261008/inherited-latch-tests.log`.
Hardware callback/rail-owner integration remains pending; normal packaging
and installed M69 are unchanged.

## 2026-10-08: owner-only A72 hardware rate API

Linux `97f46b6fefea7` connects the verified MP2 executor to the actual divider,
mux and dedicated firmware PLL setter. `mt6797_cpuclk_set_mp2_rate()` accepts
only the A72 power owner. The caller must serialize hotplug/power, keep a core
online, disable iDVFS and provision both rails for the higher endpoint.
The API pins the already-enabled MAINPLL rate before taking observer/CSPM
locks, disables MP2 DCM with verified toggle writes, executes the five-step
clock plan and restores the original DCM policy. A final full snapshot checks
that DCM restoration preserved the endpoint. DVFS creates no last-core restart
receipt. Uncertain writes or lease release fence the owner and retain the
MAINPLL rate pin; callers must retain sufficient rails on `-EUCLEAN`.

The production-provider host harness passes all39 hardware error boundaries
with both failed-write effect models, full-width SMC status failures, DCM
readback corruption, precondition refusal and retained-pin re-entry. Existing
boot/restart tests, all19 core cases/163,542 assertions, AP snapshot/transition
regressions and ARM64 provider compilation pass. Evidence:
`handoff/a72-frequency-audit-20261008/hardware-api-tests.log` and
`hardware-api-regression.log`.

No runtime consumer calls this API yet. Power-owner voltage/SRAM coordination,
CPUFreq/OPP integration and bounded hardware qualification remain required.
Normal packaging stays at `b62fc653f754f`; installed M69 is unchanged.

## 2026-10-08: SRAM runtime transaction preserves restart ownership

Linux `bf4844daa46ba` adds the provider-internal `mt6797_sram_set_running()`
transaction. It requires a completed first-start record and excludes stopped,
restart-armed or faulted state. It admits the vendor 1.0–1.2V SRAM range on
its exact25mV grid, compares two full pre-write samples against the last
verified live state, verifies two full post-write samples and updates the
live record only on success. Calibration and upper control bits must remain
unchanged. Unexpected state or uncertain writes fence further operation;
there is no voltage rollback. The original powered reset baseline survives
runtime changes, allowing existing shutdown/restart checks to remain strict.

All81 voltage pairs pass with shutdown/restart after each pair, plus256
single-bit sample corruptions, five I/O failure boundaries and admission
checks. The production SRAM core suite passes17 cases/2692 assertions;
provider boot API regressions and ARM64 regulator compilation also pass.
Evidence: `handoff/a72-frequency-audit-20261008/sram-runtime-tests.log`.
This core is not yet exposed through the exclusive power-owner API. Runtime
VPROC/SRAM ordering, CPUFreq integration and hardware qualification remain
pending; normal packaging and installed M69 are unchanged.

## 2026-10-08: exclusive live SRAM provider API

Linux `4128daa6cd1d0` exposes `mt6797_sram_set_running_voltage()` to the
exclusive A72 power owner. The caller must hold CPU hotplug serialization and
coordinate VPROC and clocks. The provider requires CPU4/CPU8 online, its
completed startup record, an exclusive matching regulator/device, clear
isolation and two matching iDVFS control reads with firmware DVFS disabled.
It never calls PSCI AFFINITY_INFO on a running core. Verified success returns
the full new SRAM sample; uncertain transactions fence the provider. The
firmware setter now rejects every nonzero return, including unexpected
positive status, before considering readback.

Production-provider tests cover22 admission failures, ten I/O/status failures,
stale SRAM state, unchanged output on failure, sticky fencing and no live
PSCI calls. Existing startup/shutdown/restart regressions, all17 core cases /
2692 assertions and ARM64 regulator compilation pass. Evidence:
`handoff/a72-frequency-audit-20261008/sram-live-api-tests.log`.
The power owner still needs the coordinated VPROC/SRAM/clock transaction and
CPUFreq integration; this API has no runtime caller yet. No hardware trial or
normal packaging change was made.

## 2026-10-08: coordinated A72 rail planner

Linux `a1884ace568e9` adds a hardware-independent CPU/SRAM voltage planner.
It uses the DA9214 driver's10mV CPU grid, the SRAM25mV grid, CPU800–1200mV
and SRAM1000–1200mV. Vendor `set_cur_volt_extbuck()` requires SRAM at least
CPU voltage and no more than300mV above it; new gap-increasing writes keep
the vendor275mV intermediate margin. The target SRAM voltage is CPU+100mV,
rounded up and clamped to the SRAM range. Each step changes exactly one
rail; both rails move monotonically toward their endpoints. An inherited
valid300mV gap is admitted without forcing a reversal in the SRAM ramp.

The exhaustive matrix covers251 valid initial rail pairs times41 CPU targets
(10,291 plans), checking every intermediate grid, bound, delta, monotonicity
and endpoint. Invalid input leaves the output unchanged. All17 power-core
cases /206,589 assertions and ARM64 core compilation pass. Evidence:
`handoff/a72-frequency-audit-20261008/rail-plan-tests.log`.
This planner has no hardware effects. Settling/readback execution, sequencing
around clock changes, CPUFreq integration and hardware qualification remain
pending. Installed M69 and normal packaging remain unchanged.

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
