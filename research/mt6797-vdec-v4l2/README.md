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

Current admission is progressive 8-bit 4:2:0 Baseline, one slice,
I/P pictures, at most one short-term reference and disabled deblocking. Input
is `V4L2_PIX_FMT_H264_SLICE` with no start code; capture is two-plane native
`V4L2_PIX_FMT_MM21`. The next build admits widths 64..320 in steps of 16 and
heights 64..256 in steps of 32; larger inter pictures remain unqualified.
Its independent coherent allocations are 256 KiB each, with separate 128 KiB
data and trailing guard regions. GStreamer's initial 320x240 probe can negotiate
320x256; this does not establish GStreamer compatibility before a real pipeline
passes. Queues
use MMAP allocation and can export their CPU storage through `VIDIOC_EXPBUF`;
buffer export is hardware tested at 64x64. Completion
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
