# MT6797 BTIF PIO clock ownership and bounded loopback gate

Date: 2026-08-30

Scope: patch-ready guidance for the dormant `linux-gemini-platform` BTIF PIO
adapter at commit `d69d55863b5971c2a8d0f296036fe77b35661447`. This is a static
source audit. No DT was enabled and no hardware, radio, firmware, reset, or
flash operation was performed.

## Decision

The PIO adapter needs one explicit runtime clock vote: the BTIF core clock
consumer named `btifc`. The provider is the MT6797 `infrasys` clock controller,
with `CLK_INFRA_BTIF` ID 30. The clock must be prepared and enabled before the
first PIO MMIO write, including `mt6797_btif_pio_hw_init()`, and disabled only
after synchronous Linux IRQ quiesce and PIO fencing. The PIO slice must not add
the APDMA clock or APDMA resources: those are required by the DMA transport,
not by the current PIO register/IRQ subset.

This is a source-backed implementation requirement, not proof that a cold
Gemini CONSYS will answer bytes. Power/reset/pads/firmware and the existing
independent experiment gates remain separate prerequisites.

## Exact clock identity and DT shape

The clock ID and provider are explicit in the current mainline tree:

* `/home/grw/src/linux-gemini-platform/include/dt-bindings/clock/mt6797-clk.h:150`
  defines `CLK_INFRA_BTIF` as `30`.
* `/home/grw/src/linux-gemini-platform/drivers/clk/mediatek/clk-mt6797.c:476`
  registers it as `GATE_ICG0(CLK_INFRA_BTIF, "infra_btif", "axi_sel", 31)`.
* `/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:220-225`
  declares `infrasys` with `#clock-cells = <1>`.
* The generic disabled BTIF node already supplies the core resource, SPI 130,
  and this clock at
  `/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:529-537`:

  > `interrupts = <GIC_SPI 130 IRQ_TYPE_LEVEL_LOW>;`
  >
  > `clocks = <&infrasys CLK_INFRA_BTIF>;`

The PIO platform driver has a source match but no PIO-specific binding and no
clock lookup today. Its match is
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio-platform.c:542-545`:

> `{ .compatible = "mediatek,mt6797-btif-pio" },`

The future PIO node/binding should therefore require the following consumer
property (the exact overlay is implementation work, not an existing binding):

```dts
clocks = <&infrasys CLK_INFRA_BTIF>;
clock-names = "btifc";
```

It should retain exactly one `core` resource at `0x1100c000/0x1000` and one
level-low SPI 130. The current PIO probe validates those constraints at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio-platform.c:473-503`.
There is no reviewed `mediatek,mt6797-btif-pio.yaml`; the existing transport
binding is not a PIO binding and must not be copied wholesale.

For comparison, the existing experimental APDMA transport already names both
clock consumers in
`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:245-258`:

> `clock-names = "btifc", "apdmac";`

and its binding requires two clocks named `btifc` and `apdmac` at
`/home/grw/src/linux-gemini-platform/Documentation/devicetree/bindings/soc/mediatek/mediatek,mt6797-btif-transport.yaml:52-80`.
That two-clock contract belongs to the APDMA transport only.

## Vendor order and what it proves

