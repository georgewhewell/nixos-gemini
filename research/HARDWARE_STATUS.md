# Current Gemini hardware status

The installed accepted system is Linux 7.2.9 with GNOME, 200% scaling, a fixed
bottom dock, NetworkManager, ModemManager, Bluetooth, IPv6 and RAM-only zram in
[accepted-baseline.json](accepted-baseline.json).
[Trial 88](desktop-responsiveness-20261011.json) installed the GCC 15.3.0 / binutils
2.46 build and passed the independent terminal audit. Its healthy boot is
`d7373628-30ae-4161-826a-4dca951d2156`. The no-swap 7.1.3 fallback is preserved
in [baselines](baselines/boot-test-76.json).

| Area | Current conclusion | Evidence and remaining work |
| --- | --- | --- |
| Protected storage, watchdog and native RTC | Working on the installed system | [Trial 88 and independent audit](desktop-responsiveness-20261011.json). Exact image/readback identity, native RTC startup/UTC/awake alarms, ordinary Nix build, retained data and terminal audit pass. The kept image was not rebooted after its explicit clock write. |
| Flash-safe paging | Working: RAM-only zram | Trial 85 exercises 128 MiB with exact data, no physical swap, no writeback and zero flash-swap writes. The preserved 7.1.3 fallback uses no swap. |
| Linux 7.2.9 platform port | Working on one maintained kernel | [Kernel record](KERNEL_BASELINE.md). Source `a25cb83` includes decoder resources, built-in IPv6, FUSE and zram, GPU DVFS and nonfatal Wi-Fi scan cancellation. Kernel and development shell use the current locked Nixpkgs default compiler (GCC 15.3.0). Earlier feature results remain scoped to their recorded inputs. |
| GPU DVFS | Seven OPPs pass bounded rendering checks | [Trial 88 GPU proof](desktop-responsiveness-20261011.json). Correct clock and voltage readbacks from 238 to 900 MHz, 13 exact pixel checks up/down, 104 job IRQs and no detected GPU faults. Native thermal cooling registers; normal simple_ondemand policy and CPU parking are restored. Sustained thermal load and subjective UI responsiveness remain unqualified. |
| Bluetooth | Registers and powers on automatically | [Bluetooth proof](bluetooth-integration-20261011.json). Normal boot registers hci0 before BlueZ, with no always-on HCI trace. Discovery observed 12 nearby devices on the preceding accepted kernel; pairing and profiles remain unqualified. |
| GNOME document portal | Working on the installed system | Trial 88 has built-in FUSE, `/dev/fuse`, an active user document portal and its `fuse.portal` mount. The [integration audit](integration-audit-20261011.json) records the missing module autoload on the preceding image. |
| GNOME/GDM, HiDPI, dock and IPv6 | Working for the recorded checks | [Desktop proof](desktop-ui-20261010.json) confirms local Wayland, active 200% scaling and an enabled fixed bottom dock with no extension errors. IPv6 ping and SSH over USB passed on the same kernel/configuration; external IPv6 routing is untested. |
| NetworkManager and ModemManager | Running; wired DHCP and modem discovery verified | [Manager proof](networkmanager-image-20261010.json). Both cross-built daemons and the shared supplicant run, with one imported Wi-Fi profile. USB recovery stays unmanaged; boot no longer requires the wired lab IP. Wi-Fi association and cellular data remain unqualified. |
| Wi-Fi scan cancellation | Controlled cancellation and ten-minute boot observation pass | [Wi-Fi regression proof](wifi-scan-regression-20261011.json). One NM scan/AbortScan drains to an aborted completion after 2.66 seconds without restarting WLAN. All 26 samples through 601.70 seconds uptime retain the interface with zero HIF faults/restarts. Association and data transfer remain unqualified. |
| Normal startup cleanup | No routine hardware test loops during boot | [Startup record](normal-startup-20261010.json). Seven GPU/audio/Wi-Fi/Weston test units are explicit diagnostics. Trial 88 reaches graphical startup in 95.056 seconds, including 50.843 seconds in kernel/initramfs. The old Wi-Fi worker and dhcpcd are retired from the default image. |
| Experimental H.264 decoder | Recorded polling implementation works for tested cases | [Decoder evidence](mt6797-vdec-v4l2/README.md), particularly trials 66–67. Progressive 8-bit I/P/B, Baseline/Main/High and tested multi-slice cases have exact pixel comparisons on their recorded 7.1.3 build. Production IRQ completion, shared hardware surfaces and the rebased module remain open. |
| Decoder IRQ completion | Tested; no interrupt delivered | [Trial 86](mt6797-vdec-v4l2/irq-trial-86.json) times out with zero delivered interrupts; masked/pending/active snapshots are zero. No successful frame was exported; the raw error-buffer comparison failed. Stop, guards, unload, supervised recovery and independent audit pass. The [clock-vote experiment](mt6797-vdec-v4l2/clock-vote-contract.json) addresses a conflict with the public ISR guard and remains unqualified. |
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
