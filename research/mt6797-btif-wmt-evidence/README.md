# MT6797 Gemini BTIF/APDMA + WMT/GPS evidence packet

Status: evidence packet for the next implementation agent. No kernel source,
device, firmware, or hardware was modified by this investigation.

## Scope and confidence

The primary local source is the vendor tree at
`/home/grw/src/gemini-linux-kernel-3.18` (commit
`8cfe6596a503612e3332d9c26e292a19525a7f07`). The reviewed mainline inventory is
`/home/grw/src/linux-gemini-connectivity-reviewed` (commit `e3f9ca908`). The
runtime evidence is a read-only Gemian capture committed in this repository.

Evidence labels used below:

* **source**: directly quoted from vendor/mainline source or DT;
* **capture**: directly quoted from a saved device observation;
* **derived**: mechanically computed from source field assignments, not a wire
  capture;
* **unknown**: not established by the available evidence. Do not turn an
  unknown into a default.

The vendor stack defines BTIF/APDMA as the WMT/STP transport for this Gemini,
and the saved Gemian capture shows that transport's drivers and IRQs active.
It does **not** establish that a mainline kernel can safely power CONSYS or
load the radio firmware yet.

## Hardware contract

### BTIF core, APDMA channels, IRQs, clocks

| Function | Vendor DT resource | Vendor IRQ | Source |
|---|---|---:|---|
| APDMA parent | `0x11000000 + 0x1000` | SPI 97 | `/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2344-2348` |
| BTIF TX APDMA | `0x11000a00 + 0x80` | SPI 116, level-low | `/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2350-2354` |
| BTIF RX APDMA | `0x11000a80 + 0x80` | SPI 117, level-low | `/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2356-2360` |
| BTIF core | `0x1100c000 + 0x1000` | SPI 130, level-low | `/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2511-2517` |
| CONSYS owner | `0x18070000 + 0x200`, AP RGU `0x10007000 + 0x100`, TOPCKGEN `0x10000000 + 0x2000`, SPM `0x10006000 + 0x1000` | SPI 284 BGF, SPI 285 WDT | `/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:3759-3772` |

Verbatim source excerpts:

> `clocks = <&infrasys INFRA_BTIF>,<&infrasys INFRA_AP_DMA>;`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2515-2516`

> `#define BTIF_RBR(base) (unsigned long)(base + 0x0)`
> `#define BTIF_IER(base) (unsigned long)(base + 0x4)`
> `#define BTIF_IIR(base) (unsigned long)(base + 0x8)`
> `#define BTIF_LSR(base) (unsigned long)(base + 0x14)`
> `#define BTIF_DMA_EN(base) (unsigned long)(base + 0x4C)`
> `#define BTIF_TRI_LVL(base) (unsigned long)(base + 0x60)`
> `#define BTIF_HANDSHAKE(base) (unsigned long)(base + 0x6C)`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/plat_inc/btif_priv.h:32-45`

The vendor hardware-init sequence sets normal mode, enables the new
handshake, clears RX and TX FIFOs, programs the TX/RX trigger levels, disables
both DMA directions initially, enables DMA auto-reset, disables TX IRQ, and
enables RX IRQ (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:476-521`).
The line-status and interrupt bits are defined at `btif_priv.h:47-60`.

