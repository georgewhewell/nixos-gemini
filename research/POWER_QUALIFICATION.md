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
