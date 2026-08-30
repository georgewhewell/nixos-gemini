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
and the exact `/run/probe-status` marker.  The manifest's `rootfs_policy`
selects the mount contract: `nixos-stage2` requires read-only p29 `/gemian`
and loop-backed `/nix/store`; `enumeration-only` rejects all mmcblk, `/gemian`,
and `/nix/store` mounts, then polls up to 35 seconds for
`emmc=present userspace_block_reads=none mounts=none`.  The watchdog profile
additionally requires watchdog identity `mtk-wdt`, sysfs state
`active`, timeout `31`, a live marker PID, and a `/proc/$pid/fd/*` link to the
watchdog character device.  The combined platform profile explicitly allows
its scoped platform logs; it does not inherit the connectivity profile's
AFE/radio blacklist.  No hardware test is authorized by these build results;
the next handoff must separately authorize one p22 Download Only cycle.

The deliberate hardware proof path is explicit but not run here:
`research/p22-recovery-harness.sh --manifest research/p22-unattended-recovery-watchdog.manifest --execute --proof-lease`.
It requires the watchdog manifest, flashes only p22 using Download Only, does
not create the acceptance marker, waits up to the manifest's 60-second SSH
window, then arms the exact Stage-A rollback before the 90-second lease
SIGKILL and its expected 31-second watchdog/preloader exposure.  The state
file records `lease_proof_rollback_armed`; the normal capture, p22/p30/p31
readbacks, and recovery checks still apply.  This path is intentionally not a
dry-run claim or a substitute for root's separate hardware authorization.
The proof verdict is sticky: rollback success alone is insufficient.  It also
requires successful candidate watchdog validation and a captured
'unattended_recovery=lease-expired watchdog_userspace=stopped' line; only then
does the harness write 'lease_proof_passed_recovered_stage_a'.  Candidate
validation or lease-evidence failure returns nonzero even if Stage-A rollback
itself succeeds.

## Locked-source host-NIC watchdog candidate: build-only 2026-08-30

At the hardware owner's request, a replacement watchdog-control bundle was
cross-built without touching the device. It uses the locked `linux-gemini`
source `1bb2a9863d9a1e6d59e513eddbec68e2866310cd` from `flake.lock`; no local
source override was used. The old `0d99e178...` artifact and its manifest
remain immutable. The new p22 image is:

* `artifacts/mainline-unattended-recovery-watchdog-hostnet-p22/boot-padded-p22.img`,
  16777216 bytes, SHA-256
  `a0bc87d21227158e2e925a6f05affdfdec773a5e44e248d41f8b6684e2bd37eb`;
  handoff `research/p22-unattended-recovery-watchdog-hostnet.manifest`.
* Exact rollback is the accepted Stage-A p22 image
  `1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`.

The kernel-built `mt6797-gemini-pda-usb11-host.dtbo` is packaged directly and
composed into the serviceability DT; the retired repository-local USB11 DTS
is not used. The resulting final DT SHA-256 is
`58fa70641900b343c466b815bcadd0cb5269d86df0b4939f436af7c0d2bc6300`.
The DT validation proves both `regulator-usb11-drvvbus` and
`regulator-usb11-vbus` have GPIOs and no `regulator-always-on` or
`regulator-boot-on`; the child has `vin-supply` from the parent. Thus an
unattached cable does not get a DT-implied VBUS assertion.

The initramfs contains only the required RTL8156 firmware
`lib/firmware/rtl_nic/rtl8156b-2.fw`, SHA-256
`5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f`.
`usb-host-net` waits up to 60 seconds for a non-gadget `r8152` interface,
requires USB VID:PID `0bda:8156`, brings it up, and runs BusyBox `udhcpc`
with a non-evaluating callback that records bound/renewed address state in
`/run/probe-status`. The new manifest's `host_net_policy=required` accepts
only the expected `192.168.23.70` address plus the ready marker carrying the
driver and VID:PID; gadget SSH remains the fallback transport. Target
BusyBox 1.37 accepts both CIDR and dotted-netmask forms for this `ip` syntax
(the qemu read-only negative-device probe returned only `can't find device`,
not a prefix parse error).

