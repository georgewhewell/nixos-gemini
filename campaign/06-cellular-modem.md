# Chapter 06: Cellular Modem Subsystem (MT6797 MD1 / CLDMA / CCIF)

## 1. Executive Summary & Baseband Architecture

The 4G LTE version of the Planet Computers Gemini PDA integrates the MediaTek **MD1 (Modem 1)** baseband processor directly on the MT6797 silicon die:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MediaTek MT6797 SoC                                │
│                                                                             │
│  ┌───────────────────────────┐         ┌─────────────────────────────────┐  │
│  │   Application Processor   │         │       Cellular Modem (MD1)      │  │
│  │   (AP / 10x ARM Cores)    │         │  - ARM Cortex-R4 Baseband Core  │  │
│  │   - Linux Kernel / NixOS  │         │  - Telecom DSP (md1dsp)         │  │
│  │   - ModemManager / oFono  │         │  - ARM7 Co-Processor (md1arm7) │  │
│  └─────────────┬─────────────┘         └────────────────┬────────────────┘  │
│                │                                        │                   │
│                │      CLDMA High-Speed Ring Buffers     │                   │
│                ├────────────────────────────────────────┤                   │
│                │   AP AO: 0x10014000  MD AO: 0x10015000 │                   │
│                │   AP PD: 0x10219000  MD PD: 0x1021a000 │                   │
│                │                                        │                   │
│                │      CCIF Hardware Mailbox & IRQs      │                   │
│                ├────────────────────────────────────────┤                   │
│                │   AP CCIF: 0x10209000 (GIC SPI 147)    │                   │
│                │   MD CCIF: 0x1020a000 (512B SRAM)      │                   │
│                │                                        │                   │
│                │      Reserved Baseband DRAM Window     │                   │
│                ├────────────────────────────────────────┤                   │
│                │   161 MiB at 0x40000000 - 0x80000000   │                   │
│                │   6 MiB Shared Memory Ring Buffer      │                   │
│                │                                        │                   │
│                │      Digital Telephony Voice PCM       │                   │
│                └────────────────────────────────────────┘                   │
│                    PCM2_INTF_CON <-> Audio Front End (AFE)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Cellular Radio Capabilities
- **4G LTE Cat-6:** FDD-LTE (Bands 1, 2, 3, 4, 5, 7, 8, 12, 17, 20, 28A), TDD-LTE (Bands 38, 40, 41), 2x Carrier Aggregation (up to 300 Mbps DL / 50 Mbps UL).
- **3G UMTS / WCDMA:** 850 / 900 / 1700 / 1900 / 2100 MHz (HSPA+ up to 42 Mbps DL / 11 Mbps UL), TD-SCDMA.
- **2G GSM:** 850 / 900 / 1800 / 1900 MHz (GPRS / EDGE Class 12).
- **SIM Architecture:** Dual SIM Dual Standby (DSDS) via physical micro-SIM / nano-SIM trays + eSIM support.

---

## 2. Dedicated eMMC Partitions & Firmware Headers

The cellular baseband relies on dedicated raw eMMC partitions for its operating system, DSP microcode, calibration, and non-volatile IMEI storage:

### Partition Table Layout

| Partition | Block Device | Label | Size | Content / Function |
| :--- | :--- | :--- | :--- | :--- |
| `p13` | `/dev/mmcblk0p13` | `md1img` | 24 MiB | Main baseband OS binary (`modem_1_lwg_n.img` / `modem_1_ltg_n.img`) |
| `p14` | `/dev/mmcblk0p14` | `md1dsp` | 4 MiB | Modem DSP filter & physical layer microcode (`dsp_1_lwg_n.bin`) |
| `p15` | `/dev/mmcblk0p15` | `md1arm7`| 3 MiB | Low-power ARM7 power management co-processor (`armv7_1_lwg_n.bin`) |
| `p16` | `/dev/mmcblk0p16` | `md3img` | 5 MiB | Optional CDMA2000 baseband binary (where equipped) |
| `p5` | `/dev/mmcblk0p5` | `nvcfg` | 8 MiB | Non-volatile modem calibration parameters & carrier profiles |
| `p6` | `/dev/mmcblk0p6` | `nvdata` | 32 MiB | IMEI numbers, RF calibration tables, SIM lock data |
| `p8` | `/dev/mmcblk0p8` | `protect1` | 8 MiB | Factory calibration and RF tuning data |
| `p9` | `/dev/mmcblk0p9` | `protect2` | 12 MiB | Carrier provisioning and custom APN profiles |