There is **no BTIF pad/pinctrl assignment in the vendor BTIF DT nodes** found by
this audit. The pin-function header exposes CONSYS GPS signals on GPIOs
228--231 (`/home/grw/src/gemini-linux-kernel-3.18/include/dt-bindings/pinctrl/mt6797-pinfunc.h:1162-1171`), but
that does not prove they are the board's BTIF pads. Treat BTIF pad mux as
**unknown** until read from the board DT/pin controller or a vendor runtime
dump. The board-specific GPS LNA host pin is separate: GPIO69 has init,
high, and low states (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1269-1313`).

The saved Gemian capture provides an independent runtime cross-check:

> `11000a00.btif_tx -> vendor BTIF DMA driver`
> `11000a80.btif_rx -> vendor BTIF DMA driver`
> `1100c000.btif -> mtk_btif`

`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:25-33`

The same capture reports BTIF TX DMA 38880, RX DMA 21806, and core 5 IRQs at
the snapshot (`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:47-51`). The capture's
Linux IRQ printout is 32 above the DT SPI numbers; use DT SPI values in a
mainline binding and obtain Linux IRQs with `platform_get_irq*()`.

### APDMA VFIFO setup, reset, and recovery

The vendor defines both TX and RX virtual FIFOs as 8192 bytes, with an
8-byte-alignment requirement (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/plat_inc/btif_dma_priv.h:30-34`). Channel-local
register offsets are TX `0x880` and RX `0x900` relative to APDMA in the legacy
non-OF path (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/plat_inc/btif_dma_priv.h:36-41`); the OF DT windows above are the
authoritative addresses for this board. Common offsets are INT_FLAG `0x00`,
INT_EN `0x04`, EN `0x08`, RST `0x0c`, STOP `0x10`, FLUSH `0x14`, VFF_ADDR
`0x1c`, LEN `0x24`, THRE `0x28`, WPT `0x2c`, RPT `0x30`, VALID `0x3c`, LEFT
`0x40`, and high address `0x54` (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/plat_inc/btif_dma_priv.h:43-80`).

The exact vendor init contract is:

1. For each direction, set **warm reset** and poll the direction's EN bit until
   it clears. The vendor's hard-reset writes are commented out
   (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:412-420` and `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:446-453`).
2. Program the physical VFIFO base, optional high address, length, WPT, RPT,
   and threshold. Clear RX DONE|THRE and enable RX DMA IRQ; clear TX INT and
   leave TX DMA IRQ disabled (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:421-475`).
3. Enable a direction by setting EN. Disable it by setting STOP and polling
   STOP clear; this waits for the current transaction rather than cutting it
   off (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:521-583`).
4. Keep software pointers and wrap bits in sync. The reset helper zeros RPT,
   WPT, and both wrap trackers (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:585-609`).

RX consumes circular data from RPT to WPT, calls the registered callback for
one or two wrapped segments, issues a memory barrier, updates RPT, and then
reenables the RX IRQ (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:993-1098`). TX copies into the
circular VFIFO, uses a memory barrier before publishing WPT, enables DMA, and
flushes a 1--7-byte tail (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:794-890`).

Do **not** copy two vendor failure modes into mainline: TX calls
`BUG_ON(buf_len > ava_len)`, explicitly noting that it panics the kernel
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:827-834`), and the vendor VFIFO reset helper initializes
its return value to `-1` even after resetting state (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_dma_plat.c:595-609`).
Mainline should return `-EAGAIN`/short write for insufficient ring space and
return success after a successful reset.

The MT6797 functional specification independently describes one BTIF TX and
one BTIF RX APDMA engine and distinguishes warm reset (waits for an in-flight
transaction) from hard reset (can break the bus). Primary mirror:
[MT6797 Functional Specification V1.0, AP_DMA section](https://www.96boards.org/documentation/consumer/mediatekx20/additional-docs/docs/MT6797_Functional_Specification_V1_0.pdf), pp. 141--142 (PDF text around lines 8425--8522). This agrees with the vendor choice above; it is not a substitute for testing this board.

### Framing, flow, and STP mode

BTIF is a byte transport; it is not a normal Linux UART node. The vendor WMT
HIF enum assigns UART=0, SDIO=1, BTIF=2 (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:118-123`).
The vendor UART baud/flow path is conditional: the default baud is applied
only when `hifType == WMT_HIF_UART` (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:735-744`). Therefore
there is no BTIF baud setting to carry into mainline. UART flow-control enum
values exist at `wmt_core.h:181-195`, but are irrelevant to BTIF.

STP constants are explicit:

> `#define MTKSTP_BTIF_FULL_MODE STP_MODE_BIT(2)`
> `#define MTKSTP_BTIF_MAND_MODE STP_MODE_BIT(3)`
> `#define MTKSTP_CRC_SIZE (2)`
> `#define MTKSTP_HEADER_SIZE (4)`
> `#define MTKSTP_WINSIZE (7)`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/stp_core.h:86-113`

Mandatory mode sends a 4-byte header (`0x80`, type/12-bit length, low length,
zero), payload, and two zero bytes (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/stp_core.c:1120-1149`). Full mode
uses a sequence/ack byte, type/length, header checksum, payload, and CRC16
low-byte first; it tracks a seven-packet window and retry timer
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/stp_core.c:1151-1207`). Thus the six-byte WMT PDU documented below
is only the STP payload, not the complete BTIF wire frame.

Product mode is conditional, not a compile-time fact:

* when BTIF is selected, generic `wmt_core_stp_init()` starts in mandatory
  mode, then enables STP (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:747-779`);
