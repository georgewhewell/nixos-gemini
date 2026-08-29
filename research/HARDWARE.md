# Planet Computers Gemini PDA - Hardware Documentation

## Overview

The Gemini PDA is a clamshell smartphone/PDA with a full QWERTY keyboard, manufactured by Planet Computers. This device runs a hybrid Linux/Android stack using libhybris for hardware abstraction.

## System-on-Chip

| Property | Value |
|----------|-------|
| Model | MediaTek MT6797X (Helio X27) |
| Architecture | ARMv8-A (AArch64) |
| CPU Cores | 10 total (deca-core) |
| - Cortex-A72 | 2 cores (big) |
| - Cortex-A53 | 4 cores (medium) |
| - Cortex-A35 | 4 cores (little) |
| GPU | Mali-T880 MP4 @ 900MHz |
| Process | 20nm |

## Memory

| Property | Value |
|----------|-------|
| RAM | 4 GB (3.7 GB usable by Linux) |
| Type | LPDDR3 |

## Storage

| Property | Value |
|----------|-------|
| Type | eMMC 5.1 |
| Capacity | 64 GB (58 GB usable) |
| Controller | MSDC (MediaTek SD Controller) |
| Address | 0x11230000 |
| Interrupt | GIC SPI 79 |

### Partition Layout

