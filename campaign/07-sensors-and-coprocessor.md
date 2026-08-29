# Chapter 07: Sensors & Co-Processor (LSM6DS3, ALS/PS, SCP)

## 1. Sensor Inventory & Hardware Wiring

The Gemini PDA contains an array of mobile sensors connected across the `I2C1` peripheral bus and dedicated interrupt lines:

| Sensor Type | Chipset / Model | Bus / Interface | 7-bit I2C Addr | Interrupt Pin / EINT | Function |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **6-Axis IMU** | STMicroelectronics **LSM6DS3** | `I2C1` (`0x11008000`) | `0x6A` (or `0x68`) | `GPIO65` (Gyro IRQ) | 3-axis Accelerometer + 3-axis Gyroscope |
| **Ambient Light & Proximity**| Sensortek **STK3X1X** | `I2C1` (`0x11008000`) | `0x48` | `GPIO88` (`EINT11`) | Screen auto-brightness & face proximity |
| **Magnetometer** | Memsic **MMC3530** | `I2C1` (`0x11008000`) | `0x30` | Polling / I2C | 3-axis Electronic Compass |
| **Barometer** | Bosch **BMP280** | `I2C1` (`0x11008000`) | `0x77` | Polling / I2C | Atmospheric Pressure & Altimeter |
| **Humidity** | STMicroelectronics **HTS221** | `I2C1` (`0x11008000`) | `0x5F` | Polling / I2C | Relative Humidity & Ambient Temperature |
| **Hall / Lid Sensor** | Magnetic Reed Switch | Internal GPIO | N/A | `GPIO66` (`EINT`) | Clamshell open / close detection |

---

## 2. Hall Effect Clamshell Lid Sensor & Keypad Interlock

The clamshell lid switch has a direct inter-driver notifier connection to the keyboard controller in the vendor kernel (`drivers/input/hall/hall.c`):

- **Hardware Pin:** `GPIO66` (`PINMUX_GPIO66__FUNC_GPIO66`, internal pull-up enabled).
- **Interlock Functionality:**
  - When the clamshell is open: Keypad matrix scanning is active; screen is awake.
  - When the clamshell is closed: Notifier (`hall_notifier_call_chain`) notifies the `aw9523` keyboard driver to suspend matrix scanning, preventing ghost key presses in pockets or bags.
- **Mainline Linux Driver:**
  - Standard upstream `gpio-keys` driver reporting `SW_LID` (`EV_SW` event code 0).
  - Systemd / Logind natively handles suspend-to-RAM on lid close and wakeup on lid open.

### Device Tree Node for Lid Switch
```dts
gpio-keys {
    compatible = "gpio-keys";
    pinctrl-names = "default";
    pinctrl-0 = <&hall_pins_default>;

    lid-switch {
        label = "Lid Switch";
        gpios = <&gpio 66 GPIO_ACTIVE_LOW>;
        linux,input-type = <5>; /* EV_SW */
        linux,code = <0>;       /* SW_LID */
        wakeup-source;
        debounce-interval = <50>;
    };
};
```

---

## 3. 6-Axis IMU (LSM6DS3) via Mainline IIO

The **LSM6DS3** is fully supported in mainline Linux via the **`st_lsm6dsx`** Industrial I/O (IIO) driver:

- **Mainline Driver:** `drivers/iio/imu/st_lsm6dsx/st_lsm6dsx_i2c.c`.
- **Features:** Hardware FIFO buffer, freefall detection, tilt detection, step counter.

### Device Tree Node
```dts
&i2c1 {
    status = "okay";
    clock-frequency = <400000>;

    imu@6a {
        compatible = "st,lsm6ds3", "st,lsm6dsx";
        reg = <0x6a>;
        interrupt-parent = <&pio>;
        interrupts = <65 IRQ_TYPE_EDGE_RISING>;
        vdd-supply = <&mt6351_vio18_reg>;
        vddio-supply = <&mt6351_vio18_reg>;
        mount-matrix = "0", "1", "0",
                      "-1", "0", "0",
                       "0", "0", "1";
    };

    light-sensor@48 {
        compatible = "sensortek,stk3310", "sensortek,stk3x1x";
        reg = <0x48>;
        interrupt-parent = <&pio>;
        interrupts = <88 IRQ_TYPE_EDGE_FALLING>;
        vdd-supply = <&mt6351_vio18_reg>;
    };

    pressure-sensor@77 {
        compatible = "bosch,bmp280";
        reg = <0x77>;
        vdda-supply = <&mt6351_vio18_reg>;
        vddd-supply = <&mt6351_vio18_reg>;
    };

    humidity-sensor@5f {
        compatible = "st,hts221";
        reg = <0x5f>;
        vdd-supply = <&mt6351_vio18_reg>;
    };
};
```

---

## 4. Sensor Co-Processor (SCP Cortex-M4) Architecture

The MT6797 includes an embedded **ARM Cortex-M4** Sensor Co-Processor (SCP) at `0x10020000`:

- **Memory Map:**
  - SRAM Base: `0x10020000` (length `0x80000` = 512 KB dedicated SRAM).
  - Config Registers: `0x100a0000` (length `0x1000`).
  - Clock Control: `0x100a4000` (length `0x1000`).
- **Interrupt:** `GIC_SPI 199 IRQ_TYPE_LEVEL_HIGH`.
- **Partitions:** `p17` (`scp1`), `p18` (`scp2`) raw eMMC partitions (2 MB each).
- **Mainline Status:**
  - Direct Linux I2C/IIO drivers provide complete, low-latency sensor access without requiring proprietary SCP binary firmware.
