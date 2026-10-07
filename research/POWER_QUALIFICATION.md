# Power qualification

The hibernation watchdog fix is now integrated as an opt-in extension of the
qualified persistent-Nix kernel. Its normal-operation hardware trial
`handoff/power-kernel-01` passed with automatic recovery to healthy M69.
Hibernation, suspend/wake and deep idle remain separate unfinished work.

## Why the watchdog change is needed

M69's device freeze/thaw callbacks do not cover all hibernation image I/O:
`hibernation_snapshot()` thaws devices before `swsusp_write()`, and the restore
kernel calls `swsusp_read()` before its device freeze callbacks. The watchdog
can therefore run while userspace keepalives are frozen.

Maintained kernel commit `48ec0f99486e2dfd47bfca2b09f853014df9ef8d` pauses
hardware at `PM_HIBERNATION_PREPARE` and `PM_RESTORE_PREPARE`, keeps it paused
across device freeze/thaw, and restores the requested running state at POST.
It covers early aborts and failed image loads, serializes start/stop requests,
and leaves ordinary suspend's noirq sequence intact. The reviewed patch is
`patches/watchdog/0001-mtk-wdt-pause-for-hibernation-io.patch`, SHA-256
`96746fd50b138dd24eaa15a305e89308a0a469cc6d4a0cfda1c0979ff5c31d54`.

`nix/mainline-power-kernel.nix` applies that patch to the existing EFI/Nix
kernel before the A72 source manifest is captured. The kernel build manifest
identifies the underlying M69 Git source; the patch above is an additional
input, and the actual source digest includes it. Every hardware DT property
and memory reservation is retained; the selected kernel provenance is rebound.
The installed M69 bundle and the previous Nix/desktop candidates still evaluate
to their original store paths.

Hardware is deliberately paused during hibernation I/O. A hang there can need
physical recovery; normal boot qualification does not establish that this
interval works. The candidate keeps hibernation policy disabled.

## Host validation and pinned artifacts

```sh
nix build .#mainlineNixosPowerBundle .#watchdogHibernationCheck \
  --out-link ../handoff/power-kernel-linux
python3 tools/test-power-kernel.py
python3 tools/qualify-uboot-recovery.py --profile power-kernel --out NEW_DIRECTORY
```

The complete ARM64 build passed. The watchdog check runs 16 sequences using the
actual driver functions with fake MMIO, plus ARM64 object builds with and
without hibernation. The regression suite passed 115 tests. The power verifier
requires the running kernel's complete ELF notes to match the built kernel,
so an unchanged configuration cannot masquerade as the changed code. It also
checks an active, owned, 31-second nowayout watchdog, the inactive hibernation
policy and absence of swap. Read-only preflight passed at
`handoff/power-kernel-preflight-01`.

| Artifact | Identity |
|---|---|
| Bundle | `/nix/store/szbyps9vyq4kiign1yca3mykdwp56l32-gemini-mainline-nixos-bundle` |
| Kernel | `/nix/store/vh1pzynqvd9zb4axjapic1rvpsnvnlzk-gemini-mainline-power-kernel-7.1.3` |
| System | `/nix/store/5fdibxs9yf8yd64gdjvg2a1yan3hapb0-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade` |
| Padded p22 SHA-256 | `d2bb1ef41563db0bffaa64f5293f979aeae167b93ab85ea5db67c9fe7d1d1fbc` |
| Squashfs | 427,044,864 bytes; `2edc71a5165f84576d2ad8d913042d7b0e94f1b2ca911304a8c43f7d7f2096cf` |
| Kernel notes SHA-256 | `30f9f47bf3b5760c5d04ddd33347d75f555972dd700e42b4dbaef52a289f9552` |

Build, source and regression evidence is under
`handoff/power-kernel-qualification`. The older `handoff/power-candidate` build
used the same watchdog source change with the earlier userspace, and was
never flashed. It is not the new candidate above.

## Remaining hardware sequence

Normal boot, recovery and controlled Linux watchdog expiry now pass. Ordinary
suspend and failed-suspend paths remain to be exercised before image I/O.
Fixed-swap installation, automatic factory restoration and active swap
after an ordinary reboot now pass. Paging under pressure also passes with the
zswap shrinker enabled from boot in the successor candidate below.
See `STORAGE_QUALIFICATION.md`. The older power runner still expects factory
GPT and no swap; the separate power/swap profile handles the installed layout.
A72 offline/on and RTC power-on need validation.

A full hibernation proof must preserve a process and memory sentinel through
save, power-off and resume with the same kernel, then verify peripherals and
watchdog operation. A successful resume retains its original boot ID. The
fresh-boot rule used by the recovery runner cannot serve as hibernation proof.
Image I/O longer than 31 seconds and recoverable failures need explicit tests.
Only then can the 24-hour suspend-then-hibernate policy be qualified. Deep idle
remains a separate firmware/kernel task.

## Candidate device result

Candidate boot `a2702350-f97b-4e35-b2c7-896e99db02c4` passed the full Linux
health checks, both A72s, the exact kernel-notes check, ordinary Nix build and
LK memory/reservation preservation. The watchdog was active, nowayout, set to
31 seconds, and owned by the running takeover service. Hibernation stayed
disabled and no sleep request was issued. Published EFI files and their older
versions were retained. Automatic recovery restored healthy M69 boot
`6ccf152f-2d43-4a71-8695-beabcf62ff3e` with unchanged GPT/p22/p30/p31 hashes. The
whole normal-operation profile passed. A final audit held both flash locks,
verified all ten ordinary Nix outputs and their proof bytes, home GC roots and
database identities, then confirmed no writer remained. All eleven archived
qualification sources match the executed code. The candidate remains opt-in;
M69 is still installed, and the published EFI default is unchanged.

## Candidate with zswap writeback enabled

The first bounded swap pressure trial exposed a memory-cgroup OOM with M69's
zswap shrinker disabled. Linux 7.1 stores incompressible pages in its zswap
pool, so pressure-driven writeback needs separate validation; see
[STORAGE_QUALIFICATION.md](STORAGE_QUALIFICATION.md).
The runtime correction subsequently passed in `handoff/swap-io-03`: a 128 MiB
pattern survived real p34 writes/reads under a 64 MiB memory-cgroup limit,
with full health and retained data afterward. Cleanup restored the original
runtime setting. The later trial below separately qualifies the boot-time policy.

