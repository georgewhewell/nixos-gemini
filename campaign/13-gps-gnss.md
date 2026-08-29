# Chapter 13: GPS & GNSS Subsystem (MT6797 CONSYS GNSS / MNL / A-GPS)

## 1. Executive Summary & Hardware Architecture

The Planet Computers Gemini PDA integrates a multi-constellation Global Navigation Satellite System (GNSS) receiver within the MediaTek **CONSYS (Connectivity Subsystem)** block:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MediaTek MT6797 SoC                                │
│                                                                             │
│  ┌───────────────────────────┐         ┌─────────────────────────────────┐  │
│  │   Application Processor   │         │       CONSYS GNSS Co-Processor  │  │
│  │   (AP / 10x ARM Cores)    │         │  - Dedicated DSP Tracking Engine│  │
│  │   - Linux Kernel / NixOS  │         │  - Hardware Correlation Filters │  │
│  │   - gpsd / Geoclue2       │         │  - A-GPS / EPO Hardware Decoder │  │
│  └─────────────┬─────────────┘         └────────────────┬────────────────┘  │
│                │                                        │                   │
│                │      STP Serial Transport Protocol     │                   │
│                ├────────────────────────────────────────┤                   │
│                │   STP Task Index 3 (GPS_TASK_INDX)     │                   │
│                │   Character Device: /dev/stpgps        │                   │
│                │   Power Control:    /dev/gps           │                   │
│                │                                        │                   │
│                │      Reserved EMI Shared Memory        │                   │
│                ├────────────────────────────────────────┤                   │
│                │   1 MiB Reserved Buffer (MPU Reg 20)   │                   │
│                │   MNL.bin Microcode Execution Base     │                   │
│                │                                        │                   │
│                │      RF Front-End & TCXO Reference     │                   │
│                └────────────────────────────────────────┘                   │
│                    26 MHz System Reference Clock / VCN28 (2.8V)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Satellite Constellations & GNSS Receiver Specifications

| Parameter | Specification | Hardware Capabilities |
| :--- | :--- | :--- |
| **Supported Constellations** | GPS, GLONASS, BeiDou, Galileo, QZSS | Concurrent multi-GNSS reception |
| **Frequency Bands** | GPS L1 C/A (1575.42 MHz), GLONASS L1-OF (1602 MHz), BeiDou B1I (1561.098 MHz), Galileo E1 (1575.42 MHz) | Single RF Front-End with wideband IF downconversion |
| **SBAS Support** | WAAS, EGNOS, MSAS, GAGAN | Differential correction decoding |
| **Sensitivity** | Acquisition: $-148\text{ dBm}$, Tracking: $-165\text{ dBm}$, Hot Start: $-160\text{ dBm}$ | High-gain internal LNA with automatic AGC |
| **Time-To-First-Fix (TTFF)**| Cold Start: $< 35\text{ s}$, Warm Start: $< 15\text{ s}$, **Hot / A-GPS Start: $< 1\text{ s}$** | Extended Prediction Orbit (EPO) support |
| **Position Accuracy** | Autonomous: $< 2.5\text{ m}$ CEP, SBAS-corrected: $< 1.5\text{ m}$ CEP | Dual-frequency correlation engines |
| **Update Rate** | 1 Hz, 2 Hz, 5 Hz, up to 10 Hz | Configurable via PMTK commands |
| **Coexistence (PTA)** | Packet Traffic Arbitration with LTE Band 7/40/41, Wi-Fi 2.4 GHz, Bluetooth | Hardware notch filtering to eliminate desense |

---

## 3. Memory Map, Partitions & Kernel Interface

### Memory Map & Reserved DRAM (`gps_emi.c:72-155`)

| Region / Device | Base Address / Major | Size | Description |
| :--- | :--- | :--- | :--- |
| **Reserved GPS EMI** | `gConEmiPhyBase + 0x100000` | 1 MiB (`SZ_1M`) | Dedicated DRAM buffer for GNSS microcode execution |
| **MPU Protection** | Region 20 | 1 MiB | Restricted access permission (CONSYS Read/Write, AP R/W) |
| **`/dev/gps`** | Misc Driver | - | Power state control (`GPS_PWRCTL_ON`, `GPS_PWRCTL_OFF`, `GPS_PWRCTL_RST`) |
| **`/dev/stpgps`** | Major 191 (`0xBF`) | - | Bidirectional NMEA and PMTK character stream |
| **`/dev/gps_emi`** | Char Device | - | IOCTL interface for firmware injection (`IOCTL_MNL_IMAGE_FILE_TO_MEM`) |

### PMIC Power Rails & Clocks
- `vcn28`: 2.8V Low-Dropout Regulator powering the 26 MHz TCXO crystal oscillator (`mt_pmic_vcn28_ldo_reg`).
- `vcn18`: 1.8V LDO powering digital baseband logic (`mt_pmic_vcn18_ldo_reg`).
- Co-Clock Reference: 26 MHz master system clock distributed by SPM.

---

## 4. Firmware Loading & Memory Initialization Protocol

The GNSS subsystem relies on the **MediaTek Navigation Library (MNL)** microcode binary (`MNL.bin`):

1. **Power Sequence (`gps.c:gps_power_on()`):**
   - Assert `SCP_SYS_CONN` power domain.
   - Enable PMIC regulators `vcn18` and `vcn28`.
   - Issue WMT function enable command (`mtk_wcn_wmt_func_on(WMTDRV_TYPE_GPS)`).
