# MT6797 Gemini BTIF runtime: next-gate evidence

Audit date: 2026-08-30.  This is a read-only research packet.  No device
write, reboot, flash, raw I2C/MMIO access, or firmware transaction was made.

The primary vendor source is
`/home/grw/src/gemini-linux-kernel-3.18` at commit
`8cfe6596a503612e3332d9c26e292a19525a7f07`.  The implementation under review is
`/home/grw/src/linux-gemini-btif-transport-reviewed` at commits
`21b6f19a9`, `aa0e3222b`, `5c016d3d9`, and `ad22557ea`.  The earlier WMT
evidence packet is
`/home/grw/src/nixos-gemini/research/mt6797-btif-wmt-evidence/README.md`.

## Verdict

| Gate | Result |
|---|---|
| BTIF pad mux, pin numbers, electrical states | **Could not determine.** The board source has no active combo BTIF pin assignment. |
| CONSYS owner and power/reset/wake sequencing | **Closed at vendor-contract level.** `mtk_wcn_consys_hw` owns power/reset; the BTIF/STP layer owns the wake pulse only after CONSYS and clocks are live. |
| Firmware names, location, revision selection, load address/protocol | **Partially closed.** Blobs and search roots are known; runtime-selected filename and address are not. The protocol and its address-command bytes are known, but the actual address is not. |
| Mandatory versus full STP at earliest exchange | **Closed for the intended vendor path.** BTIF bootstrap begins mandatory; SOC firmware download occurs after the explicit switch to full mode. A live mainline mode is not yet proven. |
| Safe first RX-only live test | **Not yet safe.** It is gated on the missing pad contract plus a real CONSYS owner and fail-closed readiness logging. |

Exact next implementation/hardware gate: do not enable the reviewed transport or
touch CONSYS from it. First implement one shared, fail-closed CONSYS owner and
obtain the Gemini board’s actual `gpio_combo_*` assignments/electrical states
from a vendor DTB/runtime pin dump or board schematic. Then add read-only
identity/mode/firmware-selection logging and run the bounded RX-only test in
the earlier packet. Do not select GPIO 228--231, 232--233, `0x0508`, or
`0x0b2c` by inference.

## 1. Pad mux and electrical state: not closed

The vendor generic DT describes BTIF core and clocks but has no `pinctrl-*`
property or pad assignment:

> `btif: btif@1100c000 {`
> `compatible = "mediatek,btif";`
> `reg = <0x1100c000 0x1000>;`
> `interrupts = <GIC_SPI 130 IRQ_TYPE_LEVEL_LOW>;`
> `clocks = <&infrasys INFRA_BTIF>,<&infrasys INFRA_AP_DMA>;`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2511-2517`

The board-specific CONSYS pinctrl contains only the GPS LNA host pin.  Its
states are explicitly GPIO69 output-low, output-high, output-low:

> `pins = <PINMUX_GPIO69__FUNC_GPIO69>;`
> `output-low;`
> `pins = <PINMUX_GPIO69__FUNC_GPIO69>;`
> `output-high;`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1269-1301`

The same file leaves `consys_pins_default` empty
(`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:1271-1274`).
The board DWS identifies GPIO69 as `GPIO_GPS_LNA_PIN`, but gives no combo
variable for BTIF:

> `<gpio69>`
> `<def_mode>0</def_mode>`
> `<def_dir>OUT</def_dir>`
> `<out_high>false</out_high>`
> `<varName0>GPIO_GPS_LNA_PIN</varName0>`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:1044-1057`

GPIO228--231 are present in that DWS only as unnamed default mode-1 inputs
with no pull enabled:

> `<gpio228>` ... `<def_mode>1</def_mode>` ... `<def_dir>IN</def_dir>` ... `<in>true</in>`
> `<gpio229>` ... `<def_mode>1</def_mode>` ... `<def_dir>IN</def_dir>` ... `<in>true</in>`
> `<gpio230>` ... `<def_mode>1</def_mode>` ... `<def_dir>IN</def_dir>` ... `<in>true</in>`
> `<gpio231>` ... `<def_mode>1</def_mode>` ... `<def_dir>IN</def_dir>` ... `<in>true</in>`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:3184-3235`

