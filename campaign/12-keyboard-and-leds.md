# Chapter 12: Keyboard Matrix & Notification LEDs

## 1. Physical Clamshell Keyboard Matrix (AW9523)

The defining hardware component of the Planet Computers Gemini PDA is its full mechanical tactile QWERTY keyboard:

- **Matrix Controller:** **Awinic AW9523** (or AW9120) 16-channel I2C GPIO expander.
- **I2C Slave Address:** **`0x58`** (Write `0xB0`, Read `0xB1`).
- **Pinctrl & Hardware Control Lines:**
  - Hardware Reset / Shutdown: `GPIO58` (`PINMUX_GPIO58__FUNC_GPIO58`).
  - Matrix Interrupt: `GPIO87` (`PINMUX_GPIO87__FUNC_EINT10`, `EINT 10`, internal pull-up enabled).
- **Matrix Dimension:** 8 Rows $\times$ 7 Columns matrix scanning all 56 physical keys:
  - Rows (Inputs): Port 0 pins `P0_0` through `P0_7` (`#define P0_KROW_MASK 0xff`).
  - Columns (Outputs): Port 1 pins `P1_0` through `P1_6` (`#define P1_KCOL_MASK 0x7f`).

```
          Columns 0..6 (Driven by AW9523 Port 1 Outputs)
               │   │   │   │   │   │   │
Rows 0..7  ────┼───┼───┼───┼───┼───┼───┤ (Sensed Inputs on AW9523 Port 0)
               │[1] [2] [3] [4] [5] [6] [7]
               │[U] [W] [Y] [T] [E] [Q] [R]
               │[S] [D] [Tab][F] [G] [A] [H]
               │[Z] [C] [N] [X] [V] [B] [Shift-L]
               │[,] [Alt-L][M][Fn][Space][.?][Ctrl]
               │['] [Left][Down][Shift-R][Up][Right][L]
               │[8] [9] [Del] [P]  [O]  [Enter][0]
               │[J] [K] [I]  -   -    -    -
```

### Complete 56-Key Mapping Array (`aw9523_key.c:130-194`)
- **Col 0:** `KEY_1`, `KEY_U`, `KEY_S`, `KEY_Z`, `KEY_COMMA`, `KEY_APOSTROPHE`, `KEY_8`, `KEY_J`
- **Col 1:** `KEY_2`, `KEY_W`, `KEY_D`, `KEY_C`, `KEY_LEFTALT`, `KEY_LEFT`, `KEY_9`, `KEY_K`
- **Col 2:** `KEY_3`, `KEY_Y`, `KEY_TAB`, `KEY_N`, `KEY_M`, `KEY_DOWN`, `KEY_BACKSPACE`, `KEY_I`
- **Col 3:** `KEY_4`, `KEY_T`, `KEY_F`, `KEY_X`, `KEY_LEFTMETA` (Fn), `KEY_RIGHTSHIFT`, `KEY_P`
- **Col 4:** `KEY_5`, `KEY_E`, `KEY_G`, `KEY_V`, `KEY_SPACE`, `KEY_UP`, `KEY_O`
- **Col 5:** `KEY_6`, `KEY_Q`, `KEY_A`, `KEY_B`, `KEY_DOT`, `KEY_RIGHT`, `KEY_ENTER`
- **Col 6:** `KEY_7`, `KEY_R`, `KEY_H`, `KEY_LEFTSHIFT`, `KEY_LEFTCTRL`, `KEY_L`, `KEY_0`

### Clamshell Lid Interlock
The keyboard driver subscribes to the Hall lid sensor (`hall_register_client`). When the clamshell lid closes, keypad scanning is suspended to avoid accidental ghost key presses in pockets or bags.

---

## 2. Keyboard Backlight (AW9120)

- **Controller IC:** Awinic **AW9120** (Chip ID `0xB223` at register `0x00`).
- **Power Down / Enable Pin:** `GPIO245` (`PINMUX_GPIO245__FUNC_GPIO245`, `aw_pdn_high` / `aw_pdn_low`).
- **Features:** 256 constant-current PWM steps, breathing light effect generator (`aw9120_led_breath`).
- **Mainline Implementation:** Exposed via `/sys/class/leds/keyboard-backlight/` for desktop environment brightness control.

---

## 3. Notification & Indicator LEDs

The Gemini PDA features dual-color notification LEDs on the outer chassis:

| LED Node | DTS Target | Color / Function | Driver Control / Data |
| :--- | :--- | :--- | :--- |
| `led0` | `led@0` (`aeon6797_6m_n.dts:155`) | Red (Alerts / Low Battery) | `compatible = "mediatek,red"`, `data = <1>` |
| `led1` | `led@1` (`aeon6797_6m_n.dts:168`) | Green (Status / Charging) | `compatible = "mediatek,green"`, `data = <2>` |
| `led6` | `led@6` (`aeon6797_6m_n.dts:181`) | LCD Backlight PWM | `compatible = "mediatek,lcd-backlight"`, `data = <5>` |

### Mainline Device Tree Integration
```dts
&i2c5 {
    status = "okay";

    aw9523: gpio-expander@58 {
        compatible = "awinic,aw9523";
        reg = <0x58>;
        interrupt-parent = <&pio>;
        interrupts = <87 IRQ_TYPE_EDGE_FALLING>;
        reset-gpios = <&gpio 58 GPIO_ACTIVE_LOW>;
        #gpio-cells = <2>;
        gpio-controller;
    };
};

matrix_keypad: keypad {
    compatible = "gpio-matrix-keypad";
    row-gpios = <&aw9523 0 GPIO_ACTIVE_HIGH>,
                <&aw9523 1 GPIO_ACTIVE_HIGH>,
                <&aw9523 2 GPIO_ACTIVE_HIGH>,
                <&aw9523 3 GPIO_ACTIVE_HIGH>,
                <&aw9523 4 GPIO_ACTIVE_HIGH>,
                <&aw9523 5 GPIO_ACTIVE_HIGH>,
                <&aw9523 6 GPIO_ACTIVE_HIGH>,
                <&aw9523 7 GPIO_ACTIVE_HIGH>;
    col-gpios = <&aw9523 8 GPIO_ACTIVE_HIGH>,
                <&aw9523 9 GPIO_ACTIVE_HIGH>,
                <&aw9523 10 GPIO_ACTIVE_HIGH>,
                <&aw9523 11 GPIO_ACTIVE_HIGH>,
                <&aw9523 12 GPIO_ACTIVE_HIGH>,
                <&aw9523 13 GPIO_ACTIVE_HIGH>,
                <&aw9523 14 GPIO_ACTIVE_HIGH>;
    debounce-delay-ms = <5>;
    col-scan-delay-us = <2>;
    wakeup-source;
};
```
