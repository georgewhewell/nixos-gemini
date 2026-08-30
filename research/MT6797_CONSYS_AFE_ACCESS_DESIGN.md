# MT6797 CONSYS AFE access and reset-release design

Date: 2026-08-30
Scope: static audit of the vendor MT6797 tree and
`/home/grw/src/linux-gemini-platform` at commit `3fc3e8dd2`. No Linux
implementation, DT, firmware, or hardware was changed.

## Executive result

The post-ID AFE window is the vendor's hard-coded physical range
`0x180b6000..0x180b60ff` (base `0x180b6000`, length `0x100`). It is not part of
the vendor `mediatek,mt6797-consys` DT `reg` list, which contains only MCU,
AP-RGU, TOPCKGEN, and SPM windows. The vendor maps it directly with
`ioremap_nocache()` after power/domain setup and before CONMCU reset release.

The current mainline platform has the same four CONSYS resources and reset
provider, but no AFE resource or live AFE backend. Its standard audio node at
`0x11220000` is a different peripheral. The current post-ID code is therefore
hardware-neutral only: its AFE callback is fake in KUnit, and no production
callback maps `0x180b6000`.

The smallest implementation-ready shape is a resource-owned AFE mapping in
the CONSYS runtime provider, used only while its exclusive lifecycle lease is
held:

```
VCN18/VCN28 + sleep mask + CONMCU reset asserted
    -> SCP_SYS_CONN domain/clock is positively owned
    -> chip ID 0x0279 observed
    -> MBIST bit 18 at CONN MCU + 0x110
    -> AFE writes in the exact table below
    -> reset_control_deassert(conn-mcu)
```

Do not reuse the unrelated audio AFE node, infer the AFE window from the
shared EMI reservation, or release reset before all AFE writes complete.

## Vendor proof: address, writes, and order

The vendor header defines the active OF-path AFE base and every offset/value:

> `#define CONSYS_AFE_REG_BASE (0x180B6000)`
> `#define CONSYS_AFE_REG_WBG_RCK_01_OFFSET (0x00000020)`
> `#define CONSYS_AFE_REG_WBG_BT_RX_01_OFFSET (0x00000060)`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/
common/common_main/mt6797/include/mtk_wcn_consys_hw.h:138-152`

The same header supplies the values:

| AFE offset | write value | condition |
|---:|---:|---|
| `0x14` | OR `0x00001000` | only `CONFIG_MTK_GPS_REGISTER_SETTING` |
| `0x20` | `0x180B0160` | unconditional in active AFE block |
| `0x50` | `0xB8925421` | unconditional |
| `0x54` | `0x00006401` | unconditional |
| `0x60` | `0xB8925421` | unconditional |
| `0x64` | `0x00006401` | unconditional |
| `0x68` | `0x08400000` | unconditional |
| `0x6c` | `0x0C110200` | unconditional |
| `0x70` | `0x012A020A` | unconditional |
| `0x84` | `0x00006401` | unconditional |
| `0x88` | `0x08400000` | unconditional |
| `0x90` | `0x012A020A` | unconditional |
| `0x8c` | `0x0C110200` | commented out, not a write |

Definitions are at `.../mtk_wcn_consys_hw.h:153-159`. The active OF code maps
exactly 256 bytes, optionally performs the GPS read/OR, then issues the RCK,
GPS, BT RX/TX, and Wi-Fi RX/TX writes:

> `consys_afe_reg_base = ioremap_nocache(CONSYS_AFE_REG_BASE, 0x100);`
> `CONSYS_REG_WRITE(consys_afe_reg_base + CONSYS_AFE_REG_WBG_RCK_01_OFFSET,`
> `                CONSYS_AFE_REG_DIG_RCK_01_VALUE);`

`.../mtk_wcn_consys_hw.c:451-482` (the optional GPS write is at `:454-457`).
The vendor then releases reset:

> `mtk_wdt_swsysret_config((1 << 12), 0);`

`.../mtk_wcn_consys_hw.c:492-496`. The identity poll and MBIST write precede
that block at `:415-449`; the MBIST operation is:

> `CONSYS_REG_WRITE(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET,`
> `                 CONSYS_REG_READ(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET) |`
> `                 CONSYS_MCU_CFG_ACR_MBIST_BIT);`

`.../mtk_wcn_consys_hw.c:438-449`; bit 18 is defined at
`.../mtk_wcn_consys_hw.h:188-190`.

The alternate non-OF branch contains a different, disabled (`#if 0`) comment
for `0x180B2000` (`.../mtk_wcn_consys_hw.c:595-602`). It must not override the
active `CONFIG_OF` path's `0x180B6000` contract.

