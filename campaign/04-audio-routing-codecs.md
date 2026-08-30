# Audio, AFE and codecs

Status: AFE/MT6351 card is BOUND-UNVERIFIED; external routing and physical
playback/capture remain UNKNOWN.

The current full Stage2 runtime exposes ALSA card mt6797mt6351, seven
playback/capture PCM endpoints, and the AFE/machine-card probes succeed in
live dmesg. The reviewed overlay enables only the AFE, MT6351 sound child, and
machine card (linux-gemini-platform@28c471502:
arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-audio.dtso:3-43).
Its evidence boundary excludes the external amplifier, headphone depop,
headset detection, and UCM routing
(`linux-gemini-platform@28c471502:arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-audio.dtso:5-20`).

An ALSA card is not a speaker or microphone result. No physical playback,
capture, jack state, amplifier timing, or volume path has been observed. Keep
vendor GPIO/amp routing out of the image.

Next gate: preserve the exact recovery image and ALSA topology, then run one
bounded playback or capture stream. Pass only with a retained stream result;
do not promote enumeration to physical audio DEVICE-TESTED.