### Firmware Image Header (`struct md_check_header`)
Modem binaries begin with a 12-byte magic identifier (`CHECK_HEADER`) parsed by `ccci_util_lib_load_img.c`:
```c
struct md_check_header {
    unsigned char check_header[12];  /* "CHECK_HEADER" */
    unsigned int  header_verno;      /* Version (v3, v4, v5, v6) */
    unsigned int  product_ver;       /* 0=Invalid, 1=Debug, 2=Release */
    unsigned int  image_type;        /* 2G, 3G, LTE (e.g. modem_ultg) */
    unsigned char platform[16];      /* "MT6797_S01" */
    unsigned char build_time[64];    /* Build timestamp */
    unsigned char build_ver[64];     /* Version string: "MOLY.LR11.W16.xx" */
    unsigned char bind_sys_id;       /* 1 for MD1, 2 for MD2 */
    unsigned char ext_attr;          /* Shrink attributes */
    unsigned char reserved[2];
    unsigned int  mem_size;          /* Requested DRAM memory size */
    unsigned int  md_img_size;       /* Payload byte size */
    unsigned int  reserved_info;
    unsigned int  size;              /* Total header structure size */
} __packed;
```

---

## 3. Memory Boundaries & DRAM Reservations

The Application Processor reserves dedicated physical memory windows for baseband execution and shared inter-core messaging:

```dts
reserve-memory-ccci_md1 {
    compatible = "mediatek,reserve-memory-ccci_md1";
    no-map;
    size = <0 0xa100000>; /* 161 MiB reserved DRAM window */
    alignment = <0 0x2000000>;
    alloc-ranges = <0 0x40000000 0 0x80000000>;
};

reserve-memory-ccci_share {
    compatible = "mediatek,reserve-memory-ccci_share";
    no-map;
    size = <0 0x600000>;  /* 6 MiB shared memory buffer */
    alignment = <0 0x4000000>;
    alloc-ranges = <0 0x40000000 0 0x50000000>;
};
```

---

## 4. Transport: CLDMA & CCIF Register Specifications

Communication between the Linux host and baseband operates via **CLDMA** (hardware descriptor rings) and **CCIF** (inter-core mailbox interrupts):

### Register Blocks & Interrupts (`mt6797.dtsi:1782-1818`, `cldma_reg.h`)

| Register Block | Physical Address | Size | Description |
| :--- | :--- | :--- | :--- |
| `AP_CLDMA_AO` | `0x10014000` | `0x1e00` | AP Always-On CLDMA control registers |
| `MD_CLDMA_AO` | `0x10015000` | `0x1e00` | Modem Always-On CLDMA control registers |
| `AP_CLDMA_PDN` | `0x10219000` | `0x1e00` | AP Power-Down CLDMA registers |
| `MD_CLDMA_PDN` | `0x1021a000` | `0x1e00` | Modem Power-Down CLDMA registers |
| `AP_CCIF_BASE` | `0x10209000` | `0x1000` | AP Mailbox signaling registers (GIC SPI 147) |
| `MD_CCIF_BASE` | `0x1020a000` | `0x1000` | Modem Mailbox signaling registers (512B SRAM) |

### Interrupt Vector Mapping
- `IRQ_CLDMA` (`GIC_SPI 265`): Triggered upon DMA transfer completion or ring buffer replenish.
- `IRQ_CCIF` (`GIC_SPI 147`): Inter-core mailbox message notification.
- `IRQ_MDWDT` (`GIC_SPI 266`): Modem watchdog exception / baseband crash notification.