## Vendor resource and clock ownership

Vendor DT declares only these four CONSYS windows:

> `reg = <0x18070000 0x0200>, /*CONN_MCU_CONFIG_BASE */`
> `      <0x10007000 0x0100>, /*AP_RGU_BASE */`
> `      <0x10000000 0x2000>, /*TOPCKGEN_BASE */`
> `      <0x10006000 0x1000>; /*SPM_BASE */`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:3759-3768`

There is no vendor DT `reg` entry for `0x180b6000`; the AFE mapping is an
unowned hard-coded access in `mtk_wcn_consys_hw_reg_ctrl()`. The vendor's
active OF sequence asserts reset, writes `PWRON_CONFG_EN`, enables its CONN
clock/domain path, waits 30 us, polls ID `0x0279`, writes MBIST, maps/writes
AFE, and deasserts reset (`.../mtk_wcn_consys_hw.c:333-355,401-496`).

The selected vendor compile flag is `CONSYS_AHB_CLK_MAGEMENT 0` and
`CONSYS_AFE_REG_SETTING 1` (`.../mtk_wcn_consys_hw.h:38-46`). With
`CONSYS_PWR_ON_OFF_API_AVAILABLE 1`, the OF path uses either legacy
`conn_power_on()` or `clk_prepare_enable(clk_scp_conn_main)` depending on
`CONFIG_MTK_CLKMGR` (`.../mtk_wcn_consys_hw.c:344-355`). The checked source
does not prove which historical Gemini build configuration was used.

## Current mainline ownership and gap

The current Gemini DT repeats only the four vendor windows and names them
`mcu`, `ap-rgu`, `topckgen`, `spm`:

`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/
mt6797-gemini-pda.dts:219-235`

The binding likewise permits exactly four `reg` items and four names
(`.../Documentation/devicetree/bindings/soc/mediatek/mediatek,mt6797-consys.yaml:42-54`).
No `0x180b6000` occurrence exists in the audited mainline CONSYS/DTS tree; the
standard audio controller is instead `audio-controller@11220000` with
`reg = <0 0x11220000 0 0x1000>` (`.../arch/arm64/boot/dts/mediatek/mt6797.dtsi:401-420`).
That audio block cannot own or substitute for ANA_WBG AFE.

The inventory driver intentionally “never maps or accesses MMIO” and only
retains resource metadata (`.../drivers/soc/mediatek/mt6797-consys.c:3-9`),
while the runtime provider maps only the MCU window and validates the other
three (`.../drivers/soc/mediatek/mt6797-consys-runtime.c:808-824`). It acquires
the exclusive CONMCU reset at `:850-854` and publishes
`RESOURCES_READY` at `:871-879`. Its lifecycle identity path reads MCU+0x8
(`:353-362`) but has no AFE pointer or AFE callback.

The current DT already correctly supplies the reset controller:

> `resets = <&watchdog MT6797_TOPRGU_CONMCU_SW_RST>;`
> `reset-names = "conn-mcu";`

`.../mt6797-gemini-pda.dts:226-234`; the ID is 12 in
`.../include/dt-bindings/reset/mt6797-resets.h:37-53`.
The reset provider serializes the WDT SWSYSRST read-modify-write, adds key
`0x88000000`, and changes bit 12 (`.../drivers/watchdog/mtk_wdt.c:167-205`).
Therefore the future AFE backend should reuse the existing exclusive reset
handle and generic `reset_control_deassert()`, not write WDT registers itself.

The existing post-ID owner expresses the correct callback order, but only as
an abstraction (`.../include/linux/soc/mediatek/mt6797-consys-postid.h:24-31`;
`.../drivers/soc/mediatek/mt6797-consys-postid.c:93-109`). Its only current
callbacks are KUnit fakes (`.../mt6797-consys-postid-kunit-test.c:111-139`).

## Required changes before live AFE access

1. **Binding/DT.** Add an `afe` memory resource of exactly
   `<0 0x180b6000 0 0x100>` and `reg-names = "afe"` to the post-ID-capable
   CONSYS node or a dedicated child owned by that driver. Extend the binding
   `reg`/`reg-names` schema accordingly; make it required for the future
   post-ID/runtime compatible, while keeping the inert inventory node valid if
   desired. Do not call the `0x11220000` audio resource AFE for this purpose.

2. **Provider.** Add an `afe` resource contract and
   `devm_ioremap_resource()` mapping in the CONSYS runtime provider, validating
   start and size before any post-ID callback. Pass that pointer only through
   the exclusive runtime lease. Keep mapping and all callbacks dormant behind
   the existing independent experiment gate.

3. **Backend.** Implement `configure_mbist`, `configure_afe`,
   `release_reset`, and `assert_reset` against the provider-owned MCU/AFE/reset
   resources. The AFE callback must use the exact vendor offsets/values above,
   omit offset `0x14` unless the GPS compile/property decision is explicitly
   made, and never write the commented `0x8c`. `release_reset` must be last.

4. **Clock/domain proof.** Keep the runtime lease held while all AFE writes
   and reset release execute. The current source proves the SCPSYS CONN domain
   vote but does not prove that its `pm_runtime_resume_and_get()` keeps the
   vendor-equivalent `clk_scp_conn_main` active for this hard-coded analog
   window. Before live enablement, inspect/trace the MT6797 SCPSYS provider or
   add an explicit named `conn` clock vote with a documented provider. I could
   not determine from this tree whether a distinct AFE clock exists; do not
   invent one.

5. **Failure semantics.** Vendor has no AFE restore path: its power-off path
   contains reset/domain/rail teardown but no AFE restoration
   (`.../mtk_wcn_consys_hw.c:611-750`). The current generic post-ID failure
   helper asserts reset and returns the owner to `IDLE` when assertion succeeds
   (`.../mt6797-consys-postid.c:35-50`), and KUnit expects `IDLE` after AFE
   failure (`.../mt6797-consys-postid-kunit-test.c:247-269`). That is not safe
   once a partial persistent AFE write is possible. Change the real backend or
   state machine to sticky `ERROR` after any AFE attempt unless a reversible
   snapshot/restore contract is proven. Do not claim rollback merely because
   reset was reasserted.

## Test oracle and remaining unknowns

The hardware-free oracle should record:

- no AFE/MMIO callback before a valid identity lease and independent gate;
- exact order `MBIST -> AFE writes -> reset deassert`;
- exact AFE offset/value list, with GPS offset `0x14` only under its explicit
  condition and no write at `0x8c`;
- MBIST, each AFE write, and reset-release failure boundaries; no later write
  after failure; reset assertion on failure;
- sticky error and retained lease after any AFE-attempt failure, unless a
  proven restore path is added; and
- removal waits for the provider/runtime lease before the mapping can vanish.

Proven: the active vendor address, table, order, reset bit, and current
mainline absence of an AFE owner. Inferred: one provider-owned mapping is the
smallest coherent mainline ownership model. Unknown: whether AP firewall/
secure firmware imposes an additional permission on `0x180b6000`, whether a
separate analog clock is required, whether the GPS conditional was enabled in
the exact Gemini image, and whether the vendor's unchecked `ioremap_nocache()`
would ever fail on this board. These require source/config provenance or a
carefully gated live observation; static evidence here cannot close them.
