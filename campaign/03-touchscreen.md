# Touchscreen

Status: SOURCE EXISTS; GENERIC UPSTREAM Novatek driver EXISTS; MT6797
APPLICABILITY **not established for the touch bus**; DT ENABLED **NO**;
DEVICE-TESTED **UNKNOWN**.

Current mainline contains `novatek-nvt-ts.c` and an `novatek,nt36672a-ts`
match, but that is a protocol/driver match, not a Gemini panel identity proof
(`/home/grw/src/linux-gemini-push/drivers/input/touchscreen/novatek-nvt-ts.c:317-330`). No Gemini touch node is present in the mainline board DT.

The vendor DTS records an I2C touch device with reset GPIO68 and interrupt GPIO85
and sets a five-point property (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/aeon6797_6m_n.dts:579-638`). It does not prove the exact controller revision, rail timing, firmware requirement, or coordinate transform. Claims of autonomous ROM boot and 100% probe reliability are removed.

Next validation: identify the controller over the correct I2C bus without
writing unknown registers; verify VTOUCH, reset timing, IRQ polarity, and a
physical coordinate stream. Record the exact DT and dmesg.
