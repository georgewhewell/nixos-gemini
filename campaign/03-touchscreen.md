# Chapter 03: Touchscreen Subsystem (Novatek NT36672 & SSD2092)

## 1. Hardware Architecture & Bus Configuration

The Gemini PDA touch panel subsystem supports both Novatek NT36672 and Solomon Systech SSD2092 capacitive digitizers across different hardware revisions:

- **Controller Models:** Novatek NT36672 (Primary) / Solomon Systech SSD2092 (Alternate).
- **Interface Bus:** `I2C4` (Base address: `0x11011000`, Interrupt `GIC_SPI 90`).
- **7-bit Slave Address:**
  - Novatek NT36672: **`0x62`** (Write `0xC4`, Read `0xC5`).
  - Solomon SSD2092: **`0x53`** (Write `0xA6`, Read `0xA7`).
- **Coordinate Resolution:** $1080 \times 2160$ reporting surface matching the LCD panel.
- **Capabilities:** 10-point multi-touch, gesture wakeup, palm rejection.

### Signal & GPIO Allocation

| Signal | SoC Pin | Function / Pinctrl | Polarity | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `CTP_EINT` | `GPIO85` | `PINMUX_GPIO85__FUNC_EINT8` | Input / Edge Rising (`EINT8`) | Touch interrupt line |
| `CTP_RST` | `GPIO68` | `PINMUX_GPIO68__FUNC_GPIO68` | Output / Active Low | Hardware reset line |
| `CTP_SCL` | `GPIO59` | `PINMUX_GPIO59__FUNC_SCL4` | Open-Drain | I2C4 Clock |
| `CTP_SDA` | `GPIO60` | `PINMUX_GPIO60__FUNC_SDA4` | Open-Drain | I2C4 Data |
| `VIO18` | PMIC | `vio18` | 1.8V Regulated | Digital I/O supply |
| `VGP2` | PMIC | `vgp2` | 2.8V / 3.0V Regulated | Analog core supply |

---

## 2. Firmware Loading Requirements

The Novatek NT36672 digitizer requires firmware upload to internal SRAM during early boot:

- **Firmware Binary:** `blobs/novatek_ts_fw.bin` (Size: 118,272 bytes, MD5 `9f1d07c08a9f62137ecf01f22e8ec3b2`).
- **Vendor Path:** `/vendor/firmware/novatek_ts_fw.bin` or `/system/etc/firmware/novatek_ts_fw.bin`.
- **Loading Protocol:**
  1. Pull `GPIO68` (`CTP_RST`) low for 10ms, then release high.
  2. Send bootloader unlock sequence over `I2C4` (`0x55 0xAA 0x00`).
  3. Stream firmware payload in 512-byte blocks with CRC16 verification.
  4. Issue software reset command and poll for ready status (`0xAA`).

---

## 3. Vendor Kernel Implementation (3.18)

- **Source Path:** `drivers/input/touchscreen/mediatek/aeon_nt36xxx/` (`nt36xxx.c`, `nt36xxx_fw_update.c`).
- **DTS Nodes in Vendor:**
  - `arch/arm64/boot/dts/novatek-nt36xxx-i2c.dtsi`: `&i2c4 { cap_touch@62 { compatible = "mediatek,cap_touch"; reg = <0x62>; }; };`
  - `arch/arm64/boot/dts/ssd2092_touch.dtsi`: `&i2c4 { solomon_touch@53 { compatible = "mediatek,solomon_touch"; reg = <0x53>; }; };`

---

## 4. Mainline Implementation Roadmap

### Step 1: Upstream Linux Driver
Use `drivers/input/touchscreen/novatek-nvt-ts.c` (or standard multi-touch `generic_ts`):
- Connects via Linux `input_multitouch` subsystem (Protocol B with tracking slots).
- Utilizes standard `request_firmware("novatek_ts_fw.bin", &client->dev)` triggered via udev.

### Step 2: Mainline Device Tree Node
```dts
&i2c4 {
    status = "okay";
    clock-frequency = <400000>;
    pinctrl-names = "default";
    pinctrl-0 = <&i2c4_pins_default>;

    touchscreen@62 {
        compatible = "novatek,nt36672-ts", "novatek,nvt-ts";
        reg = <0x62>;
        interrupt-parent = <&pio>;
        interrupts = <85 IRQ_TYPE_EDGE_RISING>;
        reset-gpios = <&gpio 68 GPIO_ACTIVE_LOW>;
        vcc_i2c-supply = <&mt6351_vio18_reg>;
        vcc-supply = <&mt6351_vgp2_reg>;
        touchscreen-size-x = <1080>;
        touchscreen-size-y = <2160>;
        touchscreen-inverted-y;
        firmware-name = "novatek_ts_fw.bin";
    };
};
```

### Step 3: Userspace Orientation Configuration
In NixOS / Wayland / `udev`:
- Define `LIBINPUT_CALIBRATION_MATRIX` to map portrait digitizer coordinates (1080x2160) to the physical landscape display (2160x1080 rotated 270°).
