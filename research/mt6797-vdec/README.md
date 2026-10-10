# Independent MT6797 H.264 implementation

This directory contains original GPL-2.0-only control translation, temporary
kernel diagnostics and independently verified H.264 fixtures. It does not expose
a video device or decode a frame. Encoding is not implemented.

The decoder target is the Linux V4L2 stateless Request API, initially progressive
8-bit 4:2:0 H.264. GStreamer `v4l2codecs` is the userspace integration target.
There is no proprietary codec firmware or `libvcodec` dependency in this work.
The installed Gemini system continues to use its qualified kernel; the probe
is an external module loaded temporarily for experiments.

Interface facts and pinned source hashes are recorded in
[mt6797-video-interface.json](../mt6797-video-interface.json). The public
MT8173 GPL kernel hardware test interface at revision
`7cdf75e7ac0ba7009ff98fe71b291b118f634e77` supplies candidate register fields.
Its seven H.264 bank bases match the published MT6797 functional specification.
That match does not prove frame-programming or output-layout compatibility.
No proprietary codec source or binary disassembly was used. The implementation
has not been developed through a formally separated clean-room organization.

## Implemented code

`mt6797-h264-controls.c` consumes the public Linux controls and produces candidate
SPS/PPS words, progressive I/P/B slice-header words and 56 scaling SRAM words.
It checks dimensions, control ranges, signed fields and unsupported features
before changing output. The Linux 8x8 scaling-list order is explicitly preserved:
Intra Y and Inter Y are entries 0 and 1. Header generation does not implement
reference-buffer binding, picture-list programming, bitstream fetch or decode.
The first macroblock index is limited to the 13-bit range exercised by the
public reference interface until the wider field is qualified.

`test-mt6797-h264-controls.c` checks independent register-word fixtures, signed QP
values, invalid controls, output preservation, SRAM locations and byte order.
Run with a native C compiler and the target kernel source:

```sh
CC=gcc bash research/mt6797-vdec/test.sh /path/to/linux
```

`probe.c` claims the decoder MMIO range on Gemini only. It borrows the disabled
larb1 node's clock and power-domain descriptions after its private driver binds.
It obtains a runtime power vote, enables the bus/active/engine clocks through
the clock framework, captures register values, releases clocks and power, and
exposes the saved result in a read-only sysfs attribute. It allocates no DMA
buffers, registers no IRQ and never issues FIFO-fetch or frame-start commands.

With `test_controls=1`, the probe requires an unused core, holds the documented
VLD software-reset bit, selects the candidate H.264 local clock and enables the
AVC parser. It tests three SPS/PPS/reference-count registers, restores their
values and the parser/clock selection, then releases power. A completed mismatch
is reported as an error in the saved JSON. Register readback is not proof of
successful decoding. The borrowed-node technique is a temporary diagnostic;
an actual driver needs its own resource, power, IRQ and IOMMU description.

On Gemini, the configured 338 MHz rate, global SMI clock vote and candidate local selector roundtrip
`0 -> 2 -> 0` were observed. SPS/PPS/reference-count and parser-enable readback
remained zero, so this probe did not establish their compatibility. The public
reference reads status fields from the control register and does not read back
SPS/PPS; zero readback may reflect write-only fields or missing initialization.
Later input tests also found both local power-down masks initially `0xffffffff`.
The early probe does not initialize these masks. Its saved diagnostic error means
expected readback was not obtained, not that
an actual decode failed. No decode was attempted. Raw evidence is under
`handoff/video-cleanroom-20261009`, with separate directories for earlier attempts.

`fifo-probe.c` uses a separate experimental DT device with its own seven MMIO
banks, power domain, clocks, interrupt description and ten larb1 IOMMU ports.
The isolated kernel branch `gemini-video-cleanroom` at `e87e65549920` enables the
existing VDECSYS clock provider and larb1. This candidate is not installed as the
accepted default. The old borrowed-node probe refuses to run with larb1 enabled.

