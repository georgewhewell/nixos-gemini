# Chapter 01: Display & DRM/KMS Subsystem

## 1. Hardware Architecture & Register Maps

The Gemini PDA display pipeline is driven by the MediaTek MT6797 MMSYS (Multimedia System) subsystem interfacing with a MIPI DSI display panel:

```
[System RAM / Framebuffer]
          │
          ▼
   ┌─────────────┐
   │  SMI LARB0  │  (0x14020000)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  DISP_OVL0  │  Overlay Engine (0x1400b000, 4 hardware layers, GIC SPI 213)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ DISP_COLOR0 │  Color Engine (0x14013000, GIC SPI 221)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ DISP_CCORR  │  Color Correction (0x14014000, GIC SPI 222)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  DISP_AAL   │  Adaptive Ambient Light / CABC (0x14015000, GIC SPI 223)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ DISP_GAMMA  │  Gamma Correction Table (0x14016000, GIC SPI 224)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │   DISP_OD   │  OverDrive Engine (0x14017000, GIC SPI 225)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ DISP_DITHER │  Dithering Engine (0x14018000, GIC SPI 226)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ DISP_RDMA0  │  Read DMA Engine (0x1400f000, GIC SPI 217)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  DISP_UFOE  │  Ultra Frame Output Engine / Compression (0x14019000)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │    DSI0     │  MIPI DSI Host Controller (0x1401c000, GIC SPI 229)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ MIPI TX PHY │  D-PHY Transmitter 0 (0x10215000)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ LCM Panel   │  Novatek NT36672 / SSD2092 (1080x2160 FHD+ IPS)
   └─────────────┘
```

### MediaTek MMSYS Memory Map (`mt6797.dtsi:3098-3127`)

| Subsystem Module | Physical Base | Size | Interrupt (GIC SPI) | Mainline Driver Target |
| :--- | :--- | :--- | :--- | :--- |
| **MMSYS_CONFIG** | `0x14000000` | `0x1000` | SPI 0 | `drivers/soc/mediatek/mtk-mmsys.c` |
| **DISP_OVL0** | `0x1400b000` | `0x1000` | SPI 213 | `drivers/gpu/drm/mediatek/mtk_disp_ovl.c` |
| **DISP_RDMA0** | `0x1400f000` | `0x1000` | SPI 217 | `drivers/gpu/drm/mediatek/mtk_disp_rdma.c` |
| **DISP_COLOR0** | `0x14013000` | `0x1000` | SPI 221 | `drivers/gpu/drm/mediatek/mtk_disp_color.c` |
| **DISP_CCORR** | `0x14014000` | `0x1000` | SPI 222 | `drivers/gpu/drm/mediatek/mtk_disp_ccorr.c` |
| **DISP_AAL** | `0x14015000` | `0x1000` | SPI 223 | `drivers/gpu/drm/mediatek/mtk_disp_aal.c` |
| **DISP_GAMMA** | `0x14016000` | `0x1000` | SPI 224 | `drivers/gpu/drm/mediatek/mtk_disp_gamma.c` |
| **DISP_OD** | `0x14017000` | `0x1000` | SPI 225 | Hardware OverDrive block |
| **DISP_DITHER** | `0x14018000` | `0x1000` | SPI 226 | `drivers/gpu/drm/mediatek/mtk_disp_dither.c` |
| **DISP_UFOE** | `0x14019000` | `0x1000` | SPI 227 | Ultra Frame Output Engine |
| **DISP_DSI0** | `0x1401c000` | `0x1000` | SPI 229 | `drivers/gpu/drm/mediatek/mtk_dsi.c` |
| **DISP_PWM** | `0x1100f000` | `0x1000` | - | `drivers/pwm/pwm-mtk-disp.c` |
| **DISP_MUTEX** | `0x1401f000` | `0x1000` | SPI 202 | `drivers/soc/mediatek/mtk-mutex.c` |
| **SMI_LARB0** | `0x14020000` | `0x1000` | SPI 233 | `drivers/memory/mediatek/smi_larb.c` |
| **SMI_COMMON** | `0x14022000` | `0x1000` | - | `drivers/memory/mediatek/smi_common.c` |
| **MIPITX0 (D-PHY)**| `0x10215000` | `0x1000` | - | `drivers/phy/mediatek/phy-mtk-mipi-dsi.c` |
| **GCE (CMDQ)** | `0x10212000` | `0x1000` | SPI 152 / 153 | `drivers/soc/mediatek/mtk-cmdq-helper.c` |