`mainlineNixosPowerSwapBundle` extends the watchdog-fixed power candidate with
`nix/mainline-swap.fragment`. The complete built configuration differs from
the previous power kernel only by enabling
`CONFIG_ZSWAP_SHRINKER_DEFAULT_ON=y`. The new fragment is recorded in the A72
provenance manifest and the device tree is rebound to the selected kernel.
The complete build and all sixteen real-driver watchdog PM sequences pass.
Earlier M69 and power bundle identities remain unchanged.

```sh
nix build .#mainlineNixosPowerSwapBundle --out-link ../handoff/power-swap-linux
```

| Artifact | Identity |
|---|---|
| Bundle | `/nix/store/mb5adwsfnri1jswcxhs6vl23hnj3jy5m-gemini-mainline-nixos-bundle` |
| Kernel | `/nix/store/b26xkc1n67c1xiz90fnzqg17w5dhvff3-gemini-mainline-power-swap-kernel-7.1.3` |
| System | `/nix/store/7vg1vqfn8v19px9k8bhcyi4yvndpszzb-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade` |
| Padded p22 SHA-256 | `fb8d164dfd9b658bb3c247fd7ec39106ed30ca4656c09d94a6c1efcc50a31f9a` |
| Squashfs | 427,048,960 bytes; `f52643cb9360a48ca4b9058d34d1aa579535ffdcae7386a8cbcdb955195605a7` |
| Kernel notes SHA-256 | `1bffbfeaa804fe8e0bd6735250ed38214b99b27efc86dca595b02d29940748b3` |

Build logs, the exact configuration diff and the artifact manifest are in
`handoff/power-swap-build`. This candidate has passed the device trial below,
but has not replaced installed M69. The old factory-only power runner cannot
qualify it; use the separate profile for its system, kernel and swap layout.

## Supervised boot with the fixed-swap layout

`tools/qualify-power-swap.py` provides a separate `power-swap` profile using
the existing boot-only writer and durable recovery supervisor. Its private
runner instance checks exact primary/backup GPT, swap header, p30/p31 and
flashinfo identities before admission and after both candidate and recovery
boots. The older factory-layout profiles retain their original behavior.

```sh
python3 tools/test-power-swap.py
python3 tools/qualify-power-swap.py --out NEW_DIRECTORY
```

The default is read-only preflight. `--execute` runs the bounded candidate
trial, additive installation of its matching userspace store and automatic
M69 recovery. The candidate must expose the pinned ELF notes and configuration,
active fixed swap, owned watchdog and enabled zswap shrinker. It runs the
128 MiB paging probe under the 64 MiB cgroup limit without any runtime policy
writes, then an ordinary unprivileged Nix build. Linux health, CPU provenance,
RAM/LK reservations, published EFI files and data retention are also required.
Sleep and hibernation remain disabled throughout this profile.

The final audit checks the original ten Nix outputs, outputs from earlier
power/swap trials and the new candidate's output. It waits for the existing
candidate/recovery services to terminate before checking M69 and releasing
ownership, then verifies all executed sources under both flash locks.
Seven profile tests cover storage and kernel identity, unchanged legacy
profiles, retained outputs and the absence of runtime policy writers. Ten
paging tests and three existing power-kernel tests also pass. Read-only
preflight passed in `handoff/power-swap-preflight-01`; host evidence is under
`handoff/power-swap-qualification`.

## Default-policy paging hardware result

Trial `handoff/power-swap-01` booted candidate
`f1ea8c93-9778-414a-adb7-e5f53c85d3a4` with the pinned kernel notes and actual
configuration. Its zswap shrinker was enabled from boot; the test performed
no runtime policy writes. All 134,217,728 pattern bytes survived under the
64 MiB memory limit and 256 MiB swap limit. Own VmSwap reached 131,080 KiB,
with 262,192 sectors read and 262,272 written on p34. Captured kernel
diagnostics had no OOM, I/O-error or kernel-fault matches. Full Linux health,
both A72s and their provenance, RAM/LK reservations, watchdog ownership,
published EFI files and an ordinary unprivileged Nix build passed.

Automatic mtkclient recovery returned healthy M69 boot
`707c2314-6c75-4cd7-bdb5-3daf94b41b18`, preserving fixed swap and the protected
storage identities. The legacy runner completed successfully, but the outer
worker then exited with an error when it redundantly stopped two already
collected transient host services (`systemctl` exit 5). The original result
is retained as `result-before-final-audit.json`. A recorded
`complete-audit.py` skipped only that redundant stop after independently
verifying both units inactive with no process, then completed the unchanged
final audit. It held both flash locks, repeated live health and all eleven
Nix-output retention checks, verified all twenty-four executed source hashes
and found no writer. See `audit-completion.json` and `final-idle-check.json`.

The runner now handles already terminal or concurrently collected units while
rejecting other stop failures and surviving processes. Four additional host
regressions pass; this cleanup revision was made after the recorded audit
and has not required another hardware trial. Archived trial sources retain
the executed version. The candidate remains opt-in, recovered M69 retains
`shrinker_enabled=N`, and sleep/hibernation were never requested.

## Linux watchdog expiry qualification

`tools/qualify-power-swap.py --watchdog-expiry` adds a controlled keepalive-loss
test after the complete normal candidate checks, paging and ordinary Nix
build. It keeps the same candidate kernel and exact fixed-swap storage guards.
The default remains read-only preflight; hardware execution needs `--execute`.

The trigger independently checks the running kernel, boot identity, service
MainPID, process start time, watchdog descriptor, active 31-second nowayout
configuration and at least 120 seconds remaining on the recovery lease. After
sync, it rechecks ownership, sends SIGSTOP and records the stopped process.
The open watchdog descriptor remains owned. A separate target service waits
55 seconds before resuming the exact owner and requesting a software reboot
if hardware expiry fails. Its stop callback also resumes that owner after an
interrupted test; it cannot signal a different boot or reused PID.

