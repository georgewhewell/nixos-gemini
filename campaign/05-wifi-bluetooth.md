# Connectivity: CONSYS, BTIF, Bluetooth, GNSS, Wi-Fi and FM

Status: SOURCE EXISTS; GENERIC UPSTREAM BTIF/APDMA and Bluetooth drivers EXIST;
MT6797 Gemini wiring and live transport **UNKNOWN**; DT ENABLED **NO**;
DEVICE-TESTED **NO**.

Current mainline has generic 8250 support (the existing generic
`mediatek,mtk-btif` binding is at
`/home/grw/src/linux-gemini-push/Documentation/devicetree/bindings/serial/8250.yaml:157-161`)
and `drivers/dma/mediatek/mtk-uart-apdma.c` (its current match table is
`/home/grw/src/linux-gemini-push/drivers/dma/mediatek/mtk-uart-apdma.c:470-477`).
Candidate commit `3291298d1` adds a
dormant PIO-only MT6797 BTIF UART node and the SoC-specific
`mediatek,mt6797-btif` compatible to the existing generic serial binding; the older
`Documentation/devicetree/bindings/soc/mediatek/mediatek,mt6797-btif.yaml` in
branch `6191785e6` is only an inventory schema, not a UART binding. Generic APDMA VFF offsets and pointer
handling are documented (`mtk-uart-apdma.c:55-75,136-177,211-239`), but MT6797
DMA address width/channel routing are not proven. The dormant PIO-only node in
commit `3291298d1` was schema/build-tested with resources
`0x1100c000/0x1000`, SPI130, `CLK_INFRA_BTIF`, `reg-shift=2`, and
`reg-io-width=4`; it remains disabled and has no device test.

The vendor tree proves STP task indices BT=0, FM=1, GPS=2, Wi-Fi=3, WMT=4
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/include/stp_exp.h:45-58`) and masks channel bits with `(header[1] & 0x70) >> 4` (`core/stp_core.c:1718,2047`). Vendor power code shows VCN18, 240 us, VCN28, sleep mask, reset, `PWRON_CONFG_EN`, domain power, 30 us, then chip-ID access (`mtk_wcn_consys_hw.c:300-342`). `blobs/WMT_SOC.cfg:1-6` sets `co_clock_flag=0`; the compile-time AHB branch is disabled separately by `CONSYS_AHB_CLK_MAGEMENT 0` (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:42`).

The board DT keeps CONSYS disabled and contains no deployed BTIF node
(`/home/grw/src/linux-gemini-push/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:207-222`). The 0x0279 identity is not a live mainline result. Identity probing must keep reset asserted and must not release AFE, request a radio function, or load firmware.

WMT is a four-byte SDU header: type 1 command, type 2 event, opcode, and
little-endian 16-bit SDU length. The vendor command/event arrays show those
types, opcodes, and lengths, including zero-length replies
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_6632.c:154-163`).
The first SDU byte is operation-specific. Variable replies require bounded
copy and an opcode-specific schema. Do not invent a universal status byte or
FM opcode table.

The existing mainline STP codec is KUnit/hardware-free only. It resets parser
state on an error and can lose unconsumed tail data
(`drivers/soc/mediatek/mtk-stp.c:187-225`); it also needs full ACK/window/
resynchronisation semantics. The custom 8 KiB ring experiment is not the
architecture: reuse upstream 8250 and validate APDMA separately, starting
PIO-first.

Next validation: passive inventory; bounded CONSYS identity; PIO byte loopback;
then WMT transcript matching exact type/opcode/length. Only after those pass
may GNSS task 2 or Bluetooth HCI be enabled. Wi-Fi and FM need independent HIF,
firmware and audio evidence; they are not implied by BT or GNSS.
