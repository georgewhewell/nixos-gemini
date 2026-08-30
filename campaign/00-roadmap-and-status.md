# Gemini PDA mainline campaign: evidence first

This guide records what is known about the Planet Computers Gemini PDA and what
still needs to be tested. It is pinned to the mainline worktree
`/home/grw/src/linux-gemini-push` (branch `gemini-v7.1.3`, commit
`6191785e643cb6397255eb417342ede9ed7fdc3f`) and the exact vendor tree
`/home/grw/src/gemini-linux-kernel-3.18` (commit
`8cfe6596a503612e3332d9c26e292a19525a7f07`).

`IN_TREE` means that source or a match table exists. It never means that
Gemini hardware works. The labels used here are deliberately separate:

| Label | Meaning |
| --- | --- |
| SOURCE EXISTS | A relevant local source, DT description, blob, or wiring record exists. |
| GENERIC UPSTREAM DRIVER EXISTS | Linux has a driver family for the device class. |
| MT6797 APPLICABILITY PROVEN | The current tree has an MT6797 match table or binding, not merely a similar SoC. |
| DT ENABLED | The Gemini board DT sets the consumer `status = "okay"`. |
| BUILD-TESTED | A named image/object/config build completed; no hardware conclusion follows. |
| QEMU/KUNIT-TESTED | A hardware-free test completed; no device conclusion follows. |
| DEVICE-TESTED | A reproducible Gemini boot/log/sysfs or physical I/O test passed. |
| UNKNOWN | Evidence is insufficient. The required validation is stated explicitly. |

## Front-page status matrix

| Area | Source / generic driver | MT6797 applicability | Gemini DT | Device result / next proof |
| --- | --- | --- | --- | --- |
| Entry, UART, eMMC | SOURCE EXISTS; upstream SoC drivers | PROVEN for declared nodes | UART and MMC0 enabled (`mt6797-gemini-pda.dts:271-289`) | DEVICE-TESTED headless baseline is recorded in `research/MAINLINE.md` and the live 2026-08-30 snapshot in `research/HARDWARE_TEST_LEDGER.md`; do not generalise to other peripherals. |
| Display / DSI / panel | GENERIC UPSTREAM DRIVER EXISTS; MT6797 DRM/DSI match tables | APPLICABILITY PROVEN for SoC blocks | Display blocks disabled (`mt6797.dtsi:851-1000`); no Gemini panel node | UNKNOWN. Add a panel binding and capture a physical mode-set. |
| Mali GPU | Panfrost exists; `mediatek,mt6797-mali` match (`panfrost_drv.c:1180-1184`) | APPLICABILITY PROVEN | GPU disabled (`mt6797.dtsi:343-358`), VGPU provider disabled (`mt6797-gemini-pda.dts:314-330`) | UNKNOWN. Prove rail/OPP safety, then probe and render a test buffer. |
| Touch | Generic Novatek driver exists (`novatek-nvt-ts.c`) | NT36672A protocol match exists, but Gemini wiring is vendor-only | No Gemini touch node | UNKNOWN. Verify board ID, reset/rail timing, interrupt and coordinates on hardware. |
| Audio | MT6797 AFE and MT6797/MT6351 machine driver exist (`sound/soc/mediatek/mt6797/`) | APPLICABILITY PROVEN by `mt6797-audio` and machine compatible | AFE disabled (`mt6797.dtsi:400-422`); PMIC integration is not live proof | UNKNOWN. Add PWRAP/codec DT and run capture/playback; amplifier pulse timing remains vendor-specific. |
| Connectivity (CONSYS/BTIF/STP) | Generic 8250/APDMA sources and `btmtkuart` exist; the generic binding is `serial/8250.yaml:157-161`; candidate `mediatek,mt6797-btif` binding is in unintegrated commit `3291298d1` | BTIF equivalence is SOURCE EXISTS; Gemini wiring/transport untested | CONSYS disabled (`mt6797-gemini-pda.dts:207-222`); no deployed BTIF node | UNKNOWN. Reuse the candidate's PIO description first; prove live bytes before WMT/GNSS/BT. |
| GNSS | `drivers/gnss/mtk.c` exists; vendor task 2 documented | Protocol identity SOURCE EXISTS, not hardware proof | No GNSS client | UNKNOWN. Complete CONSYS identity, WMT bootstrap, then checksum-valid NMEA. |
| Wi-Fi / FM | Vendor source and blobs exist | No current Gemini mainline driver/applicability proof | Disabled / absent | UNKNOWN. Wi-Fi HIF and FM command/audio contracts need independent traces. |
| Modem | Vendor CCCI/CLDMA source exists; generic WWAN is not a drop-in | MT6797 modem wiring SOURCE EXISTS only | No modem DT enable | UNKNOWN. Prove firmware ownership, MPU, CLDMA/CCIF and safe boot/teardown. |
| Sensors / SCP / Hall | Generic IMU, thermal and gpio-keys drivers exist | MT6797 thermal match exists; IMU identity/wiring vendor-only | Hall and BMI160 candidates disabled (`mt6797-gemini-pda.dts:333-346`, `536-551`) | UNKNOWN. Read IDs and event streams on a recoverable image; SCP ownership is unproven. |
| Power / PMIC / charging | PWRAP/MT6351 and charger families exist | SoC/PMIC source exists; board rail topology incomplete | Read-only rails only; charger absent | UNKNOWN. Prove reset/PWRAP/rail sequence before DVFS or charging. |
| USB / Type-C | MTU3, MUSB, PHY, and FUSB301 drivers exist | MT6797 USB nodes and local host fix are tested as recorded | Peripheral resources declared (`mt6797-gemini-pda.dts:485-501`) | DEVICE-TESTED only for the gadget and host-network paths recorded in `research/MAINLINE.md` and `research/HARDWARE_TEST_LEDGER.md`; role/PD/charging remains UNKNOWN. |
| Cameras | V4L2 framework and vendor sensor source exist | No MT6797 Gemini CAMSYS pipeline driver proof | No camera nodes | UNKNOWN. First prove sensor ID/power, then CSI frame capture. |
| Keyboard / LEDs | AW9523 pinctrl and gpio-matrix-keypad exist; AW9120/flash generic matches do not | AW9523 DT schema exists | Board nodes disabled (`mt6797-gemini-pda.dts:366-483`) | UNKNOWN for current mainline. Vendor DTS confirms pins only. |
| Storage | `mtk-sd.c` has `mediatek,mt6797-mmc` match (`:733`) | APPLICABILITY PROVEN | MMC0 enabled at 25 MHz; MMC1 disabled (`mt6797.dtsi:804-824`) | DEVICE-TESTED eMMC baseline, including a read-only p29 mount and boot-partition hashes in `research/HARDWARE_TEST_LEDGER.md`; HS200/HS400 and MicroSD remain UNKNOWN. |
| Crypto / RNG | Generic SafeXcel/EIP and RNG drivers exist | No MT6797 EIP-93 match or DT node | Disabled / absent | UNKNOWN. Identify the block and clocks from silicon before writing a node. |