The host accepts only a preloader appearance within 20–45 seconds of the
trigger request, with acknowledgement within eight seconds. The ten-second
keepalive interval means expiry can occur before a full 31 seconds has passed
since SIGSTOP. An independent USB record from the successful rescue writer
must agree within two seconds, and any host-requested rescue reboot rejects
the expiry claim. Complete M69 recovery, fixed-swap identities, all retained
Nix outputs and source hashes remain required. This test does not request
suspend or hibernation.

Eight watchdog tests exercise the actual generated shell guards with fake
signals/reboots, bounded fallback ordering, stale ownership, reset timing,
independent USB evidence and ordering after complete candidate checks. The
eleven power/swap tests also pass. Evidence is retained under
`handoff/linux-watchdog-qualification`.

Trial `handoff/power-swap-02` passed this profile. Candidate boot
`fd151c7a-2e7f-4a13-8c0e-80380c996772` first passed full Linux health,
default-policy paging, CPU/RAM checks and its ordinary Nix build. Watchdog
owner PID 549 was identified by start time and open descriptor, then observed
in state `T` after SIGSTOP. The host received that acknowledgement within
0.742 seconds. Its USB observer measured preloader return at 25.337 seconds;
the independent rescue backend measured 25.349 seconds. Their observations
differ by 12 milliseconds. No software rescue reboot was requested, and both
observations precede the 55-second target fallback.

The rescue writer verified the M69 image and rebooted automatically. Healthy
M69 boot `84c89631-45ff-4cd3-bc9f-821658785a18` retained the exact fixed-swap
layout, original persistence/EFI proofs and all twelve ordinary Nix outputs.
The final audit acquired both flash locks, verified all twenty-five executed
source hashes and found no writer. All five host services terminated
successfully, including the corrected cleanup path; no manual audit completion
was needed. The new build output is
`/nix/store/hfzgdmlvkq5kahmj4ap80r27y9q72y9s-gemini-daemon-ac814b8bd7a14fb6bfcd30718b59ff83`.
Future power/swap trials retain it automatically. See `watchdog-trigger.json`,
`watchdog-observation.json`, `watchdog-result.json` and `final-idle-check.json`.

The next diagnostic stages reviewed were `pm_test=freezer` and `pm_test=devices`.
Source inspection of the selected derivation confirms that both return
before `suspend_enter()` reaches device noirq callbacks; the watchdog stops
only in its noirq callback, and its hibernation notifier ignores ordinary
suspend notifications. Thus these stages retain watchdog coverage. The
default diagnostic delay is five seconds. Exact source hashes and derivation
identity are retained in `linux-watchdog-qualification/pm-stage-source-audit.json`.
This is preparation evidence, not a successful suspend test. Full s2idle and
hibernation still enter intervals where the hardware watchdog is paused.

## Bounded freezer and device diagnostics

```sh
python3 tools/test-pm-stages.py
python3 tools/qualify-power-swap.py --pm-test devices --out NEW_DIRECTORY
```

This is read-only preflight unless `--execute` is supplied. The runner requires
the selected kernel's prior successful watchdog-expiry/recovery evidence and
the reviewed PM source identities. `--pm-test devices` runs freezer first,
then devices; `--pm-test freezer` stops after the first diagnostic. Later
noirq test stages are not accepted by this profile.

Each stage uses a bounded target service, exact boot/kernel/watchdog-owner
guards, at least 120 seconds remaining on the recovery lease and an exclusive
PM-test lock. It selects the stage, writes `freeze` to `/sys/power/state`, and
requires a 4.5–20-second elapsed interval, one new successful suspend count,
no new failure counters and matching kernel entry/debug-delay/exit messages.
The test and its stop callback restore `pm_test=none` only for the same boot
and owned lock. Afterward, the same watchdog owner must remain active, a fresh
Panfrost render must verify all 8,192 pixels, and full candidate health and
protected storage must match the pre-test observation. The device stage is
skipped if any freezer requirement fails. Automatic M69 recovery and complete
data/source retention checks still conclude the trial.

Nine host tests exercise the generated shell guards, both stage selections,
failure cleanup, stale boot/lock ownership, counters, timing, kernel-message
validation and stage ordering. A fresh GPU render on accepted M69 also passes.
Evidence is under `handoff/pm-stages-qualification`. This prepares diagnostic
execution; it does not establish full suspend, wake or hibernation.

The first fresh-render command failed before running the GPU program because
the SSH environment supplies BusyBox `timeout`, which rejects GNU long
options. The corrected portable `timeout -s TERM -k 3` command passed on the
device and is used by the diagnostic runner. Both observations are retained
in `pm-stages-qualification/gpu-baseline` and `gpu-baseline-02`. All nine PM,
eleven power/swap and eight watchdog host tests pass.

## First PM diagnostic device result

Trial `handoff/power-swap-03` booted candidate
`b2513f24-327e-424b-96c7-95518a14f506` and passed its normal Linux, kernel,
paging and ordinary Nix-build checks. Freezer then passed with a 5.2-second
interval, success count 0 → 1, no failure-counter changes, restored
`pm_test=none`, the same watchdog owner (PID 556, start time 7828), verified
fresh rendering of all 8,192 pixels and unchanged candidate health/storage.
Its separate evidence is `pm-freezer/result.json` and the associated raw
service, kernel and GPU observations.

The device stage did not pass. Its `/sys/power/state` write returned `EBUSY`;
the kernel attributed the failure to `mtu3 11271000.usb`, whose suspend
callback returned -16. The kernel unwound the attempted suspend and returned
to userspace. The selected source's `ssusb_gadget_suspend()` explicitly returns
`-EBUSY` while `mtu->connected` is true. The USB recovery network was still
connected. This matches `nixos/power-policy.nix`, which intentionally inhibits
normal sleep with an attached USB host. The verifier rejected the incomplete
stage output; it did not turn the abort into a successful diagnostic.
Scoped failure evidence is `pm-devices/failure-summary.json`.

