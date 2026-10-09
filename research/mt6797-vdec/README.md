# Independent MT6797 H.264 implementation

This directory contains original GPL-2.0-only control translation and a temporary
kernel register probe. It does not expose a video device or decode a frame.
Encoding is not implemented.

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

On Gemini, the 338 MHz clock and the candidate local selector roundtrip
`0 -> 2 -> 0` were observed. SPS/PPS/reference-count and parser-enable readback
remained zero, so this probe did not establish their compatibility. The public
reference reads status fields from the control register and does not read back
SPS/PPS; zero readback may reflect write-only fields or missing initialization.
The saved diagnostic error means expected readback was not obtained, not that
an actual decode failed. No decode was attempted. Raw evidence is under
`handoff/video-cleanroom-20261009`, with separate directories for earlier attempts.

## Building the temporary module

Use a prepared output tree for the exact running kernel, with its configuration
and genuine `Module.symvers`. Build outside this source directory:

```sh
cp -r research/mt6797-vdec /path/to/probe-build
make -C /path/to/kernel-build M=/path/to/probe-build \
  ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- LOCALVERSION= modules
```

The current accepted kernel omits `CONFIG_COMMON_CLK_MT6797_VDECSYS`. The probe
also needs the existing open-source `clk-mt6797-vdec` provider, built for the
same kernel and loaded first. The production kernel configuration is unchanged.
Do not force-load a module with a mismatched configuration or version.

## Remaining implementation

The next requirements are hardware qualification of the candidate interface,
decoded-buffer layout and alignment, reference/MV/scratch-buffer programming,
IOMMU/DMA setup, bounded reset/completion recovery and actual frame submission.
Then add V4L2 request/queue handling and compare output with software-decoded
fixtures before exposing supported formats. Encode needs its own hardware
contract and implementation. These are required work, not completed features.
