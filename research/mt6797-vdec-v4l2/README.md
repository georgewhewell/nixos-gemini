# MT6797 V4L2 Request decoder

Original GPL-2.0-only experimental firmware-free H.264 decoder using Linux's
stateless Request API, V4L2 memory-to-memory scheduling and videobuf2. No
proprietary codec library is loaded. Public register provenance is recorded in
[the interface ledger](../mt6797-video-interface.json); development has not used
a formally separated clean-room team.

Normal and media development use the same maintained Linux 7.2.9 branch,
`gemini-7.2.9`. The [accepted image](../accepted-baseline.json) is image 102,
source `354d3657`. It supplies the decoder resources and native VDEC clock
provider but does not load this experimental module. The current native-buffer
path requires the DMA-owner SG bounce-marker fix in `01222a4b`.

## Current implementation

`v4l2.c` owns formats, controls, requests and queue scheduling; `engine.c` owns
hardware programming, completion and stop; `buffer.c` owns allocation, mappings,
cache transitions and fences. The sibling `mt6797-vdec` directory supplies the
shared control translator and original fixtures.

CAPTURE uses one native DMA-buf for each compound MM21 Y/C, motion and guarded
allocation. Two independently referenced plane views share it. With storage
luma size `L`, the advertised minimum view lengths are `L` and `L + L/2`;
chroma starts at `data_offset=L` and has an `L/2` pixel payload. Default queried
lengths cover the full backing. CREATE_BUFS preserves accepted unequal or larger
view lengths, allocating page-rounded `max(B, Y_view, C_view)` while retaining
the codec's guarded extent `B`. Either exported FD owns the complete allocation.
OUTPUT uses vb2-vmalloc NAL staging. There is no final CPU capture copy or
alternate private-picture path.

CAPTURE supports MMAP and read/write EXPBUF. Stock stateless GStreamer uses
MMAP plus exported DMA-bufs; its DMA-buf caps do not require importing CAPTURE
buffers. The locked GStreamer 1.28.6 allocator, plane metadata and GL uploader
honor these offsets and lengths without a private userspace patch. This source
review does not qualify hardware decoding or a running GStreamer pipeline.

DPB pictures and jobs hold independent DMA-buf references. Reservation fences
cover dependencies, CPU cache transitions, hardware work and post-stop checks.
Both output and reference diagnostics take exclusive ownership because the
current reference checks read memory through the CPU. Waits are bounded and
occur outside the common cache-owner mutex. CPU access and MMAP queue transitions
synchronize the decoder and attached-device mappings. Bounced and architecture
DMA-ops mappings are rejected; native unbounced direct/IOMMU mappings are accepted.
Stream-off and close drain work. An unproven stop retains objects, mappings,
power and unsignalled fences until reboot. `last_job` reads cached state.

The IRQ backend requires one real, nonunexpected event attributed to the active
command, MISC DONE16 and a nonzero single-core full-finish word, followed by
picture, error, last-macroblock, stop and guard checks. It rejects stale events,
masks after delivery and synchronizes handlers before reset or power release.
Picture-complete polling cannot qualify this backend. The exact remaining
peripheral contract is recorded in [irq-contract.json](irq-contract.json).

## Accepted results and limits

| Result | Accepted scope | Remaining limit |
| --- | --- | --- |
| [Trial 106](buffers-trial-106.json) | Native allocation/export, nine CREATE_BUFS cases, 17 objects, 34 FDs, Panfrost PRIME mapping, cache transitions and release lifetime | No codec or GPU submissions |
| [Trial 109](gpu-trial-109.json) | Native MM21 EGL import, all 5,120 synthetic 80×64 BT.601 pixels within RGB tolerance 2, exact alpha, reference release, teardown and module unload | No decoded frames or display scanout |
| [Trial 103](irq-trial-103.json) | Native SPI 240 setup accepted; AVC picture completion with ACTIVE clear; safe stop and unload | No delivered interrupt, timeout, no successful frame; used the earlier private-DMA backend |
| [Recorded polling builds](README-history-20261011.md) | Trials 66–67 compare their 104 and 683 listed pictures exactly on recorded 7.1.3 builds | Does not qualify current IRQ completion or native-buffer decoding |

Trial 109 fixes the backing-plane image bounds in the shared
[Mesa owner](../../nix/panfrost-image-extents.patch). Mesa detiles on the GPU;
the helper does no input CPU conversion. Earlier failed trials and their
original artifacts remain recorded, including [107](gpu-trial-107.json) and
[108](gpu-trial-108.json). The accepted normal image remains 102.

## Build and focused verification

Build `mt6797_vdec.ko` through this directory's Kbuild against the exact configured
kernel and symbol table. Use the locked default ARM64 compiler, GCC 15.3.0;
strict MODPOST and `W=1` are required. Preserve the shared control-translator
source. [The kernel baseline](../KERNEL_BASELINE.md) describes the inputs.

`request-test.c` exercises real media ioctls and original independently verified
fixtures. In a supervisor-owned candidate, its focused modes are:

```text
request-test VIDEO MEDIA OUTPUT_DIRECTORY LAST_JOB --single grey64
request-test VIDEO MEDIA OUTPUT_DIRECTORY LAST_JOB --buffers-only RENDER_NODE
request-test VIDEO MEDIA OUTPUT_DIRECTORY LAST_JOB --native-gpu RENDER_NODE HELPER
```

`--single grey64` submits the original 20-byte compressed I_16x16 DC input first
and alone. `--buffers-only` maps and releases surfaces without codec or GPU work.
`--native-gpu` produces the original colored MM21 fixture, releases the parent's
video/media/export references before admitting the helper, and requires exact
full-image comparison and teardown. These modes have different acceptance scopes.
Capture reads after decode require proven reset/stop safety and bracketed CPU
access. Use `../mt6797-vdec/compare-frame.py` for independent decoded-pixel checks.

Use the existing `tools/test-media-boot.py` supervisor for a justified changed
hardware contract. Reuse accepted results when their relevant inputs are unchanged;
do not rerun RTC/alarm diagnostics for unrelated media work. There is no normal
boot media qualification loop.

## Remaining owner work

1. Establish the exact MT6797 AVC full-finish to MISC `0xa4` DONE16
   enable/latch/handshake and SPI 240 assertion contract, then fix `engine.c`.
   Public DT/GIC/SYSIRQ numbering is consistent; an off-by-32 adjustment is
   unsupported. Repeating the unchanged trial-103 command cannot supply this
   missing contract.
2. Qualify successful native-buffer decoded frames through stock stateless
   userspace, GPU rendering and display import, retaining independent pixel checks.
3. Replace full reference snapshots only when their replacement safety contract
   is established. Keep diagnostic overhead out of the eventual normal playback
   path.
4. When CAPTURE imports are needed, give pixels and private motion/guards separate
   owners; retain foreign attachments through DPB/job lifetimes and validate the
   28-bit DMA ranges. Do not require our exporter or private allocation tails.
   Current reference programming has one shared chroma displacement, `C−Y=L`;
   arbitrary independent plane addresses need a proven additional contract.
   Do not CPU-read imported pixels behind the decoder's own pending fence.
5. Qualify sustained playback, thermal behavior and suspend after completion and
   decoded-surface integration work.
6. Finish the [encoder frame-programming owner](../mt6797-venc/README.md).

Historical polling pipelines and fixtures remain in
[the reproduction history](README-history-20261011.md). Retired probes and the
unused historical GStreamer recipe remain recoverable from their recorded Git
revisions; they are not alternate maintained implementations.