The identified candidate was rebooted into the existing rescue writer, which
restored healthy M69 boot `c5520087-490c-4dc8-bb69-720870cae7b6`. The final audit
held both flash locks, verified the exact fixed-swap layout and all thirteen
ordinary build outputs, matched twenty-six executed sources and found no
writer. All host trial units are inactive. The worker correctly exited with
failure after recording recovery; `result.json` and `pm-result.json` retain
the unqualified combined profile. The thirteenth retained build output is
`/nix/store/hwmrxk99ypmllmyifdv1r8zdnj8sz1d8-gemini-daemon-6a5178fef56b405c96a11fe127957fde`.

Before retrying the device stage, add and qualify a target-side guard which
holds an independent logind sleep inhibitor, disconnects the exact MTU3 gadget,
restores its connection/address, and requests bounded recovery if the host
cannot confirm return. The inhibitor must cover the disconnected interval:
otherwise removing USB can release the existing lid daemon's sleep condition.
The kernel's connected-gadget veto and the normal USB sleep policy remain
appropriate. Full suspend/wake and hibernation are still unqualified.

## Guarded software USB cycle

```sh
python3 tools/test-usb-cycle.py
python3 tools/qualify-power-swap.py --usb-cycle --out NEW_DIRECTORY
```

This profile is read-only unless `--execute` is supplied. It uses the same
power/swap candidate, complete normal checks, paging and ordinary Nix build.
It does not request sleep or change the kernel's connected-gadget veto.

Three separate target services provide the sleep inhibitor, USB action and
recovery deadline. The logind inhibitor's name, reason, mode, UID and PID
must match the running guard; its PID/start time are rechecked by the action.
The action verifies the exact kernel/boot, watchdog ownership and descriptor,
normal PM selection, connected MTU3 gadget and remaining diagnostic window.
It disconnects via the UDC's `soft_connect`, waits five seconds, reconnects,
restores usb0's address/link and requires the gadget to become configured.
Its stop callback reconnects only within the same boot and owned lock.

The 30-second action cannot stop the independent sleep inhibitor. A separate
120-second deadline requests reboot without waiting on the USB driver. If
the same candidate remains alive, it rechecks the exact watchdog owner/start
time/open descriptor and stops that keepalive process to force expiry. The
ordinary boot lease is not sufficient here: successful acceptance disables
its deadline. The independent inhibitor remains held for up to 900 seconds,
well beyond the reboot/watchdog fallback. No manual cable action is required.

Host qualification requires a real USB departure and a new enumeration,
same-boot SSH return, unchanged suspend counters and watchdog ownership,
candidate health/protected-storage checks, and logind evidence of both the
diagnostic inhibitor and the restored normal USB inhibitor. Only then does
the host acknowledge the cycle and stop all three target services. Automatic
M69 recovery and the complete locked data/source audit still conclude the
trial. The inhibitor mechanism was separately exercised on M69 and removed;
evidence and selected USB-source hashes are in `usb-cycle-qualification`.

The first trial, `handoff/power-swap-04`, observed USB re-enumeration after
5.619 seconds, but its host verifier incorrectly treated the staged program
named `fallback` as an execution marker with that same name. The trial remains
failed; complete target/inhibitor evidence was not captured before rescue.
The collision has a failing-then-passing generated-shell regression. The
timer program is now named `deadline`, and target stdout/stderr are retained
even when the completion check fails. All 38 USB, PM, power/swap and watchdog
host tests pass. The corrected hardware retry uses a new trial directory.

Trial 04 automatically restored healthy M69 boot
`95b96efd-58c9-48e2-8562-9d22ae0e141f`. Its final audit retained all fourteen
ordinary builds, matched twenty-seven executed sources and found no writer.
The new retained build is
`/nix/store/84xnmrljyk1srrz23w5cyfs61k89p75f-gemini-daemon-b053710af0584bac832ddcfd6fafa198`.
See its `usb-cycle/host-verifier-collision.json`, `host-usb-events.json`,
`result.json` and `final-idle-check.json`. This trial does not qualify suspend.

The corrected cycle passed on candidate boot
`2c737ee8-d164-492f-b53e-9c58db9eeac3` in `handoff/power-swap-05`.
The host measured 5.622 seconds without the gadget; the target's complete
disconnect/reconnect interval was 5.89 seconds. Both suspend counters remained
zero, `pm_test` remained none, and the watchdog owner remained PID 551 with
start time 7753. Logind showed diagnostic inhibitor PID 5191 before, during
and after the outage. The ordinary USB inhibitor (PID 570) disappeared during
detachment and returned afterward, proving the independent guard was needed.
The action exited successfully within its 30-second service bound, and
same-boot SSH, candidate services and protected storage passed before the
host acknowledged and stopped all three target services. The 120-second
fallback did not run. See `usb-cycle/result.json`, the three inhibitor
observations, `host-usb-events.json` and `acknowledge.sh`/stdout/stderr.

Automatic rescue restored healthy M69 boot
`1ba6746e-40e6-496d-be87-4e75ceba076f`, retaining all fifteen ordinary build
outputs and the original persistence/EFI proofs on the exact fixed-swap
layout. The final audit acquired both flash locks, matched all twenty-seven
executed sources and found no writer. All host trial services are terminal;
the worker exited successfully. The new build output is
`/nix/store/g9z1dbmjhhdgrci3l0fy37fjsb16kgni-gemini-daemon-0b5f176462bb4f849b870a6f075f7104`.
The final `result.json` qualifies the USB cycle; `final-idle-check.json` records
the complete recovery/data audit. The next step is to reuse this guard for
device-stage diagnostics. Full suspend/wake and hibernation remain unqualified.

## Device diagnostics with USB disconnected

`--pm-test devices` now runs the freezer diagnostic and full post-freezer
health check, then runs the device diagnostic inside the qualified USB guard.
Admission requires the exact candidate's retained watchdog and guarded USB
results, including the archived executed sources. The standalone `--usb-cycle`
profile continues to request no sleep.

The device script executes locally as a child of the bounded 30-second USB
action while the gadget is disconnected. It retains the existing boot/kernel,
watchdog descriptor/owner, PM selection, five-second delay and recovery-window
checks. Its cleanup resets its own PM selection before USB reconnection. A
child failure is recorded and USB reconnection still runs; a failed PM cleanup
also permits a reconnection attempt without qualifying the test. The independent
sleep inhibitor and 120-second reboot/watchdog fallback cover the whole action.
Both action and child diagnostics are captured when SSH returns, including an
incomplete parent's failure output.

