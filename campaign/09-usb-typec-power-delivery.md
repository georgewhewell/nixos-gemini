# Chapter 09: USB Subsystem, Type-C & Power Delivery

## 1. Dual Type-C Architecture

The Gemini PDA features two physical USB Type-C ports with distinct hardware topologies:

```
┌─────────────────────────────────────────────────────────────┐
│                 Left USB Type-C Port                        │
│                 (Flashing / Power / OTG / Gadget)           │
└──────────────┬──────────────────────────────┬───────────────┘
               │ Data Bus                     │ Power / CC
               ▼                              ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│   MediaTek MTU3 / SSUSB      │ │   TI BQ25890 Charger       │
│   (0x11270000 / 0x11280000)  │ │   - Primary Fast Charging  │
│   - USB 3.0 xHCI Host        │ │   - Flash Tool Download    │
│   - Legacy Android Gadget /  │ │   - 5V OTG Boost Supply    │
│     Mainline MUSB UDC        │ └────────────────────────────┘
└──────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 Right USB Type-C Port                       │
│                 (Host Expansion / Networking / UART)        │
└──────────────┬──────────────────────────────┬───────────────┘
               │ Data Bus                     │ Power / CC
               ▼                              ▼
┌──────────────────────────────┐ ┌────────────────────────────┐
│   MediaTek MUSB USB 1.1/2.0  │ │   ON Semi FUSB301A Type-C  │
│   Host Controller            │ │   (I2C0 at 0x25)           │
│   (0x11200000, T-PHY 0x11210000)│- CC attach detection     │
│   - Supports RTL8152/8153    │ │   - GPIO94 VBUS switch     │
│     Gigabit Ethernet         │ └────────────────────────────┘
└──────────────────────────────┘
```

---

## 2. Right-Port Host & RTL8152/8153 Gigabit NIC (Recently Validated)

The project's recent changes successfully integrated the right-port host controller into the mainline build:

- **Host Controller Node (`usb@11200000`):**
  - MUSB IP configured in Host-Only mode with PIO transfer fallback.
  - T-PHY at `0x11210000` with `mediatek,force-a-session-valid` property to bypass missing ID-pin interrupt transitions.
- **Type-C Controller (`typec@25` on `i2c0`):**
  - Fairchild / ON Semi **FUSB301A** at `0x25`.
  - Configured as Source role with external VBUS regulator attached via `GPIO94`.
- **Ethernet Support:**
  - Realtek RTL8153 (`0bda:8153`) Gigabit USB Ethernet adapter natively identified and bound by `r8152` driver.

---

## 3. Left-Port Dual-Role & Gadget Mode

The left port provides the primary recovery and debugging interface:

- **SoC Controller:** MediaTek MTU3 (`0x11270000`).
- **Mainline Status:**
  - Configured in Peripheral (Gadget) mode.
  - Exposes USB RNDIS Ethernet network adapter with static IP `10.15.19.82/24`.
  - Serves an interactive Dropbear SSH server on port 22 directly from initramfs and stage-2 NixOS.
- **Future Host Mode on Left Port:**
  - Enabling xHCI USB 3.0 host mode on the left port requires driving the Type-C CC logic via FUSB302 / MT6351 CC detection to switch VBUS direction safely without shorting external power supplies.
