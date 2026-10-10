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
