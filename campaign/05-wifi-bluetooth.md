# Chapter 05: Wireless Subsystem (Wi-Fi 802.11ac, Bluetooth & CONSYS)

## 1. Executive Summary & Hardware Architecture

The wireless subsystem on the Planet Computers Gemini PDA is powered by the MediaTek **CONSYS (Connectivity Subsystem)** integrating an MT6630/MT6631 class wireless combo core:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MediaTek MT6797 SoC                                │
│                                                                             │
│  ┌───────────────────────────┐         ┌─────────────────────────────────┐  │
│  │   Application Processor   │         │       CONSYS Connectivity MCU   │  │
│  │   (AP / 10x ARM Cores)    │         │  - 32-bit Andes N9 MCU Core     │  │
│  │   - Linux Kernel / NixOS  │         │  - 802.11ac 1x1/2x2 Wi-Fi MAC   │  │
│  │   - mac80211 / BlueZ      │         │  - Bluetooth 4.1 + EDR / BLE    │  │
│  └─────────────┬─────────────┘         └────────────────┬────────────────┘  │
│                │                                        │                   │
│                │      AHB / PDMA High-Speed Bus         │                   │
│                ├────────────────────────────────────────┤                   │
│                │   Wi-Fi DMA Base: 0x180f0000 (SPI 283) │                   │
│                │   AP PDMA Base:   0x11000080           │                   │
│                │   512 KB Reserved EMI Buffer (MPU 12)  │                   │
│                │                                        │                   │
│                │      CONSYS Control & Mailboxes        │                   │
│                ├────────────────────────────────────────┤                   │
│                │   CONSYS Base:    0x18070000 (SPI 284) │                   │
│                │   WDT IRQ:        GIC SPI 285          │                   │
│                │   Clocks & MTCMOS: SCP_SYS_CONN        │                   │
│                │                                        │                   │
│                │      Bluetooth High-Speed UART (BTIF)  │                   │
│                └────────────────────────────────────────┘                   │
│                    BTIF Base: 0x1100c000 (GIC SPI 118)                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Hardware Capabilities & PHY Specifications

| Feature | Specification | Hardware Engine Support |
| :--- | :--- | :--- |
| **Wi-Fi Standards** | IEEE 802.11 a/b/g/n/ac | Dual-band 2.4 GHz & 5 GHz |
| **Channel Bandwidths** | 20 MHz, 40 MHz (HT40), 80 MHz (VHT80) | Full 80 MHz VHT contiguous |
| **Modulation / Coding** | BPSK, QPSK, 16-QAM, 64-QAM, 256-QAM | MCS 0 through MCS 9 (VHT) |
| **Max PHY Data Rate** | 433.3 Mbps (1x1 VHT80 SGI) / 866.7 Mbps (2x2) | Short Guard Interval (400 ns) |
| **Packet Aggregation** | A-MPDU TX/RX (up to 64 subframes), A-MSDU RX (7935B) | Hardware Block-Ack engine |
| **Hardware Encryption**| WEP40/104/128, TKIP, AES-CCMP, GCMP, WPI/WAPI, 802.11w BIP | Line-rate hardware cryptographic accelerator |
| **Checksum Offload** | IPv4/IPv6 header & TCP/UDP checksum TX generate / RX verify | `RX_STATUS_IP_CHKSUM`, `RX_STATUS_UDP_TCP_CHKSUM` |
| **Concurrency** | Concurrent STA + SoftAP or STA + Wi-Fi Direct (P2P) | Dual MAC BSSID filters |
| **QoS / WMM** | 4 Hardware EDCA Access Categories: VO, VI, BE, BK | TXOP bursting & dynamic contention |
| **Power Management** | DTIM listen, Dynamic PS-Poll, WoWLAN (Wake-on-WLAN) | Pattern match & Magic Packet wakeup |
| **Bluetooth Engine** | Bluetooth 4.1 + EDR (3 Mbps), Bluetooth Low Energy (BLE) | Wideband Speech (mSBC), Coexistence (PTA) |

---

## 3. Register Maps, Interrupts & Clock Domains

### Primary Hardware Register Blocks (`mt6797.dtsi:3760-3781`, `mt6630_reg.h`)

