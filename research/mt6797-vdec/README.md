# Independent MT6797 H.264 implementation

This directory contains original GPL-2.0-only control translation, temporary
kernel diagnostics and independently verified H.264 fixtures. Fixed 64x64 PCM, grey and patterned intra
frames complete with exact pixel comparisons and zero hardware errors when
the private FIFO producer has a valid ending.
A production decoder or video device is not yet qualified. Encoding is not implemented.
The [experimental V4L2 Request driver](../mt6797-vdec-v4l2/README.md) now
qualifies listed Baseline I/P and Main/High I/P/B streams through 1080p. Trial 47 checks
169 exact pictures, including High 8x8 transforms and custom scaling matrices,
all 57 media checks, normal unload and strict RTC/system recovery.
Trial 50 extends the current driver to up to 16 short-term references in SD
fixtures and three at 1080p: 271 pictures match exactly, including original
reference-selection mosaics, reordered lists, weighted prediction and repeated
weighted entries. All 57 media checks and full RTC/system/recovery/audit pass.
The control translator includes atomic reference planning and a bounded
weighted-P header reader; ASan/UBSan covers every reference count and 256
weighted headers. Independent FFmpeg traces check 68 real weighted headers.
`make-multi-reference-fixture.py` builds original 2..16-reference mosaics with
optional reordering or signed weighting. All 45 variants match independently
calculated pixels and software decoding; the three sixteen-reference variants
are hardware-qualified in trial 50. Trial 51's media run adds B pictures: 288 exact output comparisons include
spatial/temporal direct, reference B pictures, explicit/implicit weighting,
custom High matrices and Main 1080p. All 57 media checks, normal unload, full RTC/system checks and strict
accepted-system recovery/audit pass.
The B translator uses stable private reference identities and full-width cached picture-order counts and masked 18-bit
hardware metadata. Both lists have independently verified planning;
512 weighted P/B headers and 74 FFmpeg traces check the bounded reader.
`make-b-reference-fixture.py` supplies mathematical forward/backward/bi
prediction mosaics; 18 software variants pass. Hardware encoding remains
unfinished.

Trial 52 qualifies long-term reference metadata with 424 exact decoded
pictures over 425 hardware commands. Eight original sixteen-reference P/B
mosaics exercise mixed/all long-term lists, marking and promotion, reordering,
explicit signed weights and implicit equal-weight fallback. The generators'
`--long-term all|mixed|promote` options preserve existing bytes when omitted.
All 108 software variants match independently calculated pixels and FFmpeg;
eight syntax traces replay MMCO2/3/4/6, and 110 weighted headers match their
independent traces. Host sanitizer checks cover all reference counts, invalid
indices through 65535, picture-number mismatches and duplicate indices.
Three native invalid-metadata requests fail before DMA, leave capture memory
untouched and preserve a usable reference. The earlier B/direct/pyramid/High,
weighted, 1080p, clocked and concurrent regressions, all 57 media checks,
normal unload and full RTC/system/recovery/audit pass. Trial 53 below qualifies
original long-term direct-motion cases; replacement/extended chains remain
unqualified.

Trial 53 reuses that module and checks 460 exact pictures over 461 hardware
commands. `make-long-term-motion-fixture.py` builds twelve original three-picture
streams covering short-term, initially long-term and promoted references,
spatial/temporal direct prediction, and B_Skip/B_Direct_16x16. A moving P picture
supplies retained co-located motion; temporal-direct prediction must change
from a POC-scaled vector to the full vector when its reference becomes
long-term, including promotion after the P picture was decoded. Every sample
matches independent mathematics and FFmpeg; syntax traces check header sizes,
direct flags and marking. Full reference pixel/motion/guard snapshots, all
earlier regressions, all 57 media checks, normal unload and full
RTC/system/recovery/audit pass. The original motion cases use 64x64 CAVLC and
integer displacements. Sustained long-term direct throughput is unqualified.