The pin-function header says only what the SoC can route, not what this board
routes.  It labels GPIO83/84 as `CONN_BT_CLK`/`CONN_BT_DATA`, GPIO224--227 as
BT RF pins, and GPIO228--231 as GPS RF pins
(`/home/grw/src/gemini-linux-kernel-3.18/include/dt-bindings/pinctrl/mt6797-pinfunc.h:487-492,1149-1171`).
It labels GPIO232/233 as alternate UART1 functions
(`/home/grw/src/gemini-linux-kernel-3.18/include/dt-bindings/pinctrl/mt6797-pinfunc.h:1173-1189`).
No local source ties any of these to the BTIF APDMA serial data path.

The vendor GPIO loader expects a separate `mediatek,connectivity-combo` DT
node and reads named properties such as `gpio_combo_urxd_pin`,
`gpio_combo_utxd_pin`, `gpio_combo_rst_pin`, and `gpio_combo_bgf_eint_pin`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_detect/wmt_gpio.c:213-230,238-267`).
No such node or property occurs in the vendor board DT sources examined:

```text
$ rg -n 'connectivity-combo|gpio_combo_' /home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts
(no matches)
```

Therefore the exact BTIF data pads, BGF wake input, reset/enable GPIOs, pull
configuration, drive/slew state, and whether any host GPIO is used are
**could not determine**.  This is not permission to use the SoC capability
names as board wiring.

## 2. CONSYS owner, power/reset, and wake: vendor ordering is closed

The vendor DT’s CONSYS node supplies MCU, AP-RGU, TOPCKGEN, SPM, BGF/WDT IRQs,
the `SCP_SYS_CONN` clock, and four rails:

> `compatible = "mediatek,mt6797-consys";`
> `reg = <0x18070000 0x0200>, <0x10007000 0x0100>, <0x10000000 0x2000>, <0x10006000 0x1000>;`
> `clocks = <&scpsys SCP_SYS_CONN>;`
> `vcn18-supply = ...; vcn28-supply = ...; vcn33_bt-supply = ...; vcn33_wifi-supply = ...;`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:3759-3773`

The owner is the vendor `mtk_wcn_consys_hw` platform implementation.  Probe
acquires the CONSYS clock, all four regulators, and pinctrl
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:226-269`).
Its power-on sequence is, verbatim in order: enable VCN18, wait 240 us,
enable VCN28 for `co_clock_type == 0`, set the CONN-to-AP sleep mask, assert
CONSYS CPU reset, configure SPM power-on, enable the CONSYS power/clock path,
poll chip ID `0x0279`, then deassert reset
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:291-343,401-436,492-496`).
The public power wrapper calls that owner, not BTIF:

> `ret = mtk_wcn_consys_hw_pwr_on(gCoClockFlag);`
> `ret = mtk_wcn_consys_hw_pwr_off(gCoClockFlag);`
> `ret = mtk_wcn_consys_hw_rst(gCoClockFlag);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/wmt_plat_alps.c:446-474`

The vendor `pwr_on` calls `reg_ctrl(1)` before `gpio_ctrl(1)`; GPIO setup
initializes GPS sync/LNA/I2S and registers then disables the BGF IRQ
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:757-795,797-815`).
Reset is a full power-off then power-on and requires the BGF IRQ disabled before
it and enabled after it (`:830-843`).

Wake is a distinct BTIF operation and must not be folded into power ownership.
The WMT control path calls STP wake, which calls the BTIF wake API
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:616-624`; `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/stp_core.c:3433-3438`).
The hardware wake operation requires live BTIF clocks, writes BTIF_WAK low,
waits 64--96 us, then writes it high:

> `BTIF_CLR_BIT(BTIF_WAK(base), BTIF_WAK_BIT);`
> `usleep_range(64, 96);`
> `BTIF_SET_BIT(BTIF_WAK(base), BTIF_WAK_BIT);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:1088-1111`

Implementation consequence: one CONSYS owner must sequence rails/domain/reset/
identity and expose a reference, while one BTIF owner must sequence clocks,
transport, and wake.  BTIF, GNSS, Bluetooth, and Wi-Fi children must not each
reset or power the shared subsystem.

## 3. Firmware selection and download: partially closed

NixOS installs the original uncompressed names:

> `cp ... ROMv3_patch_1_0_hdr.bin ...`
> `cp ... ROMv3_patch_1_1_hdr.bin ...`
> `cp ... WIFI_RAM_CODE_6797 ...`
> `cp ... WMT_SOC.cfg ...`

`/home/grw/src/nixos-gemini/nixos/firmware.nix:8-20`

The saved Gemian artifact records these local firmware boundaries:

```text
WMT_SOC.cfg size=80 sha256=f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880
ROMv3_patch_1_0_hdr.bin size=210904 sha256=450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630
ROMv3_patch_1_1_hdr.bin size=46472 sha256=5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e
WIFI_RAM_CODE_6797 size=411632 sha256=a69383d74d829430487c39eef6b5e281b25f901595c903a632a10aa8631426dd
```

`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:53-57`

The launcher search roots observed in the saved userspace inventory are
`/dev/stpwmt`, `/vendor/firmware`, and `/system/vendor/firmware/WMT.cfg`
(`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/userspace-summary.txt:1-8`).
Vendor source names `WMT_SOC.cfg` and fails if it cannot load or parse it
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_conf.h:33-34`; `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_conf.c:432-486`).

The source does establish chip revision selection: hardware revisions
`0x8A00`, `0x8A01`, and `0x8B01` map to E1, E2, and E3, all require a patch,
and all use the E1 extension
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:875-904`).
The saved runtime identifies `MT6797`, WMT `MT279`, ROM E1, and patch date
20180307 (`.../live-connectivity-rerun-20260713.txt:19-22`).

The exact filename selected at runtime is **could not determine**.  The
multi-patch path asks a search callback for each name, then requests that full
name (`wmt_ic_soc.c:2030-2087`), while the generic fallback is
`mt66xx_patch_hdr.bin` (`.../core/include/wmt_core.h:55-57`).  Static source
does not prove that either product blob is the selected runtime name.  The
exact on-device file path is likewise **could not determine**: only the search
roots above are captured.  Next implementation must log the callback’s exact
name before loading it; do not rename or guess.

The download protocol is established: read a 28-byte `WMT_PATCH` header,
remove it, send a 20-byte patch-address command, send a 20-byte part-address
command containing the selected address bytes, then send 1000-byte-or-smaller
WMT patch fragments and check events
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:370-376`; `/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2094-2135,2148-2249`).
The literal initial command templates are:

```text
WMT_PATCH_ADDRESS_CMD   = 01 08 10 00 01 01 00 01 3c 02 09 02 00 00 00 00 ff ff ff ff
WMT_PATCH_P_ADDRESS_CMD = 01 08 10 00 01 01 00 01 c4 04 09 02 00 3f 00 01 ff ff ff ff
```

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:135-153`

For `icId == 0x0279`, source mutates the first command bytes to `08 05` and
the part command bytes to `2c 0b`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2162-2169`).
But the same operation table initializes `wmt_ic_ops_soc.icId = 0x0000`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:957-968`).
Thus the actual patch RAM load address is **could not determine**.  The next
instrumentation must record chip ID, `icId`, the four address bytes returned by
patch search, and every transmitted address command.  The bytes `08 05` and
`2c 0b` are source branches, not a proven board load address.

Do not redistribute these local firmware blobs; their presence proves an
installed firmware boundary, not publication rights.

