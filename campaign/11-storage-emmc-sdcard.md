# Chapter 11: Storage Subsystem (eMMC 5.1 & MicroSD)

## 1. Hardware Architecture

The Gemini PDA contains two MediaTek SD/eMMC Controllers (MSDC):

```
┌─────────────────────────────────────────────────────────────┐
│                 MediaTek MT6797 SoC                         │
│                                                             │
│  [MSDC0 Host Controller] ─── 8-bit eMMC 5.1 Bus ──────────┐  │
│  (0x11230000, GIC SPI 79)                                 │  │
│                                                           │  │
│  [MSDC1 Host Controller] ─── 4-bit MicroSD Slot ─────────┐│  │
│  (0x11240000, GIC SPI 80)                                ││  │
└──────────────────────────────────────────────────────────┼┼─┘
                                                           ││
                                               MicroSD Bus ││ 8-bit eMMC Bus
                                                           ▼▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│   External MicroSD Slot      │ │   SanDisk / DF4064 eMMC    │
│   - Hotplug Card Detect      │ │   - 64 GB Capacity         │
│   - VMC / VMCH Power Rails   │ │   - 8-bit DDR / HS200 / 400│
│   - Up to 104 MB/s (SDR104)  │ │   - Power-on WP in LK      │
└──────────────────────────────┘ └────────────────────────────┘
```

---

## 2. eMMC Power-On Write Protection & LK Contract

A critical discovery in the Gemini hardware audit is the interaction between Little Kernel (LK) and eMMC write protection:

- **eMMC Chip:** SanDisk DF4064 64GB eMMC 5.1.
- **Write-Protect Groups:** The eMMC uses legacy CSD write-protect groups (8 MiB per group).
- **LK Power-on WP:** During early boot, Planet's LK bootloader applies hardware power-on write protection to groups 15 through 27 (sectors 245,760 through 458,751, covering partitions `p10` through `p26`).
- **Impact on Partition `p22` (`boot`):**
  - Partition `p22` is physically write-protected once LK has initialized the eMMC.
  - Linux `dd` commands writing to `/dev/mmcblk0p22` will fail with an eMMC write violation (`R1_WP_VIOLATION`), but the vendor kernel command queue silently clears the error, leading to silent write failures.
  - Updating `p22` must be performed through the pre-boot **MediaTek Flash Tool (SP Flash Tool)** over the left USB port.
  - Development builds should always target partition **`p30` (`boot2`)** or **`p31` (`boot3`)**, which are outside the write-protected sector range.

---

## 3. Dedicated MT6797 MSDC Driver Work

Research into the MediaTek MSDC IP revealed that MT6797 requires a dedicated variant driver:
- Borrowing drivers from MT6779 or MT8183 changes the wrong block-length register, causing DMA transfer corruption.
- Safe first-pass mainline contract: 8-bit eMMC at **25 MHz / 50 MHz High-Speed Mode**, avoiding HS200 / HS400 tuning until voltage regulators and pad drive strengths are verified.

### Device Tree Node for eMMC (MSDC0)
```dts
&mmc0 {
    status = "okay";
    pinctrl-names = "default", "state_uhs";
    pinctrl-0 = <&mmc0_pins_default>;
    pinctrl-1 = <&mmc0_pins_uhs>;
    bus-width = <8>;
    max-frequency = <50000000>;
    cap-mmc-highspeed;
    vmmc-supply = <&mt6351_vemc_3v3_reg>;
    vqmmc-supply = <&mt6351_vio18_reg>;
    non-removable;
};
```

---

## 4. MicroSD Card Expansion (MSDC1)

The external MicroSD tray supports cards up to 2TB:
- **Card Detect GPIO:** Connected to SoC `EINT` pin.
- **Power Supplies:** Dynamic power switching between 3.3V (standard speed) and 1.8V (UHS-I SDR50/SDR104) via MT6351 `vmc` / `vmch` regulators.
- **Mainline Status:** Needs MSDC1 node declaration and regulator binding in `mt6797-gemini-pda.dts`.
