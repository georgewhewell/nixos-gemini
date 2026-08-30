# MT6797 CONSYS post-identity backend

Status: implementation guidance, 2026-08-30.  This report is based on the
vendor tree at `/home/grw/src/gemini-linux-kernel-3.18` and mainline tree
`/home/grw/src/linux-gemini-platform` at `3fc3e8dd2370bdebf24c7eecd78275c281516a72`
(`3fc3e8dd2`).  It covers only the vendor prefix after chip identity:
MBIST, the conditional AFE writes, and CONMCU reset release/assert.  It does
not authorize a DT enablement, firmware load, transport, or radio operation.

## Bottom line

The vendor `CONFIG_OF` path proves this order after the chip-ID poll:

```
MBIST ACR bit 18 -> optional AFE register writes -> CONMCU reset deassert
```

The current mainline post-ID owner already expresses this callback order at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-postid.c:96-108`,
but it has no hardware backend.  The backend must not pretend that the
existing four mappings include AFE: the mainline Gemini node has only
`mcu`, `ap-rgu`, `topckgen`, and `spm` at
`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:219-225`.

Required implementation blockers are therefore:

1. Add a separately validated, exclusively owned AFE mapping for physical
   `0x180b6000..0x180b60ff`, or make AFE a proven board-specific optional
   operation.  Do not derive it from an unrelated resource.
2. Implement MBIST as an MCU mapping read-modify-write.
3. Implement reset release/assert through the existing exclusive
   `conn-mcu` reset handle, not a second raw WDT mapping.
4. Make the post-ID transaction fail closed.  Vendor AFE/MBIST paths have no
   demonstrated inverse, so a failed later callback cannot safely restore the
   prior analogue state.

## Vendor evidence and exact operations

### Preconditions and identity boundary

The vendor DT branch first asserts CONMCU reset, writes SPM power-on enable,
and enables the CONSYS clock/domain.  The source says:

> `mtk_wdt_swsysret_config((1 << 12), 1);`

(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:333-342`).
The configured clock path is conditional:

> `iRet = conn_power_on();`

or:

> `iRet = clk_prepare_enable(clk_scp_conn_main);`

