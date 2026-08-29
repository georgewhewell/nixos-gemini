# Chapter 04: Audio Subsystem (AFE, MT6351 Codec, AW8736 Amps)

## 1. Hardware Architecture & Signal Routing

The Planet Computers Gemini PDA audio topology consists of a dedicated SoC Audio Front End (AFE), an MT6351 PMIC integrated codec, dual external speaker amplifiers, and hardware jack detection:

```
┌─────────────────────────────────────────────────────────────┐
│                 MediaTek MT6797 SoC                         │
│                                                             │
│   AFE (Audio Front End) at 0x11220000 (IRQ: GIC SPI 151)    │
│   - Internal Audio SRAM: 0x11221000 (48 KB DMA Buffer)      │
│   - DL1 / DL2 / DL3 Playback DAIs                           │
│   - VUL1 / VUL2 / AWB Capture DAIs                          │
│   - Interconnect Matrix (AFE_CONN0 - AFE_CONN29)            │
│   - Digital Bus to PMIC: GPIO 146 (CLK), 147 (MISO), 148 (MOSI)
└──────────────────────────────┬──────────────────────────────┘
                               │ Digital Audio Bus
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 MediaTek MT6351 PMIC                        │
│                                                             │
│   Integrated Audio Codec (Regmap over PWRAP)                │
│   - Stereo 24-bit DACs & ADCs                               │
│   - True-Ground Class-G Headphone Amp (+1.6V LDO / -1.6V NCP)│
│   - Differential Line-Out Pins (AU_LOLP / AU_LOLN)          │
│   - Preamps & PGAs: PGA1 (AIN0 / AIN1), PGA2 (AIN2)         │
│   - Mic Biases: MICBIAS0 (1.9V), MICBIAS1 (Headset), MICBIAS2
│   - ACCDET Headset Detection on PMIC EINT 6                 │
└──────────────┬──────────────────────────────┬───────────────┘
               │ Lineout L / Lineout R        │ HPL / HPR / AIN1
               ▼                              ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│   Dual Awinic AW8736 Amps    │ │   3.5mm Headset Jack       │
│   - Left Amp EN: GPIO 243    │ │   - Headphone EN: GPIO 234 │
│   - Right Amp EN: GPIO 244   │ │   - Headphone CS: GPIO 235 │
│   - 1-wire pulse / 0.8W Mode │ │   - Headset Mic: AIN1      │
└──────────────┬───────────────┘ └────────────────────────────┘
               ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│   Stereo Internal Speakers   │ │   Microphone Array         │
│   - Left Speaker Transducer  │ │   - Main Mic 1: AIN0       │
│   - Right Speaker Transducer │ │   - Headset Mic: AIN1      │
│                              │ │   - Noise Canc Mic: AIN2   │
│                              │ │   - Digital Mic: GPIO 147/149
└──────────────────────────────┘ └────────────────────────────┘
```

### Hardware Inventory & Pin Mapping

| Component | Function | Bus / Base Address | Control Signals / GPIOs |
| :--- | :--- | :--- | :--- |
| **MT6797 AFE** | SoC Audio DSP & DMA | `0x11220000` (SRAM: `0x11221000`) | GIC SPI 151 (`AFE_MCU_IRQ`) |
| **MT6351 Audio** | Codec DAC/ADC/PGA | PMIC Regmap (`0x2000` & `0x0CF2`–`0x0D28`) | Internal PWRAP Interface |
| **Left Speaker Amp** | Awinic AW8736 (Left) | Differential Lineout L | `GPIO243` (`aud_pins_hpdepop_high`) |
| **Right Speaker Amp**| Awinic AW8736 (Right)| Differential Lineout R | `GPIO244` (`aud_pins_hpdepop_high_e2`) |
| **Headphone Enable** | External HP Switch | Headphone L/R | `GPIO234` (`aud_pins_headphone_en`) |
| **Headphone CS** | External HP Select | Headphone L/R | `GPIO235` (`aud_pins_headphone_cs`) |
| **ACCDET Jack Detect**| Jack insertion & Remote | AuxADC Channel 1 | PMIC `EINT6` (Debounce: 256 ms) |
| **Main Mic** | Primary speech capture | Analog differential to PMIC | `AIN0` (biased by `MICBIAS0` 1.9V) |
| **Headset Mic** | 3.5mm jack mic | Analog single-ended to PMIC | `AIN1` (biased by `MICBIAS1`) |
| **Ref / Sub Mic** | Noise-cancellation mic | Analog differential to PMIC | `AIN2` (biased by `MICBIAS2`) |
| **Digital Mic (DMIC)**| Voice-on-Wakeup (VOW) | MIPI / PDM Serial Bus | `GPIO147` (`VOW_DAT`) / `GPIO149` (`VOW_CLK`) |

---

## 2. Dual External Speaker Amplifiers (AW8736)

The Gemini PDA features **stereo external speakers** driven by two discrete **Awinic AW8736** Class-G / Class-K audio amplifiers:

- **Power Rails:** Directly powered from VBAT with internal high-voltage boost charge pumps.
- **Control Interface:**
  - Left Speaker Enable: `GPIO243` (`PINMUX_GPIO243__FUNC_GPIO243`).
  - Right Speaker Enable: `GPIO244` (`PINMUX_GPIO244__FUNC_GPIO244`).
- **Mode Switching (1-Wire Pulse Mode):**
  - Sending 3 consecutive 2 µs pulses (`High (2µs) -> Low (2µs) -> High (2µs) -> Low (2µs) -> High`) configures Mode 3 (0.8W continuous power).

---

## 3. Headset Detection & Button Detection (ACCDET)

The 3.5mm audio jack detection is managed by the MT6351 PMIC ACCDET module:

- **Interrupt:** Connected to PMIC External Interrupt `EINT 6` with a 256 ms debounce window.
- **Detection State Machine (`ACCDET_STATE_RG`):**
  - `AB = 00`: 3-pole Headphone (no mic) or Hook switch active.
  - `AB = 01`: 4-pole Headset (TRRS CTIA/OMTP with active microphone line).
  - `AB = 11`: Jack unplugged (`PLUG_OUT`).
- **Inline Remote Button Voltage Thresholds (via PMIC AuxADC Ch 1):**
  - `< 90 mV`: **Play / Pause / Call Hook** (`KEY_PLAYPAUSE` / `KEY_MEDIA`).
  - `90 mV – 240 mV`: **Volume Down** (`KEY_VOLUMEDOWN`).
  - `240 mV – 450 mV`: **Volume Up** (`KEY_VOLUMEUP`).
  - `450 mV – 800 mV`: **Voice Command** (`KEY_VOICECOMMAND`).

---

## 4. Mainline Implementation Roadmap

### Step 1: ASoC MT6797 Platform Driver (`sound/soc/mediatek/mt6797/mt6797-afe.c`)
- Implement using the modern `mtk-afe-platform-driver.c` framework.
- Define PCM DAIs: `DL1` (System playback), `DL2` (Notification), `VUL1` (Main capture), `VUL2` (Reference capture).
- Declare input/output clock mapping (`topckgen`, `infracfg`, `apll1`, `apll2`).

### Step 2: MT6351 PMIC Codec Driver (`sound/soc/codecs/mt6351.c`)
- Modeled alongside upstream `mt6358.c` / `mt6359.c`.
- Regmap-backed DAPM widgets:
  - DACs & ADCs: `DAC L`, `DAC R`, `ADC 1` (Main/Headset), `ADC 2` (Ref Mic).
  - Outputs: `Headphone L/R`, `Lineout L/R`, `Receiver`.
  - Inputs: `AIN0` (Main Mic), `AIN1` (Headset Mic), `AIN2` (Noise Cancelling Mic).
  - Biases: `MICBIAS0`, `MICBIAS1`, `MICBIAS2`.
- Export `snd_soc_jack` reports for jack insertion and inline button events.

### Step 3: Gemini Machine Driver & Device Tree
```dts
sound {
    compatible = "mediatek,mt6797-gemini-audio";
    mediatek,platform = <&audiosys>;
    mediatek,audio-codec = <&mt6351_codec>;
    pinctrl-names = "default";
    pinctrl-0 = <&aud_pins_default>;

    left-spk-amp = <&amp_left>;
    right-spk-amp = <&amp_right>;
    headphone-en-gpios = <&gpio 234 GPIO_ACTIVE_HIGH>;
    headphone-cs-gpios = <&gpio 235 GPIO_ACTIVE_HIGH>;

    audio-routing =
        "Headphone", "HP L",
        "Headphone", "HP R",
        "Left Amp", "Lineout L",
        "Right Amp", "Lineout R",
        "Left Speaker", "Left Amp",
        "Right Speaker", "Right Amp",
        "PGA1", "AIN0",
        "PGA2", "AIN2";
};

amp_left: speaker-amp-left {
    compatible = "simple-audio-amplifier";
    enable-gpios = <&gpio 243 GPIO_ACTIVE_HIGH>;
    VCC-supply = <&vbat>;
};

amp_right: speaker-amp-right {
    compatible = "simple-audio-amplifier";
    enable-gpios = <&gpio 244 GPIO_ACTIVE_HIGH>;
    VCC-supply = <&vbat>;
};
```

### Step 4: ALSA UCM2 Profiles
Create `/etc/alsa/ucm2/Planet-Gemini-PDA/`:
- `HiFi.conf`:
  - `Speaker`: Asserts GPIO 243 and 244, routes DAC to Lineout L/R.
  - `Headphones`: Asserts GPIO 234, routes DAC to Class-G Headphone L/R.
  - `InternalMic`: Enables `MICBIAS0` and `AIN0` preamp.
  - `HeadsetMic`: Enables `MICBIAS1` and `AIN1` preamp.
- Jack detection dynamically triggers PipeWire route switching between Speaker and Headphones.