* SOC init then queries/sets the chip and explicitly switches the host to
  `MTKSTP_BTIF_FULL_MODE`, waits 10 ms, and queries again
  (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1008-1045`);
* userspace `wmt_lib_set_hif()` selects BTIF from the low nibble value
  `STP_BTIF_FULL = 0x03`, and sets the transport to BTIF
  (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/linux/include/wmt_dev.h:19-22` and `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_lib.c:552-596`).

Conclusion: the intended product path is **BTIF full after successful SOC
initialization when hifconf 0x3 is selected**. The available capture does not
include the hifconf value or a raw STP frame, so “BTIF full is active now” is
not promoted to a fact. The implementation must log the selected HIF and STP
mode at runtime.

## WMT/GPS contract

### Function-control PDU

The WMT packet structure is one type byte, one opcode byte, a little-endian
16-bit SDU length, then parameters (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:325-332`).
Command type is 1, event type is 2, and function-control opcode is 6
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:334-353`). GPS is function type 2
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/include/wmt_exp.h:112-128`). The function-control implementation writes
function type at parameter 0, ON/OFF at parameter 1, and SDU length 2; it
expects a 5-byte event with matching opcode and status byte zero
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:413-424` and `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:453-488`).

Therefore the exact **WMT payload PDU**, derived from those assignments, is:

| Operation | WMT payload bytes | Expected WMT event bytes |
|---|---|---|
| GPS ON | `01 06 02 00 02 01` | `02 06 01 00 00` |
| GPS OFF | `01 06 02 00 02 00` | `02 06 01 00 00` |

These are **derived**, not captured. The exact BTIF wire bytes additionally
depend on STP mode, sequence, acknowledgement, header checksum, and in full
mode CRC16. A live trace must record both the WMT payload at the WMT/STP
boundary and the final bytes handed to APDMA.

### GPS power/pin sequence

`wmt_func_gps_on()` first performs the GPS pre-control, then sends the function
ON PDU and sets shared GPS state; it may send de-sense control if BT or Wi-Fi
is already on (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_func.c:533-569`). `wmt_func_gps_off()` performs
pre-control, sends OFF, clears state/de-sense, and conditionally powers down
GPS PALDO when FM is not on (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_func.c:572-607`).

Pre-control sets GPS sync to 1/0, then uses a host LNA control when
`wmt_gps_lna_enable == 0`; otherwise it selects EEDI/EEDO according to
`wmt_gps_lna_pin` (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_func.c:405-516`). The product board DT gives
host GPIO69 explicit low/high/low pin states
(`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1275-1301`).

The checked-in WMT configuration is:

```text
coex_wmt_ant_mode=1
wmt_gps_lna_pin=0
wmt_gps_lna_enable=0
co_clock_flag=0
```

`/home/grw/src/nixos-gemini/blobs/WMT_SOC.cfg` (80 bytes,
SHA-256 `f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880`)
and the saved capture's verbatim summary
`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/wmt-config-summary.txt:1-6`. This selects the host-LNA branch;
it does **not** by itself prove GPIO69 is physically connected to an LNA.

### GPS endpoint and readiness

GPS uses STP task index 2; BT=0, FM=1, GPS=2, Wi-Fi=3, WMT=4, STP=5
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/include/stp_exp.h:45-60`). Opening `/dev/gps` turns GPS on before checking
STP ready, registers the GPS event callback only after ready, and closing it
unregisters callbacks before turning GPS off
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/gps/stp_chrdev_gps.c:446-525`).

The next implementation must not expose GPS data until all of these gates hold:

1. CONSYS owner is powered and identity/readiness checks passed;
2. BTIF clocks are enabled and BTIF core + both APDMA resources are mapped;
3. RX/TX VFIFOs are warm-reset and initialized; RX DMA is enabled only after
   the callback/parser is installed;
4. STP mode and ready state are observed in the selected HIF (mandatory during
   bootstrap, full after SOC switch if hifconf 0x3);
5. firmware/config lookup has succeeded, with the selected filenames logged;
6. WMT GPS ON gets the exact matching event with status 0.

## Firmware boundary and unresolved load address

The NixOS module installs the original, uncompressed names
`ROMv3_patch_1_0_hdr.bin`, `ROMv3_patch_1_1_hdr.bin`, `WIFI_RAM_CODE_6797`, and
`WMT_SOC.cfg` (`/home/grw/src/nixos-gemini/nixos/firmware.nix:8-20`). The local
blob sizes/hashes are recorded in the capture
`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:53-60`.

Vendor source names the SOC configuration `WMT_SOC.cfg`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_conf.h:33-34`)
and requires it for a SOC chip, failing config loading if it cannot read/parse
it (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_conf.c:432-486`). The generic fallback patch name is
`mt66xx_patch_hdr.bin` (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:55-57`). It then performs
multi-patch search, obtains each selected filename, reads a 28-byte patch
header, strips that header, fragments the body, and downloads each patch
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1052-1091` and `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2030-2135`). The SOC table marks the
0x8A00/0x8A01/0x8B01 revisions as not workable without a patch and selects
the `_e1` extension (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:875-904`).