The harness now uses one absolute acceptance deadline, waits for SSH to go
down after dispatch, and adapts reboot dispatch between systemd and BusyBox
`/bin/reboot -f`, recording path and return code. It retains the 90-second
lease, 31-second watchdog expiry, exact p22 Download-Only gates, and p30/p31
read-only invariants. `shellcheck`, `sh -n`, and the new manifest dry-run
passed. No Flash Tool, reboot, catcher, or hardware write was performed for
this candidate; it awaits byte-level review before any execute authorization.
The unavoidable pre-watchdog-probe residual boundary remains documented in
the bundle manifest: a hang before the approximately 1.07-second MTK
watchdog probe has no guaranteed remote actuator.

## Chained p22 recovery runner and platform queue: 2026-08-30

The harness SSH paths now use `BatchMode`, one connection attempt,
`ConnectTimeout=8`, and a 3-second server-alive interval with two missed
probes terminating the connection.  This applies equally to the Gemini
ProxyJump, trex capture, Flash Tool launch, and wrapper staging paths.  The
adaptive reboot dispatcher records whether systemd or BusyBox `/bin/reboot
-f` was selected and requires the SSH session to go down within 20 seconds;
it no longer swallows a reboot command that leaves SSH alive.

`research/p22-chained-recovery-runner.sh` is a deliberately exact,
p22-only three-phase sequence: normal candidate acceptance, lease-expiry
proof with Stage-A rollback, then final normal candidate acceptance.  It
hard-rejects any manifest other than the reviewed host-NIC candidate and
accepted Stage-A rollback, checks p22/p30/p31 at every execute boundary, and
checks trex for an idle Flash Tool before and after each phase.  Its dry-run
completed all three phases successfully; no execute mode was run.  The
runner adds no post-final BROM daemon: every actual reset is already wrapped
by the harness's bounded USB capture, while a lingering watcher after final
acceptance would introduce an unnecessary process/USB ownership race.  Any
future post-final reset therefore remains an explicit new capture cycle.

The corrected combined platform bundle was also built against the same locked
kernel source, without hardware access:

* `artifacts/mainline-unattended-recovery-platform-hostnet-p22/boot-padded-p22.img`,
  16777216 bytes, SHA-256
  `a359951c3c298ecbb182b5726e54d376e36fa0d794c24ae816c3d5e263b7f877`.
* Its initramfs is byte-identical to the watchdog-control candidate at
  `15135cb7960ba23cecc5a3f4708fa2b057f034bfd1c155c6db0301cb2efbfa52`;
  final DT remains `58fa70641900b343c466b815bcadd0cb5269d86df0b4939f436af7c0d2bc6300`.

No Flash Tool, catcher, reboot, or hardware write was performed.  Current
live readbacks remain p22 `1b5f808e...`, p30 `122c0f461e...`, and p31
`1fa78de9...`.

## Pre-probe reset boundary and harness transaction hardening: 2026-08-30

The retained LK reverse-engineering record provides a concrete, but bounded,
watchdog handoff trace.  `FUN_46001e0c` calls the WDT setup at file offset
`0x1e3c`, which programs `0x10007000`, sets length argument `10`, and kicks
`0x10007008` with `0x1971`; the normal final handoff kicks again at `0x27380`
without a nearby disable call.  The explicit reboot helpers do disable WDT,
delay 8000 ms, and enter their reset loop.  The 64-bit handoff instead enters
ATF through `smc 0x82000200` and LK does not return, so this binary cannot
prove what ATF does to WDT state.  See
`artifacts/lk-analysis/REVERSE_ENGINEERING.md:7-18,47-65`.

This makes the boundary precise: p22 kernel/DT/cmdline changes can enable and
service Linux `mtk_wdt` only after the kernel has begun probing.  They cannot
execute before LK/ATF handoff or guarantee a reset during a pre-probe hang.
The live baseline recorded watchdog probe/enable at approximately 1.07 s and
then showed watchdog0 inactive with `nowayout=0`; that is Linux state, not
proof of the earlier LK/ATF state.  No exact Gemini preloader source or ATF
handoff proof is present locally.  Closing this gap requires a separately
reviewed LK/preloader/ATF artifact that proves WDT persistence, or manual
reset; no such bootloader change is being made here.

Trex has proven USB observation, SSH, and Flash Tool ownership only.  The
retained reset experiments document owner-attended power-key recovery and no
remote GPIO, relay, or power actuator.  Therefore a dead pre-probe device
cannot be made catchable by a host watcher alone; the runner correctly stops
at a manual-reset boundary rather than escalating to erase/format.