2. **EMI Buffer Allocation (`gps_emi.c:mtk_wcn_consys_gps_emi_init()`):**
   - Reserve 1 MiB contiguous physical DRAM at `gGpsEmiPhyBase`.
   - Configure EMI MPU Region 20 with `FORBIDDEN` permissions for non-authorized masters.
   - Map buffer into kernel virtual address space via `ioremap_nocache()`.
   - Copy `MNL.bin` (or `GPS_RAM_CODE`) into the mapped 1 MiB buffer.
3. **GNSS Core Execution:**
   - CONSYS GNSS DSP jumps to the entry point in EMI DRAM.
   - DSP initializes tracking correlators, RF synthesizer, and opens STP channel 3 (`GPS_TASK_INDX`).

---

## 5. Serial Transport Protocol (STP) Stream & NMEA Commands

Communication between the Linux host and the GNSS receiver occurs over **STP Task Index 3** exposed as **`/dev/stpgps`**:

### Standard NMEA 0183 Output Sentences
The receiver continuously streams standard positioning sentences:
- **`$GPGGA` / `$GNGGA`:** Global Positioning System Fix Data (Time, Latitude, Longitude, Fix Quality, Satellites Tracked, Altitude, HDOP).
- **`$GPRMC` / `$GNRMC`:** Recommended Minimum Specific GPS/TRANSIT Data (Speed over ground, True Course, Date, Magnetic Variation).
- **`$GPGSV` / `$GLGSV` / `$BDGSV` / `$GAGSV`:** Satellites in View (Azimuth, Elevation, SNR per satellite across GPS, GLONASS, BeiDou, Galileo).
- **`$GPGSA` / `$GNGSA`:** GPS DOP and Active Satellites (Fix mode 2D/3D, PDOP, HDOP, VDOP).
- **`$GPVTG` / `$GNVTG`:** Course Over Ground and Ground Speed.

### Proprietary PMTK Command Interface
The host configures receiver operational modes using standard MediaTek **`$PMTK`** packet commands:
- **Hot Restart:** `$PMTK101*32<CR><LF>`
- **Warm Restart:** `$PMTK102*31<CR><LF>`
- **Cold Restart:** `$PMTK103*30<CR><LF>`
- **Full Cold Reset (Clear NVRAM):** `$PMTK104*37<CR><LF>`
- **Set Output NMEA Sentence Intervals:** `$PMTK314,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0*28<CR><LF>`
- **Set Fix Update Rate to 5 Hz:** `$PMTK220,200*2C<CR><LF>` (200 ms interval)
- **Set Fix Update Rate to 10 Hz:** `$PMTK220,100*2F<CR><LF>` (100 ms interval)
- **Enable DGPS / SBAS:** `$PMTK301,2*2E<CR><LF>`
- **Enable Multi-GNSS Constellations (GPS + GLONASS + Galileo):** `$PMTK353,1,1,1,0,0*2A<CR><LF>`

---

## 6. Assisted GPS (A-GPS) & Extended Prediction Orbit (EPO)

To achieve instantaneous $< 1\text{ s}$ satellite locks without waiting 30 seconds for satellite broadcast ephemeris download:

1. **MediaTek EPO Service:**
   - Downloads 7-day or 14-day predicted satellite orbit files (`EPO.DAT` / `EPO.MD5`) from MediaTek EPO servers over HTTP/HTTPS:
     `http://epodownload.mediatek.com/EPO.DAT`
2. **EPO Injection Protocol:**
   - Host splits `EPO.DAT` into binary segments and pushes them across `/dev/stpgps` using PMTK binary packets (`$PMTK722...`).
   - Co-processor loads orbital ephemeris directly into DSP correlation memory.
3. **Reference Time & Location Injection:**
   - Inject approximate cellular / Wi-Fi position via `$PMTK740,lat,lon,alt,YYYY,MM,DD,hh,mm,ss*...` for instant hot-start satellite acquisition.

---

## 7. Mainline Linux & NixOS Userspace Architecture

The GNSS receiver integrates cleanly with the standard open-source Linux location stack:

```
┌─────────────────────────────────────────────────────────────┐
│                 NixOS Desktop Applications                  │
│       (GNOME Maps, Pure Maps, FoxtrotGPS, Browser Geo)      │
└──────────────────────────────┬──────────────────────────────┘
                               │ D-Bus: org.freedesktop.GeoClue2
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Geoclue2 Service                        │
└──────────────────────────────┬──────────────────────────────┘
                               │ D-Bus / Socket
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     gpsd GPS Daemon                         │
│  - Listens on `/dev/stpgps` at 115200 baud                  │
│  - Decodes NMEA 0183 & PMTK binary responses                │
│  - Exports GPSD JSON protocol on port 2947                  │
└──────────────────────────────┬──────────────────────────────┘
                               │ Character I/O
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              Kernel Driver: /dev/stpgps                     │
└─────────────────────────────────────────────────────────────┘
```

### Automatic A-GPS / EPO Download Service (Systemd Unit)
A lightweight background service can periodically refresh `EPO.DAT` when Wi-Fi/LTE is connected:
```sh
# Fetch updated 14-day orbital data
curl -s -o /var/cache/gps/EPO.DAT http://epodownload.mediatek.com/EPO.DAT
# Inject into GNSS co-processor
cat /var/cache/gps/EPO.DAT > /dev/stpgps
```