| Partition | Label | Size | Mount Point | Purpose |
|-----------|-------|------|-------------|---------|
| p1 | recovery | 16 MB | - | Android recovery |
| p5 | nvcfg | 8 MB | /nvcfg | NV config |
| p6 | nvdata | 32 MB | /nvdata | NV data |
| p8 | protect1 | 8 MB | (Android) | Protected storage |
| p9 | protect2 | 12 MB | (Android) | Protected storage |
| p13 | md1img | 24 MB | - | Modem firmware |
| p14 | md1dsp | 4 MB | - | Modem DSP |
| p15 | md1arm7 | 3 MB | - | Modem ARM7 |
| p16 | md3img | 5 MB | - | Modem 3 |
| p17-18 | scp1/scp2 | 2 MB | - | Sensor co-processor |
| p20-21 | lk/lk2 | 1 MB | - | Little Kernel bootloader |
| p22 | boot | 16 MB | - | Default Android boot image |
| p23 | logo | 8 MB | - | Boot logo |
| p24-25 | tee1/tee2 | 10 MB | - | TrustZone TEE |
| p27 | system | 2.5 GB | /system (loop) | Android system |
| p28 | cache | 432 MB | /cache | Android cache |
| **p29** | **linux** | **39.5 GB** | **/** | **Gemian root and NixOS persistent state** |
| p30 | boot2 | 16 MB | - | Side-button Gemian boot slot |
| p31 | boot3 | 16 MB | - | Alternate Gemian boot slot |
| p32 | userdata | 15.6 GB | - | Android userdata |

### eMMC write protection

The DF4064 eMMC uses the legacy CSD write-protect group definition at runtime:
1024 sectors per erase group times 16 erase groups gives an 8 MiB write-protect
group. LK applies power-on protection to groups 15 through 27, exactly sectors
245760 through 458751 (p10 through p26). This includes every sector of p22.

The live vendor kernel reports `R1_WP_VIOLATION` when p22 is written, then its
MediaTek command-queue path incorrectly clears the request error. Consequently
`dd` can exit successfully while readback remains unchanged. p22 must be
updated through the pre-boot MediaTek download path, not from running Gemian.

## Display

| Property | Value |
|----------|-------|
| Panel | NT36672 / SSD2092 |
| Resolution | 2160 x 1080 (18:9) |
| Size | 6 inches |
| Type | IPS LCD |
| Driver | mtkfb (MediaTek framebuffer) |
| Framebuffer | /dev/fb0 |
| Reserved Memory | 0x7dfb0000 - 0x7ff3ffff (~31 MB) |

Note: Display requires MediaTek-specific mtkfb driver. No mainline DRM/KMS support. `CONFIG_FB_SIMPLE` is not enabled in vendor kernel.

## USB

| Property | Value |
|----------|-------|
| Left Type-C | MTU3 at `0x11270000`, used as the mainline gadget/debug port |
| Right Type-C | USB11 MUSB at `0x11200000`, T-PHY at `0x11210000` |
| Right Type-C controller | FUSB301A on I2C0 address `0x25`, GPIO64/EINT3 |
| Right VBUS/route | GPIO94 VBUS; GPIO70 high, GPIO71 low, GPIO72 high |
| Mainline right-port speed | USB 2.0 high speed (480 Mb/s signalling) |

### USB Modes
- Host mode (via MTU3/XHCI)
- Device/Gadget mode (via MUSB)
- USB-C Power Delivery supported

The vendor kernel's left-port device mode uses the legacy Android USB gadget
interface at `/sys/class/android_usb/android0`; its known-good RNDIS identity
is `0fce:7169`. Mainline instead uses MTU3 gadget Ethernet on that port as an
independent recovery link.

The mainline right-port path was proven live on 2026-08-29 with an RTL8156
adapter (`0bda:8156`) bound to `r8152`. The FUSB301 reported source/host, VBUS
was enabled, `rtl_nic/rtl8156b-2.fw` loaded, Ethernet negotiated 1 Gb/s full
duplex, and DHCP plus direct SSH succeeded. MUSB currently uses PIO transfers;
iperf3 measured 70.2 Mb/s device-to-trex and 57.8 Mb/s in reverse. The Ethernet
PHY can advertise 2.5 Gb/s, but neither the 1 Gb/s link partner nor this USB
2.0 host path can deliver that rate.

## Kernel execution model

The inspected 3.18.41 configuration has `CONFIG_MODULES` disabled. Wi-Fi, USB,
MMC, filesystems, and the gadget stack are monolithic kernel drivers; there is
no `.ko` set and no module load order. The exact built configuration is kept in
`research/vendor-kernel.config`.

## Serial Console

| Property | Value |
|----------|-------|
| Device | /dev/ttyMT0 |
| Baud Rate | 921600 |
| Settings | 8N1 |
| Address | 0x11002000 |
| Interrupt | GIC SPI 91 |

Additional UARTs available: ttyMT1, ttyMT2, ttyMT3

## Keyboard

| Property | Value |
|----------|-------|
| Type | Physical QWERTY |
| Controller | AW9120 (I2C LED/key controller) |
| Interface | I2C |
| Backlight | Yes (via AW9120 LEDs) |

## Touchscreen

| Property | Value |
|----------|-------|
| Controller | SSD20xx (Novatek compatible) |
| Driver | mtk-tpd |
| Firmware | novatek_ts_fw.bin |
| Interface | I2C |

## Sensors

| Sensor | Controller | Interface |
|--------|------------|-----------|
| Accelerometer | LSM6DS3 | I2C |
| Gyroscope | LSM6DS3 | I2C |
| Ambient Light | m_alsps | I2C |
| Proximity | m_alsps | I2C |

## Audio

| Property | Value |
|----------|-------|
| Codec | MediaTek MT6797 integrated |
| ALSA Card | card0 (mt6797-snd) |
| PCM Devices | 30+ (various routing) |

## Wireless

### WiFi
| Property | Value |
|----------|-------|
| Chip | MT6630 (combo chip) |
| Standards | 802.11 a/b/g/n/ac |
| Driver | Built-in MediaTek `mt-wifi` platform driver |
| Firmware | WIFI_RAM_CODE_6797 |
| Interface | wlan0 |

Kernel probing alone is insufficient. The stock Bionic `wmt_loader` and
`wmt_launcher` helpers complete the MT6797 connectivity handshake. NixOS mounts
Gemian's `data/system.img` read-only for their Android linker/libraries and
passes the canonical uncompressed firmware directory to `wmt_launcher`; no
Android init, framework, or container is started.

### Bluetooth
| Property | Value |
|----------|-------|
| Chip | MT6630 (combo chip) |
| Version | Bluetooth 4.2 |
| Interface | HCI UART (hci0) |
| Manufacturer | MediaTek (70) |

### Cellular Modem
| Property | Value |
|----------|-------|
| Type | Integrated LTE modem |
| Bands | 4G LTE (region dependent) |
| Driver | oFono + ModemManager |
| Firmware | modem_3_3g_n.img (in md1img partition) |
| Interfaces | ccmni0-17 (cellular network) |

## Power

| Property | Value |
|----------|-------|
| Battery | Li-ion |
| Capacity | 4220 mAh |
| Charger IC | BQ25890 (I2C) |
| PMICs | DA9214, FAN53555, FAN49101 |
| Power Supply | /sys/class/power_supply/battery |

## LEDs

| LED | Color | Purpose |
|-----|-------|---------|
| Notification | Red | Alerts |
| Notification | Green | Status |
| LCD Backlight | White | Display |

Controlled via gemian-leds service.

## Boot Process

```
┌─────────────────┐
│   SoC BootROM   │  Fixed in silicon
└────────┬────────┘
         ▼
┌─────────────────┐
│   Preloader     │  mmcblk0boot0/boot1 (~4.8s)
│   (MT6797)      │  Initializes DRAM, loads LK
└────────┬────────┘
         ▼
┌─────────────────┐
│  Little Kernel  │  p20/p21 (lk) (~3.7s)
│   Bootloader    │  Fastboot, boot menu, loads boot.img
└────────┬────────┘
         ▼
┌─────────────────┐
│   boot.img      │  p22 (boot) - ANDROID! format
│ kernel+initramfs│  Gzip-compressed kernel
└────────┬────────┘
         ▼
┌─────────────────┐
│  Linux Kernel   │  3.18.41 (vendor BSP)
│                 │  Boots with root=/dev/ram
└────────┬────────┘
         ▼
┌─────────────────┐
│  Root FS        │  Switches to /dev/mmcblk0p29
│  (Debian/NixOS) │  Starts systemd
└─────────────────┘
```

## boot.img Format

Standard Android boot image with the following parameters:

```
Magic:          ANDROID!
Kernel size:    ~8 MB (gzip compressed)
Kernel addr:    0x40080000
Ramdisk addr:   0x45000000
Tags addr:      0x44000000
Page size:      2048
Base address:   0x40000000
```

### Creating boot.img

```bash
mkbootimg \
  --kernel Image.gz \
  --ramdisk initramfs.cpio.gz \
  --base 0x40000000 \
  --kernel_offset 0x00080000 \
  --ramdisk_offset 0x05000000 \
  --tags_offset 0x04000000 \
  --pagesize 2048 \
  --cmdline "console=ttyMT0,921600n1 root=/dev/mmcblk0p29 rw" \
  -o boot.img
```

## Clock Controllers

| Controller | Address | Phandle | Purpose |
|------------|---------|---------|---------|
| topckgen | 0x10000000 | 0x54 | Top clock generator |
| infracfg_ao | 0x10001000 | 0x02 | Infrastructure clocks |
| pericfg | 0x10003000 | - | Peripheral config |
| apmixed | 0x1000c000 | 0x55 | PLL control |

## Mainline Linux Support

### In Mainline (as of Linux 6.x)
- CPU cores (Cortex-A72, A53)
- GICv3 interrupt controller
- Clock drivers (clk-mt6797.c)
- Pinctrl (pinctrl-mt6797.c)
- UART (mediatek,mt6797-uart)
- I2C (mediatek,mt6797-i2c)
- Watchdog
- Basic device tree (mt6797.dtsi, mt6797-x20-dev.dts)

### Not in Mainline
- Display/DRM (mtkfb is vendor-specific)
- eMMC (needs DT node, driver exists as mtk-sd)
- USB3 (needs DT node, driver exists as mtu3)
- GPU (Mali T880 - no mainline driver)
- WiFi/Bluetooth (MT6630 - proprietary)
- Modem (proprietary)
- Camera
- Audio codec

## Firmware Files

Located in `/var/lib/lxc/android/rootfs/vendor/firmware/`:

| File | Size | Purpose |
|------|------|---------|
| WIFI_RAM_CODE_6797 | 411 KB | WiFi firmware |
| ROMv3_patch_1_0_hdr.bin | 210 KB | ROM patch |
| ROMv3_patch_1_1_hdr.bin | 46 KB | ROM patch |
| modem_3_3g_n.img | 4 MB | Modem firmware |
| mt6631_fm_v1_coeff.bin | 1 KB | FM radio |
| mt6631_fm_v1_patch.bin | 1 KB | FM radio |
| pcm_suspend.bin | 7 KB | Power management |
| pcm_deepidle.bin | 6 KB | Power management |
| pcm_sodi.bin | 6 KB | Power management |
| WMT_SOC.cfg | 80 B | WiFi/BT config |

Touchscreen firmware in `/system/etc/firmware/`:
| File | Size | Purpose |
|------|------|---------|
| novatek_ts_fw.bin | 118 KB | Touch panel |

## References

- [Gemian Project](https://github.com/nickhutchinson/gemini-linux-kernel-3.18)
- [postmarketOS Wiki](https://wiki.postmarketos.org/wiki/Planet_Computers_Gemini_PDA_(planet-geminipda))
- [Mainline MT6797 DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/mediatek/mt6797.dtsi)