The harness now launches the wrapper in a private `setsid` session.  The
wrapper records its PID and PGID, and cleanup sends signals to the group only
when PID equals PGID, otherwise falling back to the wrapper PID.  This bounds
orphaned `timeout`/`sudo`/Flash Tool children on interruption.  Recovered
candidate failures always remain nonzero, even when rollback succeeds, and
terminal `manual_reset_required_*`, `recovery_blocked_*`, and
`recovered_but_proof_failed_*` states are preserved by cleanup.  `sh -n`,
ShellCheck, and the existing three-phase dry-run passed; no Flash Tool,
reboot, catcher, or hardware write was performed.

## Authorized chained p22 attempt: 2026-08-30 05:37--05:39 CEST

The exact command was authorized and run once:

```text
research/p22-chained-recovery-runner.sh --manifest research/p22-unattended-recovery-watchdog-hostnet.manifest --execute
```

Read-only preflight passed: candidate `a0bc87d21227158e2e925a6f05affdfdec773a5e44e248d41f8b6684e2bd37eb`, Stage-A rollback `1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, scatter `19f5d2cba03310e744056036fb9805dfc4686b54e2c25e08d532895efd6650f8`, XML `90eec878d01866f37f927f0e6d1d768517a758790d818d6252091fca7b212605`, and Trex Flash Tool idle. Live p22/p30/p31 pre-state matched the exact expected hashes.

Phase 1 candidate Flash Tool log reports BROM/DA connection and
`Download Succeeded`, `[23] WRITE TO PARTITION [ boot ]`, and `flash_rc=0`.
The candidate did not satisfy the 60-second acceptance window.  The harness
then armed the exact Stage-A rollback.  Trex captured candidate disconnect,
preloader `0e8d:2000` at 05:38:37, a second preloader window at 05:38:47, and
gadget `0525:a4a2` at 05:38:56.  Rollback Flash Tool also reports
`[23] WRITE TO PARTITION [ boot ]`, `Download Succeeded`, and `flash_rc=0`.
Evidence is under Trex capture directory
`/mnt/Home/src/nixos-gemini-flash-p22-20260829/p22-recovery-20260830-053725/`
and local state `artifacts/p22-recovery-20260830-053725/`.

The transaction stopped fail-closed as
`manual_reset_required_no_ssh` at 05:39:32.  Gadget `0525:a4a2` remained
enumerated, but Trex `enp232s0f4u2` remained `DOWN`, so SSH and post-rollback
partition readback could not be obtained.  No phase 2 lease proof or phase 3
candidate reinstall was attempted.  No p30/p31 write, erase, format, or
firmware upgrade was issued.  All harness, wrapper, probe-capture, and Flash
Tool processes from this run exited; unrelated pre-existing Trex monitors were
not disturbed.  Further progress requires the explicitly reported manual
network/reset intervention and a fresh read-only invariant check.

## Host-plane repair and recovered readback: 2026-08-30

After the stopped attempt, root restored access over the proven right NIC and
independently re-read the device.  The recovered exact values are p22
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, p30
`122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`, and p31
`1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`.
These are readback evidence after recovery; they do not change the stopped
phase verdict above.

The next p22 transaction now owns
`research/trex-gadget-net-watcher.sh`.  Before any Flash Tool/reboot, it
requires both Trex USB identity `0525:a4a2` and the exact gadget MAC
`42:00:15:19:82:00`, resolves only that interface, and uses noninteractive
sudo to restore link UP and `10.15.19.81/24`.  It publishes a short-lived,
per-run identity marker and logs every action.  Harness cleanup kills its
run-specific PID.  Read-only right-NIC SSH fallback is enabled only after
that exact marker is armed and remains subject to the candidate's full
model/SHA/cmdline/host-net acceptance checks; reboot dispatch remains gadget
only.  A current Stage-A logical link-down/up cycle passed, restoring the
exact gadget address without reboot or flash.

The old `a0bc87d...` artifact and manifest remain immutable and will not be
rerun.  A rebuilt v2 candidate with `CONFIG_WATCHDOG_OPEN_TIMEOUT=90` is being
reviewed separately; its new manifest/runner identity and acceptance/lease
values are outside this watcher commit.

## Watchdog-control v1 diagnosis and v2 rebuild: 2026-08-30

Root recovered the failed candidate's console record after the automatic
Stage-A rollback as
`artifacts/p22-recovery-20260830-053725/console-ramoops-0-post-rollback`.
It proves that `mtk-wdt` registered running with timeout 31 and nowayout 1 at
kernel time 1.059 seconds.  It also records the 45,000-ms DVFSP late-validation
delay and kernel work through 31.752 seconds, but no retained
`stage=initramfs-entered` marker.  Trex saw the candidate gadget enumerate at
05:37:50 and disconnect for the watchdog reset at 05:38:35: exactly the old
45-second `CONFIG_WATCHDOG_OPEN_TIMEOUT` boundary.  The old candidate is
therefore rejected and will not be retried.

The rebuilt immutable v2 control is
`artifacts/mainline-unattended-recovery-watchdog-hostnet-p22-v2`.  Its exact
identities are:

* padded p22 image
  `567ac4302dda7c12f734306af56ad8fba04986fadcd6f70d53ad3b89df747638`;
* raw Android-v0 boot image
  `52faeadef939c815cd70dfc3b1f98c857491adbb672b7fe23568612be590d19e`;
* kernel `Image`
  `4f503590ed6accc0f82b8dfa4e894759706f45ec3c8451fb1c5613d75dce8651`;
* initramfs
  `15135cb7960ba23cecc5a3f4708fa2b057f034bfd1c155c6db0301cb2efbfa52`;
* final DT
  `58fa70641900b343c466b815bcadd0cb5269d86df0b4939f436af7c0d2bc6300`.

The initramfs and final DT are byte-identical to v1.  The kernel configuration
changes only the pre-userspace ownership deadline to
`CONFIG_WATCHDOG_OPEN_TIMEOUT=90`; the 31-second hardware timeout, nowayout,
boot-enabled handler, 90-second `/init` lease and five-second panic policy are
unchanged.  The padded image is the exact 6,991,872-byte raw prefix followed
only by zeroes to 16 MiB.  The new fail-closed manifest is
`research/p22-unattended-recovery-watchdog-hostnet-v2.manifest`: its normal
acceptance window is 80 seconds, still strictly shorter than the separate
90-second initramfs lease.  `nix flake check --no-build`, the full Nix image
build and the independent byte-contract checks passed; no v2 hardware action
had occurred at this point.

## Authorized v2 attempt and exact Stage-A recovery: 2026-08-30 05:51--05:58 CEST

The reviewed v2 command was started once:

```text
research/p22-chained-recovery-runner.sh --manifest research/p22-unattended-recovery-watchdog-hostnet-v2.manifest --execute
```

The candidate Flash Tool transaction was boot-only Download Only and reported
`[23] WRITE TO PARTITION [ boot ]`, `Download Succeeded`, and `flash_rc=0`.
Trex captured the candidate USB disconnect, two `0e8d:2000` preloader windows,
and subsequent `0525:a4a2` gadget enumeration.  Candidate acceptance stopped
fail-closed because its per-boot Dropbear ED25519 host key differed from the
stored key (`REMOTE HOST IDENTIFICATION HAS CHANGED`, fingerprint
`SHA256:KIiyjPJnSwS/BW9PopIITtHRzeKS3H3OOqw0+vr0kmc`).  No acceptance marker
was written and no candidate result was certified.

The first interrupted harness left no Flash Tool owner.  An exact Stage-A
rollback was then staged and armed before the next watchdog/preloader window;
a duplicate emergency wrapper was detected and terminated before it acquired
the USB port.  The surviving wrapper connected to BROM, uploaded DA, wrote
only `[23] WRITE TO PARTITION [ boot ]`, reported `Download Succeeded`, and
returned `flash_rc=0` at 05:58:09.  Its log is retained at
`/mnt/Home/src/nixos-gemini-flash-p22-20260829/p22-recovery-20260830-055149/manual-rollback-flash.log`.

Post-recovery readback over both gadget and right-NIC SSH is exact: p22
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, p30
`122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`, and p31
`1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`.
The exact-MAC watcher was stopped after the tool exited; no Flash Tool remains.
This is a recovered failed experiment, not a v2 acceptance.

The harness now externally bounds every SSH/SCP child, permits the ephemeral
candidate host-key policy only when fresh Trex state proves USB `0525:a4a2`,
MAC `42:00:15:19:82:00`, and the exact interface marker, and restores strict
host-key checking for preflight, reboot dispatch, and rollback.  A host-only
regression uses a hanging fake SSH client to prove bounded exit, and a second
fake client proves duplicate Flash Tool ownership is rejected.  `sh -n`,
ShellCheck (only the pre-existing indirect-trap informational notices), and
both regressions pass.  No further hardware action is authorized until root
reviews the host-key fix.

## Acceptance commit-point hardening: 2026-08-30

The failed v2 run exposed a subtle unattended failure boundary: writing
`/run/unattended-recovery.accepted` before a later host-side p30/p31 readback
could leave the watchdog petter alive if that later SSH call failed.  The
harness now performs the candidate p22, p30, and p31 hash checks inside the
single remote `validate_candidate` transaction before atomically creating the
lease marker.  The host-side final readback is evidence-only and best-effort
after the marker; a committed marker cannot fall through to `recover()`.

Normal pre-marker failures remain bounded: candidate host-key mode is disabled,
the rollback tool is armed first, and the initramfs lease expires to expose the
next watchdog/preloader window.  This is explicit in the recovery path and is
not claimed to cover a pre-MTK-watchdog-probe hang.

A fake-SSH state-machine regression forces the post-marker final readback to
fail and verifies that the accepted state is retained and `recover()` is not
called.  The hanging-SSH and duplicate-owner regressions continue to pass.

## Power-preflight v3 dry-run handoff: 2026-08-30

The immutable build-only bundle is present at
`artifacts/mainline-unattended-recovery-power-preflight-p22-v1` with padded
p22 image SHA-256
`2a0fe82213e5e549d12acde3a920427323ccd6d0458d59682b9847b7bf8f4802` and size
16,777,216 bytes.  Its raw boot image is `173a067a69eda6b96c8c3395f727b9373a135040bb17289dc2d3aedff2ae0213`,
initramfs is `41e215ef2563ca9c7ad68a37745f74cd038eb580635d7344e04bc50102048e2`,
and final DT is `ee57546b97a42b22111e632113e9e409ad02ff75dc75c3aace9a9cf9eca7d773`.
The artifact manifest records locked Linux source `1bb2a9863d9a1e6d59e513eddbec68e2866310cd`,
platform baseline `7199e8229c6a805a941e33a6862956949dfebd3a`, and the read-only
BQ2589x preflight observer.

The dry-run handoff is
`research/p22-unattended-recovery-power-preflight-v1.manifest`; its candidate
is p22-only, rollback is the accepted Stage-A image
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, and it
requires both gadget and right-NIC SSH, watchdog evidence, enumeration-only
storage, and the exact BQ pass marker.  The harness dry-run passed at
06:19:26 CEST while live p22/p30/p31 remained the exact Stage-A hashes and
Trex had no Flash Tool.

This manifest declares `transaction_policy=observe-always-rollback`:
persistent acceptance is disabled, and `--execute` without `--proof-lease`
fails before device contact.  An eventual reviewed proof run must validate and
capture BQ/platform/watchdog evidence, arm the exact Stage-A p22 Download Only
rollback before lease expiry, and verify recovery; it must never certify the
power candidate.  The new per-attempt Flash Tool state paths prevent stale
candidate `flash_rc=0` from satisfying rollback waits.  No v3 flash, reboot,
erase, format, upgrade, p30 write, or p31 write has occurred.

## Durable Trex-owned observe/rollback preparation: 2026-08-30

The observe-always-rollback path now acquires a Trex-global transaction flock
(`.p22-transaction.lock`) before image staging and keeps it in a bounded,
systemd-owned transaction-holder service.  Each Flash Tool wrapper separately
uses the Trex-global writer flock (`.p22-flash-writer.lock`), while its state,
PID, and PGID files remain per-attempt.  A reused run directory is rejected by
`mkdir` rather than reused, and the wrapper verifies the transaction-owner
marker before it can write.

Before candidate reboot, the harness stores and re-hashes an immutable
Stage-A p22 rescue copy and starts the Trex-owned
`p22-proof-supervisor.sh` transient service.  For
`transaction_policy=observe-always-rollback`, this supervisor waits the exact
manifest acceptance window, then stages only the verified rescue image and
launches the reviewed boot-only Download Only wrapper.  It never writes an
acceptance marker.  Therefore loss of the workstation harness or Trex SSH
session does not remove the rollback owner; all supervisor and wrapper waits
are bounded and exact process groups are the only timeout kill target.

The supervisor also treats a candidate Flash Tool failure or missing completion
state as potentially partial p22 and enters the same bounded rescue path; it
does not assume that a nonzero writer result means the old image is intact.
Its ready handshake is `supervisor_waiting_candidate`, and the harness requires
that state plus an active Trex unit before dispatching reboot.  Local EXIT/TERM
after that handshake preserves the Trex supervisor, transaction holder, and
watcher so recovery is not cancelled by loss of the workstation process.

The host-only regressions cover fake supervisor rollback (including a failed or
partial candidate), unexpected supervisor exit, nonterminal timing states,
local-exit preservation, different attempt directories contending on one
writer lock, stale owner/state rejection, bounded hanging SSH, duplicate-owner
rejection, and the observe-policy gate.  `sh -n`, ShellCheck at `-S error`, and
`research/p22-recovery-harness.test.sh` pass.
No hardware action was taken while adding this durability layer.  The latest
power-preflight candidate handoff is now v2, padded SHA
`81c1d01bba849ddfd48574739b54d67910a6501c21dcd1755e60916fe7c1a286`; it
remains dry-run/review-only.

The Trex supervisor's terminal proof is intentionally narrower than device
readback: Trex has no Gemini SSH credential, so it proves exact rescue-image
hash, p22-only wrapper completion, and serialized ownership.  The surviving
host harness must then prove device p22/p30/p31 hashes over SSH; inability to
perform that readback remains a manual-reset/readback failure, never an
acceptance.

The prepared command, to be run only after a fresh root execute authorization,
is:

```text
research/p22-recovery-harness.sh --manifest research/p22-unattended-recovery-power-preflight-v1.manifest --execute --proof-lease
```

Expected sequence is: local artifact/scatter/XML checks; Trex transaction
holder and exact-MAC watcher; rescue-copy hash; supervisor ready handshake;
candidate boot-only Download Only p22 write; bounded candidate/BQ/watchdog/
host-net evidence; supervisor-owned always-rollback; preloader/USB capture;
local Stage-A p22/p30/p31 readback; and terminal cleanup.  The runner must stop
on any missing supervisor, tool-owner, preloader, or readback proof.  This
remains a preparation record, not an execution authorization.

The recovery guarantee begins only after Linux `mtk_wdt` probe/handoff; the
Gemini LK lineage nominally arms/kicks a 10-second watchdog, but ATF-to-Linux
persistence is unproven.  A p22 kernel/DT change cannot close this pre-probe
window, so a pre-probe hang remains an explicit manual-reset boundary.

## First durable-supervisor execute audit: Trex state cache and timeout process tree: 2026-08-30

The first durable-supervisor execute attempt failed closed before reboot: local polling did not observe
Trex's `tool_started` state within 20 seconds despite the remote state being
written.  The same run recorded wrapper PID/PGID/SID `1604285`, while GNU
`timeout` created child PGID `1604297`; cleanup therefore killed the wrong
negative-PID group.  Root manually killed the exact child group and reverified
Stage-A p22 plus unchanged p30/p31.

The harness now polls all Trex-owned attempt state through bounded Trex SSH
`cat`, verifies the staged candidate/rollback bytes from Trex immediately
before each writer, and records a per-attempt SID.  The wrapper uses GNU
`timeout --foreground`, keeping normal descendants in the wrapper session;
cleanup validates the exact PID=SID and terminates all processes enumerated in
that SID, with the expected PGID fast path.  The supervisor rollback wrapper
also carries an explicit SID file.

Host-only tests include a real `setsid` + `timeout --foreground` process-tree
topology, Trex-state polling mock, duplicate writer lock, and stale owner/state
cases.  No retry, reboot, or flash was performed for this fix.

The follow-up containment fix records a per-attempt SID for both candidate and
supervisor rollback wrappers.  Cleanup requires an exact session-owner argv
match (the run state or reviewed XML) before enumerating that SID; this avoids
terminating a recycled SID.  Trex state waits now use wall-clock deadlines
around authoritative SSH reads, so a slow/cache-stale shared mount cannot
silently convert `tool_started` into a false launch failure.

The recovery guarantee begins only after Linux `mtk_wdt` probe/handoff; the
Gemini LK lineage nominally arms/kicks a 10-second watchdog, but ATF-to-Linux
persistence is unproven.  A p22 kernel/DT change cannot close that pre-probe
window, so a pre-probe hang remains an explicit manual-reset boundary.

## First durable-supervisor execute audit: unique writer/session ownership: 2026-08-30

No hardware action was taken.  The boot-only XML is now copied to the unique
per-run `RUN_SHARED/download-only-p22.xml`, hash-verified locally and on Trex,
and that path is the argv nonce for both candidate and rescue writers.  The
three bounded diagnostic `timeout` processes are no longer trusted through
generic `*.pid` cleanup; only the exact systemd units and run-specific host-net
watcher are eligible for cleanup.

The flash wrapper records `/proc` starttime in addition to PID/PGID/SID.
Cleanup requires the live attempt-unique XML in the exact session, snapshots
every member, and revalidates each member's current starttime/SID/PGID
immediately before both TERM and KILL.  Supervisor timeout cleanup applies the
same checks and refuses a stale/recycled session.  A same-XML process in a
different session is therefore not signalable by this attempt.

Host-only regressions cover stale diagnostic PIDs, same-XML foreign sessions,
leader-loss cleanup, foreground process topology, and the unique XML/starttime
handoff; shell syntax, strict ShellCheck, and the complete harness suite pass.
The next hardware action remains review-gated; p22-only, Download Only, and
the p30/p31 no-write invariant are unchanged.

## af0259fd observe-always-rollback cycle: 2026-08-30 07:43--07:48

The reviewed candidate was written only to p22.  Trex's candidate log records
BROM and DA connection, `[23] WRITE TO PARTITION [ boot ]`, `Download
Succeeded`, and rc=0 at 07:43:30.  Candidate p22 readback was
`3be59c637d058c7104522dc647b5895abceae1f96b71b1a31e2304a22cc94387`.

Candidate validation failed closed because the required host-net marker
reported `usb-host-net=missing after=60s driver=r8152`; the probe also recorded
the bounded watchdog lease-expired/stopped evidence.  The durable supervisor
armed the exact Stage-A rescue at 07:44:51.  Its Download Only writer completed
rc=0 with `Download Succeeded` at 07:46:40 and terminal rescue verification at
07:46:41.  No p30/p31 write, erase, format, or firmware upgrade occurred.

The local harness recorded `manual_reset_required_supervisor_or_readback` at
07:47:27 because its bounded readback window ended while the rescue boot was
still bringing up USB.  This was not a device loss: gadget `0525:a4a2` returned
at 07:46:59, link became `LOWER_UP` at 07:47:57, and independent SSH readback
then proved p22 `1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`,
p30 `122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`, and
p31 `1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`.
Trex transaction and supervisor units were subsequently absent.  The cycle is
therefore a candidate-rejected, rescue-successful run with a harness timing
diagnosis, not an unrecovered hardware state.

Independent post-run audit corrected the BQ interpretation.  Although the
candidate cpio has no explicit `bin/sh`, `/init` runs
`/bin/busybox --install -s /bin` before starting the helper, so the helper did
execute.  The live pstore contains `GEMINI_BQ2589X_PREFLIGHT` start,
`dmesg_relevant_errors=present`, and
`result=fail reason=dmesg_i2c_or<<<RAM_RW>>>ror` at approximately 49 seconds.
This is a fail-closed dmesg gate, not a BQ silicon identity failure: the old
matcher falsely treated the successful I2C6 field
`clock_validation_failures=0` as an error through its broad `i2c-mt65xx`/`fail`
pattern.  The reviewed correction narrows matching to I2C0/charger context and
resolves the dynamic `*-006b` adapter; the next run must capture the actual
client/property result and pass marker.

The host-net failure has independent kernel evidence: pstore records
`mtk-tphy 11210000.t-phy` failing with `-EBUSY` while requesting
`0x11210800-0x112108ff`, followed by repeated `11200000.usb` `-517` deferred
probes waiting for that PHY.  The required `r8152` interface consequently
never enumerated; this is earlier than DHCP or the host-net script.  The next
candidate therefore needs a reviewed DT/PHY correction (or a narrower host-net
acceptance experiment), plus the BQ interpreter fix, with new immutable image,
DT, initramfs, and manifest hashes.

## d69d558 USB11/BQ corrected bundle dry-run: 2026-08-30 08:06--08:09

The fresh local-source build materialized at immutable Nix output
`/nix/store/y58j7c0fh93chq2c325v0jbk8fy5frdf-gemini-ixoo-mainline-probe-emmc-probe-ssh-usb11-host-platform-display-audio-power-observe-power-preflight-unattended-recovery-bundle`, from platform source revision
`d69d55863b5971c2a8d0f296036fe77b35661447`.  Its padded p22 image is exactly
16 MiB with SHA256
`8b5d1c815bdf02e06f81fedb16c89cdecc2576840f13b1abe548ebe3bdd84329`;
initramfs is `31e331fa7cee16297e9f3ce1ede3ede7cb3c2b4ae444c7eba8042580d9eab890`,
final DT is `8346de103fb76e4b6698ec77b5b8f70b85f657fcc867cb232e7c8091fd1528ce`,
Image is `66dcc4e233fe5e4cfbb396cb5e0e7bc351ee574e8b3e57d07434af06066e18e8`,
Image.gz is `8ad554382ee2c3a3f17265b5924580c03860dbb70eb73f68060577afc8c1eb8b`,
and the kernel-built USB11 DTBO is
`a341e238e2479c6ac3f633c4262f170c6b53dbeec7867b2956fd80f656ff3469`.

Independent DT inspection proves `/t-phy@11210000` is `status=okay` with
`reg=<0x0 0x11210000 0x0 0x800>`, its `usb-phy@11210800` is enabled with
`mediatek,force-a-session-valid`, and `/usb@11200000` is enabled in host mode.
The dormant CONSYS and BTIF nodes remain disabled, and USB11 regulators have
neither `regulator-always-on` nor `regulator-boot-on`.

Independent cpio extraction proves `/init` installs BusyBox applets before
launching `/bin/bq2589x-preflight`; the corrected helper is present, as are
`usb-host-net`, the exact RTL firmware
`5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f`, and the
90-second watchdog-open/lease logic.  Kernel config records
`CONFIG_WATCHDOG_OPEN_TIMEOUT=90`, `CONFIG_WATCHDOG_NOWAYOUT=y`, and
`CONFIG_PANIC_TIMEOUT=5`.

The immutable observe-always-rollback handoff is
`research/p22-unattended-recovery-d69d558-bq-usb11.manifest`; it targets p22
only, with exact Stage-A rollback SHA
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, and
retains the fixed scatter/XML hashes and p30/p31 protections.  Read-only
`research/p22-recovery-harness.sh --manifest research/p22-unattended-recovery-d69d558-bq-usb11.manifest --dry-run`
passed at 08:11.  Live readback remained p22 Stage-A
`1b5f808e494f8c91ec5feedcbce89bf018271b30b87ce3910082cd298d8817dc`, p30
`122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`, and p31
`1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`;
Trex had no p22 writer or transaction/proof unit.  No reboot, flash, or other
hardware write was performed.  This is a review handoff, not authorization.

The pinned-profile rebuild was independently rechecked at
`/mnt/Home/src/nixos-gemini-d69d558-pinned-usb11-bq-preflight`, resolving to
`/nix/store/87j1pdyyhipbvk41lxi1di9qy572nqlw-gemini-ixoo-mainline-probe-emmc-probe-ssh-usb11-host-platform-display-audio-power-observe-power-preflight-unattended-recovery-bundle`.
It is byte-identical for the candidate, DT, initramfs, Image, Image.gz,
config, and USB11 DTBO hashes above; the pinned MANIFEST now records the exact
source revision `d69d55863b5971c2a8d0f296036fe77b35661447`.  The new manifest
was updated to this pinned immutable candidate path and its read-only dry-run
passed again.  Trex had zero `p22-*` units and no writer process; live p22,
p30, and p31 remained the Stage-A/protected hashes above.

The target static aarch64 BusyBox `ip` applet was also run under qemu with the
bundled helper's exact `ip addr replace 192.168.23.70/255.255.255.0` form
against a deliberately nonexistent interface.  It returned only
`ip: can't find device`, not a prefix-parse error, proving dotted DHCP subnet
syntax is accepted without mutating a real host interface.
