# MT6797 CONSYS runtime/controller audit

Date: 2026-08-30

Scope: the integrated `linux-gemini-platform` series through
`d69d55863b5971c2a8d0f296036fe77b35661447`, compared with the retained vendor
MT6797 CONSYS, BTIF, WMT and GPS sources. This is a source audit only. No DT
overlay was loaded and no device transaction was performed.

## Result

The CONSYS identity prefix is source-aligned for the Gemini configuration:

```
VCN18 -> 240 us -> VCN28 -> sleep mask -> CONMCU reset -> PWRON_CONFG_EN
-> SCPSYS CONN vote/ack -> 30 us -> chip ID 0x0279
```

That conclusion is proven at the ordering and constant level, not as a live
mainline hardware result. The runtime provider and controller are both
default-disabled and there is no matching runtime/controller node in the
shipped board DT. The controller's exported start function has no non-test
caller in the audited tree, so the series cannot currently reach BTIF or WMT.

The material gap is BTIF clock ownership. Vendor BTIF says its clocks are
default off and enables the BTIF clock before `hal_btif_hw_init()`; the new PIO
platform maps only `0x1100c000`, requests only SPI 130, and never gets or
enables `btifc`. Consequently the PIO register sequence is source-matched but
not a proven usable byte transport. It must remain gated until that ownership
is added and checked.

## Proven CONSYS ordering

The vendor register path writes VCN18 at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:291-330`, including the exact short delay:

> `udelay(240);`

It then sets VCN28 hardware control and enables the 2.8 V rail when
`co_clock_type == 0` (`:311-326`). The checked-in Gemini configuration is
`co_clock_flag=0` at
`/home/grw/src/nixos-gemini/blobs/WMT_SOC.cfg:6`.

The mainline lifecycle calls those operations in the same order at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-core.c:98-127`:

> `vcn18 = true;`
>
> `mt6797_consys_delay(lifecycle, MT6797_CONSYS_VCN18_SETTLE_US);`
>
> `vcn28 = true;`

The subsequent calls at `:109-131` are sleep mask, reset, PWRON, CONN domain,
30 us delay and chip-ready poll. The constants are explicit in
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:54-66`:

> `#define MT6797_CONSYS_RUNTIME_MCU_CHIP_ID 0x8`
>
> `#define MT6797_CONSYS_RUNTIME_SPM_PWRON_CONFIG_VALUE 0x0b160001`
>
> `#define MT6797_CONSYS_RUNTIME_CHIP_ID 0x0279`

Vendor confirms the same PWRON and domain sequence at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:334-402`:

> `mtk_wdt_swsysret_config((1 << 12), 1);`
>
> `CONSYS_REG_WRITE((conn_reg.spm_base + CONSYS_PWRON_CONFG_EN_OFFSET), CONSYS_PWRON_CONFG_EN_VALUE);`
>
> `udelay(30);`

The active vendor CCF/clock-provider implementation uses CONN power control at
SPM `0x32c`, status bit 1 in both status registers, and bus-protection bits 17
and 18 (`/home/grw/src/gemini-linux-kernel-3.18/drivers/clk/mediatek/clk-mt6797-pg.c:191-200,619-655`). The current SCPSYS description records the same contract at
`/home/grw/src/linux-gemini-platform/drivers/pmdomain/mediatek/mtk-scpsys.c:885-900`,
and its power-on path enables clocks, waits for ACK, clears isolation and
releases the domain reset at `:324-360`.

This distinction matters: the vendor fallback constants in
`mtk_wcn_consys_hw.h:162-182` include a different direct-path protection mask
(`BIT(18)|BIT(19)`), but that fallback is not the selected CCF path. The
mainline code is aligned with the vendor clock-provider path, not proof of the
unused fallback path.

The sleep-mask address translation is also source-backed. Vendor names
TOPCKGEN `0x10000000 + 0x1350` and bit 8 at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:67-89,162-165`.
The board's `infrasys` syscon starts at `0x10001000` and is 0x1000 bytes at
`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:220-225`;
therefore mainline offset `0x350` addresses the same absolute register. The
write is at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:254-263`.

Reset identity is proven at the logical-bit level. The board DT names reset
ID 12 at
`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:225-230`,
the vendor asserts/deasserts the same bit at
`mtk_wcn_consys_hw.c:334-340,492-496`, and the lifecycle asserts it before
PWRON at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-core.c:113-120`.
The runtime deliberately never deasserts it or writes AFE/MBIST/firmware state.

## Proven BTIF/STP ordering, with the clock gap

The vendor BTIF hardware initializer performs normal-mode setup, handshake,
FIFO clears, thresholds, DMA disable/autor reset, and RX interrupt enable at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:476-520`.
The mainline PIO subset reproduces that order at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio.c:126-150`.
The values are also source-backed: vendor defaults TX threshold to half the
FIFO and RX to 1 (`btif_plat.c:47-58` and
`plat_inc/btif_priv.h:81-101`), matching the mainline threshold writes.

But vendor calls `hal_btif_clk_ctrl(..., CLK_OUT_ENABLE)` before
`hal_btif_hw_init()` at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/mtk_btif.c:1445-1465`.
It documents that BTIF/DMA clocks are default off at
`btif_plat.c:321-325`, and separately controls the APDMA clock in
`btif_dma_plat.c:267-293`. The current platform adapter instead validates and
maps only the core resource (`0x1100c000/0x1000`) at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio-platform.c:473-503`;
its own header says:

> `Thus probe maps no APDMA resource, never obtains or votes a clock`