### Hardware Descriptors (`struct cldma_tgpd` & `struct cldma_rgpd`)
The CLDMA engine traverses linked lists of Generic Packet Descriptors (GPDs) in memory:
```c
struct cldma_tgpd {
    u8  gpd_flags;          /* Bit 0: HWO (Hardware Ownership), Bit 7: IOC (Interrupt on Completion) */
    u8  gpd_checksum;       /* Checksum byte */
    u16 debug_id;           /* Debug ID and high address bits [35:32] */
    u32 next_gpd_ptr;       /* Physical address of next TX descriptor */
    u32 data_buff_bd_ptr;   /* Physical address of payload buffer or Buffer Descriptor */
    u16 data_buff_len;      /* Byte length of packet */
    u8  desc_ext_len;
    u8  non_used;
} __packed;

struct cldma_rgpd {
    u8  gpd_flags;          /* Bit 0: HWO (Hardware Ownership), Bit 7: IOC */
    u8  gpd_checksum;
    u16 data_allow_len;     /* Maximum allowed receive buffer size */
    u32 next_gpd_ptr;       /* Physical address of next RX descriptor */
    u32 data_buff_bd_ptr;   /* Physical address of receive buffer */
    u16 data_buff_len;      /* Actual received byte length */
    u16 debug_id;
} __packed;
```

---

## 5. Packet Framing & 16-Byte CCCI Header

Every packet transmitted across CLDMA queues is prepended with a standard 16-byte `struct ccci_header` (`mt_ccci_common.h:78-88`):

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Data [0]                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Data [1]                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         Channel (16 bits)     | Seq Num (15 bits) | Assert (1)|
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Reserved                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

---

## 6. CLDMA Queue Allocation & Logical Device Channels

The vendor driver configures 8 TX queues and 8 RX queues (`port_cfg.c:19-88`), exposing standard virtual devices to userspace:

| Queue ID | Logical Channel | Device Node | Purpose / Function |
| :--- | :--- | :--- | :--- |
| **Queue 0** | `CCCI_CONTROL` / `CCCI_STATUS` | `/dev/ccci_ctrl`, `/dev/ccci_poll` | Baseband state machine, power management, boot handshake |
| **Queue 1** | `CCCI_FS_TX` / `CCCI_FS_RX` | `/dev/ccci_fs` | NVRAM filesystem bridge (serves `/nvdata/md/` & `/nvcfg/md/`) |
| **Queue 1** | `CCCI_RPC_TX` / `CCCI_RPC_RX` | `/dev/ccci_rpc`, `/dev/ccci_rpc_k` | Remote Procedure Calls (Battery status, time, thermal) |
| **Queue 1** | `CCCI_UART2` | `/dev/ttyC0` (Major 188, Minor 3) | **Primary AT Command Channel** (ModemManager / oFono / RIL) |
| **Queue 2** | `CCCI_MD_LOG` | `/dev/ttyC1` (Minor 7) | Baseband diagnostic logger & core dump stream |
| **Queue 3** | `CCCI_CCMNI1` / `CCMNI2` | `ccmni0`, `ccmni1` | High-Speed WWAN Cellular Packet Data (NAPI / GRO enabled) |
| **Queue 4** | `CCCI_CCMNI3` / `CCMNI4` | `ccmni2`, `ccmni3` | Secondary WWAN Data Channels (Multi-PDP / Tethering) |
| **Queue 5** | `CCCI_CCMNI5` .. `CCMNI8`| `ccmni4` .. `ccmni7` | Additional Data Streams (MMS, IMS, Emergency APN) |
| **Queue 6** | `CCCI_IMSV` .. `CCCI_IMSEM`| `/dev/ccci_imsv` .. `/dev/ccci_imsem` | VoLTE / IMS Voice and Signaling Channels |
| **Queue 7** | `CCCI_MDL_MONITOR` | `/dev/ccci_mdl_monitor` | Modem lifecycle monitor |

