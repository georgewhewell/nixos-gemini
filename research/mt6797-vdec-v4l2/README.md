# MT6797 V4L2 Request decoder

Original GPL-2.0-only experimental driver for the Gemini's MT6797 decoder.
It uses the public Linux stateless H.264 Request API and a register backend
derived from this project's hardware-qualified private diagnostics. No codec
firmware or proprietary codec library is loaded. Register provenance and
qualification evidence are tracked in [the interface ledger](../mt6797-video-interface.json).
This development has not used a formally separated clean-room team.

Development uses the same [Linux 7.2.9](../KERNEL_BASELINE.md) kernel as the
normal GNOME image: maintained branch `gemini-7.2.9`, source `7eb0d527`.
The former media branch is merged and retired. This kernel enables the decoder
resources and native VDEC clock provider; the experimental decoder driver is
not installed in the normal image. Picture, error and lifetime results below
qualify their recorded polling builds, rather than the new IRQ backend.

The current RAM-only 7.2.9 kernel and matching module build identities are in
[`desktop-consolidation-20261010.json`](../desktop-consolidation-20261010.json).
The [IRQ contract](irq-contract.json) records the public MT6797 acknowledge
sequence and upstream Linux APIs. A recorded successful polling snapshot has
the picture-complete bit set without the IRQ done bit; it does not establish
interrupt delivery. [Trial 82](irq-trial-82.json) loaded the IRQ candidate on
the maintained kernel. Its first 64x64 I_PCM command reached picture-complete
state but timed out without an interrupt: all ten possible CPU counters stayed
zero, and no frame was exported or compared. DMA stop, guards and normal unload
passed; supervised recovery and the independent terminal audit returned a
healthy GNOME system. IRQ completion remains unqualified.

The [next diagnostic build](irq-controller-build-20261010.json) passes strict
ARM64 MODPOST and `W=1` without warnings. It caches masked, pending and active
controller state through Linux's `irq_get_irqchip_state`, together with the
read-only AVC completion and clock status. It does not change the completion
criteria or hardware programming and has not been loaded on the board.

The candidate claims the DT interrupt with `IRQF_NO_AUTOEN`. Only a powered,
submitted command can accept a done event; a stale done bit or an event before
hardware start fails the command. The handler records the raw status and
command identity, performs the public live-read acknowledge sequence, and
masks the line after its first delivery. Reset, restore and power release wait
for every handler to retire. Picture-complete polling alone cannot satisfy a
successful decode. A bounded error check still detects fatal CABAC stalls,
and all prior private-DMA stop, guard and fencing checks remain in place.
Cached job diagnostics include `irq_command`, `irq_received_command`,
`irq_events`, `irq_unexpected` and `irq_status`; trial 82 records their failed
delivery result. Independent delivery, acknowledge, lifetime and pixel checks
remain required before using this backend in normal development.

The previously qualified polling module decodes the listed progressive H.264 Baseline I/P and
Main/High I/P/B fixtures
through 1920x1088 coded / 1920x1080 visible in the listed one-slice cases, with up to 16
references in SD fixtures, including long-term references in original 64x64
fixtures, or three short-term references in the listed HD fixtures.
Trials 52–62 qualify earlier modules. Trial 67 reruns all 683 listed pictures
on that polling build, including full-width cached POCs and POC types 1/2.
Trial 66 separately qualifies 104 exact pictures, including 54 compressed
multislice pictures at SD and 1080p and the original 64x64 Baseline packets.
Multislice lists, weights, QP and deblocking must match across a picture.
Trial 41 checks 106 exact pictures including HD, resolution changes
and visible-height I420 output; all 57 default media checks pass. Trials 44/45
check 97 exact pictures, including two 32-picture 1080p samples at 25 fps:
native MM21 and four-thread I420 conversion each render all 32 with valid
timestamps, real clock waits and zero drops. Concurrent contexts, fault/recovery,
normal unload and strict accepted-system recovery pass. Trial 45 also passes
all RTC/system checks. Trial 44's separate alarm count of two instead of one
fails its system profile and remains recorded without an established cause.
The source uses cached private DMA with explicit ownership and lazy geometry
allocation. Prior RTC/open-allocation/conversion failures remain recorded.
Hardware encoding, broader codec features, interrupt completion, sustained
playback/thermal qualification and production integration remain unfinished.

Trial 46 adds High-profile fixtures with actual 8x8 transform use. Flat scaling
passes in CABAC and CAVLC, but custom and JVT scaling fail pixel comparisons:
81 pictures match and 32 do not. The candidate incorrectly addressed scaling
SRAM through the AVC-specific bank. The public helper selects the common VLD
bank instead. Both completion and intact DMA guards were insufficient to detect
this pixel error; independent software comparison remains required. Normal
unload, all 57 media checks, RTC/system checks and strict recovery/audit pass.
The first custom fixture also has ignored x264 8x8 option names; its nonuniform
4x4 lists, raw warnings and failed output remain recorded. The corrected
generator uses `cqm8i`/`cqm8p` and rejects encoder option errors. A separate
candidate corrects the bank and requires exact scaling SRAM readback before
picture reconstruction. Trial 47 qualifies that correction with 169 exact
pictures over 170 hardware commands, including the intentional timeout.
High fixtures cover CABAC/CAVLC, actual 8x8 transforms, flat/JVT/nonuniform
matrices, 4x4-only custom scaling, and 32 pictures with changing matrix settings
inside one stream. Custom-matrix 1080p output matches in native MM21 and I420.
A zero final consumed coefficient is rejected before any hardware fetch or
decode command; capture storage remains untouched. Concurrent contexts, all
57 default media checks, normal unload, all RTC/system checks and strict
accepted recovery/audit pass. The Main 32-picture 1080p clocked regression
also passes. High-profile sustained or clocked throughput remains unqualified.

