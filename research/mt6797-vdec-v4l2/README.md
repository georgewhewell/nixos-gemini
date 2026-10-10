# MT6797 V4L2 Request decoder

Original GPL-2.0-only experimental driver for the Gemini's MT6797 decoder.
It uses the public Linux stateless H.264 Request API and a register backend
derived from this project's hardware-qualified private diagnostics. No codec
firmware or proprietary codec library is loaded. Register provenance and
qualification evidence are tracked in [the interface ledger](../mt6797-video-interface.json).
This development has not used a formally separated clean-room team.

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

Current admission is progressive 8-bit 4:2:0 Baseline, one slice,
I/P pictures, at most one short-term reference and disabled deblocking. Input
is `V4L2_PIX_FMT_H264_SLICE` with no start code; capture is two-plane native
`V4L2_PIX_FMT_MM21`. The driver admits widths 64..320 in steps of 16 and
heights 64..256 in steps of 32. Only the seven dimensions above have been tested.
Its independent coherent allocations are 256 KiB each, with separate 128 KiB
data and trailing guard regions. GStreamer's initial 320x240 probe can negotiate
320x256. Real GStreamer decoding is qualified only for the listed trial-29 streams. Queues
use MMAP allocation and can export their CPU storage through `VIDIOC_EXPBUF`;
buffer export is hardware tested at the seven listed dimensions. Completion
uses a bounded workqueue poll because actual interrupt delivery is unqualified.
It does not implement an encoder.

Userspace queue storage is allocated by videobuf2-vmalloc. Hardware reads and
writes only independent coherent DMA allocations, with private input padding,
working buffers, picture buffers and trailing guards. Before copying pixels
into capture buffers, the worker requires picture completion, zero error and
message words, break/reset acknowledgements and unchanged guards/reference
storage. It resolves references by the input timestamp and checks picture
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
pinned nixpkgs and `pkgsCross.aarch64-multiplatform`, it produces the same
userspace store path exercised in trial 29. The package contains the GStreamer
CLI, scanner, and a `plugin-path` file naming the core/base/bad plugin directories.
On a matching experimental candidate, use those files to run a pipeline:

```sh
export GST_PLUGIN_SYSTEM_PATH_1_0="$(cat "$GST_PACKAGE/plugin-path")"
export GST_PLUGIN_PATH_1_0=
export GST_PLUGIN_SCANNER="$GST_PACKAGE/helpers/gst-plugin-scanner"
"$GST_PACKAGE/bin/gst-launch-1.0" filesrc location=baseline.h264 \
  ! h264parse ! v4l2slh264dec ! filesink location=native-mm21.bin
```

The encoder, interrupt completion, general codec features, larger pictures,
resolution changes and system suspend remain unqualified. These experimental
packages and source files do not enable the decoder in the accepted system.