Qualification requires the expected single new successful suspend diagnostic,
all failure counters unchanged, scoped kernel entry/delay/exit markers, the
same watchdog owner, a real host-observed USB outage/new enumeration, restored
normal USB inhibition, cleared PM/USB locks, fresh GPU rendering and full
candidate health. The final profile also requires automatic M69 recovery and
the complete storage/data/source audit. It does not exercise noirq callbacks,
full suspend/wake or hibernation.

All 42 host tests pass, including the actual generated USB and PM programs
executed together with simulated hardware: successful order, failed-child
reconnection, stop cleanup, foreign-lock preservation and incomplete-parent
diagnostic capture. Read-only preflight passed in
`handoff/pm-detached-preflight-01`; source/test hashes are in
`handoff/pm-detached-qualification/host-tests.json`.

Candidate boot `ddf45458-0a52-40fd-8af6-7f9900972e34` passed both stages in
`handoff/power-swap-06`. Freezer took 5.25 seconds and device diagnostics took
6.55 seconds. The success counter advanced 0 → 1 → 2, while every failure
counter stayed zero. Each stage restored `pm_test=none`, retained watchdog
owner PID 555/start time 7799 and passed a fresh 8,192-pixel Panfrost render.
Candidate service health and protected-storage identities matched afterward.

During the device stage, the host observed a 7.880-second USB outage and a
new enumeration; the target's complete interval was 8.29 seconds. Logind
retained diagnostic inhibitor PID 5591 throughout, while the normal USB
inhibitor PID 578 disappeared and returned. The parent service completed
within its 30-second bound, both diagnostic locks were removed, and the
fallback did not run. Evidence is in `pm-stages.json`, `pm-freezer/`,
`usb-pm-devices/` and `pm-devices/`. These results cover device suspend/resume
callbacks before late/noirq; wake-source delivery and later PM stages still
need separate qualification.

Automatic recovery restored healthy M69 boot
`f5c4018e-0cc1-4dda-9fd2-043e6adf258f`. The final audit held both flash locks,
preserved the exact fixed-swap layout and original home/EFI proofs, retained
all sixteen ordinary Nix outputs and matched all twenty-seven current and
archived executed-source hashes. The final result qualifies both PM stages;
all five host units are inactive with PID zero, and the durable worker exited
successfully. See `result.json`, `final-idle-check.json` and
`terminal-verification.json`. The sixteenth retained output is
`/nix/store/lagdvw19i80rxhs33dznk92smj714r48-gemini-daemon-8d07305cb1974c06a2767f3168dd878b`.
The candidate remains opt-in; M69 remains installed with its original policy.

## RTC alarm delivery and cancellation

The awake RTC checks found a hardware cancellation defect on installed M69.
`handoff/rtc-alarm-delivery-01` armed a ten-second alarm using the RTC's own
clock: interrupt count advanced 0 → 1, the software alarm cleared, and the
same boot/watchdog/health checks passed. In `rtc-alarm-cancel-01`, the alarm
was cancelled eight seconds before its deadline, yet interrupt count still
advanced 1 → 2. The software queue was empty. Neither test requested sleep,
set the clock, disconnected USB or changed storage; the bounded target
services stopped and M69 remained healthy.

The selected `rtc-mt6397` driver provides `set_alarm` but lacks
`alarm_irq_enable`. `rtc_timer_remove()` clears the software queue and uses
that missing callback to disable the hardware source. It does not call the
driver's disabled `set_alarm` branch. The same missing callback also makes
the legacy `RTC_AIE_ON/OFF` ioctls return `EINVAL`; BusyBox 1.36.1's short
`rtcwake` path uses those ioctls. The observed cancellation interrupt is an
independent hardware check of this source finding.

Kernel commit `2b142e490c34d` adds the callback, updates only the one-shot
alarm-enable bits under the existing RTC register lock, latches the write
through WRTGR and propagates update/trigger/poll failures. The patch is
`patches/rtc/0001-mt6397-alarm-irq-enable.patch`. Its host check executes the
actual callback and write-trigger functions with distinct pending/latched
register state: 16 enable/disable, repeat and error sequences pass. A real
ARM64 driver-object build and the complete opt-in power/RTC bundle pass.
The complete kernel configuration matches the qualified power/swap kernel;
RTC time-setting policy is unchanged. Build evidence is in `power-rtc-build`.

```sh
python3 tools/qualify-rtc-alarm.py --mode delivery --out NEW_DIRECTORY
python3 tools/qualify-power-rtc.py --out NEW_DIRECTORY
```

Both default to read-only preflight; `--execute` is required for their device
actions. The first runs an awake alarm check on M69, with `--mode cancel`
selecting cancellation. The second uses the corrected pinned kernel, the
fixed-swap boot-only writer and automatic M69 recovery. It repeats normal
health/paging/ordinary-build checks, then alarm delivery, cancellation and
delivery again. Every alarm stage requires the same boot/kernel/watchdog,
unchanged suspend counters and full service/storage health afterward.
Both power profiles retain ordinary builds from all numbered power/swap and
power/RTC trials. The existing PM stages are not enabled on this new kernel
until their prerequisites are qualified again. All 51 host runner tests pass.

RTC readback on M69 is in 2069 while NTP corrects the system clock to 2026.
`CONFIG_RTC_SYSTOHC` is explicitly disabled in the current configuration.
The diagnostic uses RTC-relative deadlines, so the clock mismatch does not
invalidate its interrupt evidence. Correct UTC initialization and persistence
still need qualification. Awake alarm delivery does not prove wake from
suspend or power-on from an off state.

The calendar source audit found an additional compatibility issue: the
vendor MT6351 driver treats the year register as an offset from 1968, while
the current mainline driver treats it as an offset from 1900 and applies
the RTC core's range extension. A vendor default of 2010-01-01 (raw year 42)
therefore becomes 2069-12-31 in mainline, matching observed readback. This
is recorded in `power-rtc-build/calendar-source-audit.json`. Correct and
validate the MT6351 calendar conversion against firmware conventions before
enabling automatic RTC updates; simply enabling SYSTOHC is insufficient.

