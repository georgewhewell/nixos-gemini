# Chapter 10: Camera & Imaging Subsystem (ISP / MIPI CSI)

## 1. Hardware Overview

The Gemini PDA (when equipped with the optional camera module) includes a front-facing webcam and a rear-facing primary camera:

- **Rear Camera Sensor:** Samsung **S5K4H8** (or OmniVision OV5648) 5MP / 8MP CMOS image sensor.
- **Front Camera Sensor:** Hynix **HI553** / GalaxyCore GC2355 2MP / 5MP front sensor.
- **Physical Interface:** MIPI CSI-2 (Camera Serial Interface, 2 Data Lanes per sensor).
- **SoC Image Signal Processor:** MediaTek **Seninf / CamISP** hardware block (`0x15000000` / `0x15004000`).

---

## 2. Sensor & Bus Connections

| Camera | Sensor IC | I2C Bus | Slave Address | MIPI CSI Port | Power Rails | Reset / PWDN Pins |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Main (Rear)** | Samsung S5K4H8 | `I2C3` | `0x20` (or `0x6c`) | CSI-0 (2 Lanes) | `VCAM_A` (2.8V), `VCAM_D` (1.2V), `VCAM_IO` (1.8V) | `GPIO_CAM_RST0`, `GPIO_CAM_PWDN0` |
| **Sub (Front)** | Hynix HI553 | `I2C3` | `0x51` (or `0x3c`) | CSI-1 (2 Lanes) | `VCAM_A` (2.8V), `VCAM_IO` (1.8V) | `GPIO_CAM_RST1`, `GPIO_CAM_PWDN1` |

---

## 3. Mainline V4L2 / Media Controller Pipeline

In mainline Linux, MediaTek camera pipelines are modeled using the **V4L2 Media Controller** framework:

```
[Camera Sensor (S5K4H8)]
         │ MIPI CSI-2 (2 Lanes)
         ▼
[MediaTek Seninf PHY / Receiver]
         │ Internal AXI / Streaming Interface
         ▼
[MediaTek CamISP / DIP Block]
         │ DMA Output (YUV420 / NV12 / RAW)
         ▼
[/dev/video0 (V4L2 Capture Node)]
```

### Mainline Driver Requirements
1. **Seninf Driver:** `drivers/media/platform/mediatek/isp/seninf/` (handles CSI-2 PHY calibration and lane routing).
2. **CamISP Driver:** `drivers/media/platform/mediatek/isp/mtk_isp.c` (configures DMA engine and pixel format conversion).
3. **V4L2 Sensor Subdevice:** Standard upstream `drivers/media/i2c/s5k4h8.c` and `ov5648.c`.
4. **Userspace Framework:** **`libcamera`** with MediaTek pipeline handler for 3A (Auto-Exposure, Auto-White-Balance, Auto-Focus) processing.