---

## 7. Digital Telephony Voice Call Path

During cellular voice calls, audio streams directly between the baseband DSP and the MT6797 Audio Front End (AFE) via dedicated hardware PCM DAIs (`mt_soc_pcm_voice_md1.c`):

```
[Cellular Antenna / RF]
          │ LTE / 3G / 2G Voice Frames
          ▼
[MD1 Baseband DSP]
          │ Digital Telephony PCM Stream (8 kHz / 16 kHz HD Voice)
          ▼
[MT6797 AFE PCM Interface (PCM2_INTF_CON)]
          │ Hardware ASRC (Sample Rate Conversion to 48 kHz)
          ▼
[AFE Interconnect Routing Matrix (AFE_CONN)]
          │
    ┌─────┴─────────────────────┐
    ▼                           ▼
[MT6351 PMIC DAC]       [Dual AW8736 Amps]
    │                           │
    ▼                           ▼
[3.5mm Headphone Jack]  [Stereo Internal Speakers]
```

### Voice Routing Controls
- Telephony uplink: `AIN0` (Main Mic) $\to$ MT6351 ADC $\to$ AFE $\to$ `PCM2_INTF` $\to$ Baseband DSP.
- Telephony downlink: Baseband DSP $\to$ `PCM2_INTF` $\to$ AFE $\to$ MT6351 DAC $\to$ Earpiece / Headphone / Speaker Amps (`GPIO243`/`244`).

---

## 8. SIM Card Power & Hot-Swap Signals

The MT6797 manages two independent SIM interfaces via MT6351 PMIC LDO regulators:

- **SIM1 Interface:**
  - Power Rail: `mt_pmic_vsim1_ldo_reg` (`vsim1`, 1.7V to 3.1V dynamic switching).
  - Data / Clock / Reset lines connected to SoC SIM1 controller.
  - Hot-plug detection pin: `GPIO_SIM1_HOT_PLUG` (EINT).
- **SIM2 Interface:**
  - Power Rail: `mt_pmic_vsim2_ldo_reg` (`vsim2`, 1.7V to 3.1V dynamic switching).
  - Hot-plug detection pin: `GPIO_SIM2_HOT_PLUG` (EINT).

---

## 9. Mainline Linux Implementation Strategy

### Step 1: Upstream Linux WWAN CLDMA Driver (`drivers/net/wwan/mediatek_cldma.c`)
- Implement a standard Linux WWAN driver managing:
  - CLDMA descriptor allocation (`struct cldma_tgpd` / `cldma_rgpd`).
  - CCIF mailbox interrupt handling on GIC SPI 147 (`0x10209000`).
  - Registration of `/dev/ttyC0` using standard `wwan_create_port()`.
  - Registration of `ccmni0`..`ccmni7` network devices via `wwan_register_ops()`.

### Step 2: Open-Source NVRAM Bridge Daemon (`ccci_fsd`)
- A minimal user-space C/Rust helper daemon that:
  - Opens `/dev/ccci_fs`.
  - Serves baseband file requests against `/nvdata/md/NVRAM/NVD_IMEI/` and `/nvcfg/md/NVRAM/CALIBRAT/`.
  - Responds with file sizes, seek offsets, and data payloads.

### Step 3: Userspace Connection Management via ModemManager
- **ModemManager** communicates directly over `/dev/ttyC0`:
  - `AT+CPIN?`: Query SIM PIN status.
  - `AT+CEREG?`: Query LTE network attachment.
  - `AT+CSQ`: Signal quality reporting.
  - `AT+CGDCONT=1,"IP","your.apn"`: APN configuration.
  - `AT+CGACT=1,1`: Activate packet data bearer on `ccmni0`.
- Standard NetworkManager / ConnMan manages routing and DNS for `ccmni0`.
