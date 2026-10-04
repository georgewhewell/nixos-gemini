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

Normal boot and recovery are the first checks. Hardware watchdog expiry,
ordinary suspend and failed-suspend paths remain to be exercised before image
I/O. Fixed swap needs its own complete GPT write/readback/rollback transaction;
see `STORAGE_QUALIFICATION.md`. A72 offline/on and RTC power-on need validation.

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