The FIFO diagnostic requires an attached IOMMU domain and checks the SMI driver's
hardware MMU mask while its supplier holds power. `fetch=0` only records resources.
With `fetch=1 frame=0`, it allocates private coherent input and parser scratch buffers,
initializes the candidate parser and issues an input-fetch command. It compares
two known words through the barrel shifter; it never issues a frame-start command
or enables frame-output DMA. It disables global and local automatic clock-off
using the published MT6797 controls. Polls are bounded. The current version checks
both documented break acknowledgements and idle reset before releasing buffers.
Failed stop acknowledgement keeps DMA mappings, runtime power, clocks and the
module pinned until the supervised trial reboots;
the diagnostic does not free potentially active DMA buffers. Bind/unbind attributes
are suppressed. Do not force-unload it or start another decoder experiment during
a fenced test. Neither initial fetch completion nor a successful reset readback
alone is a DMA-quiescence proof. The first four fetches timed out and never met
their initial-fetch/reset condition, so all four retained their DMA mappings.
The fifth fetch also timed out, but documented stop acknowledgement `0x11` and
idle reset passed; its mappings, power and clocks were released normally.

`all_clocks=1` clears both local power-down masks under reset to test their role;
the alternative H.264 masks come from the pinned related-core interface. These
are experimental diagnostics, not production driver options. The current DMA
mask limits this test to addresses below 1 GiB; it does not establish the actual
hardware address width. A trailing mapped guard keeps the exclusive FIFO end
below the aperture boundary as well; all input and guard bytes are checked.
Per-attempt source and binary hashes accompany raw results
under `handoff/boot-test-video-fifo-*/fifo-probe`.

`minimal_clocks=1` uses the bus vote plus the larb supplier's clocks, following
the public MT6797 kernel resource sequence. The alternative also votes for the
clock provider's active and engine entries. `clear_legacy=1` clears the lower
legacy power-down controls while preserving the upper fields. These candidate
sequences need input comparison; none is treated as a working decoder interface.

`supplier-probe.c` snapshots the existing power-controller, VDEC PLL and top-mux
registers without writes. Its saved module parameter contains seven words in
that order (power control, both domain statuses, PLL control/PCW/power, mux).
Run it while `fetch=0 hold_resources=1` holds the FIFO diagnostic's resource vote;
unload the supplier snapshot first, then the resource holder. `hold_resources`
is rejected with `fetch=1`. A supplier-register snapshot is not a measured
clock frequency or a hardware-video test.

The current FIFO diagnostic completes each register write with the kernel's
arm64 `mb()` (DSB SY), matching the public interface's synchronization primitive.
Attempt directories retain the exact source used before and after this change.
MT6797's required interrupt-clear mode bit is set during input initialization;
no clear pulse or IRQ handler is used. The legacy JSON field `dma_started` means
the software issued its fetch command, not that a hardware transfer was observed.

Nineteen initial fetches timed out. Four subsequent trial-12 fetches compared
all known barrel words exactly after clearing MISC `0xf4` bit 0. All eight
bus-only trial-07 fetches, including the
corrected padded allocation, acknowledged break/idle and unloaded normally.
The supplier snapshot observes power control `0xe0d`, PLL control `0x121`,
PCW `0xd0000`, PLL power `0x80000001` and mux `0x81010100`. The matching public
MT6797 power driver uses SRAM PDN bit 8 and ACK bit 12, as does the current
framework. The other set bits are not evidence that additional SRAM banks need
enabling. These supplier observations alone do not establish input transfer.

The public MT6797 resource driver maps codec registers using
`pgprot_noncached`, which is Device-nGnRnE in its arm64 architecture code. Current
arm64 default `ioremap` uses Device-nGnRE, allowing early write acknowledgement.
The FIFO diagnostic uses the resource-managed non-posted mapping by default to
match the vendor attributes. All four trial-08 fetches with this mapping still
timed out; stop acknowledgement, buffer guards and normal unload passed.

