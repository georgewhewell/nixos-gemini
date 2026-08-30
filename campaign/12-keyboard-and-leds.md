# Keyboard, notification LEDs and camera flash

Status: keyboard is BOUND-UNVERIFIED; LEDs and camera flash are MISSING.

The current full Stage2 runtime has keyboard-matrix input/event0 and dmesg
reports polling mode at 20 ms. No physical key press/release is retained for
this image. The current board source describes the AW9523 8x7 matrix and keeps
the base consumers disabled (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:468-586); the reviewed
polling overlay enables 400 kHz I2C5, 20 ms polling, and 2 us settling
(linux-gemini-platform@28c471502:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-keyboard.dtso:32-55).

No /sys/class/leds entries exist in the live image. AW9120, notification LED,
flash, camera, and sensor paths remain outside the keyboard overlay's scope.

Next gate: capture a bounded retained press/release subset. Do not enable the
AW9523 IRQ domain or light output without separate electrical evidence.