Trial 54 qualifies three original 25-picture retention/replacement chains
using the same module: 535 pictures match exactly over 536 hardware commands.
`make-long-term-chain-fixture.py` promotes the first picture to long-term
index 1, keeps or replaces it using MMCO6 or MMCO2/6, and crosses the four-bit
frame-number wrap. The final P mosaic selects both the latest short-term
picture and the independently known long-term source. Mathematical pixels,
FFmpeg and independent marking replay agree. Hardware confirms the expected
private long-term/output slots and complete retained pixel/motion snapshots.
All earlier regressions, all 57 media checks, normal unload and full
RTC/system/recovery/audit pass. Wider POC ranges and broader codec, production
and encoding work remain unfinished.

Trial 55 retains 647 exact picture comparisons and all 57 media checks,
including twelve original POC-boundary streams, but its observer misses the
cleanup phase at the end of the live window; unload is unconfirmed. Its
separate first RTC alarm reports zero interrupts. Recovery and the strict
accepted-board audit pass. This incomplete trial does not qualify new scope.

Trial 56 completes the same media suite with less observer overhead: 647
pictures match over 648 frame commands, including the intentional timeout.
`make-wide-poc-motion-fixture.py` builds 48 mathematical/FFmpeg-verified
64x64 CAVLC streams. Twelve hardware streams cross -131072, +131072 and
+262144 with nearby references, spatial/temporal B skip/direct motion and
unequal implicit weights. Full cached counts remain authoritative; only the
hardware fields are masked to 18 bits, as in the pinned public related-core
helper. The current hardware word is read back before reconstruction.
Type-0 full-count/LSB and bottom-delta contradictions fail before DMA; host
sanitizers cover full-width arithmetic and same-low-bit cache mismatches.
All previous reference, weighted, HD, clocked and concurrency regressions,
57 media checks, normal unload and the command-free encoder resource probe
pass. The separate final RTC alarm observes zero interrupts and fails the
system profile. Automatic recovery restores the accepted image, with taint
zero and no temporary codec modules, but the strict board audit finds a
recovered-boot Wi-Fi HIF fault. Both failures remain recorded; this is a media
pass, with full system and production qualification incomplete.

Trial 57 reuses the trial-56 module and checks 683 exact output pictures over
684 owned frame commands. `make-poc-type-motion-fixture.py` builds original
64x64 CAVLC I/P/B motion streams using POC type 1 with cycle offsets 8 and
32760, and type 2 with derived counts 0/2/1. Thirty-eight software variants
match independently calculated pixels and FFmpeg, and independent syntax
traces derive all counts from frame numbers, cycle offsets and nonreference
deltas. Twelve hardware variants cover temporal/spatial B skip/direct,
ordinary and saturated POC distance scaling, and implicit weighting. All 36
new output pictures match; full cached counts, hardware-word readback and
complete retained pixel/motion/guard snapshots also match. All previous
regressions, 57 media checks, normal unload and the command-free encoder
resource probe pass. All RTC/system checks and strict accepted-system
recovery/audit pass. The accepted boot is healthy with taint zero, no failed
services, no temporary codec modules and no kernel fault patterns.