The vendor controller registers its receive callback, enables the BTIF clock,
then initializes hardware, registers the IRQ, and leaves the IRQ disabled:

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/mtk_btif.c:1455-1482`:

> `hal_btif_rx_cb_reg(p_btif_info,`
>
> `i_ret = hal_btif_clk_ctrl(p_btif_info, CLK_OUT_ENABLE);`
>
> `i_ret = hal_btif_hw_init(p_btif_info);`
>
> `i_ret = _btif_irq_reg(p_btif_irq, btif_irq_handler, p_btif);`
>
> `_btif_irq_ctrl(p_btif_irq, false);`

The vendor explicitly records the default-off assumption at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:321-325`:

> `clock of DMA and BTIF is default off, so we assume it to be off by default`

The current mainline PIO code reaches MMIO hardware init without a clock vote:

* `/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio.c:302-315`
  calls `mt6797_btif_pio_hw_init(pio)` while attaching a full STP owner.
* `/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio.c:334-346`
  does the same for mandatory bootstrap ownership.
* `/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio-platform.c:260-273`
  enables SPI 130 only after the mandatory callback has been installed.

Therefore the clock vote belongs to the platform lease boundary, before either
attach path can call hardware init. Enabling it only in the direct full attach
would leave the mandatory bootstrap path uncovered; enabling it only in the
low-level PIO library would give the library an unsafe implicit hardware
dependency.

## Patch-ready ownership and unwind

The smallest implementation is:

1. Add `<linux/clk.h>`, `struct clk *btifc_clk`, and a boolean recording a
   successful enable to `struct mt6797_btif_pio_platform`.
2. In probe, call `devm_clk_get(dev, "btifc")` and return `dev_err_probe()` on
   error. This obtains a managed reference but does not turn the clock on.
3. In `mt6797_btif_pio_platform_reserve()`, while the state is being changed
   from READY to LEASED, call `clk_prepare_enable(btifc_clk)` before returning
   the lease. If it fails, restore READY and return the error. This covers both
   `bootstrap_create()` and `attach_full_stp()`.
4. On close, keep the current order: mark QUIESCING, synchronously disable the
   Linux IRQ, call `mt6797_btif_pio_close()` to clear IER/fence the PIO, then
   call `clk_disable_unprepare(btifc_clk)` and finally publish FENCED. Disable
   only when the successful-enable boolean is set.
5. Do not use `devm_clk_get_enabled()`: that would make a merely probed,
   otherwise dormant adapter consume the clock for its whole device lifetime.

The process-context and error semantics are documented in the kernel headers:

* `/home/grw/src/linux-gemini-platform/include/linux/clk.h:557-575`:

  > `Context: May sleep.`
  >
  > `Drivers must assume that the clock source is neither prepared nor enabled.`
  >
  > `The clock will automatically be freed when the device is unbound`

* `/home/grw/src/linux-gemini-platform/include/linux/clk.h:599-616` says
  `devm_clk_get_enabled` returns a clock “prepared and enabled” and
  automatically disables/unprepares it at unbind. That lifetime is wrong for a
  lease-gated PIO adapter.
* `/home/grw/src/linux-gemini-platform/include/linux/clk.h:1164-1177` gives
  the exact helper behavior:

  > `ret = clk_prepare(clk);`
  >
  > `ret = clk_enable(clk);`
  >
  > `if (ret) clk_unprepare(clk);`

* `/home/grw/src/linux-gemini-platform/include/linux/clk.h:1179-1184` defines
  the matching `clk_disable_unprepare()` pair.

The existing APDMA implementation is a direct error-unwind precedent at
`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-transport.c:426-487`:

> `ret = clk_prepare_enable(btif->btifc_clk);`
>
> `ret = clk_prepare_enable(btif->apdmac_clk);`
>
> `goto err_btif_clk;`
>
> `clk_disable_unprepare(btif->btifc_clk);`

Its teardown disables IRQs and clears core/DMA state before disabling APDMA and
BTIF clocks at `:394-424`. The PIO version should use the same clock helper
discipline, but omit APDMA and put the PIO fence between IRQ quiesce and clock
disable. `clk_prepare_enable()` may sleep, and both PIO reserve and close are
mutex/process-context paths; neither belongs in the IRQ thread.

## Why APDMA is not part of this PIO patch

The vendor `btif_clock_ctrl()` only votes APDMA when a TX or RX mode is DMA:
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/mtk_btif.c:1428-1442`:

> `i_ret = hal_btif_clk_ctrl(p_btif_info, ctrl_flag);`
>
> `if (BTIF_MODE_DMA == p_btif->rx_mode)`
>
> `i_ret += hal_btif_dma_clk_ctrl(..., ctrl_flag);`
>
> `if (BTIF_MODE_DMA == p_btif->tx_mode)`

The vendor PIO fallback sets TX/RX modes to PIO and enables the RX IRQ at
`.../btif/common/mtk_btif.c:1243-1267`:

> `p_btif->tx_mode = BTIF_MODE_PIO;`
>
> `p_btif->rx_mode = BTIF_MODE_PIO;`
>
> `_btif_irq_ctrl(p_btif_irq, true);`

Conversely, the vendor build defaults both directions to DMA at
`.../btif/common/inc/mtk_btif.h:77-90`, and tries DMA before PIO fallback at
`.../btif/common/mtk_btif.c:1175-1223`. This proves the product's normal path
is APDMA-oriented, but does not prove that APDMA is needed for the deliberately
bounded PIO adapter. Adding an APDMA clock without its two windows, two DMA
IRQs, ring programming and ownership would be incomplete and unsafe.

## Smallest guarded loopback/IRQ gate

The first gate should remain hardware-free and preserve the existing two
independent experiment gates. Extend the existing PIO KUnit coverage only after
the platform clock ownership patch:

* The fake bus supplies read/write callbacks at
  `/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-btif-pio.c:640-679`.
* Test setup attaches full STP and asserts DMA RX/TX are clear, autor-reset is
  set, thresholds are set, and RX IER is enabled at `:708-757`.
* `mt6797_btif_pio_test_partial_tx()` queues a 20-byte frame, invokes the TX
  IRQ twice, verifies all bytes reached the transmit sink, and verifies TX IER
  clears at `:770-797`.
* `mt6797_btif_pio_test_rx_fragmentation()` injects a partial then complete STP
  frame and verifies exactly one decoded payload callback at `:822-844`.
* Close/fence behavior is checked by the lease-exclusion test at
  `:862-882`, and the mandatory handoff test verifies IER is zero after close
  at `:900-947`.

Add one platform-level assertion around this existing fake bus: no IO callback
may occur until the fake `btifc` enable hook has run, and the hook must be
disabled only after the synchronous IRQ disable and PIO close. This is the
smallest test that closes the ordering gap without a byte on the live radio
path. It must not call CONSYS WMT function-on, load firmware, release the
CONMCU reset, enable pads, or create a GNSS/Bluetooth client.

There is a source-backed candidate for a later live, no-radio test: the vendor
BTIF internal loopback bit is `BTIF_TRI_LOOP_EN` (bit 7), and its helper says
loopback “can only be done after set BTIF to normal mode” at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:699-716`.
The vendor stress tester enables loopback and writes bounded bytes at
`.../btif/common/mtk_btif_exp.c:704-718`. If and only if a later owner proves
the reset/power contract, a separately gated live test could enable that bit
after clocked normal-mode init, send a tiny bounded frame, service SPI 130,
verify the RX callback, clear loopback, and close. No STP/WMT command or radio
function activation belongs in that test.

The live loopback result is currently **unknown**: the reviewed mainline PIO
driver does not expose loopback, and no source proves that a reset-held cold
Gemini CONSYS will produce an internal-loopback IRQ without firmware or other
CONSYS state. Do not treat a successful KUnit fake-bus run as live-byte proof.

## Classification and next gate

### Proven

* `btifc` is the consumer name, `&infrasys` is its provider, and ID 30 is
  `CLK_INFRA_BTIF`; the gate is the `infra_btif` bit on `axi_sel`.
* Vendor enables the BTIF clock before hardware init and leaves the IRQ masked
  until setup is complete.
* Current mainline PIO hardware init is reached from both mandatory and full
  attach paths without a clock vote.
* APDMA clock/resource ownership is conditional on DMA mode in vendor source;
  the current PIO adapter has one core resource and SPI 130 only.
* Mainline KUnit already proves deterministic fake-bus TX/RX, fencing and IER
  clearing, but not CCF ordering or live bytes.

### Inferred

* Enabling `btifc` at platform lease acquisition is the smallest ownership
  boundary that covers both bootstrap and direct attach while keeping probe
  inert. This follows the call graph; it is not a measured hardware result.
* A PIO DT contract containing only `btifc`, core and SPI 130 is internally
  coherent with the reviewed PIO code. It does not establish that the Gemini
  board's pads, CONSYS reset, or firmware state are ready.

### Could not determine

* Whether the board's cold/reset-held CONSYS can run the BTIF internal loopback
  test without firmware or WMT function control.
* Whether the product's normal BTIF path can be made PIO-capable; vendor
  defaults to APDMA and the current adapter deliberately does not own APDMA.
* Whether any currently absent PIO DT overlay should be added to the shipped
  board; no PIO binding/node is enabled in the audited tree.

The next implementation gate is therefore narrow: add required `btifc`
ownership and failure unwind, then run the gated fake-bus/platform ordering
test. Only after that passes should anyone evaluate the separately gated live
internal-loopback candidate.