(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:344-355`).
The source then waits 30 microseconds and polls MCU offset `0x8` for
`0x0279` at `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:401-424`.  The timeout only logs diagnostics at `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:426-436`;
it does not return an error.  A new backend must retain the mainline
fail-closed timeout semantics and must not copy that log-and-continue bug.

The vendor call path is `wmt_plat_pwr_ctrl(FUNC_ON)` →
`mtk_wcn_consys_hw_pwr_on()` → `mtk_wcn_consys_hw_reg_ctrl(1, ...)` at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/wmt_plat_alps.c:446-455`
and
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:797-814`.
`wmt_plat_init()` separately calls `mtk_wcn_consys_hw_init()` at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/wmt_plat_alps.c:325-358`; that init owns EMI MPU/remap/clear and is outside
this report.

### MBIST

The applicable `CONFIG_OF` code is:

> `CONSYS_REG_WRITE(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET,`
> `CONSYS_REG_READ(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET) |`
> `CONSYS_MCU_CFG_ACR_MBIST_BIT);`

(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:438-449`).
The constants are MCU physical base `0x18070000`, ACR offset `0x110`, and
MBIST bit `BIT(18)`, from
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:80-84,188-189`.
Thus the target is `0x18070110`, and the operation is an RMW OR, preserving
all other ACR bits.

The write is deterministic and repeating it leaves bit 18 set (inferred from
the OR operation), but the source provides no clear operation and no MBIST
completion/status poll.  Treat it as a one-way persistent configuration: no
rollback is proven.  The old non-DT branch repeats the same RMW at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:583-593`; that does not change which path is selected for
the Gemini DT build.

### Conditional AFE

The vendor header enables the block:

> `#define CONSYS_AFE_REG_SETTING          1`

(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:39-46`).
In the DT branch, the source maps AFE at `0x180B6000` and then writes the
following offsets (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:451-490`):

| offset | value | vendor symbol |
| ---: | ---: | --- |
| `0x20` | `0x180B0160` | `CONSYS_AFE_REG_DIG_RCK_01_VALUE` |
| `0x50` | `0xB8925421` | `CONSYS_AFE_REG_WBG_RX_01_VALUE` |
| `0x54` | `0x00006401` | `CONSYS_AFE_REG_WBG_RX_02_VALUE` |
| `0x60` | `0xB8925421` | `CONSYS_AFE_REG_WBG_RX_01_VALUE` |
| `0x64` | `0x00006401` | `CONSYS_AFE_REG_WBG_RX_02_VALUE` |
| `0x68` | `0x08400000` | `CONSYS_AFE_REG_WBG_TX_01_VALUE` |
| `0x6c` | `0x0C110200` | `CONSYS_AFE_REG_WBG_TX_02_VALUE` |
| `0x70` | `0x012A020A` | `CONSYS_AFE_REG_WBG_TX_03_VALUE` |
| `0x84` | `0x00006401` | `CONSYS_AFE_REG_WBG_RX_02_VALUE` |
| `0x88` | `0x08400000` | `CONSYS_AFE_REG_WBG_TX_01_VALUE` |
| `0x90` | `0x012A020A` | `CONSYS_AFE_REG_WBG_TX_03_VALUE` |

The offsets and values are defined verbatim at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:138-159`.
`0x8c` (WF TX 02) is deliberately commented out at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:479-480`.  A further optional write at offset `0x14`
(`OR 0x1000`) is compiled only under `CONFIG_MTK_GPS_REGISTER_SETTING`,
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:454-457`; the checked source tree does not prove that this config was set
in the Gemini image.  Keep that write behind a separately evidenced option.

The vendor mapping is:

> `consys_afe_reg_base = ioremap_nocache(CONSYS_AFE_REG_BASE, 0x100);`

(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:451-454`).  It does not check the returned pointer
before the writes.  Mainline must validate the resource and mapping before
entering the callback.  No AFE mapping is present in the Gemini `consys`
node, and no AFE clock/resource name is present in the current runtime.

These are full writes, not read-modify-write (except the optional GPS write),
so repeating the sequence writes the same values (an implementation-level
inference, not a vendor safety guarantee).  The vendor off path at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:611-750` contains no AFE inverse writes.  Therefore AFE
configuration is not proven reversible; a backend should mark the owner
terminal after an AFE write has occurred if a later step fails.

### CONMCU reset release and assert

The vendor DT branch releases reset after MBIST and AFE:

> `mtk_wdt_swsysret_config((1 << 12), 0);`

(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:492-496`).
The helper reads `MTK_WDT_SWSYSRST`, applies key `0x88000000`, changes only
the requested CONMCU bit, writes it, and serializes the operation under a
spinlock at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/mt6797/mtk_wdt.c:396-449`.
The WDT header identifies `SWSYSRST` as base `+0x18` and CONMCU as `0x1000`
at `/home/grw/src/gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/mt6797/mt_wdt.h:18-27,85-104`.

The mainline binding already identifies reset 12:
`/home/grw/src/linux-gemini-platform/include/dt-bindings/reset/mt6797-resets.h:37-53`.
The Gemini node supplies the exclusive reset handle:

> `resets = <&watchdog MT6797_TOPRGU_CONMCU_SW_RST>;`

and names it `conn-mcu` at
`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:229-230`.
The current WDT reset controller performs the same locked RMW/key sequence
at `/home/grw/src/linux-gemini-platform/drivers/watchdog/mtk_wdt.c:167-205`.
Use `reset_control_deassert()` for release and `reset_control_assert()` for
failure/stop through that existing exclusive handle.  Do not duplicate raw
WDT access in the post-ID backend.

Reset assert/deassert is reversible as a reset-control operation when the
provider succeeds and is idempotent at the bit level.  It does not reverse
AFE or MBIST state, so “assert reset” is containment, not full rollback.

## Clock, power, and mapping contract

Vendor configuration says `CONSYS_PWR_ON_OFF_API_AVAILABLE=1` and
`CONSYS_AHB_CLK_MAGEMENT=0` at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:39-46`.  The chosen power API is
build-config dependent (`conn_power_on()` versus `clk_prepare_enable()`),
and the checked source does not identify the exact historical Gemini kernel
configuration.  The vendor does not require a separate AHB clock in this
configuration.  No SPI130/APDMA/BTIF clock is part of this post-ID prefix;
those belong to later transport work.

