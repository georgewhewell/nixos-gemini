# Chapter 02: GPU & 3D Acceleration (Mali-T880 / Panfrost)

## 1. Hardware Architecture & Register Maps

The Gemini PDA's graphical acceleration is driven by an ARM Mali-T880 MP4 GPU embedded within the MT6797 SoC:

- **GPU Core:** ARM Mali-T880 (Midgard 4th Generation / Core ID `0x0880`, 4 Unified Shader Cores).
- **Physical Register Base:** **`0x13040000`** (Size: `0x4000` / 16 KB).
- **Peak Clock Frequency:** Up to 900 MHz (Helio X27 speed bin).
- **Graphics APIs:** OpenGL ES 1.1 / 2.0 / 3.0 / 3.1 / 3.2, Vulkan 1.0, OpenCL 1.2 / 2.0.

### Interrupt Mapping (`mt6797.dtsi:3052-3054`)

| Interrupt Name | GIC SPI Number | Interrupt Vector | Description |
| :--- | :--- | :--- | :--- |
| `JOB` | GIC SPI 264 | IRQ 296 | Mali Job slot execution complete / job fault |
| `MMU` | GIC SPI 263 | IRQ 295 | Mali MMU page fault / TLB invalidation |
| `GPU` | GIC SPI 262 | IRQ 294 | Mali GPU power management & global status |

---

## 2. Power Rails, DVFS OPPs & Clocks

1. **Power Domain (SCPSYS MTCMOS):**
   - Main GPU Power Domain: `SCP_SYS_MFG` / `SCP_SYS_MFG_ASYNC`.
   - Core Power Domains: `SCP_SYS_MFG_CORE0` through `SCP_SYS_MFG_CORE3` (individual dynamic power gating per shader core).
2. **Voltage Regulation (`VGPU` Rail):**
   - High-current buck converter provided by external **Fairchild FAN53555 / Richtek RT5735** (`0x60` on `I2C7` GPUPM) or Dialog DA9214.
   - Voltage Range: 0.60V to 1.15V.
3. **DVFS Operating Performance Points (OPP):**
   - 900 MHz @ 1.05V (Boost Level 0)
   - 780 MHz @ 0.95V (Level 1)
   - 700 MHz @ 0.90V (Level 2 Nominal)
   - 610 MHz @ 0.85V (Level 3)
   - 520 MHz @ 0.80V (Level 4)
   - 442.5 MHz @ 0.75V (Level 5)
   - 365 MHz @ 0.70V (Level 6)
   - 301.5 MHz @ 0.65V (Level 7 Minimum)

---

## 3. Mainline Panfrost Driver Integration

The Mali-T880 (`Core ID 0x0880`) is fully supported in mainline Linux through the open-source **Panfrost DRM driver** (`CONFIG_DRM_PANFROST=y`) and the Mesa Panfrost Gallium driver (`panfrost_dri.so`):

### Mainline Device Tree Node
```dts
gpu: gpu@13040000 {
    compatible = "mediatek,mt6797-mali", "arm,mali-t880", "arm,mali-midgard";
    reg = <0 0x13040000 0 0x4000>;
    interrupts = <GIC_SPI 264 IRQ_TYPE_LEVEL_LOW>,
                 <GIC_SPI 263 IRQ_TYPE_LEVEL_LOW>,
                 <GIC_SPI 262 IRQ_TYPE_LEVEL_LOW>;
    interrupt-names = "job", "mmu", "gpu";
    clocks = <&mfgsys CLK_MFG_BG3D>;
    clock-names = "core";
    power-domains = <&scpsys MT6797_POWER_DOMAIN_MFG>;
    mali-supply = <&fan53555_vgpu>;
    operating-points-v2 = <&gpu_opp_table>;
    #cooling-cells = <2>;
    status = "okay";
};
```

### Userspace Acceleration
- With Panfrost active, Wayland compositors (Sway, Phosh, Plasma Mobile) run hardware-accelerated rendering at 60 FPS without software rasterization CPU overhead.
