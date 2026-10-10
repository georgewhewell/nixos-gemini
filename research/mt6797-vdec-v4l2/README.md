# MT6797 V4L2 Request decoder

Original GPL-2.0-only experimental driver for the Gemini's MT6797 decoder.
It uses the public Linux stateless H.264 Request API and a register backend
derived from this project's hardware-qualified private diagnostics. No codec
firmware or proprietary codec library is loaded. Register provenance and
qualification evidence are tracked in [the interface ledger](../mt6797-video-interface.json).
This development has not used a formally separated clean-room team.

The current module decodes the listed progressive Baseline/Main I/P fixtures
through 1920x1088 coded / 1920x1080 visible, using one slice and one short-term
reference. Trial 41 checks 106 exact pictures, including 720p and 1080p,
five resolution/profile segments and visible-height I420 conversion. All 57
default media checks and normal unload pass. Its cached private DMA buffers
use explicit CPU/device ownership and picture storage is allocated only for
valid decoding requests. Trial 39 separately checks two concurrent SD streams.
Hardware encoding, broader codec features, interrupt completion and production
integration remain unfinished. All RTC/system checks and strict accepted-system recovery pass. Trial 38's
RTC miss and trial 40's failed unlimited-open check remain recorded.

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

Hardware-tested scope is progressive 8-bit 4:2:0 Baseline and the Main/CABAC
streams qualified in trial 37 below, one slice,
I/P pictures, at most one short-term reference, with enabled or disabled deblocking.
Main/CABAC retains the specifically checked trailer flag described below. Input
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
buffer export is hardware tested at the seven listed dimensions. Completion
uses a bounded workqueue poll because actual interrupt delivery is unqualified.
It does not implement an encoder.

Userspace queue storage is allocated by videobuf2-vmalloc. Hardware reads and
writes only independent private DMA allocations, with input padding, working
buffers, picture buffers and trailing guards. The current buffers are cached:
the worker synchronizes them for the device before the first fetch, then for
the CPU only after a proven hardware stop. Before copying pixels
into capture buffers, the worker requires picture completion, break/reset
acknowledgements and unchanged guards/reference storage. Baseline requires zero
error/message words. The experimental Main trailer classification below retains
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

# Optional bounded timeout, stale timestamp and retained-reference recovery:
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
```

`../mt6797-vdec/make-baseline-fixture.py` reproduces the changing-gradient x264
fixtures and records their software-decoded references, commands, hashes and
public header trace. It verifies the selected Baseline CAVLC or Main CABAC profile, one reference,
unweighted prediction, one slice per picture and the selected deblocking mode. It reproduces the original 128x96 stream
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

The encoder, interrupt completion, general codec features beyond this scope,
system suspend and untested stream configurations remain unqualified. These experimental
packages and source files do not enable the decoder in the accepted system.