Candidate `08870804-1ab7-4e41-bb45-e62daa055a5b` passed delivery, cancellation
and delivery again in `power-rtc-01`. The observed interrupt deltas were
1, 0 and 1 over 13.15, 13.18 and 13.15 seconds. Each alarm was scheduled ten
seconds ahead; cancellation occurred eight seconds before its deadline.
The same kernel/boot/watchdog owner, normal service health and protected
storage passed after each stage. The software alarm was empty, the diagnostic
lock removed and the bounded service stopped after every check. Suspend
counters stayed unchanged. This qualifies the cancellation correction and
rearming while awake; it does not qualify suspend/wake or RTC power-on.

Automatic recovery restored healthy M69 boot
`3a618486-e533-4f69-84b8-b6ea0439e7bb`. The final audit held both flash locks,
retained all seventeen ordinary build outputs and the original home/EFI
proofs, preserved the exact fixed-swap layout, matched all twenty-nine
current/archived executed sources and found no writer. All five host units
are inactive with PID zero, and the worker exited successfully. The complete
result and terminal audit are `power-rtc-01/result.json`,
`final-idle-check.json` and `terminal-verification.json`. Its new output is
`/nix/store/sblsi0r6jkqdxkximn94bljn1r08rmb4-gemini-daemon-7cf9376829654d22ac8c6fc7f9bb624f`.
The RTC correction remains opt-in; installed M69 still has the original
cancellation defect. Its ordinary clock and sleep policies were not changed.

| RTC candidate artifact | Identity |
|---|---|
| Bundle | `/nix/store/7bh3lx2npyddffbyn41bcgrzaambv0qi-gemini-mainline-nixos-bundle` |
| Kernel | `/nix/store/5nghlvadfma5lkqm7zcq1apiairg2i9y-gemini-mainline-power-rtc-kernel-7.1.3` |
| System | `/nix/store/5ang3jm5vv0nz4aq0m89z2624vbg159p-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade` |
| p22 SHA-256 | `18d709f77e7f25630491418b159896c5618160349f4f342ad08c52fc4170f7f3` |
| Kernel notes SHA-256 | `af7979b3d4dee258d896645fead8c4e72356d9b305871c0992b6ce1ead8c5ddf` |
| Squashfs | 427,040,768 bytes; `4bfae12544e2d4d885a1a11552ebc27ab0e24d945498d4a44317f497a3316ae5` |

## MT6351 firmware calendar compatibility

The separate `mainlineNixosPowerRtcCalendarBundle` applies kernel commit
`827742e655b8f476bb8087b0f50eb836ac3eb5a9` after the qualified alarm callback.
Only MT6351 uses the firmware's 1968 year origin. Both clock and alarm
callbacks add/subtract the 68-year offset, and the driver describes the
native 1968–2095 hardware range without RTC-core rotation. Other supported
PMICs keep their previous encoding and range extension. Linux's normal
calendar validation still governs which dates applications may set.

`rtcCalendarCheck` compiles the actual ARM64 RTC driver and exercises its
real time/alarm callbacks against latched fake registers. All 140,254 valid
hardware dates across the three chip-data variants round-trip, including
leap days, alarm metadata preservation, RTC-core offsets and range limits.
The sixteen alarm register/error sequences also pass. The full bundle builds,
the kernel configuration is unchanged, and the older power/swap and alarm-only
bundle identities are unchanged. All 59 host runner tests pass. Build evidence
is in `handoff/power-rtc-calendar-build`, with the build log alongside it.

```sh
python3 tools/qualify-power-rtc-calendar.py --out NEW_DIRECTORY
```

Default preflight is read-only. `--execute` uses the existing fixed-swap
candidate/automatic-recovery runner. After normal boot, paging and an ordinary
Nix build, a bounded target service checks its kernel, boot, watchdog owner,
empty alarm and host UTC before writing the clock through `hwclock -w -u`.
Readback and ticking must agree with independently sampled host UTC. The
service is stopped and full same-boot health checked before running alarm
delivery, cancellation and delivery again. Periodic kernel RTC updates remain off;
no suspend is requested. The pre-existing NixOS shutdown clock-save unit
remains enabled (see the policy correction below). Calendar trials join the retained ordinary-output
inventory alongside previous power/swap and alarm trials.

After automatic M69 recovery and the complete storage/source audit, the
runner reads the RTC with both flash locks held. M69 still has the old epoch,
so it explicitly reverses the RTC-core rotation and applies the firmware year
origin to that readout. The resulting UTC must match the host. This proves
retention through that recovery path; it does not claim M69 now reports a
correct native date or that the corrected kernel has booted from the new date.
A failed retention check marks the overall profile failed even if the earlier
clock write and storage recovery succeeded.

The first calendar trial (`power-rtc-calendar-01`) booted the expected kernel
and read 2010-01-01, matching the vendor calendar. It stopped in Stage 1 before
uploading userspace or writing the RTC: p29 contained 104 cached test images,
with 173,860 KiB available against the upload guard's 418,056 KiB requirement.
The original rescue discriminator required `/run/current-system`, so it did
not recognize a candidate still in Stage 1. Its 660-second rescue scan window
also preceded the 720-second Stage 1 watchdog lease plus reset latency.
A separate host command checked the exact candidate boot/kernel/p22/GPT,
requested a read-only remount and rebooted into the existing rescue writer.
SSH observation timed out; the supervisor independently verified rescue
write/readback and reboot. This is a failed trial with host intervention,
not a qualified automatic failure path. M69 boot
`3213b6e1-e46f-4386-a1b1-f8566deb5c4c` passed the final audit: seventeen outputs,
31 current/archived executed sources, both locks and no writer. All five host
units stopped. Supplemental request evidence is `stage1-rescue.json`.

