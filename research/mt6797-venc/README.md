# MT6797 firmware-free video encoder

No encoder frame has been submitted or produced. A native implementation needs
a public MT6797-compatible frame-programming contract; resource access and idle
reset checks do not establish it. Register provenance and historical observations
remain in [the interface ledger](../mt6797-video-interface.json).

The examined public MT8173 encoder driver, Chromium EC handler and
[April 2026 common encoder proposal](encoder-common-interface-20260423-lead.json)
do not supply direct frame programming. They delegate SPS/PPS/frame commands to
VPU/SCP firmware or a private overlay. This does not establish that MT6797
requires firmware. No proprietary codec source, library or firmware has been
examined or used by this work.

The public [MT6582 kernel wrapper](https://android.googlesource.com/kernel/mediatek/+/f3aa758d997877557afc249dfc45db452e585f6f/drivers/misc/mediatek/videocodec/mt6582/videocodec_kernel_driver.c)
also supplies IRQ/ACK handling and maps encoder registers to callers. Its
[GPL HAL](https://android.googlesource.com/kernel/mediatek/+/f3aa758d997877557afc249dfc45db452e585f6f/drivers/misc/mediatek/videocodec/mt6582/common/hal/src/hal.c)
has empty initialization/control cases. These inspected sources supply no
direct frame backend or MT6797 register-compatibility contract.

Remaining work belongs in one native V4L2 encoder driver:

1. Establish source-plane address/pitch fields, reference and reconstruction
   layout, bitstream address/limit, scratch sizes, address units, geometry/QP,
   start, completion/error and active-DMA stop contracts from admissible public
   sources. Similar silicon is a lead requiring MT6797 validation.
2. Implement the smallest fixed-QP intra-frame path using current V4L2,
   videobuf2, DMA, power and supplier interfaces.
3. Independently decode the produced bitstream and compare its content, then
   qualify stop/error/lifetime before expanding codec features or throughput.

The old command-free resource probe passed its recorded checks repeatedly,
including trial 67. The idle-reset probe has only a strict Linux 7.2.9 build;
it has no hardware or encoded-output result. Their unused Kbuild/probe sources
are retired from the maintained tree. Retrieve them, with the prior explanatory
README, from packaging revision
`b77005c0fe410b9d1569ccb3d74be5eae6bb8f78`; all recorded evidence, including
[idle-reset/build.json](idle-reset/build.json), remains intact. Do not repeat
command-free checks as evidence of encoder progress.
