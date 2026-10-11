# Current Gemini hardware status

The installed accepted system is Linux 7.2.9 with GNOME, 200% scaling, a fixed
bottom dock, NetworkManager, ModemManager, Bluetooth, IPv6 and RAM-only zram in
[accepted-baseline.json](accepted-baseline.json).
[Trial 96](desktop-radio-activation-20261011.json) installs the GCC 15.3.0 / binutils
2.46 build with the native modem failure snapshot, hostless PCM bounds fix and
SMS/call applications. Its desktop checks and independent terminal audit pass.
The recorded healthy Linux boot is `11579f72-f9f4-4c86-988d-f5e8069a75f7`;
the modem still fails separately. The no-swap 7.1.3 fallback is preserved
in [baselines](baselines/boot-test-76.json).

| Area | Current conclusion | Evidence and remaining work |
| --- | --- | --- |
| Protected storage, watchdog and native RTC | Working for the recorded checks | [Trial 96 and independent audit](desktop-radio-activation-20261011.json) pass exact image/readback identity, ordinary Nix build and retained data. Native RTC startup/UTC/awake alarms retain [trial 88](desktop-responsiveness-20261011.json) evidence; unchanged RTC behavior is not repeatedly tested during focused desktop updates. |
| Flash-safe paging | Working: RAM-only zram | Trial 85 exercises 128 MiB with exact data, no physical swap, no writeback and zero flash-swap writes. The preserved 7.1.3 fallback uses no swap. |
| Linux 7.2.9 platform port | Working on one maintained kernel | [Kernel record](KERNEL_BASELINE.md). Installed source `ce9fec5` retains RFKILL, directed scanning, modern allowed-AKM admission, supplicant capability handling and cached passive-channel joins; it adds bounded modem failure metadata and the hostless PCM pointer guard. Kernel and development shell use the locked Nixpkgs default compiler (GCC 15.3.0). |
| GPU DVFS | Seven OPPs pass bounded rendering checks | [Trial 88 GPU proof](desktop-responsiveness-20261011.json). Correct clock and voltage readbacks from 238 to 900 MHz, 13 exact pixel checks up/down, 104 job IRQs and no detected GPU faults. Native thermal cooling registers; normal simple_ondemand policy and CPU parking are restored. Sustained thermal load and subjective UI responsiveness remain unqualified. |
| Bluetooth | Desktop radio access and bounded discovery pass | [Trial 94 Bluetooth proof](desktop-radio-activation-20261011.json). GNOME sees an unblocked, powered controller through native RFKILL. A 16-second scan as `gemini` finds 14 RSSI devices, one named, with fresh LE events, all controller statuses successful and zero Bluetooth/WLAN transport faults. No continuous trace runs at boot. Pairing, profiles and the owner's particular target remain unqualified. |
| Onboard stereo playback | Corrected effective hardware mapping | [Audio proof](desktop-radio-activation-20261011.json). Native UCM exposes the onboard sink; PipeWire reports logical FL/FR and hardware FR/FL with ALSA hardware-map override disabled. Plain ALSA speaker/headphone/default paths pass independent sample comparisons. Acoustic orientation remains unverified. |
| GNOME document portal | Working on the installed system | Trial 88 has built-in FUSE, `/dev/fuse`, an active user document portal and its `fuse.portal` mount. The [integration audit](integration-audit-20261011.json) records the missing module autoload on the preceding image. |
| GNOME/GDM, HiDPI, dock and IPv6 | Working for the recorded checks | [Desktop proof](desktop-ui-20261010.json) confirms local Wayland, active 200% scaling and an enabled fixed bottom dock with no extension errors. IPv6 ping and SSH over USB passed on the same kernel/configuration; external IPv6 routing is untested. |
| NetworkManager and ModemManager | Running; wired DHCP and modem discovery verified | [Manager proof](networkmanager-image-20261010.json). Both cross-built daemons and the shared supplicant run, with one imported Wi-Fi profile. USB recovery stays unmanaged; boot no longer requires the wired lab IP. Wi-Fi association and traffic pass on trial 95; cellular data remains unqualified. |
| Wi-Fi scanning and activation | NetworkManager association and traffic pass | [Trial 95 scan, association and data evidence](desktop-radio-activation-20261011.json). Directed/wildcard scans preserve the automatic connection with zero HIF faults/restarts. Three of three ICMP replies pass through wlan0 with zero interface errors/drops. No manual connection or profile changes were made; preferred SSID selection/network switching remain unqualified. Prior cancellation/ten-minute results remain in the [regression proof](wifi-scan-regression-20261011.json). |
| Cellular SIM/eSIM, SMS and voice | Native modem bring-up incomplete | [Trial 96 transport evidence](desktop-radio-activation-20261011.json). HS2 completes, then the modem watchdog fires at 107 seconds without standalone SIM diagnostics. The numeric snapshot reports nine cores and is rejected by the public eight-core decoder; its cause remains unknown. The failed ModemManager SIM initialization does not prove card absence. Continue native control, SIM and speech development. |
| SMS and call applications | Installed; normal daemons running | [Application proof](sms-voice-integration-20261011.json). GNOME Calls, Spacebar and callaudiod use the existing ModemManager/session APIs on trial 96. Cross-runtime and isolated QEMU UI startup checks pass; Calls and the SMS receiver run on the board. Native transport/SIM, speech control and call audio remain unfinished. Delivery and acoustics are unqualified. |
| Normal startup cleanup | No routine hardware test loops during boot | [Startup record](normal-startup-20261010.json). Seven GPU/audio/Wi-Fi/Weston test units are explicit diagnostics. Trial 88 reaches graphical startup in 95.056 seconds, including 50.843 seconds in kernel/initramfs. The old Wi-Fi worker and dhcpcd are retired from the default image. |
| Experimental H.264 decoder | Recorded polling implementation works for tested cases | [Decoder evidence](mt6797-vdec-v4l2/README.md), particularly trials 66–67. Progressive 8-bit I/P/B, Baseline/Main/High and tested multi-slice cases have exact pixel comparisons on their recorded 7.1.3 build. Production IRQ completion, shared hardware surfaces and the rebased module remain open. |
| Decoder IRQ completion | Tested; no interrupt delivered | [Trials 89–90](mt6797-vdec-v4l2/irq-trial-90.json) on the recorded trial-88 build retain GCON `0x111` despite changed CCF votes and deliver zero decoder interrupts across all CPUs. No successful frame was exported. Stop, guards, unload, supervised recovery and independent audit pass. The [clock ownership followup](mt6797-vdec-v4l2/clock-vote-contract.json) remains unqualified; the next module must be rebuilt for the installed kernel. |
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