| Block | Physical Base | Size | Interrupt (GIC SPI) | Purpose / Description |
| :--- | :--- | :--- | :--- | :--- |
| **`wifi`** | `0x180f0000` | `0x1100` | GIC SPI 283 (`IRQ_WIFI_DMA`) | Wi-Fi MAC registers, packet data ports, RX/TX status |
| **`consys`** | `0x18070000` | `0x0200` | GIC SPI 284 (`BGF_EINT`) | CONSYS MCU config & firmware patch loader |
| **`consys_wdt`**| `0x18070000` | - | GIC SPI 285 (`WDT_EINT`) | CONSYS hardware watchdog & crash notification |
| **`ap_pdma`** | `0x11000080` | `0x0080` | - | High-speed Peripheral DMA controller |
| **`btif`** | `0x1100c000` | `0x1000` | GIC SPI 118 | Bluetooth serial interface controller |
| **`ap_rgu`** | `0x10007000` | `0x0100` | - | Reset generation unit for CONSYS |
| **`topckgen`** | `0x10000000` | `0x2000` | - | Top clock generation unit |
| **`spm`** | `0x10006000` | `0x1000` | - | System Power Manager MTCMOS domain |

### Power Supplies & Regulators (MT6351 PMIC)
- `vcn18`: 1.8V digital logic supply (`mt_pmic_vcn18_ldo_reg`).
- `vcn28`: 2.8V TCXO crystal oscillator supply (`mt_pmic_vcn28_ldo_reg`).
- `vcn33_bt`: 3.3V Bluetooth RF transceiver supply (`mt_pmic_vcn33_bt_ldo_reg`).
- `vcn33_wifi`: 3.3V Wi-Fi PA (Power Amplifier) and RF LNA supply (`mt_pmic_vcn33_wifi_ldo_reg`).

---

## 4. MAC Register Specifications (`mt6630_reg.h`)

The Wi-Fi core at `0x180f0000` exposes the following memory-mapped control registers (MCRs):

| Offset | Register Name | Description | Key Bitfields / Operation |
| :--- | :--- | :--- | :--- |
| `0x0000` | `MCR_WCIR` | Chip Identification Register | Returns `0x6630` or `0x6797` chip signature |
| `0x0004` | `MCR_WHLPCR` | HIF Low Power Control | Bit 0: Sleep enable, Bit 1: Wakeup trigger |
| `0x0008` | `MCR_WSDIOCSR`| Control Status Register | Bus clock status & readiness |
| `0x000C` | `MCR_WHCR` | HIF Control Register | `W_INT_CLR_CTRL`, `MAX_HIF_RX_LEN`, `RECV_MAILBOX_RD_CLR_EN` |
| `0x0010` | `MCR_WHISR` | HIF Interrupt Status | Bit 0: `TX_DONE`, Bit 1: `RX0_DONE`, Bit 2: `RX1_DONE`, Bit 3: `D2H_SW_INT` |
| `0x0014` | `MCR_WHIER` | HIF Interrupt Enable | Bitmask corresponding to `WHISR` |
| `0x0020` | `MCR_WASR` | Abnormal Status Register | Hardware FIFO overflow/underrun alerts |
| `0x0024` | `MCR_WSICR` | WLAN SW Interrupt Control | Host-to-firmware software interrupt line |
| `0x0034` | `MCR_WTDR1` | WLAN TX Data Port 1 | 32-bit FIFO write window for outbound frame descriptors |
| `0x0050` | `MCR_WRDR0` | WLAN RX Data Port 0 | 32-bit FIFO read window for inbound data frames |
| `0x0054` | `MCR_WRDR1` | WLAN RX Data Port 1 | Inbound event and management frame port |
| `0x0070` | `MCR_H2DSM0R`| Host to Device Send Mailbox 0| Command message notification |
| `0x0078` | `MCR_D2HRM0R`| Device to Host Recv Mailbox 0| Firmware response notification |
| `0x0130` | `MCR_WTQCR0` | WLAN TXQ Count 0 (AC_BK) | Free page credits for Background queue |
| `0x0134` | `MCR_WTQCR1` | WLAN TXQ Count 1 (AC_BE) | Free page credits for Best Effort queue |
| `0x0138` | `MCR_WTQCR2` | WLAN TXQ Count 2 (AC_VI) | Free page credits for Video queue |
| `0x013C` | `MCR_WTQCR3` | WLAN TXQ Count 3 (AC_VO) | Free page credits for Voice queue |
| `0x0140` | `MCR_WTQCR4` | WLAN TXQ Count 4 (CMD) | Free page credits for Management/Command queue |

---

## 5. DMA Engine & High-Speed Descriptor Framing

The Wi-Fi subsystem uses dedicated **Peripheral DMA (PDMA)** at `0x11000080` coupled with a 512 KB reserved EMI shared memory window:

