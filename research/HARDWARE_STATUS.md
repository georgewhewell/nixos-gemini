# Current Gemini hardware status

The installed accepted system is Linux 7.2.9 with GNOME, 200% scaling, a fixed
bottom dock, IPv6 and RAM-only zram in [accepted-baseline.json](accepted-baseline.json).
[Trial 81](desktop-ui-20261010.json) passed and was kept on the device; the
independent terminal audit passed. Its healthy boot is
`fe38f475-ef36-4a5f-b89f-b6aaeedebe5b`. The no-swap 7.1.3 fallback is preserved
in [baselines](baselines/boot-test-76.json).

| Area | Current conclusion | Evidence and remaining work |
| --- | --- | --- |
| Protected storage, watchdog and native RTC | Working on the installed system | [Trial 81 and independent audit](desktop-ui-20261010.json). Exact image/readback identity, native RTC startup/UTC/awake alarms, ordinary Nix build, retained data and terminal audit pass. The kept image was not rebooted after its explicit clock write. |
| Flash-safe paging | Working: RAM-only zram | Trial 81 exercises 128 MiB with exact data, no physical swap, no writeback and zero flash-swap writes. The preserved 7.1.3 fallback uses no swap. |
| Linux 7.2.9 platform port | Working on one maintained kernel | [Kernel record](KERNEL_BASELINE.md). Source `7eb0d52` includes decoder resources, built-in IPv6 and zram. Earlier feature results remain scoped to their recorded inputs. |
| GNOME/GDM, HiDPI, dock and IPv6 | Working for the recorded checks | [Desktop proof](desktop-ui-20261010.json) confirms local Wayland, active 200% scaling and an enabled fixed bottom dock with no extension errors. IPv6 ping and SSH over USB passed on the same kernel/configuration; external IPv6 routing is untested. |
| Normal startup cleanup | No routine hardware test loops during boot | [Startup record](normal-startup-20261010.json). Seven GPU/audio/Wi-Fi/Weston test units remained unstarted. The kept image reaches graphical startup in 95.061 seconds, including 50.736 seconds in kernel/initramfs. |
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
required supervised recovery protection and final audit remain mandatory;
`--keep` leaves a passing image installed. Retention checks protect
the fixed data/build fixtures and the accepted trial's Nix build; the current
candidate's new output is checked separately. Historical output records no
longer make the admission set grow with every trial. They remain on disk.

The supported build is `nix build` / `nixosConfigurations.gemini`, composed by
`nix/gemini.nix`. Old configurations are in the frozen recovery input. Linux
and U-Boot keep their own source repositories; extra source worktrees preserve
historical diagnostics. The temporary media kernel branch was merged and
deleted locally and remotely. Normal and media development use the same
`gemini-7.2.9` kernel in the maintained default build. Packaging development
uses `master`; its duplicate development branch is also retired.

[Board store cleanup](development-store-cleanup-20261010.json) removed 1,485
unrooted obsolete kernel/system paths, all preserved on the host, freeing
6.1 GiB of filesystem space. Accepted recovery, protected files, retained Nix
outputs and boot entries are unchanged. Trials 77–79 restored the accepted
recovery after their respective startup or assertion failures. Their independent
terminal audits pass; see the recorded trial for its exact boot identities.

The former 966-line chronological status log is preserved in
[history](history/HARDWARE_STATUS-20261010-before-consolidation.md). Its dated
statements describe those trials; this page records the current conclusion.