Trial 48 tests weighted P prediction. An original CAVLC P-skip picture with
signed luma/chroma weights matches every independently calculated sample.
The x264 weighted clips stop before reconstruction because a six-bit cursor
check expects bit 47 but observes 15. The input mode retains the public SUM6
append setting; compatibility of the related helper's sixth counter bit is
unqualified. The trial preserves 113 exact output comparisons, 123 input
fetches and 116 picture commands, including the intentional timeout; two
successful pictures are not exported by the failed pipelines. All stop/guard
checks, normal unload, all 57 media checks, RTC/system checks and strict
accepted recovery/audit pass. A separate candidate checks the low five cursor
bits and actual next RBSP bits before and after the table. Trial 49 qualifies
that correction with 164 exact output pictures across 165 picture commands,
including the intentional timeout. The 58 weighted-stream pictures cover
signed original luma/chroma factors, Main/High CABAC/CAVLC, custom scaling,
Main 1080p and I420 conversion. Every weighted operation checks the input
window; cached status retains the full observed counter, words and masks.
High matrix transitions, concurrent streams, the Main clocked 32-picture
1080p regression, all 57 media checks, normal unload, all RTC/system checks,
strict accepted-system recovery and the final board audit pass. The accepted
boot is healthy with taint zero and no temporary media modules. Weighted
sustained or clocked throughput remains unqualified.

Trial 50 qualifies multiple short-term references with 271 exact decoded
pictures over 272 picture commands, including the intentional timeout. Three
original 64x64 mosaics select every one of 16 distinct references: default
ordering, explicit reordering, and signed per-entry luma/chroma weighting. Their
expected samples are calculated independently and checked against FFmpeg.
x264 chains cover three-reference Baseline, sixteen-reference Main/CABAC and
three-reference weighted High with custom scaling. The latter uses five
logical list entries for three distinct pictures, exercising repeated entries
with separate weights. Three-reference 1080p output matches in native MM21 and
I420. The one-reference weighted, High matrix-transition and clocked Main
1080p regressions also pass. A missing third reference and inconsistent second
reference metadata fail before DMA; capture storage stays untouched and the
next valid request still uses the retained reference. All 57 media checks,
concurrent contexts, normal unload, RTC/system checks, accepted recovery and
the final board audit pass. Sixteen-reference HD throughput remains unqualified.

The private cache has 17 possible picture slots, allocated only when a real
request needs another output. Planning validates all active DPB timestamps,
geometry, short-term frame numbers and picture-order counts before allocating or powering
the hardware. Output never overlaps an active reference. Repeated logical list
entries may share a private picture. Every retained cached picture, including
its guard, is copied before DMA and compared after a proven stop. The ordered
worker owns the shared bounded snapshot and 256-entry register save area;
the latter avoids enlarging the kernel stack as reference tables grow. The
qualified sixteen-entry weighted sequence saves and restores 122 registers.
Single-reference streams retain the two-picture allocation path.

Trial 51 adds the B-picture backend. Its media run passes 288 exact output
pictures over 289 hardware commands, including the intentional timeout.
Five original 64x64 streams exercise two sixteen-entry lists with forward,
backward, bidirectional, explicit signed and unequal implicit prediction.
Their mathematical pixel references also match independent FFmpeg decoding.
x264 Main streams exercise spatial and temporal direct prediction and both
CABAC and CAVLC. A custom-matrix High stream includes reference B pictures
and implicit weighting; Main 1080p temporal-direct output matches in MM21
and I420. The P16, weighted-P and clocked 32-picture Main 1080p regressions
also pass. Invalid B list-1 and out-of-range signed POC controls fail before
DMA, leave capture storage untouched and retain the next valid reference.
Concurrent contexts, all 57 media checks and normal unload pass. All RTC/system checks, strict accepted-system recovery and the final board
audit pass. The accepted boot is healthy with taint zero, no temporary media
modules and no failed services.

The B backend retains full motion data with each private picture. The public
uncompressed layout occupies Y + interleaved chroma + Ysize/4 motion; the
allocation then has padding and a trailing guard. Motion addresses use
16-byte units and the full layout places bottom-field data 64 bytes after
top-field data. Reduced motion mode is cleared. Reference identities use
stable private picture slots across reordered and repeated lists. Snapshots
compare every retained pixel, motion and guard byte after a proven stop;
userspace sees the image planes alone. The shared register save area grows
to 256 entries; the weighted sixteen-entry B sequence saves and restores
220 registers. Host ASan/UBSan covers 512 weighted P/B headers and both
reference lists at every count from 1 through 16. Seventy-four weighted
headers, including six original B headers, match independent FFmpeg traces.
The 18 original B count/prediction/weighting combinations also match every
mathematically calculated software sample. Independent syntax traces confirm
53 B pictures in the hardware run, including five reference B pictures.
Encoder statistics report actual direct-prediction and skip macroblock use. B-picture sustained or clocked
throughput remains unqualified.

