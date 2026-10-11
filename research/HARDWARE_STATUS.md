# Current Gemini hardware status

The installed accepted system is Linux 7.2.9 with GNOME, 200% scaling, a fixed
bottom dock, NetworkManager, ModemManager, Bluetooth, IPv6 and RAM-only zram in
[accepted-baseline.json](accepted-baseline.json).
Image 116 uses the GCC 15.3.0 / binutils 2.46 build, native MMC clock admission,
populated error counters and standard eMMC high-speed mode. Its retained-storage,
ordinary Nix build, focused desktop checks and independent terminal audit pass.
Fresh CPU sampling, FUSB301 event suppression and GNSS receive attribution retain
their accepted results. Unchanged Wi-Fi and telephony application inputs retain
their scoped results. The [cellular owner](sms-voice-integration-20261011.json)
records AT failure handling and qualified native SIM-pin ownership; modem stability
and eUICC access remain unfinished.

Experimental media work shares the maintained kernel. Native buffers pass
[trial 106](mt6797-vdec-v4l2/buffers-trial-106.json), and the shared Mesa owner fix
passes the synthetic MM21 rendering check in
[trial 109](mt6797-vdec-v4l2/gpu-trial-109.json). Both restore image 102 and pass
their terminal audits. Decoder IRQ completion, decoded-surface rendering and
encoding remain unfinished. Image 111 installs the shared DMA and Mesa owner
changes in the normal desktop; it does not load the experimental decoder.
Earlier failed trials retain their original records. The no-swap 7.1.3 fallback
is preserved in [baselines](baselines/boot-test-76.json).

