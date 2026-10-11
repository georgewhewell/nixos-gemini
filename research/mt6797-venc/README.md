# MT6797 encoder resource diagnostic

`resource-probe.c` is an original GPL-2.0-only, command-free bring-up module.
It is not an encoder implementation. Its interface facts come from the public
MT6797 register table, public Linux clock/device-tree definitions and the
resource ownership established by the decoder diagnostics. See the
[interface ledger](../mt6797-video-interface.json) for source provenance.

Build `mt6797_venc_resource_probe.ko` with Kbuild against the matching configured
candidate kernel. The probe borrows the disabled encoder node's VENC power
domain after binding its private platform device and obtains encoder/bus clock
references from the public VENC clock provider. Larb3 remains owned by its real
SMI supplier, which already serves JPEG on Gemini. It requires the
Gemini board and a disabled encoder node; it does not configure IOMMU ports or allocate
DMA storage. It snapshots only the documented encoder chip-enable, dynamic
clock and local clock-control registers at offsets `0xec`, `0xf4` and `0xfc`.
It writes no encoder registers and releases its clock and power votes before
exposing the cached result.

In a supervisor-owned experimental boot, load the module, read
`/sys/bus/platform/devices/mt6797-venc-resource-probe/result`, and unload it
normally. Successful compilation alone does not qualify resource access.
Neither register snapshots nor a successful power cycle qualify video encoding.
The frame-programming contract is still missing from the examined public
documentation and GPL resource drivers; no proprietary codec source, library
or firmware is used here.

The first hardware attempt in trial 34 rejected an assumption that larb3 was
disabled, returning EBUSY before encoder register access. Trial 35 qualifies the corrected resource ownership: both clock APIs report
325 MHz, global clock status is `0x11`, chip-enable is zero, local DCM is one,
and local gate control is `0xffffffff`. Power-vote release, normal unload and
supervisor/recovery/audit pass. These are command-free resource observations,
with no encoded output or hardware frame command.

A usable direct encoder backend still needs the source-plane address and pitch
fields, reference/reconstruction layout, bitstream address and limit fields,
scratch sizes and address units, picture geometry/QP controls, start sequence,
and completion/error/stop conditions. The public
[2016 MT8173 encoder patch](https://lkml.indiana.edu/hypermail/linux/kernel/1602.2/05539.html)
reads the output byte count at `0x98` but delegates SPS, PPS and frame commands
to the VPU. Its register-write helper is unused. That supplies no direct frame
setup to port. The
[public Chromium EC handler](https://chromium.googlesource.com/chromiumos/platform/ec/+/08f5a1e6fc2c9467230444ac9b582dcf4d9f0068/baseboard/mtscp-rv32i/venc.c)
is a stub unless a private overlay is present. These findings are limited to
the inspected sources; they do not establish that MT6797 requires firmware.

The [April 2026 common encoder interface proposal](https://lists.openwall.net/linux-kernel/2026/04/23/383)
also delegates SPS, PPS and frame commands to `vpu_enc_encode`. It supplies plane
and bitstream addresses through shared firmware parameters and reads the byte
count at `0x98`. It provides no direct MT6797 frame-register contract. The
archived source hashes and this limited finding are recorded in
[the source lead](encoder-common-interface-20260423-lead.json).
Its current owner review records exact pinned GPL source lines and hashes,
the missing frame contract and the next step: establish MT6797-compatible
frame programming before implementing and qualifying one fixed-QP intra frame.

The resource probe also passes in trials 36–41, with normal unload and released
power votes. Trial 38 separately misses the supervisor's final RTC alarm; that
failure remains recorded. No trial produces an encoded picture.

Trials 47–51 also pass the command-free resource probe with normal unload and
released power votes. Trials 49/50 qualify weighted and multiple-reference
decoder pictures and pass the full RTC/system/recovery/audit checks. The encoder frame contract remains
unfinished; these results produce no encoded picture.

Trial 51 also qualifies listed B decoder pictures and passes full system
recovery and audit. Its encoder probe still performs no encoder register
writes, DMA fetches or frame commands; hardware encoding remains unfinished.

Trial 56 completes the command-free resource probe with released votes and
normal unload. Its decoder media suite passes; the separate system profile
fails the final RTC alarm, and the recovered boot's strict audit finds a Wi-Fi
HIF fault. The accepted boot image and codec cleanup are verified. No encoder
frame command, DMA or encoded output is qualified by this result.

Trial 57 passes the same command-free probe, with normal unload, the full
RTC/system profile and a clean accepted-board recovery audit. Its additional
POC-type decoder fixtures do not program the encoder. The direct encoder
frame contract and encoded output remain unfinished.

Trial 67 repeats the same command-free probe while checking the corrected
decoder module. Released power votes, normal unload, full RTC/system checks
and the strict accepted-board recovery audit pass. No encoder DMA, frame
command or encoded picture is qualified.

The separate [`idle-reset/probe.c`](idle-reset/probe.c) diagnostic now builds
against Linux 7.2.9 with matching generated symbols and strict MODPOST.
It has not been loaded on hardware. It attempts three bounded idle pause/reset
cycles using the public GPL reset/IRQ glue, records attempted and completed
cycles separately, and verifies restoration of the original control words.
If it cannot restore controls after writing them, it retains module, clock and
power ownership until the supervised reboot. It programs no frame addresses,
picture state or encode command. A successful idle reset would still leave
active DMA stop, IRQ delivery and encoded output unqualified. Build provenance
is in [`idle-reset/build.json`](idle-reset/build.json).
