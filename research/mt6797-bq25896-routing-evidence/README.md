# Gemini MT6797 BQ2589x routing evidence

Research-only packet for the next charger gate.  No device probing, writes,
reboot, or flash was performed for this packet.  The local vendor tree is at
`/home/grw/src/gemini-linux-kernel-3.18`, vendor HEAD is
`8cfe6596a503612e3332d9c26e292a19525a7f07`, and the reviewed mainline power
tree is `/home/grw/src/linux-gemini-power-reviewed` at
`e69a5d4bfdd188f898a82bf01c74a5720c6bfbad`.

## Conclusion

The strongest board-specific evidence gives this route:

```
Gemini charger (7-bit address 0x6b)
    -> vendor DWS I2C_CHANNEL_0
    -> MT6797 i2c0 @ 0x11007000
    -> GPIO37=SCL0_0, GPIO38=SDA0_0
```

This is high-confidence routing evidence, not yet proof that the silicon is
specifically BQ25896.  The vendor configuration selects
`CONFIG_MTK_BQ25896_SUPPORT` [vendor defconfig, lines 177–188] and the live
capture reports `0-006b:sw_charger/bq25890` [live controller audit, lines
24–30], but the capture explicitly says the exact part number was not logged
[live charger capture, lines 28–34].  Therefore the exact BQ2589x variant
**could not be determined** from the available evidence.

## Verbatim source evidence

### Bus, address, and board pins

The board-specific DWS assigns the charger to channel 0 and address 0x6B:

> `<varName>SW_CHARGER</varName>`
>
> `<channel>I2C_CHANNEL_0</channel>`
>
> `<address>0x6B</address>`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:3679-3683`

The same board DWS names the physical pads:

> `<gpio37>` ... `<varName0>GPIO_I2C0_SCA_PIN</varName0>`
>
> `<gpio38>` ... `<varName0>GPIO_I2C0_SDA_PIN</varName0>`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:627-644`

The vendor controller node is the matching MT6797 I2C0 instance:

> `i2c0:i2c@11007000 {`
>
> `compatible = "mediatek,mt6797-i2c";`
>
> `id = <0>;`
>
> `reg = <0x11007000 0x1000>,`
>
> `interrupts = <GIC_SPI 84 IRQ_TYPE_LEVEL_LOW>;`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2448-2457`

The MT6797 pin binding gives GPIO37/38 the I2C0 alternate functions:

> `#define MT6797_GPIO37__FUNC_SCL0_0 ...`
>
> `#define MT6797_GPIO38__FUNC_SDA0_0 ...`

`/home/grw/src/gemini-linux-kernel-3.18/include/dt-bindings/pinctrl/mt6797-pinfunc.h:162-166`

The current mainline SoC description uses that same pair in `i2c0_pins_a`:

> `pinmux = <MT6797_GPIO37__FUNC_SCL0_0>,`
>
> `         <MT6797_GPIO38__FUNC_SDA0_0>;`

`/home/grw/src/linux-gemini-power-reviewed/arch/arm64/boot/dts/mediatek/mt6797.dtsi:257-262`

The DWS sets bus 0 to 400 kbit/s and non-push-pull operation:

> `<i2c_bus0>`
>
> `<speed_kbps>400</speed_kbps>`
>
> `<pullPushEn>false</pullPushEn>`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:3637-3642`

### Vendor driver corroboration

The legacy non-DT fallback hard-codes logical bus 0 and converts 0xD6 to the
7-bit address 0x6B:

> `#define bq25890_SLAVE_ADDR_WRITE   0xD6`
>
> `#define bq25890_BUSNUM 0`
>
> `I2C_BOARD_INFO("bq25890", (bq25890_SLAVE_ADDR_WRITE >> 1))`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/power/mt6797/bq25890.c:39-46,1154-1157`

This is corroboration only: the non-DT fallback is a software default, while
the DWS and live inventory establish the board route.

### Charger status interrupt

The board DWS assigns the charger status signal the semantic EINT number and
electrical mode:

> `<eint158>`
>
> `<varName>CHR_STAT</varName>`
>
> `<polarity>Low</polarity>`
>
> `<sensitive_level>Level</sensitive_level>`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws:140-146`