The separate common-SRAM reset in the public caller pulses VLD `0x2ec` bit 8;
it is different from the input reset at `0x108`. `common_reset=1` tests that
initialization before input commands. `async_write=1` also tests the older
interface's write-pointer enable at VLD `0xd0` bit 18, after input reset. Its
buffer barrier and software DMA fence precede that potentially active write.
Both trial-09 variants timed out, acknowledged stop and left all guards intact.
Trial-09's system qualification failed the first RTC alarm interrupt-count
check; the input tests do not qualify that candidate for installation.

`clock-probe.c` measures the public MT6797 CKGEN channels for AXI, VDEC and MM
while a separate resource-only consumer holds power. It changes only the idle
frequency meter's debug controls and restores them after bounded polling.
The shared divider, clock muxes, PLLs and power controls are not changed. Raw
counts and counter-input rates use 1,024 cycles of the 26 MHz reference; rates
are after the existing meter divider. No upstream divider encoding is assumed.
Initial trial-09 diagnostics refused before writes because the first version
required a zero divider; its saved state shows divider setting 1. That refusal
is not a clock-frequency measurement or hardware-video result.

The revised resource-only trial-11 diagnostic records counts `3072,6656,6400`
for AXI/VDEC/MM, corresponding to counter-input rates `78,169,162.5` MHz after
the unchanged divider field 1. Meter controls restore exactly. These observations
establish clock-signal presence at the meter, without inferring an upstream
divider encoding, input transfer or hardware frame output.

That trial also observes MISC `0xa8=0`, `0xf4=1` and global clock/reset words
`0x111/1` before any input initialization. The public common caller clears
MISC `0xf4` bit 0. `clear_caller_gate=1` tests that single operation before
input reset, preserving other bits and restoring the original word after
documented stop/idle. All four trial-12 local/legacy mask combinations passed
known-word input comparison, both stop acknowledgements, buffer guards and
normal unload. The full hardware field meaning and frame compatibility are not
inferred. That trial failed the final RTC alarm interrupt-count check and does
not qualify the candidate for installation. No frame was submitted.

## Independent frame reference

`frame=1 fetch=1 clear_caller_gate=1` adds a private single-frame diagnostic
after the known-word input comparison. It stops input before replacing its
bytes with the original fixture. Output, motion-vector, prediction and both
wrapper buffers have trailing guards; all destinations exist before hardware
configuration. Polls are bounded. Unproven stop retains every mapping, clock
vote and the module until supervised reboot. No V4L2 node is exposed.

The read-only `frame_result` attribute records the software submission,
completion/error/IRQ words and guard checks. `frame_output` contains a CPU
snapshot made only after documented stop and idle reset; it never exposes a
live DMA mapping. A done bit alone is not a decoded-frame comparison. The
supervised trial and independent NV12/MM21 comparisons remain required.

Trials 13/14 submitted I_PCM but timed out without changing any output bytes.
Trial 14 read back the SPS/PPS/slice, geometry and output/wrapper registers
correctly, with all three decoder clock votes and the public H.264 masks.
Both trials passed input, guards, documented stop and normal unload. Register
readback does not establish a decoded frame.