## 4. STP mode at the earliest exchange: closed statically, live state pending

The vendor BTIF HIF enum is UART=0, SDIO=1, BTIF=2
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:118-123`).
Generic STP initialization selects BTIF mandatory mode and enables STP
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:747-779`).
SOC initialization then explicitly selects `MTKSTP_BTIF_FULL_MODE`, enables it,
waits 10 ms, queries STP again, and only then enters patch download
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1008-1055`).
Therefore the intended sequence is **mandatory for bootstrap, full for the
subsequent SOC firmware exchange**.  This is not the claim that the reviewed
mainline transport is already in either mode.

Mandatory framing is a 4-byte header + payload + two zero bytes
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/stp_core.c:1120-1149`).
Full framing uses sequence/ack, header checksum, payload, CRC16, and a
seven-packet window (`:1151-1207`).  A WMT PDU is not a complete BTIF wire
frame.

The reviewed implementation explicitly remains conservative:

> `It does not establish pad muxing, CONSYS power ownership, firmware loading`
> `or a safe STP full-mode transaction.`

`/home/grw/src/linux-gemini-btif-transport-reviewed/drivers/soc/mediatek/mt6797-btif-transport.c:3-9`

It initializes the software parser as mandatory and starts RX only
(`/home/grw/src/linux-gemini-btif-transport-reviewed/drivers/soc/mediatek/mt6797-btif-transport.c:431-475`),
and logs that there is “no firmware or TX enabled”
(`/home/grw/src/linux-gemini-btif-transport-reviewed/drivers/soc/mediatek/mt6797-btif-transport.c:572-579`).

## 5. Safe first RX-only live test: prerequisites and stop condition

No safe live test can be approved until the pad/CONSYS gaps above are closed.
The minimum prerequisites are:

1. A single CONSYS owner has an opt-in reference-counted get/put API, owns
   rails, domain, reset, identity polling, BGF wake IRQ, and failure cleanup;
   BTIF never powers or resets CONSYS directly.
2. Board-verified BTIF pad mux and electrical states are represented in DT;
   no GPIO is selected from a pin-function header alone.
3. BTIF core and APDMA windows/IRQs/clocks are acquired from DT.  Vendor
   resources are core `0x1100c000`, TX `0x11000a00`, RX `0x11000a80`, with
   SPI 130/116/117 (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2344-2360,2511-2517`).
4. Both 8192-byte VFIFOs are DMA32, 8-byte aligned, warm-reset and pointer-
   initialized; install the RX parser before enabling RX.  The reviewed
   driver’s KUnit and runtime code cover the transport ring rules in commits
   `aa0e3222b` and `ad22557ea`, but do not close the CONSYS/pad contract.
5. Readiness logging records CONSYS chip/ROM ID, `icId`, selected HIF, STP
   mode, exact firmware names/search roots, patch address bytes, IRQ counts,
   and raw RX bytes.  There must be no automatic retry or reboot.
6. With the already-running vendor radio left alone, accept only passive RX
   observation first.  A later ON/OFF WMT experiment must be separately
   authorized and use the earlier packet’s exact derived payloads and status-
   zero events; it is not part of this RX-only gate.

Abort on a timeout, malformed frame, invalid ring pointer, unexpected reset,
watchdog symptom, or loss of the debug/network channel.  The first test must
not perform firmware download, HCI, Wi-Fi, raw register probing, or a power
cycle.

## Exact handoff

The implementation agent should first add the shared CONSYS owner and a
read-only diagnostic path, then stop with `BTIF transport: pad contract
missing` unless board pin data is present.  The hardware/research agent should
produce one checkable artifact containing the vendor-combo DTB (or schematic)
assignments for `gpio_combo_urxd_pin`, `gpio_combo_utxd_pin`,
`gpio_combo_bgf_eint_pin`, reset/power pins, and each pull/output state.  Only
after that artifact exists should the flashing/test agent schedule the
RX-only boot experiment.