Trial 52 adds long-term references with 424 exact output pictures over 425
hardware commands, including the intentional timeout. Eight original 64x64
streams exercise sixteen-reference P and B lists: all-long-term and mixed
references, marking the current picture long-term, promoting previous
short-term pictures, P-list reordering, identical B-list swapping, signed
explicit weights and implicit equal-weight fallback. All 108 original
software variants match mathematically calculated pixels and FFmpeg. Eight
independent syntax traces replay MMCO2/3/4/6; 110 weighted P/B headers match
independent traces. Linux carries the long-term index in DPB `frame_num`,
rather than the cached picture's original NAL frame number. The driver checks
its range, progressive picture-number equality and uniqueness, while retaining
timestamp, geometry and POC checks. Three invalid long-term metadata requests
fail before DMA, leave capture storage untouched and preserve the next valid
reference. The trial retains all B16, direct-prediction, pyramid, High-matrix,
weighted, 1080p, clocked and concurrent-context regressions from trial 51.
Every retained pixel, motion and guard byte matches after a proven stop.
All 57 media checks, normal unload, RTC/system checks, accepted recovery and
the final board audit pass. The accepted system is healthy with taint zero,
no temporary media modules and no failed services. This trial does not qualify
long-term temporal-direct motion; trial 53 below checks that separately.
Replacement/extended chains and broader codec features remain unqualified.

Trial 53 reuses the same module and qualifies twelve original 64x64 motion
streams: short-term, initially long-term and subsequently promoted references,
each with spatial or temporal direct prediction and B_Skip or B_Direct_16x16.
A nonuniform I_PCM picture is followed by an explicit moving P picture; the
final B picture must use its retained co-located motion. For temporal direct,
the short-term case derives half the co-located vector, while the long-term
case retains that full vector and gives list1 zero motion. Promotion after the
P picture was decoded exercises the reference-identity rule in public H.264
8.4.1.2.3, note 2. All three pictures in each stream match mathematical samples
and FFmpeg, including image-edge replication. Independent syntax traces check
marking, direct flags and header sizes. All 460 output pictures match over 461
hardware commands, including the timeout; every retained pixel, motion and
guard byte is unchanged. The trial reruns all trial 52 regressions and passes
all 57 media checks, normal unload, RTC/system checks, accepted recovery and
the final audit. These original motion fixtures use CAVLC and integer sample
displacements; broader long-term direct-motion throughput remains unqualified.

Trial 54 also reuses that module and qualifies long-term index replacement
and short-term frame-number wrap. Three original 25-picture streams promote
the first I_PCM picture to index 1, then retain it, replace it using MMCO6,
or explicitly release and replace it using MMCO2/6. The four-bit frame number
wraps at picture 16. A final P mosaic selects both the latest short-term
picture and the expected original or replacement long-term picture; every
sample is independently calculated and checked against FFmpeg. Independent
syntax replay verifies the exact retained picture and marking operations
across the wrap. The hardware status confirms the expected private long-term
slot, separate output slot and two complete reference pixel/motion snapshots.
All 535 output pictures match over 536 hardware commands, including the
timeout. All earlier regressions, all 57 media checks, normal unload,
RTC/system checks, accepted recovery and the final audit pass. Wider POC
ranges, multiple slices, interlace, IRQ completion, production integration,
sustained thermal playback and hardware encoding remain unfinished.

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