## Connectivity safety facts

The vendor configuration is `co_clock_flag=0` (`blobs/WMT_SOC.cfg:1-6`). The
MT6797 power-on order to preserve in any future experiment is VCN18, 240 us,
VCN28, topckgen sleep mask, assert CONSYS CPU reset, `PWRON_CONFG_EN`,
SCP_SYS_CONN/CCF domain, 30 us, then chip ID `0x0279`. The compile-time AHB
branch is disabled by `CONSYS_AHB_CLK_MAGEMENT 0`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:42`); this is distinct from `WMT_SOC.cfg`. Identity probing must not release reset, touch
AFE, request a radio function, or load firmware.

The vendor off path disables SCP_SYS_CONN/VCN28/VCN18
(`mtk_wcn_consys_hw.c:611-750`), but does not reverse the topckgen sleep-mask
write (`:328-330`) or `PWRON_CONFG_EN` (`:342`). A clean reverse-all sequence is
therefore UNKNOWN; never promise one in a test plan.

WMT SDUs use type 1 for command and type 2 for event, followed by opcode and a
little-endian 16-bit SDU length. The first SDU byte is operation-specific and
zero-length SDUs exist. Replies must be bounded by length and schema; invented
universal status bytes are not acceptable. STP's vendor channel extraction uses
`(header[1] & 0x70) >> 4` (`stp_core.c:1718`, `:2047`), not `header[1] >> 4`.

The existing mainline STP codec is only a hardware-free foundation. Its parser
returns on callback/framing errors and resets state
(`drivers/soc/mediatek/mtk-stp.c:187-225`); it does not yet provide the full
ACK/window/resynchronisation contract. KUnit is regression coverage, not device
progress.

## Falsifiable next-step plan

1. Rebuild and archive the exact branch, DTB, config and KUnit result. Keep the
   deployed DT disabled for CONSYS/BTIF and all unproven consumers.
2. Add a passive, no-MMIO resource inventory. Check every address, IRQ, clock,
   reset, rail and reserved region against vendor DTS and live DT.
3. Implement a bounded CONSYS identity experiment in the order above. Assert
   reset on every failure, record before/after registers, and report restoration
   gaps rather than guessing.
4. Reuse generic upstream 8250 support and use the candidate commit's dormant
   PIO description first. Validate `drivers/dma/mediatek/mtk-uart-apdma.c`
   separately; the custom 8 KiB ring experiment is not the architecture and is
   not a live transport result.
5. Validate mandatory STP framing with fragmented/error vectors, preserving
   unconsumed input and masking NAK from channel extraction. Add ACK/window and
   resync before firmware or clients.
6. Only after a live byte transport is demonstrated, validate exact WMT
   transactions and then GNSS task 2. Bluetooth, Wi-Fi, FM and modem are later,
   separate tracks.

Every hardware gate must name its image, DT overlay, expected log, timeout,
rollback image and evidence artifact. A compile pass or QEMU/KUnit pass cannot
be promoted to DEVICE-TESTED.
