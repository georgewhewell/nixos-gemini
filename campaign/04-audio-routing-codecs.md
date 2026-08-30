# Audio, AFE and codecs

Status: SOURCE EXISTS; an OPT-IN AFE/MT6351 enumeration overlay is in the
Nix-pinned input; external routing and DEVICE-TESTED audio **UNKNOWN**.

The audio overlay enables only the MT6797 AFE, an MT6351 sound child, and their
machine card (`linux-gemini-platform@1bb2a9863:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-audio.dtso:3-43`). Its own evidence boundary excludes the
external amplifier, headphone depop, headset detection and UCM routing
(`:5-20`). Nix's queued smoke profile selects it and the composition check
asserts the AFE status and machine compatible (`flake.nix:396-415`,
`nix/mainline.nix:568-577`). Neither is a device capture.

Vendor GPIO and legacy amplifier code remain source evidence only. No retained
ledger entry proves an ALSA card, playback, capture, jack state, speaker output
or amplifier timing on this Gemini.

After the read-only recovery baseline is re-established, the exact gate is a
recovery-only overlay boot with saved dmesg and ALSA topology. Pass only after
one enumerated card and one bounded playback or capture stream are retained;
keep amplifier GPIOs and routes absent until separately evidenced.
