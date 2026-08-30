# Storage: eMMC and MicroSD

Status: GENERIC UPSTREAM MediaTek MMC driver EXISTS; MT6797 APPLICABILITY
PROVEN; MMC0 DT ENABLED at a conservative speed; eMMC DEVICE-TESTED in the
recorded baseline; HS200/HS400 and MicroSD **UNKNOWN**.

The current DT has `mediatek,mt6797-mmc` matches for MMC0 at `0x11230000`/SPI79
and MMC1 at `0x11240000`/SPI80
(`/home/grw/src/linux-gemini-push/arch/arm64/boot/dts/mediatek/mt6797.dtsi:804-824`); `mtk-sd.c:733` selects the MT6797 variant. The Gemini board enables only MMC0, 8-bit, 25 MHz, non-removable (`mt6797-gemini-pda.dts:277-289`).

`research/MAINLINE.md`, `research/BOOT_PROBE.md`, and the read-only 2026-08-30
snapshot in `research/HARDWARE_TEST_LEDGER.md` record eMMC access, the p29
read-only root/store path, and boot-partition identities. They do not prove
high-speed timing, tuning, write safety, SD-card detection, or card voltage
switching. The old HS200/HS400 and SDR104 acceptance logs are removed.

Next validation: keep p31 as recovery; test MMC0 read-only first, then one
controlled write to the development slot. Add MMC1 only with verified pins,
card-detect and rail levels. Retune/high-speed tests require repeated cold and
temperature-controlled captures.
