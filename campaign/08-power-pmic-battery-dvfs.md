# Chapter 08: Power Management, PMIC, Battery & DVFS

## 1. Power Distribution & PMIC Architecture

The Gemini PDA utilizes a multi-chip power architecture to regulate the deca-core MT6797 SoC, display, radios, and peripherals:

```
┌─────────────────────────────────────────────────────────────┐
│                 Battery (4220 mAh Li-Ion)                   │
└──────────────────────────────┬──────────────────────────────┘
                               │ VBAT (3.4V - 4.4V)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 TI BQ25890 Switch-Mode Charger              │
│                 (I2C0 at 0x6B, OTG Boost 5V)                │
└──────────────┬──────────────────────────────┬───────────────┘
               │ SYS_POWER                    │ VBUS (OTG)
               ▼                              ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│   MediaTek MT6351 PMIC       │ │   Dialog DA9214 Buck PMIC  │
│   (PWRAP at 0x1000d000)      │ │   (I2C6 APPM at 0x68)      │
│   - VIO18 (1.8V IO)          │ │   - VPROC / VA72 (A72 big) │
│   - VEMC_3V3 (3.0V eMMC)     │ │   - GPIO 61 Pinctrl        │
│   - VMC / VMCH (MicroSD)     │ └────────────────────────────┘
│   - VGP2 (2.8V LCD/Sensors)  │ ┌────────────────────────────┐
│   - VCORE / VSRAM            │ │   Fairchild FAN53555 Buck  │
│   - Audio Codec & ACCDET     │ │   (I2C7 GPUPM at 0x60)     │
│   - RTC & Fuel Gauge AuxADC  │ │   - VGPU (Mali-T880 Rail)  │
└──────────────────────────────┘ └────────────────────────────┘
```

---

## 2. PMIC-Wrapper (PWRAP) & MT6351 Primary PMIC

- **PWRAP Base Address:** `0x1000d000` (Size: `0x1000`), Interrupt: `GIC_SPI 178`.
- **Mainline Driver:** `drivers/soc/mediatek/mtk-pmic-wrap.c` and `drivers/mfd/mt6397.c`.
- **Key Regulators in MT6351 (`arch/arm64/boot/dts/mt6351.dtsi`):**
  - `vio18` (1.8V fixed): Digital I/O supply for eMMC, sensors, and panel logic.
  - `vemc_3v3` (3.0V–3.3V): eMMC 5.1 Flash VCC (`mt_pmic_vemc_ldo_reg`).
  - `vmc` / `vmch` (3.0V–3.3V / 1.8V): MicroSD slot power rails.
  - `vgp2` (2.8V fixed): Novatek LCD analog supply.
  - `vcore` (600 mV–1393.75 mV, 6.25 mV steps): Core logic rail.
  - `vusb33` (3.3V fixed): USB PHY supply.
  - `vdram` (900 mV–1210 mV): LPDDR3 DRAM supply.
  - `vcn33_bt` & `vcn33_wifi` (3.3V–3.6V): MT6630 combo radio supplies.

---

## 3. External I2C Buck Regulators

1. **Dialog Semiconductor DA9214 (Dual-Phase VPROC / A72 Buck):**
   - Bus: `I2C6` (APPM at `0x1100e000`, Slave Address **`0x68`**).
   - Control GPIO: `GPIO61` (`PINMUX_GPIO61__FUNC_GPIO61`).
   - Output: Buck A (`Reg 0xD7`) & Buck B (`Reg 0xD9`), 300 mV to 1570 mV in 10 mV steps.
   - Powers the dual **Cortex-A72 Big cluster** (`VA72`).
2. **Fairchild FAN53555 / Richtek RT5735 (VGPU Buck):**
   - Bus: `I2C7` (GPUPM at `0x11010000`, Slave Address **`0x60`** for FAN53555 / `0x1C` for RT5735).
   - Output: 600 mV to 1300 mV powering the **ARM Mali-T880 MP4 GPU** (`VGPU`).
3. **Fairchild FAN49101 (Buck-Boost Regulator):**
   - Bus: `I2C0` (`0x11007000`, Slave Address **`0x70`**).
   - Auxiliary voltage stabilization.

---

## 4. Texas Instruments BQ25890 Charger & Battery Profile

- **Battery Cell:** Single-cell Li-ion Polymer, 4.35V max charge, **4220 mAh (16.24 Wh)**.
- **Charger IC:** **Texas Instruments BQ25890**:
  - Bus: `I2C0` at 7-bit Slave Address **`0x6B`** (Write `0xD6`, Read `0xD7`).
  - Charging Currents: USB Standard `500 mA`, AC Charger `800 mA`–`3.25 A` fast charge.
  - Fast Charge Voltage: Configured via `CON6_VREG` (`0x06`) up to 4.40V in 16 mV steps.
  - OTG 5V Boost: Configured via `CON3_OTG_CONFIG` and `CONA` (4.55V–5.51V, up to 2.4A output).
  - Mainline Driver: Upstream `drivers/power/supply/bq25890_charger.c`.
- **Fuel Gauge (FG 2.0):**
  - Coulomb counter using a $10\text{ m}\Omega$ sense resistor (`r_fg_value = <10>`).
  - NTC thermistor: 17 temperature points ($-20^\circ\text{C}$ to $+60^\circ\text{C}$).

---

## 5. Tri-Cluster CPU DVFS & Thermal Throttling

The Helio X27 features 10 CPU cores across three distinct frequency/voltage clusters:

```
┌─────────────────────────────────────────────────────────────┐
│                 MediaTek MT6797 Tri-Cluster CPU             │
├──────────────────────────────┬──────────────────────────────┤
│ Cluster 0 (4x Cortex-A35)    │ 16 Steps: 221 MHz - 1.39 GHz │
│ (Little Cores 0..3)          │ Power: MT6351 VPROC          │
├──────────────────────────────┼──────────────────────────────┤
│ Cluster 1 (4x Cortex-A53)    │ 16 Steps: 325 MHz - 1.95 GHz │
│ (Medium Cores 4..7)          │ Power: MT6351 VPROC          │
├──────────────────────────────┼──────────────────────────────┤
│ Cluster 2 (2x Cortex-A72)    │ 16 Steps: 338 MHz - 2.57 GHz │
│ (Big Cores 8..9)             │ Power: Dialog DA9214 VA72    │
├──────────────────────────────┼──────────────────────────────┤
│ CCI-500 Interconnect Bus     │ 16 Steps: 169 MHz - 923 MHz  │
└──────────────────────────────┴──────────────────────────────┘
```

### Critical Thermal Safety Policy
- **Thermal Controller (TS_AP):** Base `0x1100b000`, GIC SPI 78, Clock `INFRA_THERM`.
- **Thermal Sensors:** 5 on-die CPU sensors (`TS1`–`TS5`), DA9214 PMIC junction sensor (`Reg 0x51`, critical trip: 150°C), BQ25890 charger sensor, and Battery NTC.
- **Safety Gate:** CPUs 8–9 (`maxcpus=10`) must remain disabled until closed-loop thermal throttling trip points (passive cooling at 75°C, A72 hotplug shutdown at 85°C, emergency reset at 105°C) are active in mainline Linux.
