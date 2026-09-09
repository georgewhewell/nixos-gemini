{ lib, pkgs, ... }:
let
  # DPCM requires a connected backend at PCM open, before ctl_elems hooks
  # run at hw_params. These digital interconnects stay selected; DAPM still
  # powers the analog paths only for an active stream.
  playbackInterconnects = [
    { name = "ADDA_DL_CH1 DL1_CH1"; value = 1; idle = 1; }
    { name = "ADDA_DL_CH2 DL1_CH2"; value = 1; idle = 1; }
  ];
  captureInterconnects = [
    { name = "UL1_CH1 ADDA_UL_CH1"; value = 1; idle = 1; }
    { name = "UL1_CH2 ADDA_UL_CH2"; value = 1; idle = 1; }
  ];
  # The fixed machine card exposes Playback_1 at 0 and Capture_1 at 3.
  # UCM users open those hardware PCMs; plain ALSA applications use the
  # default hooks below, which restore their route controls on close.
  headphones = [
    { name = "DAC In Mux"; value = "Normal Path"; idle = "Normal Path"; }
  ] ++ playbackInterconnects ++ [
    { name = "HPL Mux"; value = "Audio Playback"; idle = "Open"; }
    { name = "HPR Mux"; value = "Audio Playback"; idle = "Open"; }
  ];
  microphone = captureInterconnects ++ [
    { name = "AIF Out Mux"; value = "Normal Path"; idle = "Normal Path"; }
    { name = "ADC L Mux"; value = "Left Preamplifier"; idle = "Idle"; }
    { name = "ADC R Mux"; value = "Right Preamplifier"; idle = "Idle"; }
    { name = "PGA L Mux"; value = "AIN0"; idle = "None"; }
    { name = "PGA R Mux"; value = "AIN0"; idle = "None"; }
    { name = "PGA Volume"; value = [1 1]; idle = [0 0]; }
  ];
  alsaValue = value:
    if builtins.isList value then "[ ${lib.concatMapStringsSep " " toString value} ]"
    else if builtins.isString value then builtins.toJSON value
    else toString value;
  csetValue = value:
    if builtins.isList value then lib.concatMapStringsSep "," toString value
    else if builtins.isString value then "'${value}'"
    else toString value;
  sequence = controls: field: lib.concatMapStringsSep "\n" (control:
    "cset ${builtins.toJSON "name='${control.name}' ${csetValue control.${field}}"}"
  ) controls;
  hookedPcm = name: device: controls: ''
    pcm.${name}_routes {
      type hooks
      slave.pcm "hw:CARD=mt6797mt6351,DEV=${toString device}"
      hooks.0 {
        type ctl_elems
        hook_args [
          ${lib.concatMapStringsSep "\n" (control: ''
            {
              name ${builtins.toJSON control.name}
              preserve true
              lock true
              optional false
              value ${alsaValue control.value}
            }
          '') controls}
        ]
      }
    }
    pcm.${name} {
      type plug
      slave {
        pcm "${name}_routes"
        format S16_LE
        rate 48000
        channels 2
      }
    }
  '';
  digitalRoutes = pkgs.writeShellScript "gemini-audio-digital-routes" ''
    set -euo pipefail
    ${lib.concatMapStringsSep "\n" (control: ''
      ${pkgs.alsa-utils}/bin/amixer -q -c mt6797mt6351 cset ${lib.escapeShellArg "name='${control.name}'"} 1
      ${pkgs.alsa-utils}/bin/amixer -c mt6797mt6351 cget ${lib.escapeShellArg "name='${control.name}'"} |
        ${pkgs.gnugrep}/bin/grep -Fq ': values=on'
    '') (playbackInterconnects ++ captureInterconnects)}
  '';
  ucm = pkgs.runCommand "gemini-alsa-ucm" {} ''
    mkdir -p "$out/share/alsa"
    cp -R --no-preserve=mode ${pkgs.alsa-ucm-conf}/share/alsa/ucm2 "$out/share/alsa/ucm2"
    mkdir -p "$out/share/alsa/ucm2/conf.d/mt6797-mt6351"
    mkdir -p "$out/share/alsa/ucm2/MediaTek/Gemini"
    ln -s ../../MediaTek/Gemini/Gemini.conf \
      "$out/share/alsa/ucm2/conf.d/mt6797-mt6351/mt6797-mt6351.conf"
    cat > "$out/share/alsa/ucm2/MediaTek/Gemini/Gemini.conf" <<'UCM'
    Syntax 4
    SectionUseCase."HiFi" {
      File "/MediaTek/Gemini/HiFi.conf"
      Comment "Gemini headphones and internal microphone"
    }
    UCM
    cat > "$out/share/alsa/ucm2/MediaTek/Gemini/HiFi.conf" <<'UCM'
    SectionVerb {
      Value { TQ "HiFi" }
    }
    SectionDevice."Headphones" {
      Comment "Headphones"
      Value {
        PlaybackPriority 200
        PlaybackPCM "hw:''${CardId},0"
        PlaybackChannels 2
        PlaybackMixerElem "Headphone"
        PlaybackVolume "name='Headphone Volume'"
      }
      EnableSequence [
        ${sequence headphones "value"}
      ]
      DisableSequence [
        ${sequence (lib.reverseList headphones) "idle"}
      ]
    }
    SectionDevice."Mic" {
      Comment "Internal microphone"
      Value {
        CapturePriority 200
        CapturePCM "hw:''${CardId},3"
        CaptureChannels 2
        CaptureMixerElem "PGA"
        CaptureVolume "name='PGA Volume'"
      }
      EnableSequence [
        ${sequence microphone "value"}
      ]
      DisableSequence [
        ${sequence (lib.reverseList microphone) "idle"}
      ]
    }
    UCM
  '';
in {
  system.build.geminiAudioDigitalRoutes = digitalRoutes;
  environment.variables.ALSA_CONFIG_UCM2 = "${ucm}/share/alsa/ucm2";
  environment.etc."asound.conf".text = ''
    # ASoC power follows the selected stream. No GPIO is written by userspace.
    ${hookedPcm "gemini_headphones" 0 headphones}
    ${hookedPcm "gemini_mic" 3 microphone}
    pcm.!default {
      type asym
      playback.pcm "gemini_headphones"
      capture.pcm "gemini_mic"
      hint.description "Gemini headphones and internal microphone"
    }
    ctl.!default {
      type hw
      card "mt6797mt6351"
    }
  '';
}
