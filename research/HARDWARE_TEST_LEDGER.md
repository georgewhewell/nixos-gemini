# Gemini hardware test ledger

This is a handoff checklist and live-state record for hardware flashing.  It
does not approve a candidate, a target, or any write.  Only the campaign owner
may provide those explicitly.

## Observed baseline: 2026-08-30

Host time is authoritative; the Gemini RTC reported 2023-02-15 and must not be
used to timestamp a test.

| Item | Observed value |
|---|---|
| Host path | workstation `ssh -J trex -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes root@10.15.19.82` |
| Left USB gadget | high-speed `0525:a4a2`, `gemini-pda-mainline` / `Gemini-L-DA921x-Bind`, serial `GEMINI_DA921X_BIND_20260729`; host driver `cdc_ether` |
| USB network | Gemini `usb0` `10.15.19.82/24`; trex `enp232s0f4u2` `10.15.19.81/24`, host MAC `42:00:15:19:82:00` |
| SSH | OpenSSH 9.6 listening on all IPv4 addresses; key-only root login works through `trex` |
| Right-port network | `enu1` UP, `192.168.23.70/24` |
| Running system | NixOS 23.05, Linux `7.1.3-gemini-da921x-lkro`, GCC 12.2.0 / binutils 2.40 |
| Root/store | p29 mounted read-only with `norecovery`; loop-mounted SquashFS hash `1aec7ab82d592e49da6e8c916d36cda097467855fdbd90a76b4d942a0b2a1da3` |
| p22 / `boot` | `/dev/mmcblk0p22`, 16 MiB, SHA-256 `08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3` |
| p30 / `boot2` | `/dev/mmcblk0p30`, 16 MiB, SHA-256 `122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159` |
| p31 / `boot3` | `/dev/mmcblk0p31`, 16 MiB, SHA-256 `1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513` |
| Persistent failure evidence | pstore mounted read-only; device dmesg and persistent journal are available (the independent recheck found a retained `console-ramoops-0` record) |

The p22 hash and stage-1 store hash match the locally retained
`artifacts/mainline-nixos-connectivity-m0/MANIFEST`; its kernel image hash is
`782091be243b37b12f0b8f0991629ff18dfdfd6862a4fbd2c34bde1678ddfbc7`.
Together with the distinct p30 and p31 hashes, this proves the observed running
image is p22.  It does not make p22 an experimental target.

## Independent recheck: 2026-08-30 02:30--02:41 CEST

This read-only recheck was performed by the hardware-test owner.  Host time is
authoritative; the device RTC was `2023-02-15T20:40:42+00:00`.

| Item | Independently observed value |
|---|---|
| Host path | Workstation reached `10.15.19.82` through `trex`; `trex` had `enp232s0f4u2` UP at `10.15.19.81/24`, MAC `42:00:15:19:82:00`; key-only SSH succeeded with the documented jump command |
| Host USB observation | `trex lsusb` currently shows `0525:a4a2` Linux-USB Ethernet/RNDIS Gadget; workstation USB logs retain the 2026-08-29 high-speed enumeration/disconnect/reconnect sequence for `0e8d:2000` preloader, `0525:a4a2` gadget, and failed `0e8d:20ff` tethering identity |
| Running system | `gemini-mainline-nixos`; NixOS 23.05; Linux `7.1.3-gemini-da921x-lkro`; GCC 12.2.0 / binutils 2.40 |
| Device identity | model `MT6797X`; compatible `planet,gemini-pda mediatek,mt6797`; online CPUs `0-7`, offline `8-9` |
| Cmdline identity | `console=tty0 console=ttyS0,921600n8 earlycon maxcpus=8 ... rdinit=/init ... initcall_blacklist=mt6797_a72_power_driver_init fw_devlink=rpm`; gadget addresses `42:00:15:19:82:01` / `42:00:15:19:82:00` and serial `GEMINI_DA921X_BIND_20260729` |
| Network/SSH | `usb0` `10.15.19.82/24`; `enu1` `192.168.23.70/24`; `0.0.0.0:22` listening; SSH source observed as `10.15.19.81` |
| Root/store | `/dev/mmcblk0p29` mounted `/gemian` read-only with `norecovery`; `/dev/loop0` mounted `/nix/store` read-only SquashFS; `/sys/fs/pstore` mounted read-only |
| Boot targets | Live GPT labels resolve `boot -> /dev/mmcblk0p22`, `boot2 -> /dev/mmcblk0p30`, `boot3 -> /dev/mmcblk0p31`; each reports 32768 sectors / 16777216 bytes and none appears in `/proc/mounts` |
| Boot hashes | p22 `08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3`; p30 `122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`; p31 `1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513` |
| pstore | `console-ramoops-0` exists, 65524 bytes, SHA-256 `1daf7da673a9ead3301f67e8c8bf074abe5c38dda84e85e8844abc5255339971`; its tail records an earlier orderly reboot, so pstore is not empty and must be captured before any failure reboot |
| Boot progress | `/gemian/nixos-boot.log` exists (272 bytes) and records persistent-partition mount, NixOS store discovery/mount, and stage-2 switch |