That is safe while the adapter is inert, but unsafe to treat as a live-byte
path. The current PIO `attach` can reach `mt6797_btif_pio_hw_init()` and enable
SPI 130 without any explicit `btifc` clock ownership
(`mt6797-btif-pio.c:302-315` and `mt6797-btif-pio-platform.c:260-273`). This is the smallest concrete implementation gap in the series.

There is a second transport qualification. Vendor defaults both TX and RX to
DMA (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/inc/mtk_btif.h:77-90`),
and the product setup first attempts DMA before falling back to PIO
(`mtk_btif.c:1175-1223`). Thus current PIO is an intentionally bounded subset,
not evidence that Gemini's normal BTIF/APDMA path is PIO-capable.

The STP bootstrap's WMT constants and ordering are source-matched. Vendor
defines query/set/full replies at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:115-124,188-191`;
mainline retains the corresponding payloads at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-stp-bootstrap.c:87-98`.
Mainline performs mandatory query, mandatory set, full handoff, 10 ms delay,
full query and promotion at `:240-350`; vendor's mode setup and SOC init are at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:747-809`.
This proves byte/vector correspondence, not that a cold CONSYS will answer:
the mainline series has no firmware loader and no proof that the retained
firmware is already running after the identity prefix.

## GNSS boundary

Vendor fixes GPS to STP task 2 at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/include/stp_exp.h:45-58`:

> `#define GPS_TASK_INDX       (2)`

Vendor GPS reads and writes raw task-2 payloads at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/gps/stp_chrdev_gps.c:136-158,202-225`.
Opening the vendor endpoint first calls `mtk_wcn_wmt_func_on(WMTDRV_TYPE_GPS)`
at `:446-479`; the function-control WMT packet sets type and ON/OFF fields at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:395-424`.
That is radio-function activation and is intentionally absent from the
reviewed runtime/controller series.

The mainline tree already contains the safe hardware-free GNSS half. Channel 2
is declared at
`/home/grw/src/linux-gemini-platform/include/linux/soc/mediatek/mtk-stp.h:21-25`;
the full-STP session accepts only WMT/GNSS at
`drivers/soc/mediatek/mt6797-consys-stp-session.c:110-113`, and exposes a
lease-owned GNSS callback at `:519-566`. The GNSS endpoint binds that callback
and inserts accepted payloads into the Linux GNSS raw FIFO at
`/home/grw/src/linux-gemini-platform/drivers/gnss/mtk-consys.c:21-44,219-265`.
Its header explicitly says:

> `This function binds no hardware and does not power GPS on.`

KUnit exercises task-2 callback ownership and routing at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-stp-session.c:1223-1259`,
and endpoint lifecycle/stream behavior at
`drivers/gnss/mtk-consys-kunit-test.c:161-245`. Therefore adding another
GNSS codec or another task constant would be invented duplication.

## Status classification

### Proven

* Identity-prefix constants and call ordering match the selected vendor CCF
  path through chip ID `0x0279`.
* CONMCU reset is asserted before domain enable and remains asserted by this
  series; no AFE, shared-EMI mapping, firmware load, WMT function command, or
  GNSS/Bluetooth/Wi-Fi/FM client is present in the runtime/controller path.
* Vendor STP task 2 and the existing mainline lease-owned GNSS endpoint are
  source-backed, with hardware-free KUnit coverage.
* All runtime, controller and bootstrap actions require independent
  default-false module/DT gates. No non-test caller starts the controller in
  the audited tree (`rg` over the Linux tree found only the exported function
  and its KUnit calls).

### Inferred

* The `0x350` INFRACFG access is the same absolute sleep-mask register as the
  vendor TOPCKGEN `0x1350`, based on the DT base-address arithmetic above.
* SCPSYS supplies the relevant CONN clock/power ACK/bus-protection boundary,
  because its MT6797 data matches the vendor clock-provider implementation.
  This is a static ownership inference, not a live trace.

### Could not determine

* Whether a cold, reset-held Gemini CONSYS responds to the mandatory WMT/STP
  query without vendor firmware/patch state already running.
* Whether the board's normal BTIF transport can safely use PIO. Vendor defaults
  to APDMA and the current adapter does not own APDMA.
* Whether the board-level GPS_SYNC, GPS LNA, I2S and BGF EINT states are wired
  as the vendor source expects. The vendor power-on GPIO calls are at
  `mtk_wcn_consys_hw.c:757-775`; the current identity/runtime path intentionally
  omits them.
* Whether a mainline GNSS `set_power()` owner can reproduce the vendor GPS
  function-control transaction safely; no such caller exists in-tree.

## Smallest safe next slice

Do not add a GPS ON command, firmware loader, AFE write, reset release, or
shared-EMI interpretation. The smallest implementation slice is:

1. Give the PIO adapter explicit `btifc` clock ownership and enable it only
   inside the already independent attach/bootstrap gate; disable it after
   synchronous IRQ/PIO quiesce. Keep APDMA out of that slice.
2. Add a guarded internal PIO loopback/byte test that proves clocked register
   access, FIFO/IRQ ordering and fail-closed teardown, without CONSYS WMT
   function control or firmware traffic.
3. Reuse the existing opaque full-STP GNSS endpoint and KUnit tests; do not
   create a second task-2 API. A live GNSS `set_power()` callback remains a
   separate, later gate requiring exact vendor WMT reply evidence.

This slice advances toward a GNSS byte path while preserving the current
no-firmware/no-radio boundary. Until it passes, `GNSS task 2` remains a
protocol/source fact, not a device capability.