[H.264 clause 8.2.1](https://www.itu.int/rec/dologin_pub.asp?id=T-REC-H.264-202408-S%21%21PDF-E&lang=e&type=items) permits full signed 32-bit picture-order counts, while used
`DiffPicOrderCnt` values must fit signed 16 bits. Both the pinned 2014 and
2024 specifications agree. The exploratory 524296-distance stream is
nonconformant and excluded. Two legal 32760-distance, exactly-midpoint
spatial/implicit variants disagree with FFmpeg's one-reference midpoint
shortcut: the normative clipped-distance calculation predicts weights 0/64,
while that shortcut uses 32/32. Their original disagreement is retained;
the generator rejects these variants and they remain hardware-unqualified.
This does not establish all POC-type or field combinations. Multislice,
interlace, IRQ completion, production integration and encoding remain unfinished.

Trials 58 and 59 qualify complete multislice packets in the private diagnostic.
Trial 58's original two-slice I_PCM picture matches all 6,144 sample bytes,
with zero hardware errors and final macroblock coordinates 3/3. Its isolated
eight-macroblock halves never signal picture completion; even the first half
has unfinished output after its bounded timeout. Zero error words and an
expected macroblock coordinate do not prove that the pixel pipeline finished.
All five cases prove break and idle reset, unchanged guards and normal unload.
Trial 58's full RTC/system/recovery checks and strict recovered-board audit pass.

Trial 59 checks eleven exact complete pictures: original I_PCM/P_Skip pairs
partitioned into two, four, sixteen, and uneven 1/5/3/7-macroblock slices, plus
one-slice gradient and existing PCM controls. Every P packet reads a guarded
copy of its exact hardware-decoded I reference; the reference remains unchanged.
All completed pictures have zero hardware error/message words, final coordinates
3/3 and proven stop/guard checks. Every temporary module unloads normally.
Trial 59's full RTC/system/recovery checks and strict recovered-board audit pass.
This qualifies these fixed 64x64 CAVLC packets. V4L2 Request accumulation and
other per-slice header, reference, weighting, entropy and deblocking variations
remain unqualified; the Request driver still advertises its trial-57 scope.

`make-multislice-pcm-fixture.py` builds original nonuniform I_PCM/P_Skip pairs
using `--partition one|two|four|sixteen|uneven`. It checks every output sample
against independent mathematics and FFmpeg before writing the fixtures;
54 independently traced slice headers also match. For each partition, generate
an output directory named `multislice-pcm-<partition>`, then reproduce the
checked-in diagnostic header with:

```sh
python3 make-multislice-probe-header.py --fixtures /path/to/fixtures \
  --out multislice64-fixture.h
```

The private probe's read-only `frame_slice` parameter selects the existing PCM
control (0), isolated first/last eight-MB slices (1/2), two-slice packet (3),
full gradient control (4), four-slice packet (5), sixteen-slice packet (6), or
uneven packet (7). `frame_p_skip=1` chains a matching P packet for modes 3..7.
Isolated slices are diagnostics of incomplete pictures, never valid references.
The supervised experiments and exact module/source identities are retained in
`qualification.multislice_private_probe` in the interface ledger.

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
Trial 14 captured SPS/PPS/slice, geometry and output/wrapper readback with all
three decoder clock votes and the public H.264 masks. The programmed SPS
`0x342001` reads as `0x340001`, including without a frame command; its candidate
max-reference bit remains unqualified.
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
or the supplier's MMU mask. Trial 18 tests these variants: five commands still
stall with unchanged output, and guards/idle/unload/system recovery pass.
Twenty frame commands have no successful pixel comparison.
The pinned public GPL MT6795 kernel at
`3c1166fd1c809473bde680bf1f7ebdd07f395104` adds further candidate initialization
facts. `extended_clocks` tests MISC `0x178`: zero leaves it unchanged, one
writes the reference `0x1f` mask, and two clears it. This frame-only diagnostic
saves the original word and verifies restoration after proven idle.
`frame_bank8=1` sets the public MC queue bank bit at `0x5e4[17]` while preserving
other bits; `frame_format=1` sets its non-field-compact output bit at `0x920[24]`.
Both MC words are restored after idle. The newer reference has different core
routing on some configurations; none of its extra MMIO banks is mapped here.
These additional facts are candidates, not proven MT6797 compatibility.
Trial 19 finds MISC `0x178` initially `0xffffffff`. Its `0x1f` reference mask
does not unlock output; zero produces 4,992 pixel writes. PCM matches 4,608 of
6,144 samples in the candidate MM21 layout, with additional written chroma
mismatches; the grey fixture matches all 4,992 written samples. Missing strips
and frame timeout remain. The MC queue bit changes no output, and bit24 at
`0x920` is already set. Clock restoration, guards, idle/unload and full system
recovery pass. Partial matches do not qualify the entire layout or a frame.
`frame_pixels=1` tests the newer TOP `0x70` width/height word for the fixed
64x64 fixture. `frame_crc=1` separately tests the newer MISC `0x4[4]` setting,
preserving other bits. Both words use the existing post-idle save/restore path;
trial 20 verifies complete exact 64x64 output with pixel dimensions set. The
CRC/access bit makes no observed difference to PCM output or raw warning.
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

The experimental driver now has hardware-qualified V4L2 request/queue handling,
private DMA and reference storage, native MM21 capture, bounded recovery and
exact software comparisons for the fixtures described above. Remaining work
includes wider POC and HD-reference coverage, multiple slices,
interlaced pictures, interrupt completion,
system suspend/resume, sustained playback/thermal checks and accepted-system
integration. Encoding needs its own public frame-programming contract and
implementation; the command-free resource probe does not encode pictures.

Private frame trial `handoff/boot-test-video-frame-20` supplies TOP `0x70`
pixel dimensions. Four frame commands complete with state `0x80000001` and
match all 6,144 sample bytes in MM21: PCM with PP mode 0/1 and CRC off/on,
plus compressed grey. PCM confirms non-neutral U/V ordering; flat grey alone
cannot distinguish layouts. Direct MC output still times out with output untouched.
All completed jobs report raw error/message `0x40` and IRQ `0x3001`; the
original observer requires zero error, so its result remains failed and the
patterned fixture was not submitted. A subsequently inspected pinned GPL
MT6795 verifier (`verify/vdec_verify_vdecode.c`, SHA256
`d74a9ec6e6ac703ac9710308f6d97c71577c4dfbd9445bca05cf3d71452b99ff`)
accepts exactly `0x40` only with picture-complete set. This policy does not
establish the bit's meaning or an error-free job. Raw evidence is preserved.
Thirty actual commands now include four complete exact pixel comparisons and
zero strict error-free comparisons. Input, guards, stop/idle and normal unload
pass; full boot/paging/Nix/all RTC/recovery and final no-writer audit pass. The
accepted system is healthy and untainted at `c4d13cb9-c801-437c-b187-b6cdcc533d42`.
References, varied geometry, production IRQ handling, V4L2 lifecycle and encoding
remain unqualified.

The next optional diagnostics compare poisoned FIFO padding with valid zero
padding and an original Annex B end-of-sequence NAL, retaining the outer guard.
Both endings independently decode to every expected FFmpeg sample for all three
fixtures. `frame_ref_first=1` separately resets picture-number SRAM before
programming SPS/PPS, matching the public reference order. Both changes build
against the exact candidate kernel; hardware results are still pending.

Private frame trial `handoff/boot-test-video-frame-21` identifies producer
padding as the raw `0x40` trigger. The original poisoned padding retains that
warning; zero padding and an original Annex B end-of-sequence NAL followed by
zeros both give exact PCM output with error/message zero. Compressed grey also
passes. The original compressed patterned intra fixture matches every sample;
a separate valid-ending follow-up removes its warning too. The first follow-up
health guard refused expected out-of-tree taint `4096` before issuing a command.
The retry proved the same boot/module and completed idle matrix, admitted
exactly that expected taint, and ran inside the existing observation window.
No competing boot or forced unload occurred.
Seven actual commands finish with exact 6,144-sample MM21 comparisons; five
have zero hardware errors. Moving picture-number SRAM reset before SPS/PPS
changes neither output nor the SPS max-reference readback difference. All input
bytes and outer guards remain unchanged, stop/idle and normal unload pass,
and full boot/paging/Nix/all RTC/recovery plus final no-writer audit pass.
Aggregate: 37 frame commands, 11 complete exact pixel comparisons, 5 strict
error-free comparisons and 5 command-free controls. The accepted board is
healthy and untainted at `f7e5744a-fcb4-4e5b-96cf-a1382812bb19`.

An original Linux DPB translator now prepares progressive P-reference metadata,
rejecting inactive/invalid/field references, reserved bytes and PicNum overflow
without altering output. ASan/UBSan host tests pass. A compiled private
`frame_p_skip=1` diagnostic decodes PCM, requires zero-error completion and
proven idle, preserves its actual hardware output in a separately allocated
guarded reference, then submits the original five-byte P-skip NAL. Both CPU
outputs and raw completion words are retained; final checks require the entire
reference allocation unchanged. Reference metadata is captured before submission.
No mapping is released on unproven stop. This reference test has not yet run.
The P fixture metadata now uses public V4L2 PFRAME flag `8`; NAL/sample bytes
are unchanged. Production IRQ handling, V4L2 lifecycle, varied geometry and
encoding remain unqualified.

Private frame trial `handoff/boot-test-video-frame-22` passes the command-free
control and PCM baseline. The guarded reference job completes its first PCM
picture with zero errors and both stop acknowledgements. Its next step wrongly
requests another break while VLD reset is held; acknowledgement times out
before loading or commanding the P NAL. Reference registers are not programmed.
The old cache retains the first-picture state; input mismatch reflects restored
known-word producer bytes while stale bookkeeping expects a P slice. This
does not isolate a hardware overwrite. The matrix stops with mappings and
clocks fenced until supervised reboot, and no reference pixel snapshot is
exported. Only two actual frame commands and six input fetches occur. P is
not counted as a frame command or comparison. Aggregate: 39 commands, 12
complete exact comparisons, 6 strictly error-free comparisons, 6 controls.

The final RTC delivery check records interrupt delta zero over 13.22 seconds;
the candidate run fails and is not qualified for installation. Accepted recovery
and final no-writer/source checks pass. The independent audit finds the normal
system healthy, untainted and clear of temporary probes at `00dd456a-14ad-40d6-ab82-62c8134e554c`.

The compiled restart fix retains the successful first stop/reset proof, skips
the duplicate break, and clears stale producer/submission caches before P.
`frame_interrupt=1` separately requests the real DT interrupt while powered,
requires delivered IRQ plus picture-complete status, and acknowledges the
published RISC clear sequence. Four unclassified interrupts disable the line
and fail the job. Callback synchronization and IRQ release precede power-off;
failed DMA stop retains resources until reboot. Input endings must be valid.
The next matrix tests corrected restart, active wrapper path and real IRQs.
These additions build with strict modpost against the exact kernel, but P
decoding and interrupt-driven jobs remain unqualified. V4L2 and encoding
are not implemented.

Private frame trial `handoff/boot-test-video-frame-23` proves the corrected
PCM-to-P-skip restart. Both actual hardware I/P snapshots match all 6,144
samples with zero error/message words, under active and extended wrapper
paths. Whole reference allocations remain unchanged. Slot0 receives the
full reference IOVA, PicNum0 and MV metadata `0x200000/0x600000`; the current
P picture uses frameNum1 and POC2. Active-wrapper patterned intra also passes.
Two interrupt-driven PCM/grey jobs produce exact pixels and native complete
status, but zero IRQs arrive and their software completion waits time out.
They remain failed jobs. No unclassified interrupt or storm occurs.
Seven actual commands produce complete exact pixel comparisons; five polling
jobs meet every required completion check. Input/guards, documented stop/idle
and normal unload pass for every profile. Full boot/paging/Nix/all RTC/
recovery and final no-writer audit pass. The accepted board is healthy and
untainted at `8857cf5e-abd1-47d5-970f-4a878d9d263f`. Aggregate: 46 commands, 19 native-complete
exact pixel comparisons, 13 error-free pixel comparisons and 11 successful
zero-error polling jobs, with 7 command-free controls.

The separately developed V4L2 backend initially targets the tested fixed
64x64 progressive Baseline, single-slice, one short-term reference cases.
It uses bounded worker polling, request control translation, private guarded
DMA, full reference comparisons and per-context timestamp lookup. A fatal
stop failure retains independent DMA ownership and power until reboot.
Backend/frontend integration is still being implemented and is not hardware
qualified. No V4L2 video node is advertised by the accepted system. Varied
geometry, broader codec coverage and encoding remain unqualified.


### 2026-10-10: V4L2 registration trial 24 and callback correction

The original Request-API frontend and private-DMA backend build with strict
modpost against the exact candidate kernel and genuine media-module exports.
Trial `handoff/boot-test-video-frame-24` first failed to load because BusyBox
modprobe looked for absent `/lib/modules`; explicit candidate Nix-store module
paths resolved that setup failure. The same-boot/same-blob retry registered the
driver, then udev `v4l_id` triggered a kernel panic in `query_capability+0x48`.
Retained pstore proves Linux 7.1 passed `priv=NULL`; the new callback wrongly
converted it to a file context. No owned userspace decode test or frame command
ran. The corrected capability query uses no per-file state, and set-format now
uses `file_to_v4l2_fh(file)`. Both changes compile; a new trial is pending.

The supervisor rejected the candidate and verified accepted recovery boot
`d59d8301-c9a0-470e-8ec1-c476743d9a3d`, protected hashes, all 35 source hashes
and no writer. The stricter recovered-board journal audit also failed: it found
a WiFi HIF fault `-75` and an automatic WLAN restart in the accepted kernel.
That boot is healthy and untainted, but has no fault-free audit. Both failures
are retained separately; no decoder qualification is inferred from trial 24.

The original fixture generator now admits 64/128 pixel widths and 64/96/128
pixel heights. Independent FFmpeg checks prove all samples in new 128x96 PCM,
grey, patterned intra and I-to-P streams. Default 64x64 NALs, streams, sample
bytes and C arrays remain byte-identical. Wider hardware decoding is untested.


### 2026-10-10: V4L2 request binding trial 25

`handoff/boot-test-video-frame-25` proves the corrected frontend survives udev
capability queries and userspace G/TRY/S_FMT. The media-node lookup was corrected
for this kernel's platform media nodes. The first request source QBUF then
warned and returned EINVAL: Linux requires the `buf_out_validate` callback.
Cached jobs, input fetches and frame submissions remain zero; no public-API
pixel comparison is available. The frontend unloaded normally. The missing
callback is now implemented, validates progressive field metadata, and builds
with strict modpost. Cached status distinguishes input-fetch attempts from
frame commands so an input-stage stop failure cannot be mistaken for no DMA.

The supervisor separately rejected RTC delivery-after's interrupt-count check.
Accepted recovery boot `0cb93554-b871-4f9f-8566-e49824470e1e`, protected hashes,
all frozen source hashes and no writer are verified. Its strict journal audit
passes with taint zero, no temporary codec device/module and no fault patterns.
The failed candidate and successful recovery are recorded separately.

An original explicit-motion P_16x16 fixture now independently decodes to the
derived four-pixel horizontal luma shift (two chroma pixels), including right
edge replication. Both full 64x64 pictures match all 12,288 reference samples
in FFmpeg. This fixture has not been submitted to hardware.

The Request frontend now collects complete picture packets from slice requests.
Trial 61 qualifies the listed original 64x64 Baseline packets, held-buffer
lifetime, rejection before DMA and retained-reference recovery; see the
[frontend's qualification notes](../mt6797-vdec-v4l2/README.md). Private trials
58/59 remain evidence for whole packets rather than partial-slice completion.

`make-baseline-fixture.py --slices N` generates compressed multislice fixtures
for separate qualification, with one slice by default. It checks the software
picture count and independently traced slice starts: each picture starts at
macroblock zero, stays inside its coded geometry and uses strictly increasing
starts. The default 64x80 stream and decoded reference remain byte-identical to
the earlier fixture. Software fixtures cover Baseline, Main/CABAC, custom-scaling
High CAVLC/CABAC, temporal/implicit B and weighted P streams; they make no hardware
encoder claim. The hardware status of each fixture is recorded separately.
