# Current Gemini hardware status

The installed recovery is the accepted no-swap Linux 7.1.3 system in
[accepted-baseline.json](accepted-baseline.json). The development system is
Linux 7.2.9 with GNOME and LZ4 zram. These are separate, deliberate roles.

| Area | Current conclusion | Evidence and remaining work |
| --- | --- | --- |
| Recovery, protected storage, watchdog and native RTC | Working on the accepted recovery | [Trial 76 and independent audit](ram-only-recovery-hardware-20261010.json). Both image writes/readbacks, distinct boots, RTC startup/UTC/alarms, persistent Nix build and final audit pass. No further baseline trial is needed for this image. |
| Flash-safe recovery paging | Working: no swap | Swap is disabled from boot, zswap is off, disk resume is unset, generated masks are present, and p34 receives zero writes. This temporary kernel has no zram. |
| Linux 7.2.9 platform port | Earlier port qualified; current zram change built | [Kernel record](KERNEL_BASELINE.md). The current RAM-only kernel needs its first device qualification. Old disk-backed paging results do not qualify zram. |
| GNOME/GDM and normal zram policy | ARM64 build and inspected runtime paths pass | [Runtime record](gnome-cross-runtime-20261010.json): 711 ELF files and 90 script checks, zero foreign ELF files; three helper CLI checks pass under QEMU. Normal and media bundles build. Desktop and zram need their first device qualification. |
| Experimental H.264 decoder | Recorded polling implementation works for tested cases | [Decoder evidence](mt6797-vdec-v4l2/README.md), particularly trials 66–67. Progressive 8-bit I/P/B, Baseline/Main/High and tested multi-slice cases have exact pixel comparisons on their recorded 7.1.3 build. Production IRQ completion, shared hardware surfaces and the rebased module remain open. |
| Decoder IRQ completion | Host candidate built | [IRQ build](mt6797-vdec-v4l2/irq-build-20261010.json). Strict ARM64 MODPOST and `W=1` pass. Actual delivered done IRQs are unqualified. |
| Video encoding | Unfinished | Resource and idle/reset probes exist; no encoded frame has been produced. |
| Suspend/hibernation | Unqualified; hibernation disabled | Earlier post-hibernation GPU/Wi-Fi faults prevent qualification for normal use. Camera and vibrator are outside the requested scope. |

## Acceptance and testing

Call a feature working when its stated acceptance checks pass for the recorded
kernel, DTB, userspace and driver build, with recovery and the terminal audit
complete. Keep that evidence as the accepted result. Host compilation qualifies
a build; it does not qualify hardware behavior.

Run tests for changed behavior, an observed regression or a specific unmet
acceptance check. Reuse existing results when their relevant inputs are
unchanged. Documentation, archival cleanup and build aliases need no hardware
trial. Kernel, boot, storage or shared resource changes justify the applicable
integration checks. Do not run another baseline cycle simply to reconfirm an
unchanged accepted image. Diagnostic watchdog/PM runs are explicit experiments.

Ordinary boot trials use `tools/test-boot.py` with the durable supervisor. Its
required recovery and final audit remain mandatory. Retention checks protect
the fixed data/build fixtures and the accepted trial's Nix build; the current
candidate's new output is checked separately. Historical output records no
longer make the admission set grow with every trial. They remain on disk.

The supported build is `nix build` / `nixosConfigurations.gemini`, composed by
`nix/gemini.nix`. Old configurations are in the frozen recovery input. Linux
and U-Boot keep their own source repositories; extra source worktrees serve
preserved diagnostics or the experimental media branch. New features belong
in the maintained default build.

[Board store cleanup](development-store-cleanup-20261010.json) removed 1,485
unrooted obsolete kernel/system paths, all preserved on the host, freeing
6.1 GiB of filesystem space. Accepted recovery, protected files, retained Nix
outputs and boot entries are unchanged. The current media system is staged
and rooted in the normal store; it has not been booted.

The former 966-line chronological status log is preserved in
[history](history/HARDWARE_STATUS-20261010-before-consolidation.md). Its dated
statements describe those trials; this page records the current conclusion.