The observed p30 hash is the current live value and agrees with the current
mainline bundle identity.  Older narrative text in `research/BOOT_PROBE.md`
describes a prior failed p30 image (`d25799…`); that historical hash is not
evidence about the current device and must not be used for a write or restore.
The current trex USB path is live; the workstation itself does not currently
have a Gemini USB interface, so future flash observation must be armed on trex
and the workstation/jump route must be rechecked immediately before power
changes.

## Gate before any write

1. Record the review handoff: candidate path, expected SHA-256, exact byte
   size, intended partition label, purpose, and explicit authorization.  Stop
   if any item is absent or mismatches the bundle manifest.
2. Re-hash and size-check the local candidate.  Confirm Android header/layout
   and padding are appropriate for its target; a p30 candidate must be at most
   16 MiB and a padded p30 image exactly 16 MiB.
3. Re-establish the host observation path before power changes: `trex` kernel
   journal/dmesg, USB interface state, `10.15.19.82` reachability, and the
   current SSH route.  Save an initial timestamp from the host.
4. On a known-good running Gemini, resolve the target from
   `/dev/disk/by-partlabel`, require a `/dev/mmcblk0p*` target, require 32768
   sectors (16 MiB), and prove that it is not mounted.  Never substitute a
   remembered partition number.
5. For p30 only, read back a new full 16 MiB backup to the host, check its size
   and SHA-256, and preserve it as the sole restore source.  Re-check the
   candidate hash after transfer and re-check the resolved target immediately
   before the authorized write.
6. p31 is recovery only: never write it and never use it as a restore source.
   Runtime `dd` is never valid for p22.  A p22 write requires the exact scatter
   with only `boot` selected, offset `0xb100000`, size `0x1000000`, and Flash
   Tool **Download Only** in the preboot left-port environment.

## Prepared two-stage acceptance matrix

No candidate is accepted by this preparation record.  The campaign owner must
fill the handoff fields below for each stage and explicitly authorize the
corresponding slot/write path.

| Gate | Stage A: hardware-neutral connectivity/Nix baseline | Stage B: opt-in CONSYS identity |
|---|---|---|
| Candidate handoff | Absolute image path; SHA-256; exact bytes; Android header/layout; kernel/DTB/config/initramfs hashes; source/build provenance; target label; review link; explicit authorization | All Stage A fields, plus exact CONSYS patch/DT overlay, expected ID `0x0279`, register/rail trace format, and explicit opt-in authorization |
| Slot/write | `boot`/p22 only through exact scatter, `Download Only`, `boot` entry only; or `boot2`/p30 runtime write if explicitly selected | `boot2`/p30 only; never p22/p31; runtime write only after fresh p30 backup and live-GPT re-resolution |
| Pre-write stop conditions | Missing field, hash/size mismatch, wrong header, target mounted/wrong size, absent rollback image, or p31 touched | Any Stage A failure, plus missing bounded resource/sequence proof or any consumer/firmware enablement |
| Host capture | Arm `trex` `journalctl -kf`/`dmesg -w`, `lsusb`, `ip monitor`, timestamp, and `script` transcript before power/boot selection | Keep the same capture continuously; mark identity-probe start/end and every USB loss/re-enumeration |
| Boot acceptance | Within 120 s: expected gadget identity (`0525:a4a2`), `usb0`/SSH or declared probe shell; collect uname, cmdline, DT model/compatible, CPUs, routes, dmesg/journal, pstore, and target read-back hash | Same boot evidence; within 5 s of probe start: bounded ID read returns `0x0279` and records before/after registers/resources |
| Safety acceptance | No unexpected storage writes, no CONSYS/WMT/radio/firmware activity, p22/p31 hashes unchanged unless p22 was the explicitly authorized target | Reset asserted on success and every timeout/error; no AFE/radio/firmware access; report unresolved vendor off-path writes as failure/unknown |
| Failure/rollback | Stop after one failed boot; capture pstore before another boot, device logs, `/gemian/nixos-boot.log`, trex USB journal, and post-failure target hash; recover via p31/known-good path | Same; restore only from the fresh stage-specific backup and verify its hash; p31 remains untouched |