The revised calendar runner checks capacity before boot. If necessary it
archives only the preceding opt-in RTC userspace image on the host, verifies
all bytes and confirms it is absent from active loop devices and installed
Gemini initrds/loader entries. Its original Nix bundle is retained too.
Removal of that device cache copy occurs inside the existing, identified
Stage 1 provisioning transaction, after its writable/journalled mount guards.
No active read-only/noload mount is made writable. The archived image remains
available for restoration; accepted boot images, EFI payloads and ordinary
Nix outputs stay covered by their existing audits. Broad cache consolidation
is still pending.

The calendar profile now also recognizes its exact Stage 1 kernel/p22/GPT and
store request. With the original owner, network service and rescue scanner
still active, it can restore the mount read-only and request reboot. SSH output
is retained even when the rebooted connection times out; a verified request
is separate from the supervisor's actual reset/recovery proof. It does not
create a second writer. Eight further tests cover archival/capacity, guard
ordering, altered archives, Stage 1 identity and timed-out SSH observations;
all 67 host runner tests pass. This recovery extension still needs its own
end-to-end failure-path qualification.

Trial `power-rtc-calendar-02` exposed a separate USB sysfs race. mtkclient
returned zero and its 16 MiB readback matched the candidate, but the host
observer raised `ENODEV` while a USB attribute disappeared during reboot.
The trial correctly remained failed. Because the outer runner skipped Linux
rescue identification after a failed writer observation, the new Stage 1
helper was invoked explicitly against the already-owned trial. Its retained
identity/read-only-mount marker passed, and the existing supervisor restored
M69 boot `6ec8f8f8-6127-4f31-80d7-1025d5af0a3f`. The final audit retained all
seventeen outputs, matched 33 executed sources, acquired both locks and found
no writer; all five units stopped. Neither cache pruning nor the explicit
calendar write was reached.

The USB observer now treats `ENOENT` and `ENODEV` as an incomplete snapshot
while the port directory still exists; only observed directory absence means
departure. Other I/O errors remain fatal, and the existing DA acknowledgement,
first-preloader ordering and complete image/GPT readback requirements remain.
Linux rescue identification now also runs after a writer observation failure,
with up to 150 seconds for the exact candidate to expose SSH. It stops if the
supervisor has already restored M69. Regression tests reproduce both defects
before correction and pass afterward, including the actual mocked trial flow.
All 98 relevant host tests pass; logs are retained in the calendar build folder.

RTC policy correction: `CONFIG_RTC_SYSTOHC` disables periodic kernel RTC
updates, but does not disable NixOS's `save-hwclock.service`. Both installed
M69 and the calendar candidate enable that unit through
`shutdown.target.wants`; it runs `hwclock --systohc --utc` when `/dev/rtc`
exists. The candidate's enabled unit and `/dev/rtc -> rtc0` alias were observed
on hardware. Source and runtime evidence are
`power-rtc-calendar-build/shutdown-clock-source-audit.json` and
`power-rtc-calendar-03/rtc-shutdown-policy.stdout`. The original calendar
helper's broad `automatic_rtc_updates=false` field must therefore be read as
“periodic kernel updates disabled” only; the trial retains an explicit
`rtc-clock-policy-correction.json` alongside the original results.

Shutdown clock writes use the corrected encoding on this candidate and the
old encoding on recovered M69. Thus preservation through candidate shutdown
and M69 startup does not establish preservation through another M69 shutdown.
Corrected-kernel startup from retained UTC and consolidation of the shutdown
policy remain separate work. The firmware's handling of the year written by
legacy M69 also needs evidence; a missing SYSTOHC option alone cannot explain
or rule out RTC writes.

Trial `power-rtc-calendar-03` passed native UTC write/read/ticking on candidate
`fe63c100-2a12-4723-9e5f-adb88d0718e1`. The clock advanced from the firmware's
2010 default to 2026-10-07 01:51:25 UTC, agreed with the independent host clock,
and ticked normally. Alarm delivery, cancellation and rearming then passed
with interrupt deltas 1, 0 and 1. Normal candidate health, real swap traffic
and an ordinary Nix build also passed. The exact preceding RTC userspace
cache was archived and verified before its device copy was removed; the
calendar userspace was installed successfully.

Automatic recovery restored healthy M69 boot
`9c33eada-e721-43f7-bba0-8651ee17c9b0`. The final locked audit retained all
eighteen ordinary outputs, matched 33 executed sources and found no writer;
all five host units stopped. However, the final RTC read decoded back to
2010-01-01, so the overall calendar profile correctly failed retention.
An intermediate legacy runner's PASS line is not the complete result: use
the wrapper's final `result.json` and `rtc-calendar-result.json`. The original
clock-policy field is corrected in `result-annotated.json`, with the original
result retained and explicitly referenced.

The download-agent reboot packet previously set `dont_resetrtc=0`, explicitly
requesting an RTC reset. The new opt-in `mtkclientRtc` package adds
`reset --bootmode reboot --preserve-rtc`; the calendar profile selects its
exact store path for both candidate and rescue DA exits. Other profiles keep
their original package and reset behavior. This option sets the existing RTC
word in the MT6797's seven-word packet, preserves mode and acknowledgement
handling, and rejects unsupported DA protocols before sending a command.
All 36 package tests and 99 host runner tests pass. Hardware retention with
this option is recorded separately below.

### Complete calendar and preservation trial

`power-rtc-calendar-04` passed on candidate
`41fde88d-db2c-458a-8bb5-49e6a830c51c`. Both candidate and rescue DA commands
used the pinned RTC-preserving package. The previously installed calendar
userspace was reused, with no further cache removal. Full normal health,
real paging and an ordinary unprivileged Nix build passed. Native UTC was
written/read as 2026-10-07 02:14:35, ticked normally and agreed with host UTC.
Alarm delivery/cancellation/rearm produced interrupt deltas 1, 0 and 1 over
13.14, 13.18 and 13.16 seconds; cleanup, unchanged watchdog ownership and
same-boot health passed after every stage. No suspend was requested.