The precise runtime patch filename is **not established** by source alone: the
multi-patch path asks a search service for each valid filename
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2072-2087`), while the checked-in blobs use product
names `ROMv3_patch_1_*`. Do not rename or guess; instrument the patch-search
callback and log the requested name.

The precise patch RAM load address is also **unknown/contradictory**. The
source has an MT6797 address branch only when `wmt_ic_ops_soc.icId == 0x0279`,
writing address bytes `08 05` and patch address bytes `2c 0b`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2162-2169`). But the same vendor operation table
initializes `wmt_ic_ops_soc.icId = 0x0000`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:957-968`). The runtime capture identifies the combo as
`MT6797`, WMT `MT279`, ROM E1, and patch date 20180307, but records no firmware
load (`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:19-22` and `:74-77`). Therefore
the next agent must capture chip-ID/ops ID and every address command before
claiming a load address.

Do not redistribute or infer licensing from these local blobs. Their presence
is an installed firmware boundary, not proof that a new mainline distribution
may publish them.

## Shared ownership and contradictions

CONSYS is one shared resource owner. The WMT context stores an array of driver
states (`eDrvStatus[WMTDRV_TYPE_MAX]`) and one HIF configuration
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:313-323`); GPS uses shared state bits and checks
BT/Wi-Fi state before de-sense control (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_func.c:551-565`). Thus
BT/GPS/WMT STP task endpoints must serialize through one CONSYS/BTIF owner.
Wi-Fi has its own vendor hardware path and firmware, but shares CONSYS power,
identity, firmware, and coexistence policy; do not independently reset CONSYS
from a GNSS or Bluetooth child.

Contradictions and their safe interpretation:

1. **Vendor active vs reviewed mainline dormant.** Vendor DT has three BTIF
   resources and two clocks. Reviewed mainline currently has only a disabled
   core UART-like node, one BTIF clock, and an explicit comment that PIO has no
   APDMA dependency until a CONSYS owner exists
   (`/home/grw/src/linux-gemini-connectivity-reviewed/arch/arm64/boot/dts/mediatek/mt6797.dtsi:524-537`).
   Its binding/driver says inventory-only and does not map registers, enable
   clocks, request IRQs, allocate DMA, power CONSYS, expose an ABI, or
   instantiate STP (`/home/grw/src/linux-gemini-connectivity-reviewed/Documentation/devicetree/bindings/soc/mediatek/mediatek,mt6797-btif.yaml:12-18`;
   `/home/grw/src/linux-gemini-connectivity-reviewed/drivers/soc/mediatek/mt6797-btif-inventory.c:47-107`). This is a known
   implementation gap, not evidence the vendor resources are wrong.
2. **Mandatory vs full STP.** Generic init is mandatory; successful SOC init
   switches host to full. The live capture lacks mode state. Log it.
3. **GPS LNA path.** `WMT_SOC.cfg` selects host LNA, and the board DT gives
   GPIO69 states. Vendor platform code also has a conditional alternate
   MT6306 GPIO path; do not assume that alternate is live on this board without
   the `MTK_WCN_MT6306_IS_READY` runtime condition.
4. **Patch ID/address.** MT6797-specific address code is gated on 0x0279 while
   the static ops ID is 0. Capture the actual path; do not use `0x0508`/`0x0b2c`
   as a proven address.
5. **Historical board docs.** Existing `research/HARDWARE.md` calls the combo
   MT6630, but the live capture says MT6797/MT279. The live chip-ID capture and
   vendor MT6797 source win; repair the stale prose separately.

## Bounded first live experiment

This is a test design for the implementation/flashing agent, not permission to
flash or reset the device from this research lane.

1. Add an opt-in debug path with the default DT node disabled. Keep one CONSYS
   owner and one BTIF transport lock; child BT/GPS/Wi-Fi clients acquire a
   function reference instead of touching clocks, reset, or supplies directly.
2. On start, log DT SPI resources, mapped bases, Linux IRQs, clock state,
   CONSYS chip/ROM IDs, selected HIF (`hifconf`), STP mode/ready, requested
   firmware names, patch addresses, and every TX/RX frame. Do not transmit a
   function command until all readiness gates above pass.
3. Allocate coherent 8192-byte TX/RX rings, warm-reset both DMA directions,
   initialize pointers/thresholds, register RX parser, then enable RX. Use
   STOP-and-poll for shutdown. Never use APDMA hard reset or vendor `BUG_ON`.
4. With the vendor radio already in its normal Gemian state, send exactly one
   GPS ON WMT payload (`01 06 02 00 02 01`) through the real STP path. Verify
   event payload `02 06 01 00 00`. Then send exactly one OFF payload and verify
   the same status-zero event. Do not add HCI, Wi-Fi, patch download, or retry
   traffic to this first experiment.
5. Acceptance: captured WMT payloads match byte-for-byte; STP parser accepts
   the selected mode and sequence/CRC; RX/TX IRQ counters advance; GPIO69
   follows low -> high -> low for the host-LNA path; OFF leaves DMA disabled or
   quiescent and no watchdog, kernel panic, CONSYS reset, or SSH loss occurs.
6. Abort on timeout, malformed event, unexpected chip reset, ring pointer
   anomaly, or any watchdog/SSH symptom. Do not automatically retry. Recover
   using the known Gemian side-button path only after the device is safe.

## Next-agent API and acceptance test

The smallest useful split is:

```text
struct mt6797_consys_owner {
        int (*get)(enum mt6797_func);       /* power/ref + readiness */
        void (*put)(enum mt6797_func);
        int (*wmt_xact)(const u8 *tx, size_t tx_len,
                        u8 *rx, size_t rx_len, unsigned int timeout_ms);
};

struct mt6797_btif_transport {
        int (*start)(struct mt6797_consys_owner *owner);
        void (*stop)(void);
        ssize_t (*tx)(const u8 *buf, size_t len); /* -EAGAIN, never BUG_ON */
        int (*set_rx)(void (*consume)(const u8 *, size_t));
};
```

The API is deliberately transport-first: GNSS calls `get(GPS)`, sends the
WMT PDU through `wmt_xact`, and registers STP task 2; Bluetooth and Wi-Fi use
the same owner and cannot reset the physical transport underneath it. The
first KUnit/host test should inject a deterministic STP frame and verify
header/length/checksum/CRC parsing, circular-ring wrap, short-space `-EAGAIN`,
and WMT ON/OFF event validation. The first device test is the single ON/OFF
pair above with frame logging and no firmware download.

## Upstream status

The current reviewed branch is intentionally an inventory, not a functional
BTIF/WMT implementation. The official MediaTek SoC support matrix currently
lists MT6797 BTIF, HCI UART, and APDMA as N/S rather than upstream support:
[MediaTek mobile-chip matrix](https://mtk.docs.kernel.org/matrix/mobile_chips.html).
The upstream mailing list guidance for MT6797 is explicit: “use it only as
reference and rewrite the drivers from scratch” ([Linux-mediatek message,
18-Feb-2021](https://lists.infradead.org/pipermail/linux-mediatek/2021-February/021988.html)).
That matches the local branch boundary: reuse generic Linux patterns where
appropriate, but port the vendor contract above rather than pretending
`btmtkuart` is the MT6797 BTIF driver.