Capture tooling is ready on both workstation and `trex`: `ssh`, `scp`,
`date`, `ip`, `lsusb`, `journalctl`, `dmesg`, `tee`, `script`, `stdbuf`,
`sha256sum`, `stat`, `od`, `nc`, and `screen`.  `picocom`, `minicom`, and
`socat` are absent; if a serial node appears, use `screen` or a controlled
`stty`/`cat` capture.  The current trex USB sysfs identity is
`/sys/bus/usb/devices/1-2` (`0525:a4a2`, `gemini-pda-mainline`,
`Gemini-L-DA921x-Bind`, serial `GEMINI_DA921X_BIND_20260729`).

## Stage A transaction readiness: 2026-08-30 03:02--03:03 CEST

The exact authorized candidate was staged as the scatter's `boot.img` and
verified at SHA-256 `1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`,
size 16777216 bytes.  `trex` journal, USB polling, udev, and IP captures were
armed.  A bounded 60-second monitor saw no MediaTek preloader `0e8d:2000`;
`trex` remained on gadget `0525:a4a2`, so the Flash Tool process was not
started and no device write occurred.  The preloader transition remains the
sole physical blocker; captures are still armed for the next explicit reboot
or cable action.

The later trex journal records a preloader window at 02:57:34--02:57:37 CEST
(`0e8d:2000`, `ttyACM2`), followed by gadget `0525:a4a2` at 02:57:43.  The
Stage-A flash monitor was not yet running during that window; no Flash Tool
log or return code exists, so this is a reboot/re-enumeration observation, not
evidence of a write.  At the next check the gadget was enumerated but
`enp232s0f4u2` was DOWN and SSH timed out.

## Stage B source preflight: 2026-08-30 03:02--03:06 CEST

Read-only audit of `/home/grw/src/linux-gemini-platform` at clean commit
`0da60c35b` found the explicitly gated
`mt6797-consys-live` backend and
`mt6797-gemini-consys-identity.dtso` overlay.  The candidate contract must
identify the final DTB containing that overlay and boot with
`mt6797_consys_live.identity_experiment=1`; the base board node remains
disabled.  The source declares the following bounded identity sequence:

```text
VCN18=1.8 V -> 240 us -> VCN28=2.8 V -> INFRACFG offset 0x350 bit 8
-> assert CONMCU reset -> SPM PWRON_CONFG_EN=0x0b160001
-> SCPSYS CONN power-domain vote -> 30 us
-> read MCU+0x8 until 0x0279 (20 ms interval, 200 ms cap)
```

Acceptance requires `pre-identity`, `identity 0x0279 observed`, and
`post-identity` state records; reset must remain asserted and VCN votes must be
released.  A timeout or read error is a failed identity attempt, not a retry
permission.  The trace must show no AFE, WMT, radio, or firmware activity.
The source's cleanup cannot restore its persistent sleep-mask and PWRON
configuration writes; those residuals must be reported as an explicit
restoration gap, never described as a clean full off path.  This source audit
does not authorize deployment.  Review commits `41f987351` and `938803bed`
corrected provider ownership/runtime-PM teardown and GNSS endpoint publication
before the integrated source was built.

### Stage B immutable build: 2026-08-30

The Stage-B image is build-complete but not flash-authorized.  It is queued
behind Stage A and a fresh p30 backup:

| Field | Exact value |
|---|---|
| Bundle | `/home/grw/src/nixos-gemini/artifacts/mainline-consys-identity-p30` |
| Padded p30 image | `probe-padded-boot2.img`, 16777216 bytes, SHA-256 `59b9febf7b397a3cca0ef82407af1c1d347f1751550ab7006aa29f0429e90716` |
| Bundle manifest | `MANIFEST`, SHA-256 `f9aac2db3fe38a33109b2747c6ed8245b3fb1c6478db2b65534e19dd4dd0505a` |
| Source | `/home/grw/src/linux-gemini-platform`, commit `0da60c35b`, NAR `sha256-V7BMwHlvvKF4HRP/wHaCc3Ma+rmlWVBaOYpIARbKZdI=` |
| Kernel | `Image` SHA-256 `aaec346961cffa397e8181e1c3983752f0c1125628e61ea68e9218672d539f03`; `Image.gz` SHA-256 `015a6c2b037245223b90e98ee459ef3fb6d950f78c174fa3cf973fc29034c490` |
| Device trees | base SHA-256 `e6aa4b9d20360c260f313292be41f92df2deb8613ca6c665a9f045b6b4d880e7`; final SHA-256 `70c1b17ec8d5744ff5ac60bc7250c958dc99708e4afd463f632e45823ff1eeea`; identity DTBO SHA-256 `4a94c3dbbb4249badf1ee526d7b467fc3103f8c08f694d44f77488b50d652ba0` |
| Config/initramfs | config SHA-256 `9336f23d5c9047a27b5f4c635e7c865d73ec73049211de57ec7fee4be591dbf1`; initramfs SHA-256 `076a87ecef49ca534bff73e504c3b3f7673e3a79477caf64d2cd8f9411899460` |
| Required parameter | `mt6797_consys_live.identity_experiment=1` is enforced in the built-in command line |

Nix evaluation, kernel/config assertions, exact base/intermediate/final DT
hash assertions, Android-v0 image construction, and 16 MiB padding all passed.
This record still lacks a fresh p30 backup and explicit p30 authorization, so
the write gate remains closed.

### Stage B handoff fields and verdicts

Before any Stage-B p30 write, the campaign owner must provide one immutable
bundle record containing: absolute padded-image path, SHA-256 and exact byte
size; manifest path and matching digest; source commit
`0da60c35b`; kernel `Image`/`Image.gz`, base
DTB, final DTB with the overlay, config, and initramfs hashes; exact cmdline
including `mt6797_consys_live.identity_experiment=1`; fresh p30 backup path,
size, and SHA-256; and explicit authorization for `boot2`/p30 only.  A Stage B
image is rejected if the overlay, parameter, or config enables any radio,
firmware, WMT, BTIF, GNSS, Wi-Fi, FM, modem, AFE, or A72 path.

The single hardware attempt is accepted only if the captured boot reaches the
normal gadget/SSH baseline and dmesg contains the ordered state records
`pre-identity`, a successful `identity 0x0279 observed`, and `post-identity`.
The post-state must show reset asserted, VCN18/VCN28 votes released, and no
cleanup error; the probe must complete its 20 ms polling loop within the
200 ms cap.  Any timeout, missing ID, reset/vote cleanup error, unexpected
consumer/firmware activity, USB loss without recovery, or absent pstore/log
evidence is a failed attempt.  On failure, stop and recover once through the
known-good path; capture pstore before another boot and never retry the
identity probe on the same boot.

## Acceptance and failure collection

Start host log capture before the boot selection.  Record the preloader and
gadget USB identities, interface MAC/address, enumeration time, first reachable
SSH or probe-shell time, and loss/re-enumeration events.

For a successful candidate, collect its `uname -a`, `/proc/cmdline`, CPU
online/offline state where relevant, network addresses/routes, required service
or feature result, dmesg/journal, and the declared candidate hash read back
from its target.  Do not change drivers or configuration simply to turn a test
green.

On failure, stop rather than retrying.  Recover through p31 or the existing
known-good path, then capture `/sys/fs/pstore` before another experimental
boot, device dmesg/journal, `/gemian/nixos-boot.log` when applicable, the trex
USB/kernel journal window, and the target partition's post-failure hash.

The detailed p30 procedure remains [BOOT_PROBE.md](BOOT_PROBE.md); default-p22
preboot flashing restrictions remain [README.md](../README.md).

## Stage A hardware attempt: 2026-08-30 03:38--03:44 CEST