Automatic recovery restored M69 boot
`e402eccb-143e-49cb-afb6-d8a3fc5a7b49`. Its old RTC encoding read epoch
3684709197; explicit legacy decoding yields 1791339597, or
2026-10-07 02:19:57 UTC. The independent host observation was
1791339597.574–1791339597.918. Thus the correctly encoded clock survived the
candidate shutdown, download-agent rescue and M69 startup. The final wrapper
result is passed, its worker exited zero and all five host units are inactive
with PID zero. The final audit held both flash locks, retained nineteen
ordinary outputs and original home/EFI proofs, matched 33 current/archived
executed sources, preserved the fixed-swap layout and found no writer.
See `result.json`, `rtc-calendar-reboot.json`, `final-idle-check.json` and
`terminal-verification.json` in that trial's handoff directory.

The first candidate RTC read was 2094-10-07, exactly the extra 68 years
expected from M69's existing shutdown clock-save encoding. This is further
evidence that DA preservation does not repair legacy Linux clock writes.
M69 still reports an incorrect native date; the final UTC check explicitly
decodes it. Next, qualify corrected-kernel startup from retained UTC while
controlling the identified legacy shutdown writer, then consolidate the
correct kernel and clock policy. Repeat watchdog/PM prerequisites on this
kernel before advancing sleep tests. Awake alarm delivery and reboot clock
retention do not prove suspend wake or RTC power-on.

| Calendar candidate artifact | Identity |
|---|---|
| Bundle | `/nix/store/h06d3dmfs3j0kdy19j61x8aghcxp8qqr-gemini-mainline-nixos-bundle` |
| Kernel | `/nix/store/x7pps048pisms3b1xpmfpa8khfmndkyq-gemini-mainline-power-rtc-calendar-kernel-7.1.3` |
| System | `/nix/store/8zl369z86ddcqwybwi4b700afxw0n4xq-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade` |
| p22 SHA-256 | `92528b092a5ef5caab863c353978da9866046db5d37ebcba824b070b3fd93a79` |
| Kernel notes SHA-256 | `0de66a120a0d13afcd3f6177cd260daa1426b6d38dc6b738fc1316ae4260eb10` |
| Squashfs | 427,040,768 bytes; `5377cc00ba1f7eb87d38ba552787362df1f5308daa3dbc0aaf14753785aa8938` |

### Native RTC startup qualification

`tools/qualify-power-rtc-startup.py` reuses the calendar candidate and pinned
RTC-preserving mtkclient package. Its read-only preflight requires an already
retained, firmware-decoded RTC value matching host UTC, unchanged healthy M69,
the exact enabled shutdown unit and no existing runtime clock-policy drop-in.
It retains the complete existing storage and ordinary-build inventory.

Only after the original transaction owner, candidate writer, supervisor and
network service are active does execution install a temporary systemd
`ConditionPathExists` drop-in under `/run`. Its unique condition path is absent,
so the incompatible legacy shutdown writer is skipped. The real unit is
started to verify the failed condition, zero command PID/start timestamp and
continued RTC agreement with the host before requesting the existing reboot.
No RTC register or persistent service policy is written by this helper.
Setup errors remove the owned drop-in; final cleanup checks the original
policy on recovered M69, or removes the exact owned file if the initial boot
never changed. The runtime drop-in disappears across reboot.

After normal candidate health, paging and an ordinary build, but before the
calendar helper's explicit `hwclock` write, the new check requires native RTC
and system UTC to match the host. It also requires `rtc0/hctosys=1` and a unique
kernel RTC initialization message whose date, epoch and monotonic timestamp
agree with that retained value and current uptime. The candidate shutdown
writer must still be unexecuted. This distinguishes correct startup from
NTP correcting the system clock after an incorrectly decoded RTC. The full
UTC write/read, alarm sequence, automatic recovery and final locked data/source
audit follow. A failed startup or policy-cleanup check fails the whole profile.

All 40 relevant host tests pass, including nine new tests for stale or
misencoded RTC values, missing/duplicate kernel initialization evidence,
uptime/time disagreement, runtime policy guard ordering, source-profile
isolation, recovery after missing startup proof and cleanup failures. The
actual generated cleanup shell is also exercised against an isolated
filesystem: it removes the exact owned policy on the original boot, preserves
foreign contents and refuses to remove a stale file from a different boot.
The read-only preflight passed in `power-rtc-startup-preflight-01`.

The complete hardware trial `power-rtc-startup-01` passed on candidate
`fb08f986-7fdf-42c4-977b-9e79773b8caa`. The real legacy shutdown unit's condition
was observed false, its command stayed unexecuted, and decoded RTC still
matched UTC immediately before the initial reboot. The corrected kernel
initialized the system clock to 2026-10-07 02:30:08 UTC at boot time 1.339061 s.
At uptime 218.27 s, native RTC epoch 1791340425 matched the independent host
observation 1791340424.980–1791340425.498. This evidence precedes the calendar
write at epoch 1791340427; readback/ticking and all three awake alarm stages
then passed (IRQ deltas 1/0/1 over 13.14/13.17/13.14 s).

Automatic recovery restored healthy M69 boot
`fd1a8110-b44a-4c43-b0e7-7abee14a53ea`. The firmware-decoded RTC was 1791340747,
matching host UTC again. The runtime drop-in was absent and the exact original
enabled shutdown unit was restored. The final audit acquired both locks,
retained all twenty ordinary build outputs and original home/EFI proofs,
matched 35 current/archived executed sources, preserved protected storage and
found no writer. The worker exited zero; all five host units are inactive with
PID zero. The final `result.json`, `rtc-startup-result.json`,
`rtc-calendar-reboot.json`, `final-idle-check.json` and
`terminal-verification.json` contain the complete result. This qualifies the
corrected native startup path and temporary legacy transition; canonical
kernel/clock-policy promotion remains separate.

For subsequent sleep work, the selected source confirms that the RTC driver
enables its child wake IRQ, the PMIC parent installs the wake mask and enables
its upstream IRQ, and the watchdog stops in `suspend_noirq`. The `platform`
PM test reaches that no-IRQ boundary; it is supported for s2idle. The `processors`
and `core` PM tests are explicitly rejected for s2idle. These source facts do
not qualify the physical wake path. Repeat the relevant watchdog/USB/PM
prerequisites on the selected kernel and establish bounded recovery through
no-IRQ before unattended full suspend/wake trials.