Mainline already validates and maps the four vendor DT resources with exact
base/size pairs (`mcu 0x18070000/0x200`, `ap-rgu 0x10007000/0x100`,
`topckgen 0x10000000/0x2000`, `spm 0x10006000/0x1000`) at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:114-152`.
Its resource lease is restricted to `RESOURCES_READY` at `:534-565`, and its
identity activation is explicitly separate at `:595-654`.  The post-ID API
requires the canonical active lease and serializes callbacks at
`/home/grw/src/linux-gemini-platform/include/linux/soc/mediatek/mt6797-consys-postid.h:24-50`
and `/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-postid.c:71-116`.

The runtime turns on the CONN power-domain vote through
`of_genpd_add_device()`, `pm_runtime_enable()`, and
`pm_runtime_resume_and_get()` at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:292-307`.
This is the mainline power/clock boundary, but the checked source does not
prove that it supplies every clock state assumed by the historical vendor
image.  Readback of live clock/domain state is outside this no-hardware
research task.  The backend must require the canonical identity lease and
must not independently power-cycle or enable an unowned clock.

There is also a DT integration gap before any live probe: the runtime looks up
`mediatek,infracfg` and `mediatek,spm` at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:832-841`
and requires `mediatek,conn-power-domain` at `:856-862`, while the current
Gemini `consys` node shown at
`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:219-235`
does not declare those properties.  That is a future, separately reviewed
DT step; this report does not add or enable it.

## Patch-ready backend contract

The next implementation can fit the existing four callbacks in
`struct mt6797_consys_postid_ops`:

1. `configure_mbist`: require an active, provider-owned MCU mapping; RMW
   `readl(mcu + 0x110) | BIT(18)`; return an error on mapping/ownership
   failure.
2. `configure_afe`: require a separately validated AFE mapping of exactly
   `0x100` bytes at physical `0x180b6000`; write the proven list above in
   source order; compile/configure the GPS-single write only if its board
   setting is proven.  No `0x8c` write.
3. `release_reset`: call `reset_control_deassert(conn-mcu)` only after the
   first two callbacks succeed.
4. `assert_reset`: call `reset_control_assert(conn-mcu)` on stop and on every
   failure after reset ownership has been established.

The owner mutex already prevents concurrent starts/stops.  The provider
resource lease must remain held across the backend transaction, and provider
removal must wait for it.  On MBIST failure before any known persistent write,
assert reset and release the lease if that succeeds.  On AFE or reset-release
failure, assert reset as containment; if containment fails, retain the lease
and expose a sticky error.  Do not report the subsystem as cleanly off after
an AFE write or failed reset assertion.

## Safe staged acceptance

1. **Static/fake stage:** test exact register offsets, values, callback order,
   failure boundaries, and sticky error/unwind with fake in-memory ops and
   QEMU KUnit.  Keep DT disabled and the independent experiment gate false.
2. **Resource-only stage:** validate the future AFE resource and exclusive
   reset provider in a negative/probe-only configuration.  Do not invoke
   post-ID callbacks or map/write live AFE registers.
3. **Preflight stage:** before any future live attempt, capture the existing
   watchdog mode/length/status/interval by a controlled method.  Mainline
   `mtk_wdt_probe()` calls `mtk_wdt_init()` at
   `/home/grw/src/linux-gemini-platform/drivers/watchdog/mtk_wdt.c:458-520`,
   and `mtk_wdt_init()` rewrites mode/timeout when the watchdog is already
   enabled at `:323-356`; therefore this probe is not proven read-only.
4. **Single gated hardware stage (only with explicit authorization):** with
   serial recovery and a known-good image, verify mappings and reset asserted;
   invoke MBIST, then AFE, then reset release once; record register readback
   and stop.  Do not start BTIF/WMT, download firmware, or enable a radio.
   If reset must be asserted afterward, treat AFE/MBIST configuration as
   retained and the experiment as requiring recovery rather than rollback.

## Proven, inferred, and unknown

**Proven by source:** the DT vendor ordering; MCU ACR `0x110` bit 18; AFE
base/offset/value list and disabled WF-TX-02 write; reset WDT offset/key/bit;
mainline `conn-mcu` reset binding; current post-ID callback order and
provider/resource lease fencing.

**Inferred, not a safety proof:** MBIST OR and repeated full AFE writes are
deterministic at the register level; reset bit operations are bit-level
idempotent; the mainline genpd vote is the intended power/clock boundary.

**I could not determine:** whether `CONFIG_MTK_GPS_REGISTER_SETTING` or
`CONFIG_MTK_CLKMGR` was enabled in the exact Gemini vendor build; whether a
live boot/ATF image preconfigured AFE/MBIST; whether genpd supplies every
vendor clock requirement on the live board; AFE/MBIST inverse semantics or a
safe reset-release rollback; and whether AFE writes are safe in the presence
of any other live CONSYS owner.  These remain acceptance gates, not reasons
to invent register writes or a rollback path.
