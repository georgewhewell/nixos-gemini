# MT6797 V4L2 Request decoder

Original GPL-2.0-only experimental driver for the Gemini MT6797 decoder.
It uses Linux's stateless H.264 Request API, V4L2 memory-to-memory scheduling
and videobuf2 queues. No codec firmware or proprietary codec library is loaded.
Public register provenance and original hardware diagnostics are recorded in
[the interface ledger](../mt6797-video-interface.json). Development has not used
a formally separated clean-room team.

Normal and media development share the maintained Linux 7.2.9 kernel and
`gemini-7.2.9` branch. The [accepted image](../accepted-baseline.json) is image
102, source `354d3657`. The normal system includes decoder resources and the
native VDEC clock provider; it does not enable this experimental module.
The [kernel baseline](../KERNEL_BASELINE.md) records the maintained toolchain
and interfaces. Historical modules must be used with their exact recorded
kernel configuration and symbol table.

The current IRQ backend has not completed a successful decode.
[Trial 97](irq-trial-97.json) builds against the exact image-96 kernel with
GCC 15.3.0, strict MODPOST and `W=1`. It owns bus/engine clocks and adopts and
releases the inherited ACTIVE gate through CCF, rejecting another owner.
Powered clock snapshots change from `0x111` to `0x101`, satisfying the public
ACTIVE-clear guard, but the command times out with no interrupt across all ten
CPUs. Capture retains its `0x79` test sentinel: those mismatches do not measure
decoder-private pixels. Stop, guards, unload, supervised return to image 96
and independent terminal audit pass. The undelivered interrupt predates the
7.2 rebase: trial 23's compressed grey frame had correct private pixels with
zero IRQs.

The remaining owner contract is the exact MT6797 condition that asserts MISC
`0xa4` done bit 16 after AVC picture completion. The public
[IRQ contract](irq-contract.json) establishes the clock guard, done check and
live-read acknowledge sequence; it does not establish source enablement.
Clock ownership alone did not fix the submitted PCM completion. Preserve command attribution,
stale-event rejection, IRQ synchronization before reset/power release,
bounded failure, private-DMA stop proof and fences. Picture-complete polling
cannot qualify the IRQ backend. Production integration requires this contract.
Historical compressed-grey trial 23 used clock guard `0x111`; the current
ACTIVE-clear `0x101` trial submitted only PCM. The existing request test now
has `--single grey64` for that unmeasured compressed case. It uses the original
20-byte I_16x16 DC fixture and its normal controls, then closes the stream.
The observer requires one command, real attributed delivery, every expected
sample, the five powered clock snapshots, stop and guards. Aliasing grey as
PCM or accepting a missing-input error cannot qualify the observation.

The installed native kernel source, `354d3657`, also verifies SYSIRQ polarity write
acceptance before programming its GIC parent. Its actual-callback host regression
passes GCC 15 sanitizers and rejects the old callback; the normal ARM64 kernel
build, required checks and supervised platform admission pass. Decoder SPI 240
has not yet been requested on this source. Its INTPOL word 7 bit 16 is separate
from decoder MISC done bit 16; acceptance does not establish decoder completion.
The existing [IRQ note](irq-contract.json) retains this boundary and next step.

The recorded polling implementation has a separate accepted scope on its
7.1.3 builds: trial 67 compares all 683 listed pictures exactly; trial 66
compares 104 pictures, including 54 compressed multislice pictures. Fixtures
cover progressive 8-bit Baseline/Main/High I/P/B, CABAC/CAVLC, tested scaling,
weighting, short/long-term references and POC modes. Listed single-slice cases
reach 1920x1088 coded / 1920x1080 visible. SD fixtures exercise up to 16
references; listed HD cases exercise three. Multislice lists, weights, QP and
deblocking must match across a picture. Tested short clocked playback is not
sustained playback or thermal qualification, and none of these results
qualifies the current IRQ module. Exact fixtures, failed variants, commands,
module identities and trial scopes remain in the unchanged
[trial history](README-history-20261011.md).

Userspace queues use vb2-vmalloc storage; hardware uses separate cached DMA
surfaces with explicit ownership, padding and guards. The worker synchronizes
for the device before fetch and for the CPU only after a proven hardware stop.
It validates references before allocation/power and checks guards and retained
reference storage before copying output. Stream-off and close drain work.
An unproven stop retains DMA, clocks, power and a module reference until reboot.
The `last_job` sysfs attribute reads cached state rather than live registers.
Exporting CPU capture storage does not qualify shared hardware surfaces.
Native DMA-buf attachment mapping, modifiers, cache boundaries, reference
lifetime and completion fences remain unfinished.

Build `mt6797_vdec.ko` through this directory's Kbuild against the exact
configured kernel, retaining the sibling `mt6797-vdec` control translator.
The experimental DT supplies seven decoder banks, three clocks, the VDEC power
domain, larb1 and ten decoder IOMMU ports. Use the existing supervised
`tools/test-media-boot.py` path for a justified changed-contract observation;
unchanged RTC/alarm checks do not run there. Host compilation alone does not
qualify hardware behavior.

`request-test.c` exercises real media ioctls with original independently
verified fixtures. In a supervisor-owned candidate:

```text
request-test /dev/videoN /dev/mediaN OUTPUT_DIRECTORY \
  /sys/bus/platform/devices/16020000.video-codec/last_job

request-test /dev/videoN /dev/mediaN OUTPUT_DIRECTORY \
  /sys/bus/platform/devices/16020000.video-codec/last_job --single grey64

request-test /dev/videoN /dev/mediaN OUTPUT_DIRECTORY \
  /sys/bus/platform/devices/16020000.video-codec/last_job \
  FIXTURE_DIRECTORY 64 64 export faults
```

It checks requests, capture metadata, open/stream/close, invalid references,
export lifetime and optional timeout paths. Compare saved MM21 samples against
independent expected output with `../mt6797-vdec/compare-frame.py`.
Original fixture generators and the recorded GStreamer pipelines are retained
in the [reproduction history](README-history-20261011.md).
`gstreamer-userspace.nix` cross-builds userspace; its local buffer-error patch
propagates failed capture through request failure, qualified on its recorded
polling build. It does not establish successful hardware completion.

Video encoding has produced no frame. Other codec features, sustained playback,
production IRQ completion, shared surfaces and suspend remain unqualified.
Keep these tasks in their native owners and reuse unchanged accepted results;
there is one maintained kernel and no normal-boot media qualification loop.