The exact handoff was independently rechecked immediately before the attempt:
candidate `boot-padded-p22.img`, 16777216 bytes, SHA-256
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`; shared
scatter `boot.img` matched that digest; the MT6797 XML selected `BromUSB`,
checksum level `both`, and `download-only/da-download-all`.  The scatter had
only `boot`/SYS23 enabled (`0xb100000`, `0x1000000`, `EMMC_USER`); `boot2`,
`boot3`, and recovery were not downloadable.  Fresh pre-write p22 backup
`artifacts/stage-a-20260830/p22-before-stage-a.img` was 16777216 bytes and
SHA-256 `08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3`.

The trex catcher was armed before reboot and recorded the first catchable
window at `03:41:16+02:00`: `0e8d:2000`, `MT65xx Preloader`, `ttyACM2`.
The bounded workstation loop issued seven `sync; reboot` requests and stopped
when that state was recorded.  The exact console Flash Tool was started once;
its log confirms `rom list:Index(23)` with only the staged `boot.img`, then the
preloader disappeared and BROM search ended `S_TIMEOUT`/exit status 1 at
`03:43:17+02:00`.  No retry, format, firmware-upgrade, erase, or p31 access
was performed.  Because the tool returned before a connection/write, this is
not a candidate flash and is not a Stage-A acceptance.

The device did reboot and returned to the known-good gadget at `03:41:25+02:00`;
trex captured the complete disconnect, `0e8d:2000` attach/detach, and
`0525:a4a2` reconnect.  The host interface came back DOWN and was restored
host-side only (`10.15.19.81/24`); SSH then reached the device.  Post-attempt
read-back proves no storage change: p22 remained
`08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3`, p30
remained `122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`,
and p31 remained `1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`.
The returned system reported Linux `7.1.3-gemini-da921x-lkro`, model `MT6797X`,
compatible `planet,gemini-pda mediatek,mt6797`, `cpus=0-7`, USB `10.15.19.82`,
Ethernet `192.168.23.70`, and the expected baseline command line.  Current
post-attempt evidence is in `artifacts/stage-a-20260830/device-postattempt.txt`,
`device-dmesg-postattempt.txt`, `device-journal-postattempt.txt`,
`console-ramoops-0-postattempt`, and the trex capture files.  pstore retained
the orderly shutdown record; its post-attempt SHA-256 is
`9ba0397a528753fccb950cb4417cd8a141b7686152159b2629c750d546fd15c2`.

**Verdict: Stage A write attempt failed before write; candidate not accepted.**
The unchanged p22 digest verifies the rollback/known-good path, and p31 was
untouched.  Stage B remains build-complete but explicitly unauthorized.

## Stage A corrected retry and acceptance: 2026-08-30 03:49--03:54 CEST

The failed attempt was compared with the available successful deployment
record `artifacts/mainline-default-first-boot-20260829.txt`.  Both use the
same MT6797 DA, `BromUSB`, checksum level `both`, and
`download-only/da-download-all`; the successful record ends `100% of image data
has been sent (16.00M of 16.00M)` and `Download Succeeded.`  The failed log had
already loaded the XML/scatter and image (`rom list:Index(23)`), but showed
`Connecting to BROM...`, `Search usb, timeout set as 120000 ms`, then removal
of `ttyACM2` with blank VID/PID and `S_TIMEOUT`.  It never reached
`USB port is obtained`, `Downloading & Connecting to DA`, or any image/write
phase.  This rules out an absolute-path, scatter-target, DA-permission, or
checksum problem.  The supported correction was to start the console Flash
Tool before reboot, allowing its documented 120-second BROM wait to catch the
short preloader window.  Plain BusyBox `reboot` was also observed to return 0
without promptly restarting; the already evidenced `systemctl reboot --no-wall`
actuator returned `Input/output error` but did trigger the preloader sequence,
so it was used once within the bounded retry.

The same candidate and exact boot-only scatter/XML were reverified, with a
fresh p22 pre-write readback/backup at
`artifacts/stage-a-20260830/p22-before-retry1.img`: 16777216 bytes,
SHA-256 `08631fe982b6693f30ab64280edf501ef65c86c703b9fe54e2cfeff7027ec8f3`.
The pre-armed Flash Tool acquired `/dev/ttyACM2` at `03:50:33+02:00` with
`vid is 0e8d`, `pid is 2000`, and `USB port is obtained`; it logged
`Downloading & Connecting to DA...`, `Download DA now...`, `Downloading
images...`, `Download Succeeded.` and exited 0 at `03:50:37+02:00`.  The
bounded reboot loop stopped after its four-request cap; no retry, erase,
format, firmware-upgrade, or p31 operation occurred.

Trex captured preloader at `03:50:33` and `03:50:43`, then gadget
`0525:a4a2` at `03:50:52`; the host interface was restored host-side and SSH
returned.  At post-boot validation, p22 read back the exact candidate
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, p30
remained `122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`,
and p31 remained `1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`.
The boot reported Linux `7.1.3-gemini-da921x-lkro`, `MT6797X`, compatible
`planet,gemini-pda mediatek,mt6797`, CPU `0-7`, USB `10.15.19.82`, and Ethernet
`192.168.23.70`.  `/dev/mmcblk0p29` was mounted `/gemian` read-only with
`norecovery`; `/nix/store` was read-only SquashFS.  No WMT/BTIF/CONSYS platform
devices or firmware requests appeared; only the expected built-in initcalls
and reserved-memory identity were present.  Evidence is in
`artifacts/stage-a-20260830/retry1/flash-tool.log`,
`device-retry1.txt`, `device-retry1-acceptance.txt`,
`device-feature-negative-retry1.txt`, `device-dmesg-retry1.txt`,
`device-journal-retry1.txt`, `console-ramoops-0-retry1`, and the trex capture
files.  The retained pstore record SHA-256 is
`cf77d164ff734affb1626c8b4fb318541d4c3d79594262e5cef411135f23f703`.

**Verdict: Stage A accepted after the timing/actuator correction.**  Stage B
remains closed pending its separate explicit handoff and authorization.

## Stage B preflight and unattended-selection gate: 2026-08-30

The immutable Stage-B artifact was independently checked before any write:
`artifacts/mainline-consys-identity-p30/probe-padded-boot2.img` is a regular
16777216-byte file with SHA-256
`59b9febf7b397a3cca0ef82407af1c1d347f1751550ab7006aa29f0429e90716`.
`MANIFEST` hashes to
`f9aac2db3fe38a33109b2747c6ed8245b3fb1c6478db2b65534e19dd4dd0505a`; every
listed Nix-store payload hash (Dropbear, authorized keys, Image/Image.gz,
final DTB, initramfs, raw boot image, and padded image) matched.  The
manifest identifies the source NAR as
`sha256-V7BMwHlvvKF4HRP/wHaCc3Ma+rmlWVBaOYpIARbKZdI=`, ixoo baseline
`7199e8229c6a805a941e33a6862956949dfebd3a`, candidate
`a24b2d264844ee2bb50e77dc7aceaa6b902c7b6a`, and the
`bounded-0x0279-reset-held-v1` CONSYS identity profile.  The clean local
source checkout is at commit `41f987351d4f54dc60f6c68179238eb9892d6ebb`,
whose ancestry contains the identity implementation commit `8fe066799`; the
artifact's NAR/store hashes, not the mutable checkout, are the provenance
authority.

A fresh read-only p30 check resolved `/dev/disk/by-partlabel/boot2` to
`/dev/mmcblk0p30`, verified it is 16777216 bytes, inactive and unmounted, and
confirmed the active root is p29.  The fresh rollback snapshot
`artifacts/stage-a-20260830/p30-before-stage-b.img` is 16777216 bytes and
SHA-256
`122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`.
p31 was not opened or accessed.

The unattended boot-selection gate is **not met**.  The retained LK audit
`artifacts/ixoo-7199e822/experiments/2026-07-12-boot-contract-recovery/results/lk-boot2-software-selection-audit-20260718.txt`
finds `boot2_key_code=0x11`, no `reboot_boot2_string`, absent
`boot_target_sysfs`, `reboot_mode_sysfs`, and `boot_slot_sysfs`, no kexec or
`fw_printenv`, and concludes `direct_gemian_reboot_to_boot2=not-found` with
`current_supported_workflow=hold-the-silver-button-during-LK-selection`.
The public README independently states normal power-on selects p22 and the
side button selects p30; prior hardware records label p30 selection
`owner-attended` and `automatic_boot2_selection=no`.  Flash Tool's `-b`
option only controls reboot after a write; it is not an MTK-LK slot selector.
No accepted software, kexec, USB, watchdog, or remote GPIO path can select
p30 without repurposing the artifact or changing the bootloader.

**Verdict: Stage B stopped at preflight; no p30 write was performed.**  The
device remains on the accepted Stage-A p22 image, and no catcher, Flash Tool,
reboot loop, or watchdog process was armed.  The next discriminating action
requires one owner-attended physical side-button selection with host captures
already armed; it must not be replaced by an automatic reboot or a p31 path.

## Bounded default-p22 recovery harness and reboot dry-run: 2026-08-30 03:59--04:06 CEST

The read-only recovery dry-run was performed while the accepted Stage-A image
was running.  The pre-state recorded p22 as the candidate digest
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, p30 as
`122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`, and p31
as `1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`.
`systemctl reboot --no-wall` returned `Call to Reboot failed: Input/output
error` but did perform an orderly reboot: trex recorded gadget disconnect at
03:59:11, `0e8d:2000`/`MT65xx Preloader` with `ttyACM2` at 03:59:13,
preloader disconnect at 03:59:16, and gadget `0525:a4a2` at 03:59:22.  SSH
returned, the host interface was restored host-side, and all three partition
digests remained unchanged.  Post-boot pstore contains the orderly
`mtk-wdt ... shutdown` and `reboot: Restarting system` records.

The captured evidence is under
`artifacts/stage-a-20260830/recovery-dryrun/`: post dmesg SHA-256
`c12554350714e161a5571167022269c97c185efe7e3a56336cf99becf424cf56`, post
journal `30d19f0d7469e53e587202a90c7ee50ef3b5ff87484c6b3a3d01bc0d81dcc6e4`,
and pstore `ba1c58c388344dfd0672df9e142da1841f9c4807fdc4088f668cee10a36d47f7`.
The corresponding trex USB/kernel/IP/udev captures are in
`/mnt/Home/src/nixos-gemini-flash-p22-20260829/stage-a-20260830/`.

The watchdog preflight found `/dev/watchdog0` (`mtk-wdt`) inactive, timeout
31 seconds, `nowayout=0`, with `RuntimeWatchdogUSec=0` and only a ten-minute
`RebootWatchdogUSec`.  Therefore Linux can prove a normal reboot actuator and
preloader recovery, but cannot guarantee a watchdog reset through a pre-init
hang.  The harness deliberately does not induce a hang or claim that
guarantee.

The bounded transaction is implemented by
`research/p22-recovery-harness.sh` and
`research/p22-flash-wrapper.sh`.  It has no default write mode: `--execute` is
required, while `--dry-run` independently verifies the exact 16 MiB candidate
and rollback hashes, immutable boot-only scatter/XML hashes, one and only one
downloadable entry at offset `0xb100000`/size `0x1000000` in `EMMC_USER`, and
the current p22/p30/p31 readbacks.  The execute state machine captures pstore,
dmesg, p22 pre-hash, trex USB/kernel/IP logs, and a state file; stages only
`boot.img`; starts Flash Tool Download Only before requesting reboot; allows a
manifest-selected SSH/acceptance window (120 seconds for the original
Stage-A manifest, 60 seconds for watchdog profiles); and, on failed acceptance, stages the
exact known-good p22 rollback, pre-arms the same boot-only tool, and permits a
clean reboot or natural watchdog/preloader transition within bounded waits.
There is no force reset, erase, format, firmware upgrade, p30 target, or p31
write.  Capture processes have a 900-second timeout and are stopped by the
exit trap; tool and acceptance/recovery waits are bounded and leave explicit
state markers.  The script passed `sh -n` and
`sh research/p22-recovery-harness.sh --dry-run` at 04:06:19 CEST.

**Verdict: recovery mechanism is proven for orderly reboot and known-good
return, but pre-init watchdog recovery remains unproven by hardware design.**
No Stage-B artifact was flashed and no p30/p31 write occurred.

## Next-experiment p22 handoff flow: 2026-08-30

The previously Stage-A-hardcoded transaction was tightened into a fail-closed
exact-manifest flow.  `research/p22-next-experiment.manifest` carries the
candidate and rollback paths, SHA-256 digests and sizes, target identity,
scatter/XML digests, staging/capture paths, and the expected model, DT
compatible, cmdline token, CPU, gadget, and Ethernet identities.  The parser
accepts only known `key=value` fields, rejects duplicates, missing fields,
relative or unsafe paths, non-`boot/p22` targets, non-16 MiB images, and unsafe
acceptance tokens; it never sources the manifest as shell.  Thus a future
reviewed p22 artifact can be handed off by replacing this exact manifest while
the target and read-only p30/p31 guards remain fixed.

The harness now passes manifest values only after local validation and uses the
exact `/dev/mmcblk0p22` target, with p30 and p31 remaining read-only invariants.
The Flash Tool wrapper timeout is 240 seconds and the harness waits 250 seconds
for `flash_rc`, avoiding the former exact-180-second completion race.  The
trex launch no longer uses `setsid -f`; the recorded PID names the wrapper
process, while `timeout` bounds Flash Tool.  A failed candidate acceptance waits
for a terminal candidate-tool state before staging rollback, so it cannot start
two USB owners concurrently.

The manual-reset boundary is explicit in the script comments and terminal
states: because watchdog0 is inactive with `nowayout=0`, a pre-init hang with
no preloader cannot be reset remotely.  The harness stops with
`manual_reset_required_no_preloader` or `manual_reset_required_no_ssh`, leaving
captures and state for an owner-attended physical reset.  It never claims
watchdog recovery, never writes p30/p31, and never erases/formats/upgrades
firmware.  Validation performed without flashing: `sh -n`,
`shellcheck -S error -s sh` (no errors), default dry-run, explicit manifest
dry-run, missing-manifest rejection (rc 2), and missing-mode rejection (rc 2).

## Unattended p22 recovery bundles: build-only handoff 2026-08-30

Two opt-in p22-only bundles were cross-built against the clean local platform
tree `/home/grw/src/linux-gemini-platform` at commit
`581fed2ea3e2d13ddaaae5679f8c798bf7d28601`, whose ancestry contains the
reviewed watchdog `start_at_boot` commit `31d677ba3`.  The local input NAR is
`sha256-5M9rjBPOfHMePbJ0/TeXg6oEKy3iIvXLWGrGHeTbEBc=`.  The watchdog-control
bundle is Stage-A USB/SSH/storage plus only the watchdog delta, while the
combined bundle additionally enables the already reviewed platform overlay.
Neither bundle has been flashed or boot-tested.

The immutable candidate handoffs are:

* `artifacts/mainline-unattended-recovery-watchdog-p22/boot-padded-p22.img`,
  16777216 bytes, SHA-256
  `0d99e17867d8621b9a309209f88abc2a27e06039a342b0fcd26ac168e8c82d03`;
  manifest `research/p22-unattended-recovery-watchdog.manifest`.
* `artifacts/mainline-unattended-recovery-platform-p22/boot-padded-p22.img`,
  16777216 bytes, SHA-256
  `e8bfdf8a7488279f972a7fdd64e86ab8048b13280457d8c6ba07392c01efe579`;
  manifest `research/p22-unattended-recovery-platform.manifest`.

Both use the currently accepted Stage-A p22 image as rollback
(`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`) and
retain p30 `122c0f46...` and p31 `1fa78de9...` as read-only invariants.  Their
current-source DT identities are base
`7e6bd77e10a6a58b772455643d26e5d495ec35b7aa81e070672bf3a701ea300c`,
serviceability
`235c17ebc0653f48c0a4c1215a384a90217856aacde85db44710ec43f2040044`,
and USB-host composition
`cd5c0e688aeaf33d9e61c4b9df57a82b6a97f7017f16f6eaf373a7fc38044705`.

The recovery substrate is explicit in each bundle and config assertions:
built-in `CONFIG_MEDIATEK_WATCHDOG=y`, `CONFIG_WATCHDOG_NOWAYOUT=y`,
`CONFIG_WATCHDOG_OPEN_TIMEOUT=45`, `CONFIG_PANIC_ON_OOPS=y`,
`CONFIG_PANIC_TIMEOUT=5`, and cmdline `panic=5 mtk_wdt.start_at_boot=1`.
`/init` selects `/dev/watchdog` or `/dev/watchdog0`, starts BusyBox watchdog
in foreground mode with `-t 10 -T 31`, and records a healthy marker only if
the process survives its first second.  A separate 90-second lease worker
SIGKILLs that exact PID unless the acceptance command atomically writes
`/run/unattended-recovery.accepted` containing exactly
`unattended_recovery=healthy`; with the 31-second hardware timeout this gives
the already-running rollback Flash Tool a subsequent preloader window when
network/USB acceptance is lost.  The residual boundary remains the interval
before the MTK watchdog probe (observed around 1.07s on the live baseline),
and no watchdog IRQ/pretimeout reset is assumed.

Acceptance is fail-closed and profile-specific: exact p22 hash, model,
compatible, `maxcpus=8`, `panic=5`, `mtk_wdt.start_at_boot=1`, CPU `0-7`,
the expected IPs resolved to whichever interfaces own those addresses,
read-only p29/store, and the exact `/run/probe-status` marker.  The watchdog
profile additionally requires watchdog identity `mtk-wdt`, sysfs state
`active`, timeout `31`, a live marker PID, and a `/proc/$pid/fd/*` link to the
watchdog character device.  The combined platform profile explicitly allows
its scoped platform logs; it does not inherit the connectivity profile's
AFE/radio blacklist.  No hardware test is authorized by these build results;
the next handoff must separately authorize one p22 Download Only cycle.
