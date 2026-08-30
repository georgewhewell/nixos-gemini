# Audio, AFE and codecs

Status: SOURCE EXISTS; GENERIC UPSTREAM DRIVER EXISTS; MT6797 APPLICABILITY
PROVEN for AFE and the MT6351 machine-driver interfaces; DT ENABLED **NO**;
DEVICE-TESTED **UNKNOWN**.

The current tree contains the MT6797 AFE PCM/clock/DAI files and the
`mt6797-mt6351` machine driver. Their compatibles are `mediatek,mt6797-audio`
and `mediatek,mt6797-mt6351-sound`
(`/home/grw/src/linux-gemini-push/sound/soc/mediatek/mt6797/mt6797-afe-pcm.c:869-878`; `mt6797-mt6351.c:232-240`). The shared MT6797 DT declares the AFE resources but leaves the controller disabled (`arch/arm64/boot/dts/mediatek/mt6797.dtsi:400-422`).

The vendor tree contains board GPIO descriptions and legacy AW8736 pulse code
(`/home/grw/src/gemini-linux-kernel-3.18/sound/soc/mediatek/mt_soc_audio_6797/AudDrv_Gpio.c`), which are wiring evidence only. There is no proof that a current ASoC card, PMIC wrapper, amplifier control, jack detect, or UCM profile works on Gemini. The former “PROVEN speaker tone”, DC-calibration, and exact interrupt-lock claims are removed.

Next validation: bring up PWRAP/MT6351 read-only first, bind the AFE with a
minimal card, and capture one playback and one capture stream. Treat amplifier
GPIO timing and routing as separate, device-tested gates.