Private diagnostic trials 58/59 establish complete-picture packet consumption.
The Request frontend now collects nonfinal slices in a bounded per-context CPU
packet and completes each OUTPUT request while retaining its untouched CAPTURE.
The final request submits that packet once through the existing guarded engine.
All slices must share timestamp, geometry, SPS/PPS/decode metadata and slice
settings. The first macroblock starts at zero and then increases; a bounded
RBSP reader compares complete headers after excluding the first-macroblock code.
Changing per-slice lists, weights, QP or deblocking remains unsupported. A rejected
batch releases capture as an error before DMA and leaves earlier references usable.
Streamoff and close discard unfinished packets. Held capture timestamps are
kept private until completion to prevent the mem2mem core from publishing an
unfinished picture on a timestamp change. See the [private diagnostic](../mt6797-vdec/README.md)
and the stateless decoder [Request contract](https://docs.kernel.org/userspace-api/media/v4l/dev-stateless-decoder.html).

Trial 60 passes the native and five GStreamer picture checks with 49 exact
pictures, but its overall media diagnostic fails when the observer's incorrect
15-second compliance deadline interrupts the blocking-wait check. Normal unload,
full RTC/system checks and strict accepted-board recovery pass; this failed
attempt remains recorded. Trial 61 repeats the same driver with the established
30-second deadline and passes all 57 media checks. Its 86 native multislice
requests produce 27 exact pictures, complete 54 intermediate requests without
DMA, and reject five timestamp/order/control/header/capacity faults before DMA.
OUTPUT-only and CAPTURE-only streamoff, close/reopen, interleaved contexts and
retained-reference recovery pass. Original 64x64 Baseline I_PCM/P_Skip pictures
use one, two, four, sixteen and uneven slices. The whole run compares 49 pictures
and records 164 requests, 50 hardware picture commands (including the existing
intentional timeout) and 98 intermediate requests without DMA. Full RTC/system
checks, normal unload and strict accepted-board recovery pass. Main/High/CABAC
multislice and compressed packets require separate qualification.

Trial 62 qualifies the same driver against the complete earlier regression:
683 exact pictures over 684 hardware commands, including the intentional timeout.
All 62 dynamic streams, sixteen-reference and long-term cases, full POCs, B/direct
prediction, weighted tables, High matrices, HD MM21/I420, the clocked Main sample,
concurrent contexts and all 57 media checks pass. Normal unload, the command-free
encoder resource probe, every RTC/system check and the strict accepted-board audit
pass. The extra Request buffering leaves this earlier single-slice scope intact.

Trial 63 tests compressed multislice packets on the same module. All eight
320x240 Baseline two-slice pictures match, as do the first two custom-scaling
High 1080p four-slice pictures. The third High picture returns EIO with
whole-picture DONE, final coordinates 119/67, intact guards and a proven stop,
but raw error/message words `0x4000`/`0`. The existing CABAC tail condition
requires both words to be `0x4000`, so its zero cached tail fields were never
sampled. The third picture is not exported or pixel-qualified. The pipeline
propagates the capture error, and the remaining six compressed streams are not
run. All 57 media checks and normal unload pass; the overall media diagnostic
fails. Its separate RTC delivery-before test records zero interrupts and fails
the system profile. Accepted-system recovery and the strict board audit pass.
The 59 exact exported pictures, both failures and untested scope remain recorded.
A new parser-window diagnostic and independent picture comparisons are needed
before accepting the new error-word combination or qualifying Main/High
compressed multislice generally.

Trial 64 samples the completed bit-14/zero-message parser window while keeping
acceptance unchanged. All 13 pipelines run; 91 exported pictures match every
sample. High CABAC at SD and 1080p, and the Main B stream, each reproduce a
completed rejected picture with aligned parser word 1 and intact stop/guards.
The five other compressed profiles pass 35 pictures; the three partial streams
export seven correct prefix pictures. Missing pictures remain unqualified.
The [pinned public GPL helper](https://github.com/DroidThug/android_kernel_leeco_MT6795/blob/3c1166fd1c809473bde680bf1f7ebdd07f395104/drivers/misc/mediatek/vdec/hal/vdec_hal_if_h264.c#L2262)
reads the current message but classifies the error accumulator, independently
of message equality, and checks the byte-aligned window for a sole CABAC trailer
flag. Trial 64 verifies that diagnostic precondition on Gemini. All 57 media
checks, normal unload, full RTC/system supervision, recovery and the strict
board audit pass; the overall media diagnostic still fails as expected.

Trial 65 tests the corrected accumulator-based trailer classifier. All 104
exported pictures match, including all 54 compressed multislice pictures and
the malformed-CABAC stream's correct initial I picture. The malformed second
picture retains explicit bit-8 EIO and no trailer classification. Its observer
still applies the old equal-error-word predicate, so the completed High 1080p
pipeline and overall observer are marked failed despite correct pixels and
status. That harness failure remains archived; a fresh repeat with the corrected
predicate is required. All 57 media checks, normal unload, full RTC/system
checks, accepted recovery and the strict board audit pass.

Trial 66 repeats the same corrected module with the corrected observer and
passes all 104 exact comparisons. All eight compressed streams complete: SD
Baseline, Main, Main B, weighted Main and High CABAC/CAVLC with two or four
slices, plus Main/High 1080p with four slices. The 54 compressed pictures include
the previously rejected CABAC cases. The native/original multislice suite adds
49 pictures; malformed CABAC exports its one correct I picture then reports
explicit EIO for bit 8, with no trailer classification. The complete run uses
334 requests and 106 fetch/picture commands. All 57 media checks, normal unload,
full RTC/system checks, recovery and the strict board audit pass. Changing
per-slice lists, weights, QP or deblocking remains unsupported; the wider
one-slice feature regression on this corrected module requires a separate run.

Trial 67 completes that regression on the exact trial-66 module: all 683
pictures match over 684 fetch/picture commands, including the intentional
timeout. All 62 dynamic streams, sixteen-reference and long-term cases,
POC boundaries and types 1/2, B/direct motion, weighting, High matrices,
HD MM21/I420, the clocked Main sample and concurrent contexts pass. All 57
media checks, normal unload, the command-free encoder resource probe, full
RTC/system checks, accepted recovery and the strict board audit pass. The
accepted boot has taint zero, no temporary media modules, no failed services
and no kernel fault patterns. The encoder frame contract remains unfinished.

The original bounded slice reader validates the prediction table and complete
P header against Linux's stateless controls before any allocation, power vote
or DMA ownership transfer. It handles emulation-prevention bytes, signed and
inferred default weights, POC variants and bounded reference-list/marking
syntax. Host ASan/UBSan checks cover 256 independently constructed weighted headers
with 1, 2, 4 and 16 entries, and atomic reference plans for every count from
1 through 16. Sixty-eight real P headers match independent FFmpeg syntax traces,
including repeated weighted entries and the original sixteen-entry table. A weighted request
with a mismatched luma offset fails before fetch or reconstruction and leaves
the whole capture allocation untouched. Table operations use bounded polling
and the existing break/reset and DMA fencing path.

The first module builds against the 7.1.3 candidate kernel with strict modpost
and genuine exported-symbol metadata from that kernel and its media modules.
The first registered frontend trial (`boot-test-video-frame-24`) panicked when
udev queried its capabilities: this kernel passes a null ioctl `priv` argument.
The corrected capability query uses no per-file context; set-format obtains
the file handle from `file_to_v4l2_fh(file)`. That correction's next hardware
trial survived udev and G/TRY/S_FMT in `boot-test-video-frame-25`; request QBUF
then exposed the required `buf_out_validate` hook. That callback is now
implemented. No owned decoder command ran during trials 24/25. Trial 26 then
passed eight public-request hardware frames: every 64x64 MM21 sample matches
the independently decoded original PCM, grey, patterned intra and P-skip
fixtures, with zero decoder error/message words. Request completion and reuse,
capture metadata, six open/stream/close contexts, missing-reference rejection
before DMA and normal module unload passed. The supervisor's RTC/system checks,
accepted recovery and strict kernel-journal audit also passed. These results
apply to the archived trial-26 module, not arbitrary H.264 streams. Trial 27
also passed twelve 64x64 frames including explicit motion, MMAP and exported
queue mappings whose completed storage survives video-file close. At 64x96,
intra pixels matched but inter pixels repeated row 63: the extension wrote
width into the motion-compensation height word. That height is now corrected.
Trial 27 unloaded normally and passed supervisor/recovery/journal checks.
Trial 28 then passed 48 original I/P/motion pictures across 64x64/96/128,
128x64/96/128 and 320x256. Every sample matches, error/message words stay zero,
all bytes beyond each picture payload retain their guard value, and request,
export/close, unload, supervisor and strict recovery checks pass. GStreamer
discovers the decoder but its slice-mode weight control was absent; compliance
also found missing media bus information/events and discarded colorimetry.
The next build supplies that control for unweighted pictures, event callbacks,
matching media bus information and retained output/capture colorimetry.
Trial 29 validates those corrections: six original ioctl-test pictures and
fourteen GStreamer pictures match their independent software references. The
GStreamer tests cover P-skip, explicit motion, patterned intra at 128x96 and
320x256, and an eight-frame x264 Baseline sequence at 128x96 with changing
luma/chroma, residual coefficients and chained P pictures. All 57 default
v4l2-compliance 1.32.0 media/video checks pass without warnings. GStreamer
1.28.6 discovers the real device and decodes through its unchanged
`v4l2slh264dec` element. The observer completed capture, status collection and
normal unload, then failed while composing its final JSON because fixture
metadata shadowed module metadata; its report is reconstructed offline from
the preserved results. The raw reporting failure is retained with the trial. Supervisor RTC/system
checks, accepted recovery and the strict kernel-journal audit also pass.

Hardware-tested scope is progressive 8-bit 4:2:0 Baseline, Main/CABAC,
the High-profile streams in trial 47, weighted P streams in trial 49 and
multiple-reference streams in trial 50, B streams in trial 51 and long-term
reference mosaics in trial 52, original motion streams in trial 53 and
replacement/wrap chains in trial 54, POC boundaries in trial 56 and listed
POC-type 1/2 streams in trial 57 above:
one slice, Baseline I/P or Main/High I/P/B
pictures, up to 16 short-term references at SD, 16 short/long-term references
in the original 64x64 mosaics and three short-term references in the listed HD fixtures, with
enabled or disabled deblocking.
CABAC retains the specifically checked trailer flag described below. Input
is `V4L2_PIX_FMT_H264_SLICE` with no start code; capture is two-plane native
`V4L2_PIX_FMT_MM21`. The current driver admits coded widths 64..1920 and heights 64..1088
in steps of 16; trial 41 checks the explicitly listed HD and SD fixtures.
Negotiated MM21 storage height is padded to 32 rows; prediction uses the coded
height, and cached references must match it. Trial 30 passes all 18 original
request pictures at 64x64, 64x80 and 320x240 plus 18 pictures through seven
GStreamer pipelines. The 64x80 and 320x240 motion streams match their coded
samples in padded storage. The eight-frame x264 320x240 stream times out on its
first picture and produces no output: zero error/message words, state 1, safe
break/reset, unchanged guards and normal unload. All 57 compliance checks and
supervisor/recovery/journal checks pass. The later lookahead trial described below qualifies this same compressed stream.
Qualified trials through 37 use 256 KiB coherent allocations with 128 KiB data
and trailing guard regions. The next SD candidate expands picture allocations
to 640 KiB, with 512 KiB capacity and a 128 KiB guard; it checks all bytes after
the actual picture payload. Scratch allocations remain 256 KiB. GStreamer's initial 320x240 probe can negotiate
320x256. Real GStreamer decoding is qualified for the explicitly listed archived streams. Queues
use MMAP allocation and can export their CPU storage through `VIDIOC_EXPBUF`;
buffer export is hardware tested at the seven listed dimensions. Those qualified
builds use a bounded workqueue poll; actual interrupt delivery remains unqualified.
It does not implement an encoder.

Userspace queue storage is allocated by videobuf2-vmalloc. Hardware reads and
writes only independent private DMA allocations, with input padding, working
buffers, picture buffers and trailing guards. The current buffers are cached:
the worker synchronizes them for the device before the first fetch, then for
the CPU only after a proven hardware stop. Before copying pixels
into capture buffers, the worker requires picture completion, break/reset
acknowledgements and unchanged guards/reference storage. Baseline requires zero
error/message words. The experimental CABAC trailer classification below retains
raw flags and admits only its specifically checked completion condition. It resolves references by the input timestamp and checks picture
metadata against the per-file cache. Stream-off and close wait for the worker.
An unproven hardware stop retains private DMA allocations, clocks, runtime
power and a module reference until reboot; it still returns errored userspace
buffers safely. The read-only `last_job` sysfs attribute reports cached status
and never reads live registers.

Build `mt6797_vdec.ko` with Kbuild against the matching configured kernel build
directory, retaining this directory's sibling `mt6797-vdec` control translator.
The experimental DT must supply the seven decoder banks, three clocks, VDEC
power domain, larb1 and its ten decoder IOMMU ports. Normal accepted Gemini
systems currently have that node disabled.

`request-test.c` is an original userspace ioctl exerciser. Cross-build it with
Linux media UAPI headers and libc, then run it in a supervisor-owned candidate
boot:

```text
request-test /dev/videoN /dev/mediaN OUTPUT_DIRECTORY \
  /sys/bus/platform/devices/16020000.video-codec/last_job

# Original external fixtures, with explicit motion and exported-buffer mappings:
request-test /dev/videoN /dev/mediaN OUTPUT_DIRECTORY \
  /sys/bus/platform/devices/16020000.video-codec/last_job \
  FIXTURE_DIRECTORY 128 96 export

# Optional timeout, stale references, invalid scaling/weights/reference metadata:
request-test /dev/videoN /dev/mediaN OUTPUT_DIRECTORY \
  /sys/bus/platform/devices/16020000.video-codec/last_job \
  FIXTURE_DIRECTORY 64 64 export faults
```

It submits the independently verified original fixtures, checks request
completion/reinitialization, capture sizes/timestamps/sequences, repeated
open/stream/close and a missing reference rejection. Optional external fixtures
exercise other admitted dimensions and an explicit four-pixel P-picture motion;
export mode checks that completed capture storage survives video-file close.
It saves MM21 samples and
cached hardware status for independent host comparison with
`../mt6797-vdec/compare-frame.py`. This is an API and hardware qualification
exerciser; successful compilation alone is not a decode qualification.

`../mt6797-vdec/make-weighted-skip-fixture.py` constructs the signed weighted
P-skip fixture from an original `make-pcm-fixture.py` output. It checks every
luma/chroma sample with independent FFmpeg decoding. Copy its
`weighted64-p.nal` into the 64x64 fixture directory for the optional fault
test. `make-baseline-fixture.py --weighted-pred --fade` creates Main/High
x264 clips with actual luma/chroma weighting; combine it with `--entropy`,
`--transform-8x8`, `--scaling` and `--refs` for the separately qualified
combinations.

`make-multi-reference-fixture.py` constructs distinct original I_PCM references
and a P picture whose macroblocks select every reference. It accepts 2..16
references and optional `--reorder` or `--weighted`; all 45 count/mode variants
match independently calculated samples and FFmpeg. Trial 50 hardware-tests
the three sixteen-reference variants. For the optional native fault test,
copy plain `final-p.nal` outputs with 16 and 2 references into the existing
64x64 fixture directory as `multi16-p.nal` and `multi2-p.nal`, respectively.

```sh
python3 research/mt6797-vdec/make-multi-reference-fixture.py \
  --out /path/to/multi16 --ffmpeg /path/to/ffmpeg --refs 16
# Add --reorder or --weighted for the other original qualification streams.
```

`make-b-reference-fixture.py` constructs original B16x16 prediction mosaics
with two lists of 2..16 references. Select forward (`l0`), backward (`l1`) or
bidirectional (`bi`) prediction and `none`, `explicit` or `implicit` weighting.
The reference file records display order, including the B picture before its
future reference. `make-baseline-fixture.py --bframes 2` generates compressed
Main/High samples; select `--direct spatial|temporal`, `--b-pyramid normal` and
`--implicit-bipred` for the listed qualification modes. The native fault test
also needs the plain two-reference B fixture's `final-b.nal` copied as
`fault-b2.nal` into the 64x64 fixture directory.

```sh
python3 research/mt6797-vdec/make-b-reference-fixture.py \
  --out /path/to/b16 --ffmpeg /path/to/ffmpeg --refs 16 \
  --prediction bi --weighting explicit
```

The cross-build recipe in `gstreamer-userspace.nix` accepts `buildPkgs` and
`targetPkgs`, so it does not depend on this workspace path. With the repository's
pinned nixpkgs and `pkgsCross.aarch64-multiplatform`, the original recipe produced
the userspace store path exercised in trials 29 through 34. The current recipe
adds `gstreamer-v4l2-buffer-errors.patch`: unmodified GStreamer 1.28.6 ignores
`V4L2_BUF_FLAG_ERROR` on successful capture DQBUF, allowing failed pictures
to reach the sink. The patch propagates that flag through request failure;
trial 36 verifies five actual driver errors produce nonzero pipeline status
and no failed picture output. Eight subsequent Baseline pictures match exactly. The package contains the GStreamer
CLI, scanner, and a `plugin-path` file naming the core/base/bad plugin directories.
On a matching experimental candidate, use those files to run a pipeline:

```sh
export GST_PLUGIN_SYSTEM_PATH_1_0="$(cat "$GST_PACKAGE/plugin-path")"
export GST_PLUGIN_PATH_1_0=
export GST_PLUGIN_SCANNER="$GST_PACKAGE/helpers/gst-plugin-scanner"
"$GST_PACKAGE/bin/gst-launch-1.0" filesrc location=baseline.h264 \
  ! h264parse ! v4l2slh264dec ! filesink location=native-mm21.bin

# Clocked I420 conversion, checked on the trial-44 1080p sample:
"$GST_PACKAGE/bin/gst-launch-1.0" filesrc location=main.h264 \
  ! h264parse ! v4l2slh264dec \
  ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 \
  ! videoconvert n-threads=4 ! video/x-raw,format=I420 \
  ! filesink sync=true qos=true max-lateness=20000000 location=decoded.i420
```

`../mt6797-vdec/make-baseline-fixture.py` reproduces the changing-gradient x264
fixtures and records their software-decoded references, commands, hashes and
public header trace. It verifies the selected Baseline/Main/High profile,
entropy/scaling/weighting mode, reference count, requested slices per picture
and deblocking mode. `--slices` defaults to one and accepts up to sixteen,
bounded by the coded macroblock rows. The default remains Baseline CAVLC with one reference and
unweighted prediction. It reproduces the original 128x96 stream
and reference byte for byte with the pinned FFmpeg build.

Trial 31 adds cached macroblock/pipeline progress, elapsed time and the engine
result before frontend cancellation. Reading `last_job` only accesses this
snapshot. Three exact 320x256 pictures precede a fourth-picture timeout; the
320x240 stream times out on its first picture. Both fail near the final
macroblocks with exactly 17 readable zero bytes after the end marker. Trial 32
reserves a further 128-byte readable zero block within private input storage,
with a compile-time upper-bound check. All 84 pictures then match: 18 original
ioctl pictures and 66 GStreamer pictures, including both formerly stalled
streams and a 32-picture 320x240 chain crossing four-bit frame-number wrap.
All 57 default compliance checks, normal unload, RTC/system/recovery and strict
kernel-journal audit pass. NAL/header sizes are now assigned after engine status
initialization and are validated in this trial. That tested SD build's maximum NAL size is 130816 bytes. The next HD candidate
uses a 1 MiB private input region plus a 128 KiB guard, with maximum NAL size
1048320 bytes and the same bounded end-marker lookahead. Its motion buffer
uses 512 KiB data plus a guard; picture capacity is 3 MiB plus a guard.
Prediction and wrap buffers retain their qualified sizes. Trial 40 verifies all 66 positive pictures, including Baseline/Main 720p,
Main 1080p in 1088 coded rows, uncropped Baseline 1920x1088, and exact 1080p
I420 output. All guards, normal unload, RTC/system/recovery and strict accepted
board audit pass. Default compliance passes 56/57: many unused opens exhaust
the eager per-file HD allocations. Large uncached guard scans/copies also add
130–235 ms to native jobs, so real-time playback is unqualified. A staged fix
allocates private pictures only after a valid request and to its actual storage
geometry, and uses the public Linux cached DMA API with explicit ownership.
The lifecycle/coherence candidate is now the current source, awaiting hardware
qualification. Picture allocations are deferred until a validated job and
sized to its negotiated storage. Linux non-coherent DMA pages use explicit
bidirectional synchronization before the first fetch and after a proven stop;
CPU guard/reference checks then run on the returned ownership. A fatal stop
keeps device ownership and pinned allocations until reboot.

Trial 33 tests enabled deblocking at 64x80, 128x96 and 320x240, plus the original
long chain. Its 73 successful pictures match independent software references.
An intentional truncated I_PCM picture reaches the one-second engine timeout,
stops safely with intact guards, and returns errored buffers. Its overwritten
slot's old timestamp is rejected before DMA; a P picture using the other
retained reference still matches. All 57 default compliance checks and normal
unload pass. Supervisor RTC/system/recovery checks and the strict kernel-journal audit also pass. The driver also requires
final macroblock coordinates to match the coded picture and invalidates every
cached reference if private guard/reference storage changes.

The next build admits Main-profile CABAC I/P pictures within the existing
geometry/reference limits. It initializes AVC context SRAM at offset `0x234`
after programming PPS and slice/QP controls, using a fact from the pinned public
GPL related-core interface. Trial 34 completes two independently matching 128x96 pictures, then fails the
Main streams; the 64x80/320x240 first pictures also fail. Later missing-reference
errors hide the original engine status. Baseline regression and all 57 default
compliance checks pass. The next source preserves `last_engine_failure`, a
read-only cached snapshot whose job number identifies the last error after
hardware fetch; later admission failures do not replace it. Trial 35 verifies these cached snapshots and identifies only the CABAC
zero-word trailer check (bit 14, raw error/message `0x4000`) after complete
pictures with final macroblock coordinates and intact guards. Trial 36 appends one optional escaped CABAC zero word (`00 00 03`) before the
private end marker. Software decoding verifies all 24 pictures remain unchanged,
but the hardware still flags each CABAC I picture. This trailer is removed.
The next source checks the documented sole-bit-14 completion condition: complete
macroblock coordinates and a byte-aligned parser window at zero or a start code.
It retains the raw error/message, bit cursor, tail word and classification in
cached diagnostics. All other errors and failed stop/guard checks remain fatal.
Trial 37 verifies all 56 Main pictures across 64x80, 128x96 and 320x240,
including a 32-picture chain, against independent software references. Completed
flagged pictures expose the parser start code and retain raw error/message
`0x4000`. Nine native and eight Baseline regression pictures also match. A
deliberately invalid CABAC alignment bit reports raw `0x100`, stops safely at
the one-second deadline, and causes a GStreamer request timeout before capture
error propagation can be checked. Its observer retains this negative-test
failure. The next source stops promptly on this specific fatal error and tests
it alongside 640x480/640x464/352x288 decoding. Trial 38 validates both: all 58 positive
pictures match, including deblocked Baseline/Main at 640x480 and 640x464 in
480-row storage, plus 352x288. Invalid alignment stops in 53 ms with raw
`0x100`, safe reset and intact guards. GStreamer returns an error and emits only
the independently matching preceding I picture. All 57 compliance checks and
normal decoder/probe unload pass. The separate final RTC alarm check misses
its interrupt; the supervisor preserves that system-profile failure, restores
the accepted system, and the strict recovery audit passes. The same module is
repeated in trial 39: 122 exact pictures cover the original SD/error cases,
five sequential resolution/profile segments, 640x464 I420 output and two
concurrent Main/Baseline reference chains. All media, RTC/system/recovery and
strict accepted-board checks pass in the repeat. The previous RTC miss remains
recorded without an established cause. `first_context_failure` also preserves each
context's first rejection, so pre-DMA failures cannot be hidden by later
missing references. The fixture
generator's `--deblocking` and `--entropy cabac` options generate separately
verified x264 references; their use makes no hardware encoder claim.

Trial 40 expands the bounded input to 1 MiB plus a 128 KiB guard, motion
storage to 512 KiB plus its guard, and picture capacity to 3 MiB plus its guard.
All 66 compared pictures match, including Baseline/Main at 1280x720,
Main 1920x1080 in 1088-row storage, Baseline 1920x1088 and visible-height
I420 output. One of 57 default media checks fails: opening many unused file
contexts exhausts eagerly allocated private picture storage. Normal unload
and all RTC/system/recovery checks pass; the API failure remains archived.

Trial 41 uses Linux's noncoherent DMA API with explicit ownership transfers.
Opening a file allocates no private picture DMA; valid decoding allocates two
pictures sized to the actual geometry, with 64 KiB rounding and at least
128 KiB of trailing guard. Geometry changes invalidate retained timestamps
before reallocating storage. Every input, work, picture and retained-reference
check remains in place. A failed hardware stop retains device ownership,
power and allocations until reboot. All 106 positive pictures match, the
malformed-input and stale-reference checks pass, and all 57 media checks pass,
including unlimited opens. The final sampled Main 1080p engine work is about
17 ms, measured before capture copying; sustained playback is unqualified.

Trial 42 repeats the cached HD, mixed-resolution, fault and media checks and
adds concurrent 1280x720 Main / 640x480 Baseline streams, with sixteen exact
pictures. A clocked eight-picture 1080p I420 pipeline uses valid 25 fps
timestamps, synchronization, QoS and a 20 ms lateness limit. All eight decoder
requests complete, but only six pictures reach the sink; its own drop counter
is zero. Those six pictures match their timestamped references in a separate
offline comparison. The strict eight-picture clock check fails and remains
archived. All 57 media checks, normal unload and full RTC/system/recovery/audit
pass. This result does not qualify real-time playback.

Trial 43 qualifies a 32-picture Main 1080p native MM21 sample at 25 fps: all
32 timestamps are valid, actual clock waits occur, the sink renders 32 and
drops zero, and every sample matches. Queued one-thread I420 conversion emits
27 of 32 pictures and fails the strict clock check. All 27 rendered pictures
match in a separate timestamped comparison; five completed pictures are not
exported. This trial checks 92 exact pictures including native fault/recovery,
Baseline and concurrent-stream regressions. All 57 media checks and normal
unload pass. These short samples do not qualify sustained playback or thermal
behavior. The failed conversion result remains archived.

All RTC/system checks and strict accepted-system recovery also pass.

Trial 44 sets `videoconvert n-threads=4` behind the two-buffer queue. Both
native MM21 and I420 pipelines now emit all 32 Main 1080p pictures at valid
25 fps timestamps. Each sink records 32 rendered and zero dropped; real clock
waits occur and every sample matches. Native faults, Baseline and concurrent
contexts bring the trial to 97 exact pictures. All 57 media checks, normal
unload and strict accepted recovery pass. The RTC delivery-before alarm records
two interrupts instead of one; the full system profile fails and remains
archived without an established cause. The prior serial
and queued one-thread conversion failures remain archived. These short
1.28-second samples do not qualify sustained playback or thermal behavior.

Trial 45 repeats the same module, fixtures and four-thread pipeline settings.
Both 32-picture 1080p samples again match every sample and timestamp, with 32
rendered and zero dropped per sink. The native faults, Baseline regression,
concurrent contexts and all 57 default media checks pass; all 97 compared
pictures are exact. This repeat also passes every strict RTC/system check,
normal unload, accepted recovery and kernel-journal audit. Trial 44's duplicate
alarm count and trial 38's earlier missed alarm remain recorded without an
established cause. Accepted kernel/configuration pins and bootloader are
unchanged. The source and pipelines remain experimental with the stated
one-slice I/P/reference and short-playback limits.

The encoder, interrupt completion, general codec features beyond this scope,
system suspend and untested stream configurations remain unqualified. These experimental
packages and source files do not enable the decoder in the accepted system.