The current diagnostic also enables the public decoder cycle counter and
starts working-buffer data at zero while keeping output and trailing guards
poisoned. Trial 15 timed out on all four PCM/compressed and error-bypass variants,
with output unchanged. `frame_flat=1` selects an independently verified 20-byte compressed
I_16x16 DC fixture. `frame_error_bypass=1` tests the related-core AVC bits 14/15;
concealment is not enabled, and raw error words and pixel comparisons remain
required. `frame_pattern=1` selects a verified 27-byte compressed intra fixture
with calculated luma DC blocks at QP 46; it is exclusive with `frame_flat`.
Its chroma is neutral, so it does not qualify colour ordering.
`frame_wrapper_bypass=1` selects three small-picture extension writes that are
inside a disabled reference block. The default now follows the active path.
Cached local register words and post-idle prediction/MV/wrapper change flags
record setup and working-memory activity without exposing live DMA storage.
Trial 16 timed out with all framework votes and either all local clocks enabled
or the public masks, with both wrapper paths tested. MV working memory changed,
and prediction changed with the extension. This includes setup/reset activity.
`frame_config_only=1` omits the decode command after configuration to identify
that baseline. `dma_bits=28` tests smaller IOVAs after observing a truncated
prediction-end word; the default remains 30 and only 28..30 are admitted.
`frame_work` contains four CPU snapshots in prediction/MV/VLD-wrapper/PP-wrapper
order, each 64 KiB, captured only after documented stop and idle reset.
Cached pipeline words read public status/configuration registers only.
Trial 17's command-free control leaves working memory zero; actual commands
produce 28 MV flags. Extended-wrapper DMA30/DMA28 snapshots are identical.
No output pixels or complete frame result were produced. The MV pattern and
bit counter are consistent with seven parsed macroblocks; this is an inference.
`frame_h264_pp=1` writes the public H.264 PP selector at MC `0x268`.
`frame_mc_output=1` selects direct MC output via the public disabled-deblocking
branch; every current fixture has deblocking disabled. `subsystem_reset=1`
pulses the documented whole-decoder active-low reset before any DMA command.
It requires unchanged clock/SMI/reset readback and does not write clock gates
or the supplier's MMU mask. These three variants are not hardware qualified.
These experiments are not production controls.

`make-pcm-fixture.py` constructs a 64x64 Baseline IDR frame with sixteen I_PCM
macroblocks, original pixel gradients and deblocking disabled. It uses public
H.264 syntax and no encoder library, then requires FFmpeg to decode all 6,144
sample bytes exactly. It emits Annex B, a slice NAL, planar YUV and control/hash
metadata, plus a generated C header containing only the original test NALs.
This fixture generator is not a hardware encoder.

With `--p-skip`, it also emits an original five-byte P-slice NAL referencing
the I_PCM picture. FFmpeg must reproduce all 12,288 samples across both frames.
Its separate metadata records the 26-bit slice header, frame number and POC.
This reference checks fixture syntax; hardware reference-picture decoding
still needs its own buffer/list programming and output comparison.

```sh
python3 research/mt6797-vdec/make-pcm-fixture.py --out /path/to/fixtures \
  --ffmpeg /path/to/ffmpeg
python3 research/mt6797-vdec/compare-frame.py /path/to/raw-allocation \
  --fixture /path/to/fixtures --layout mm21 --stride 64 --chroma-offset 4096
```

`compare-frame.py` requires an explicit NV12 or public MM21 layout and compares
every sample against the verified fixture. Both unpacking paths were checked
with independently packed software allocations. No hardware frame or output
layout has been qualified. Initial hardware input fetches timed out even though
the MMU mask, global clock votes and local power controls were observed; the exact
attempt results are recorded in the interface ledger.

## Building the temporary module

Use a prepared output tree for the exact running kernel, with its configuration
and genuine `Module.symvers`. Build outside this source directory:

```sh
cp -r research/mt6797-vdec /path/to/probe-build
make -C /path/to/kernel-build M=/path/to/probe-build \
  ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- LOCALVERSION= modules
```

The current accepted kernel omits `CONFIG_COMMON_CLK_MT6797_VDECSYS`. The old probe
also needs the existing open-source `clk-mt6797-vdec` provider, built for the
same kernel and loaded first. The production kernel configuration is unchanged.
The resource candidate has this provider built in and must not load an extra copy.
Do not force-load a module with a mismatched configuration or version. Its exported
symbol table is extracted from the exact candidate ELF with strict modpost; zero
CRC entries are valid only because that configuration disables `MODVERSIONS`.

## Remaining implementation

The next requirements are hardware qualification of the candidate interface,
decoded-buffer layout and alignment, reference/MV/scratch-buffer programming,
IOMMU/DMA setup, bounded reset/completion recovery and actual frame submission.
Then add V4L2 request/queue handling and compare output with software-decoded
fixtures before exposing supported formats. Encode needs its own hardware
contract and implementation. These are required work, not completed features.
