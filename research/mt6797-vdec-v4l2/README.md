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
[Trial 103](irq-trial-103.json) builds against the exact image-102 kernel with
GCC 15.3.0, strict MODPOST and `W=1`. Native SPI 240 setup and polarity write
acceptance pass. One original compressed grey picture reaches fetch and
submission with ACTIVE clear (`0x101`); AVC reports picture completion, the
last macroblock and zero syntax error. It nevertheless times out with no IRQ
across all ten possible CPUs and MISC status `0x3001`. That earlier private-DMA
backend leaves CPU capture at its `0x79` sentinel on failure; private pixels
are not measured. This result does not qualify the replacement allocation path.
Native stop, guards and unload pass, followed by supervised return to image
102 and independent terminal audit with 54 matching source hashes and taint 0.

[Trial 97](irq-trial-97.json) previously measured the first PCM command under
the same ACTIVE-clear ownership. The undelivered interrupt predates the 7.2
rebase: trial 23's compressed grey frame had correct private pixels with zero
IRQs under the older `0x111` clock guard. These are distinct input/owner scopes.

The remaining owner contract is the exact MT6797 completion enable, latch,
handshake and path to SPI 240 after AVC picture completion. Exact GPL resource
glue pins the ISR status word to physical `0x160200a4`, matching this driver.
The public [IRQ contract](irq-contract.json) establishes the clock guard, done check and
live-read acknowledge sequence; it does not establish source enablement.
Clock ownership and accepted native polarity setup did not fix completion for
either submitted input. The snapshots do not exclude a transient assertion
or exhaust clock/routing causes. Preserve command attribution,
stale-event rejection, IRQ synchronization before reset/power release,
bounded failure, private-DMA stop proof and fences. Picture-complete polling
cannot qualify the IRQ backend. Production integration requires this contract.
The existing request test has `--single grey64` for the focused case. It uses
the original 20-byte I_16x16 DC fixture and its normal controls. On success it
closes the stream and reports a scoped completion marker.
The observer requires one command, real attributed delivery, every expected
sample, the five powered clock snapshots, stop and guards. Aliasing grey as
PCM or accepting a missing-input error cannot qualify the observation.

The installed native kernel source, `354d3657`, also verifies SYSIRQ polarity write
acceptance before programming its GIC parent. Its actual-callback host regression
passes GCC 15 sanitizers and rejects the old callback; the normal ARM64 kernel
build, required checks and supervised platform admission pass. Trial 103
accepts decoder SPI 240 setup on this source. Its INTPOL word 7 bit 16 is separate
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

CAPTURE now uses one native DMA-buf object for each compound MM21 Y/C, motion
and guarded allocation. Two independently referenced plane views share that
object; QUERYBUF and EXPBUF describe the same hardware storage. Format
`sizeimage` describes logical Y/C lengths, while queried mapping lengths cover
the whole backing and chroma `data_offset` is the luma length. Empty buffers
retain those offsets with zero logical payload. OUTPUT retains vb2-vmalloc
NAL staging. The final CPU capture copy and alternate private-picture path are
removed; retained DPB pictures and jobs own independent DMA-buf references.

Reservation fences cover dependencies, CPU cache transitions, hardware work
and post-stop checks. Output and reference errors have separate fences; both
use exclusive ownership because reference diagnostics also access memory
through the CPU. CPU access and ordinary MMAP queue transitions synchronize
the decoder mapping and every attached device mapping. Dependency waits are
bounded and happen outside the common cache-owner mutex. Stream-off and close
drain work; an unproven stop retains objects, mappings, power and unsignalled
fences until reboot. The `last_job` attribute reads cached state.

This path requires the pinned kernel's native direct/IOMMU SG bounce-marker
fix (`01222a4b`). Gemini's GPU uses direct DMA with its own MMU. Unbounced
direct and IOMMU attachments are eligible; bounced mappings and architecture
DMA-ops routes are rejected. CAPTURE currently supports MMAP and read/write
EXPBUF, without importing other DMA-bufs. CREATE_BUFS accepts equal queried
backing lengths; accepting logical-only sizes or larger backing requests is
unfinished. These restrictions are in the driver, with no downstream copy
fallback. Hardware allocation, export, GPU/display imports and decoded pixels
on this new path remain unqualified.

The pinned GCC 15.3 build passes the normal kernel checks and full image build.
The module passes a fresh ARM64 build with `W=1` and `KCFLAGS=-Werror`; all 163
required exports match that kernel. Host regressions with ASan/UBSan exercise
the actual buffer ownership, cache-transition, fence and request-test code,
including failure and fatal-retention paths. These checks cover source and
build behavior; the new image has not been installed or hardware-qualified.

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

It selects capture outside the active userspace DPB and brackets exported CPU
access with DMA_BUF_IOCTL_SYNC. It checks requests, plane offsets and bounds,
open/stream/close, invalid references, export lifetime and optional timeout
paths. Compare saved MM21 samples against
independent expected output with `../mt6797-vdec/compare-frame.py`.
Original fixture generators and the recorded GStreamer pipelines are retained
in the [reproduction history](README-history-20261011.md).
`gstreamer-userspace.nix` cross-builds userspace; its local buffer-error patch
propagates failed capture through request failure, qualified on its recorded
polling build. It does not establish successful hardware completion.

Remaining work stays here: establish the exact completion path to SPI 240;
qualify native allocations/export lifetime and real GPU/display imports with
independent MM21 comparisons; remove reference snapshot overhead only after
its replacement safety contract is proven; finish CAPTURE import and allocation
semantics, sustained playback and suspend. The encoder owner still needs a
public firmware-free frame-programming contract and has produced no frame.
Reuse unchanged accepted results; there is one maintained kernel and no
normal-boot media qualification loop.