| Area | Current conclusion | Evidence and remaining work |
| --- | --- | --- |
| Protected storage, watchdog and native RTC | Working for the recorded checks | [Trial 101 and independent audit](gnss-integration-20261011.json) pass exact image/readback identity, ordinary Nix build and retained data. Native RTC startup/UTC/awake alarms retain [trial 88](desktop-responsiveness-20261011.json) evidence; unchanged RTC behavior is not repeatedly tested during focused desktop updates. |
| Flash-safe paging | Working: RAM-only zram | Trial 85 exercises 128 MiB with exact data, no physical swap, no writeback and zero flash-swap writes. The preserved 7.1.3 fallback uses no swap. |
| Linux 7.2.9 platform port | Working on one maintained kernel | [Kernel record](KERNEL_BASELINE.md). Installed source `47753893` adds protected native SIM-pin selection and preserves zero WWAN open count after removal, retaining standard fatal AT withdrawal, bounded DBM initialization, accepted MSDC/CQHCI recovery and procfs work. Actual-path sanitizer regressions, strict ARM64 objects, normal builds and supervised trial/audit pass. Kernel and development shell use the locked Nixpkgs default compiler (GCC 15.3.0). Experimental codec qualification retains its recorded scope. |
| GPU DVFS | Seven OPPs pass bounded rendering checks | [Trial 88 GPU proof](desktop-responsiveness-20261011.json). Correct clock and voltage readbacks from 238 to 900 MHz, 13 exact pixel checks up/down, 104 job IRQs and no detected GPU faults. Native thermal cooling registers; normal simple_ondemand policy and CPU parking are restored. Sustained thermal load and subjective UI responsiveness remain unqualified. |
| Desktop and CLI performance | Native USB and procfs overhead fixed; responsiveness remains open | [Performance evidence](desktop-responsiveness-20261011.json). Accepted 114 removes unused IRQ-tail work: 40 traced CPU records with zero IRQ-counter lookups, versus 245 per report on 113. Passive 30-second parking CPU is 1.05% of one core versus 3.93%; both windows retain cores 0–1 without transitions. Activity is uncontrolled and UI latency remains unqualified. Policy/cadence and prior native USB/topology fixes are retained. Qualify PMU counters, measured CPU capacities and deep idle; attribute remaining latency. |
| eMMC timing | Standard high speed and checked recovery installed; recorded storage checks pass | [Native MMC evidence](desktop-responsiveness-20261011.json). Image 114 requests 52 MHz and runs at 47,999,984 Hz on the unchanged 8-bit bus, pads and supplies. All 15 native counters stay zero around retained storage and one ordinary Nix build; independent audit passes. Bounded reset/FIFO/STOP and MSDC/CQHCI lifetime regressions pass; no hardware recovery fault is claimed. Sustained storage, physical isolation and generic CQE error propagation remain open. |
| Bluetooth | Desktop radio access and bounded discovery pass | [Trial 94 Bluetooth proof](desktop-radio-activation-20261011.json). GNOME sees an unblocked, powered controller through native RFKILL. A 16-second scan as `gemini` finds 14 RSSI devices, one named, with fresh LE events, all controller statuses successful and zero Bluetooth/WLAN transport faults. No continuous trace runs at boot. Pairing, profiles and the owner's particular target remain unqualified. |
| Onboard stereo playback | Corrected effective hardware mapping | [Audio proof](desktop-radio-activation-20261011.json). Native UCM exposes the onboard sink; PipeWire reports logical FL/FR and hardware FR/FL with ALSA hardware-map override disabled. Plain ALSA speaker/headphone/default paths pass independent sample comparisons. Acoustic orientation remains unverified. |
| GNOME document portal | Working on the installed system | Trial 88 has built-in FUSE, `/dev/fuse`, an active user document portal and its `fuse.portal` mount. The [integration audit](integration-audit-20261011.json) records the missing module autoload on the preceding image. |
| GNOME/GDM, HiDPI, dock and IPv6 | Working for the recorded checks | [Desktop proof](desktop-ui-20261010.json) confirms local Wayland, active 200% scaling and an enabled fixed bottom dock with no extension errors. IPv6 ping and SSH over USB passed on the same kernel/configuration; external IPv6 routing is untested. |
| NetworkManager and ModemManager | Running; wired DHCP and modem discovery verified | [Manager proof](networkmanager-image-20261010.json). Both cross-built daemons and the shared supplicant run, with one imported Wi-Fi profile. USB recovery stays unmanaged; boot no longer requires the wired lab IP. Wi-Fi association and traffic pass on trial 95; cellular data remains unqualified. |
| Wi-Fi scanning and activation | NetworkManager association and traffic pass | [Trial 101](gnss-integration-20261011.json) directed/wildcard scans preserve automatic association with zero HIF faults/restarts or shared-radio fences after GNSS power cycles. [Trial 95](desktop-radio-activation-20261011.json) passes three of three ICMP replies through wlan0 with zero interface errors/drops. Native detach-before-notify teardown passes host race checks; preferred SSID selection/network switching remain hardware-unqualified. No manual connection or profile changes were made. Prior cancellation/ten-minute results remain in the [regression proof](wifi-scan-regression-20261011.json). |
| Cellular SIM/eSIM, SMS and voice | AT lifetime and SIM-pin ownership fixed; native modem bring-up incomplete | [Cellular owner](sms-voice-integration-20261011.json). Installed116 reaches READY, then watchdog failure; standard AT HUP/ERR and six protected SIM-pin claims pass. The generic AT lpa-gtk/lpac candidate is source-integrated and cross-built, but117 failed healthy boot and audited rollback restored116. No candidate LK metadata/AT observation or watchdog cause was established. The next candidate adds native configured-policy precedence (public Gemini12, not discovered hardware capability) and standard typed-AT active-seat access. Installation, eUICC APDUs, provisioning, SMS and speech remain unqualified. |
| SMS and call applications | Installed; normal startup verified on trial 96 | [Application proof](sms-voice-integration-20261011.json). GNOME Calls, Spacebar and callaudiod use the existing ModemManager/session APIs. Their package inputs retain trial 96 startup evidence; image 101's full cross-runtime check passes. Native transport/SIM, speech control and call audio remain unfinished. Delivery and acoustics are unqualified. |
| GNSS | Native power lifetime and receive attribution pass; reception remains absent | [Trial 112 proof](gnss-integration-20261011.json) and [owner record](../campaign/13-gps-gnss.md). The existing CONSYS/STP owner and standard `lna-supply` pass whole-frame admission and teardown checks. Two 10-second opens/closes pass LNA off/on/off, zero taint and subsequent Bluetooth/NetworkManager checks. Both windows and CRC-valid/admitted/inactive/rejected frame counts stay zero. No validated task-2 frame reaches the selected boundary; malformed traffic before CRC is not excluded. Public receiver output/initialization, framing, position, sustained coexistence and suspend remain unfinished. |
| Normal startup cleanup | Hardware tests are explicit; obsolete RTC presence service removed | [Startup record](normal-startup-20261010.json). Accepted 114 removes the per-boot M39 presence check and its udev-settle dependency, preserving rendered logind policy and the exact recovery build. Six diagnostic service entrypoints and GNOME cross checks pass; unchanged RTC acceptance is reused. Recorded graphical startup is 95.056 seconds on trial 88, including 50.843 seconds in kernel/initramfs; no new boot-time speedup is claimed. The old Wi-Fi worker and dhcpcd are retired. |
| Native tiled GPU import and rendering | Working for the recorded synthetic 80×64 fixture | [Trial 109](mt6797-vdec-v4l2/gpu-trial-109.json) fixes the backing-plane image bounds in the shared Mesa owner. All 5,120 BT.601 pixels pass with the original RGB tolerance of 2 and exact alpha; parent/video/export release, caller FD closure, EGL/GL teardown and module unload pass. Six GPU job IRQs progress with no detected faults; zero codec jobs are submitted. Recovery and the independent audit pass all 65 source hashes. Actual decoded frames, display scanout and sustained playback remain unqualified. |
| Experimental H.264 decoder | Recorded polling cases work; native buffer API, mapping and lifetime pass on hardware | [Decoder owner](mt6797-vdec-v4l2/README.md). Trials 66–67 compare progressive 8-bit I/P/B, Baseline/Main/High and tested multislice pixels exactly on their recorded 7.1.3 builds. [Trial 106](mt6797-vdec-v4l2/buffers-trial-106.json) adds nine CREATE_BUFS cases to 17 native objects, 34 FDs, Panfrost PRIME mappings, cache transitions and release lifetime with zero codec/GPU submissions. Strict ARM64 builds and sanitizer failure regressions also pass. Four obsolete probes are retired to Git history. Decoder IRQ completion, GPU rendering of decoded surfaces, display imports and suspend remain unqualified. |
| Decoder IRQ completion | Tested; no interrupt delivered | [Trial 103](mt6797-vdec-v4l2/irq-trial-103.json) uses the exact image-102 kernel. Native SPI 240 setup/polarity acceptance passes; a compressed grey picture completes in AVC with ACTIVE clear (`0x101`), zero syntax error and zero IRQ delta across all ten CPUs. Stop, guards, unload, supervised return to image 102 and independent audit pass. This uses the earlier private-DMA backend; no successful frame or replacement-buffer path is qualified. Exact done-source enablement/handshake remains unfinished. |
| Video encoding | Unfinished | [Encoder owner work](mt6797-venc/README.md) requires the public frame-programming contract and one independently decoded intra frame. Unused command-free probes are retired to Git history; their source and evidence are preserved. No encoded frame has been produced. |
| Suspend/hibernation | Unqualified; hibernation disabled | Earlier post-hibernation GPU/Wi-Fi faults prevent qualification for normal use. Camera and vibrator are outside the requested scope. |