The available generated `cust_eint.dtsi` does not contain EINT158 or a
charger consumer (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/cust_eint.dtsi:14-78`).  The only nearby-looking GPIO in the source is for the *different,
unbound* RT9466 alternative:

> `rt,intr_gpio_num = <246>;`
>
> `rt,intr_gpio = <&pio 246 0>;`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/rt9466.dtsi:12-20`

Thus EINT158 is established as a board signal name/mode, but its physical
GPIO pad and Linux interrupt-resource mapping **could not be determined**.
Do not reuse RT9466 GPIO246 for BQ2589x.

### Live output artifact

The prior bounded, read-only vendor capture records:

> `charger_i2c0_0x6b=sw_charger;bound_bq25890`
>
> `bq25890_probe=vendor_probe_completed;exact_part_number_not_logged_in_capture`

`/home/grw/src/gemini-pda-mainline/experiments/2026-07-12-charger-power-recovery/results/live-charger-battery-recovery-20260714.txt:12-16,28-34`

Its recorded command output artifact was
`/home/grw/src/gemini-pda-mainline/artifacts/device-inventory/20260714T162500Z-battery-recovery-charger/charger-power.txt`
(the raw artifact is not present in this checkout); recorded SHA-256 is
`cc71770ddae5a8ca97bd8d94fa80a1b6ac94c37845d49b308a0663875d68ea48`.
The capture metadata says `hardware_write=none` and `remote_sudo=not_used`
[same result file, lines 1–10].

## Comparison with reviewed commits

* `4f2c0404b` makes normal BQ25890 DT nodes require interrupts and all charge
  limits, while `ti,read-only` intentionally relaxes those requirements
  [`/home/grw/src/linux-gemini-power-reviewed/Documentation/devicetree/bindings/power/supply/bq25890.yaml:13-28,102-118`].
* `07c618915` centralizes write blocking (`-EPERM`), makes read-only hardware
  init read status only, and skips normal IRQ/OTG/regulator registration
  [`/home/grw/src/linux-gemini-power-reviewed/drivers/power/supply/bq25890_charger.c:375-387,968-975,1555-1599`].
* `e69a5d4bf` deliberately leaves both the candidate node and its parent
  disabled, documenting that physical controller and IRQ proof were missing
  [`/home/grw/src/linux-gemini-power-reviewed/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-power-observe.dtso:3-10,20-29`].

## Exact next safe gate

Do one unattended, recoverable observation boot before any normal charger
enablement:

1. In the reviewed tree, create a test-only DT fragment that enables only
   `&i2c0`, applies `pinctrl-0 = <&i2c0_pins_a>`/`pinctrl-names = "default"`,
   and enables one child at address `0x6b` with compatible
   `"ti,bq25896", "ti,bq25890"` and `ti,read-only`.  Do not add an IRQ,
   battery consumer, charge limits, RT9466, FAN49101, or any other new child.
2. Build it into the minimal cross-compiled image with the reviewed
   `i2c-mt65xx` and BQ driver built in. Boot under the existing bounded
   watchdog/BROM recovery procedure, with automatic stop/rollback after one
   attempt.
3. Accept only if the kernel applies GPIO37/38, registers I2C0 without
   timeout/ownership errors, and the BQ driver reads a recognized ID and
   exposes only its read-only status fields. Capture serial/netconsole,
   `dmesg`, I2C adapter inventory, and power-supply inventory as a named
   artifact. Any NACK/timeout or unknown ID is a stop condition; leave the
   node disabled.
4. Do not enable normal BQ mode until exact silicon identity, the CHR_STAT
   GPIO-to-EINT mapping, battery/system-rail wiring, and conservative limits
   are separately evidenced. Those IRQ/rail facts remain **could not
   determine** at this gate.

Source hashes for the board DWS, vendor board DTS, and vendor BQ driver are
recorded by the research command run as:

```
sha256sum /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/dws/mt6797/aeon6797_6m_n.dws
sha256sum /home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts
sha256sum /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/power/mt6797/bq25890.c
```

with results `82090af7b6d9251e3c24f2285e62d4bd8d1f7891980f2357a71ea38b73300fb5`,
`d1bd9d83941dffb44615f69e9113c7b79d87b3e9e87057619c70370f56456f5a`, and
`01f79a7dba68dd916e7fbc1bd20be448d10ff6706521112a7904cdb86900add6`.
