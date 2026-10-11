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
  # UCM owns the route controls; plain ALSA applications use preserving
  # control hooks. PipeWire applies the same physical channel correction
  # through its node map while plain ALSA uses the route PCM below.
  headphonePath = [
    { name = "DAC In Mux"; value = "Normal Path"; idle = "Normal Path"; }
  ] ++ playbackInterconnects ++ [
    { name = "HPL Mux"; value = "Audio Playback"; idle = "Open"; }
    { name = "HPR Mux"; value = "Audio Playback"; idle = "Open"; }
  ];
  headphones = headphonePath ++ [
    { name = "Speaker Switch"; value = 0; idle = 0; }
  ];
  speakers = headphonePath ++ [
    { name = "Speaker Switch"; value = 1; idle = 0; }
  ];
  microphone = captureInterconnects ++ [
    { name = "AIF Out Mux"; value = "Normal Path"; idle = "Normal Path"; }
    { name = "ADC L Mux"; value = "Left Preamplifier"; idle = "Idle"; }
    { name = "ADC R Mux"; value = "Right Preamplifier"; idle = "Idle"; }
    { name = "PGA L Mux"; value = "AIN0"; idle = "None"; }
    { name = "PGA R Mux"; value = "AIN0"; idle = "None"; }
    { name = "PGA Volume"; value = [1 1]; idle = [0 0]; }
  ];
  # The headset is AIN1 on the left PGA. The right PGA's second input is
  # AIN3, so capturing it would mix in a different physical input.
  headsetMicrophone = captureInterconnects ++ [
    { name = "AIF Out Mux"; value = "Normal Path"; idle = "Normal Path"; }
    { name = "ADC L Mux"; value = "Left Preamplifier"; idle = "Idle"; }
    { name = "ADC R Mux"; value = "Idle"; idle = "Idle"; }
    { name = "PGA L Mux"; value = "AIN1"; idle = "None"; }
    { name = "PGA R Mux"; value = "None"; idle = "None"; }
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
  controlHooks = name: device: controls: ''
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
  '';
  hookedPcm = name: device: controls: ''
    ${controlHooks name device controls}
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
  # Both onboard outputs share Playback_1 and the MT6351 HP buffers. On
  # this board their physical stereo order is reversed. Correct samples
  # once at the standalone playback PCM. PipeWire's native UCM transport
  # uses its hardware channel map below; capture is separate.
  playbackPcm = name: slave: ''
    pcm.${name} {
      type route
      slave {
        pcm ${builtins.toJSON slave}
        channels 2
      }
      ttable.0.1 1
      ttable.1.0 1
    }
  '';
  hookedPlaybackPcm = name: controls: ''
    ${controlHooks name 0 controls}
    ${playbackPcm "${name}_stereo" "${name}_routes"}
    pcm.${name} {
      type plug
      slave {
        pcm "${name}_stereo"
        format S16_LE
        rate 48000
        channels 2
      }
    }
  '';
  # Keep the qualified stereo hardware transport and select only its left
  # channel. The outer plug converts that mono stream for ordinary clients.
  # UCM owns its controls; the standalone PCM uses preserving control hooks.
  headsetMonoPcm = name: slave: ''
    pcm.${name} {
      type plug
      slave {
        pcm {
          type route
          slave {
            pcm ${builtins.toJSON slave}
            format S16_LE
            channels 2
          }
          ttable.0.0 1
        }
        format S16_LE
        rate 48000
        channels 1
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
      Comment "Gemini speakers, headphones, internal and headset microphones"
    }
    UCM
    cat > "$out/share/alsa/ucm2/MediaTek/Gemini/HiFi.conf" <<'UCM'
    SectionVerb {
      Value { TQ "HiFi" }
    }
    SectionDevice."Speaker" {
      Comment "Internal speakers"
      ConflictingDevice [ "Headphones" ]
      Value {
        PlaybackPriority 200
        PlaybackPCM "hw:mt6797mt6351,0"
        PlaybackChannels 2
        PlaybackMixerElem "Headphone"
        PlaybackVolume "name='Headphone Volume'"
      }
      EnableSequence [
        ${sequence speakers "value"}
      ]
      DisableSequence [
        ${sequence (lib.reverseList speakers) "idle"}
      ]
    }
    SectionDevice."Headphones" {
      Comment "Headphones"
      ConflictingDevice [ "Speaker" ]
      Value {
        PlaybackPriority 300
        JackControl "Headphone Jack"
        JackHWMute "Speaker"
        PlaybackPCM "hw:mt6797mt6351,0"
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
      ConflictingDevice [ "Headset" ]
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
    SectionDevice."Headset" {
      Comment "Headset microphone"
      ConflictingDevice [ "Mic" ]
      Value {
        CapturePriority 300
        JackControl "Headset Mic Jack"
        CapturePCM "gemini_headset_mic_ucm"
        CaptureChannels 1
        CaptureMixerElem "PGA"
        CaptureVolume "name='PGA Volume'"
      }
      EnableSequence [
        ${sequence headsetMicrophone "value"}
      ]
      DisableSequence [
        ${sequence (lib.reverseList headsetMicrophone) "idle"}
      ]
    }
    UCM
  '';
in {
  # Keep UCM on the native hardware PCM that ACP can probe. Its physical
  # order is right then left; PipeWire's channel mixer maps ordinary FL/FR
  # client streams to these positions. Capture and other cards are separate.
  services.pipewire.wireplumber.extraConfig."51-gemini-playback-channels" = {
    "monitor.alsa.rules" = [{
      matches = [{
        "media.class" = "Audio/Sink";
        "api.alsa.path" = "hw:mt6797mt6351,0";
      }];
      actions.update-props = {
        "audio.position" = ["FR" "FL"];
        "api.alsa.use-chmap" = false;
      };
    }];
  };
  system.build.geminiAudioDigitalRoutes = digitalRoutes;
  system.build.geminiAudioUcm = ucm;
  environment.variables.ALSA_CONFIG_UCM2 = "${ucm}/share/alsa/ucm2";
  # Expose the exact active board profile for read-only candidate validation.
  environment.etc."gemini/audio-ucm-hifi.conf".source =
    "${ucm}/share/alsa/ucm2/MediaTek/Gemini/HiFi.conf";
  environment.etc."asound.conf".text = ''
    # ASoC power follows the selected stream. No GPIO is written by userspace.
    ${hookedPlaybackPcm "gemini_speakers" speakers}
    ${hookedPlaybackPcm "gemini_headphones" headphones}
    ${hookedPcm "gemini_mic" 3 microphone}
    ${controlHooks "gemini_headset_mic" 3 headsetMicrophone}
    ${headsetMonoPcm "gemini_headset_mic" "gemini_headset_mic_routes"}
    ${headsetMonoPcm "gemini_headset_mic_ucm" "hw:CARD=mt6797mt6351,DEV=3"}
    pcm.!default {
      type asym
      playback.pcm "gemini_speakers"
      capture.pcm "gemini_mic"
      hint.description "Gemini speakers, headphones and internal microphone"
    }
    ctl.!default {
      type hw
      card "mt6797mt6351"
    }
  '';
}