---

## 2. LCD Panel & Power Sequencing

The Gemini PDA supports Novatek NT36672 and Solomon Systech SSD2092 FHD+ LCD panels:

- **Panel Models:** Novatek NT36672 / Solomon SSD2092 5.99" IPS LCD (18:9 aspect ratio).
- **Resolution & Timings:**
  - Active Display Area: **1080 $\times$ 2160 pixels**.
  - Horizontal: H-Active 1080, HFP 42, HBP 42, HSA 10 (H-Total 1174 pixels).
  - Vertical: V-Active 2160, VFP 10, VBP 15, VSA 3 (V-Total 2188 lines).
  - Refresh Rate: 60 Hz, DSI PLL Clock: 440 MHz (Burst Video Mode, 4 DSI Data Lanes, 24-bit RGB888).
- **Power Supplies & Bias IC:**
  - `VIO18` (1.8V digital logic from MT6351 PMIC).
  - `VGP2` (2.8V / 3.0V analog power from MT6351 PMIC).
  - `LCM_VSP` (+5.5V positive bias) controlled via **GPIO 60** (`aeon_lcd_bias_enp`).
  - `LCM_VSN` (-5.5V negative bias) controlled via **GPIO 251** (`aeon_lcd_bias_enn`).
  - Dual-polarity bias IC: Texas Instruments TPS65132 / LP3101 on `I2C0` (slave address `0x3E`).
- **Hardware Reset:** Managed through MMSYS register `DISP_REG_CONFIG_MMSYS_LCM_RST_B` (`0x14000150`).
- **Backlight Control:** Managed directly via hardware **`DISP_PWM`** at `0x1100f000`.

---

## 3. Mainline Implementation Roadmap

### Step 1: Extend MediaTek DRM Driver for MT6797
- Add MT6797 routing table to `drivers/gpu/drm/mediatek/mtk_drm_drv.c`:
  `OVL0 -> COLOR0 -> CCORR -> AAL -> GAMMA -> DITHER -> RDMA0 -> DSI0`.
- Wire `DISP_MUTEX` (`0x1401f000`) and `SMI_LARB0` (`0x14020000`).

### Step 2: Mainline Panel Driver (`panel-novatek-nt36672.c`)
- Implement power sequencing:
  1. Enable `vio18` and `vgp2`.
  2. Assert GPIO 60 (`bias_enp`) and GPIO 251 (`bias_enn`).
  3. Configure TPS65132 / LP3101 I2C regulator for $\pm 5.5\text{V}$.
  4. Toggle reset line via MMSYS register `0x14000150`.
  5. Transmit DCS command table (Exit Sleep `0x11`, Display On `0x29`).

### Step 3: Device Tree Integration
```dts
mmsys: mmsys@14000000 {
    compatible = "mediatek,mt6797-mmsys", "syscon";
    reg = <0 0x14000000 0 0x1000>;
    #clock-cells = <1>;
};

dsi0: dsi@1401c000 {
    compatible = "mediatek,mt6797-dsi";
    reg = <0 0x1401c000 0 0x1000>;
    interrupts = <GIC_SPI 229 IRQ_TYPE_LEVEL_LOW>;
    clocks = <&mmsys CLK_MM_DSI0_ENGINE>,
             <&mmsys CLK_MM_DSI0_DIGITAL>;
    clock-names = "engine", "digital";
    phys = <&mipi_tx0>;
    phy-names = "dphy";

    panel@0 {
        compatible = "novatek,nt36672";
        reg = <0>;
        bias-enp-gpios = <&gpio 60 GPIO_ACTIVE_HIGH>;
        bias-enn-gpios = <&gpio 251 GPIO_ACTIVE_HIGH>;
        iovdd-supply = <&mt6351_vio18_reg>;
        vci-supply = <&mt6351_vgp2_reg>;
        backlight = <&disp_pwm>;
    };
};
```