## Acceptance and testing

Call a feature working when its stated acceptance checks pass for the recorded
kernel, DTB, userspace and driver build, with recovery and the terminal audit
complete. Keep that evidence as the accepted result. Host compilation qualifies
a build; it does not qualify hardware behavior.

Fix a failure in the driver or subsystem that owns the contract. Remove replaced
implementations and stale options as the working path is integrated. Keep one
default stack; experimental results belong in their recorded history. A
userspace workaround does not qualify an unfinished driver.

Record remaining owner work here and return to it: GNSS needs its public
initialization/data-delivery contract, then stream, position and sustained
coexistence qualification; passing power cycles do not prove a fix.
Desktop/CLI performance needs remaining native governor/workqueue cost and
user-visible latency attributed. Accepted 114 qualifies the native procfs
CPU-prefix fix and its bounded owner-cost observation; repeat it for changed
behavior or regression. Checked MSDC/CQHCI reset/FIFO/STOP ownership is installed,
with no observed hardware recovery fault. Finish sustained storage, physical
isolation and generic CQE recovery error propagation. Qualify
native PMU counters before measured A53/A72 scheduling capacities,
and a proper deep-idle owner. Cellular watchdog/SIM/speech and
media completion remain open as recorded above.

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
The trial-105 preparation removes another 1,062 unrooted development paths,
all present on the host, freeing 1.4 GiB. Accepted, witness, candidate and
unpreserved dependency closures are excluded; trial 105 audits their retention.

The closure audit identifies a packaging follow-up: move GLib's runtime schema
compiler to its `bin` output and update GNOME's runtime path; separate GI
development generators from Orca/GDM Python wrapper dependencies. Multiple
routes retain a 142 MB host Python, so fixing GNOME alone cannot remove it all.
This belongs in GLib/GI package output and wrapper ownership. Native build-tool
interpreters must remain native; verify both target runtime helpers and the
reachable closure after the correction.

The former 966-line chronological status log is preserved in
[history](history/HARDWARE_STATUS-20261010-before-consolidation.md). Its dated
statements describe those trials; this page records the current conclusion.