```
[Linux SKB Data Buffer]
          │
          ▼
[Prepend 28-Byte TX Descriptor (Long Format)]
┌─────────────────────────────────────────────────────────────┐
│ DW0: TX Byte Count [15:0] | Ethernet Type Offset [23:16]    │
│ DW1: WLAN Index [7:0] | Header Format [9:8] | PKT_FT [15]   │
│ DW2: TID [2:0] | Protection [4] | A-MPDU [5] | Queue [15:8] │
│ DW3: PID [7:0] | Retry Limit [15:8] | TX Time [31:16]       │
│ DW4: Fixed Rate [0] | Rate Code [15:8] | Antenna [31:24]    │
│ DW5: Tx Power Offset [7:0] | Bandwidth [17:16] (20/40/80M)  │
│ DW6: Reserved                                               │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
[Execute PDMA Burst Transfer via 0x11000080 -> 0x180f0034]
          │
          ▼
[CONSYS Wi-Fi MAC Hardware Transmitter]
```

### RX Status Header Format (Parsed on RX Interrupt `0x180f0050`)
Every packet delivered from `MCR_WRDR0` begins with hardware status words:
- **DW0:** Byte Count (Bits 0..16), IP Checksum Valid (`BIT 7`), TCP/UDP Checksum Valid (`BIT 8`), Packet Type (`BITS 13..15`).
- **DW1:** Unicast to Me (`BIT 1`), Multicast (`BIT 2`), Broadcast (`BIT 3`), Key ID (`BITS 6..7`).
- **DW2:** RX Timestamp (32-bit TSF timer).
- **DW3:** Channel Number, RSSI (Received Signal Strength), SNR (Signal-to-Noise Ratio), Rate Code (MCS 0..9).

---

## 6. Firmware Architecture & Boot Sequence

CONSYS requires two-stage firmware loading via the Serial Transport Protocol (STP):

1. **Stage 1: CONSYS ROM Patch (`WMT_SOC.cfg` & `ROMv3_patch_1_0_hdr.bin`)**
   - Assert `SCP_SYS_CONN` MTCMOS power domain.
   - Enable PMIC rails (`vcn18`, `vcn28`, `vcn33_bt`, `vcn33_wifi`).
   - Pulse hardware reset via `AP_RGU` (`0x10007000`).
   - Download ROM patch fragments (Opcode `0x01`, Subcode `0x01`) in 1000-byte chunks.
   - Issue `WMT_RESET_CMD` (`0x01, 0x07, 0x01, 0x00, 0x04`) to start the 32-bit Andes MCU.
2. **Stage 2: Wi-Fi RAM Firmware (`WIFI_RAM_CODE_6797` / `WIFI_RAM_CODE`)**
   - Transmit Wi-Fi firmware image directly across HIF mailbox registers into CONSYS SRAM.
   - MCU executes Wi-Fi MAC firmware and reports `WLAN_READY` over `MCR_D2HRM0R`.

---

## 7. Mainline Linux Driver Architecture Blueprint

To achieve maximal performance, low latency, and upstream compatibility, the driver should follow the **`mac80211`** framework (as in upstream `drivers/net/wireless/mediatek/mt76/`):

```
┌─────────────────────────────────────────────────────────────┐
│                 Linux mac80211 Subsystem                    │
│   (cfg80211, nl80211, hostapd, wpa_supplicant, iwd)         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│          Mainline MediaTek Wi-Fi Driver (mt76_consys)       │
│                                                             │
│  - `mt76_consys_init()`: Maps 0x180f0000 & 0x18070000        │
│  - `mt76_consys_firmware_load()`: request_firmware()        │
│  - `mt76_consys_tx()`: Encapsulates 28-byte TXD + PDMA burst│
│  - `mt76_consys_rx_poll()`: NAPI polling loop from WRDR0    │
│  - `mt76_consys_set_channel()`: VHT80 frequency synthesizer │
│  - `mt76_consys_set_key()`: Hardware crypto key table       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 MT6797 CONSYS Hardware (0x180f0000)         │
└─────────────────────────────────────────────────────────────┘
```

### Key Performance Configurations
1. **NAPI Polling:** Bind RX ring processing to NAPI with a budget of 64 packets per interrupt to eliminate context-switch overhead during gigabit TCP transfers.
2. **Scatter-Gather PDMA:** Enable 64-byte burst lengths on `AP_DMA_HIF_0_CON` (`0x11000080 + 0x18`) to achieve maximum memory throughput.
3. **Dynamic A-MPDU Window:** Scale TX Block-Ack density dynamically up to 64 frames (65,535 bytes) for maximum throughput on 80 MHz channels.
