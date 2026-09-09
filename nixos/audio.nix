{ config, pkgs, ... }:
let
  playback = pkgs.pkgsStatic.stdenv.mkDerivation {
    pname = "gemini-audio-playback";
    version = "1";
    src = ../nix/audio-playback.c;
    dontUnpack = true;
    buildPhase = ''
      $CC -std=c11 -Wall -Wextra -Werror -Wpedantic -O2 -static "$src" -o gemini-audio-playback
    '';
    installPhase = ''
      install -Dm0755 gemini-audio-playback "$out/bin/gemini-audio-playback"
    '';
  };
  capture = pkgs.pkgsStatic.stdenv.mkDerivation {
    pname = "gemini-audio-capture";
    version = "1";
    src = ../nix/audio-capture.c;
    dontUnpack = true;
    buildPhase = ''
      $CC -std=c11 -Wall -Wextra -Werror -Wpedantic -O2 -static "$src" -o gemini-audio-capture
    '';
    installPhase = ''
      install -Dm0755 gemini-audio-capture "$out/bin/gemini-audio-capture"
    '';
  };
  tone = pkgs.runCommand "gemini-audio-qualification.wav" {
    nativeBuildInputs = [pkgs.buildPackages.python3];
  } ''
    python3 - "$out" <<'PY'
    import math, struct, sys, wave
    frames = 36000
    with wave.open(sys.argv[1], 'wb') as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        for i in range(frames):
            ramp = min(i, frames - 1 - i, 480) / 480
            value = round(512 * ramp * math.sin(2 * math.pi * 440 * i / 48000))
            output.writeframesraw(struct.pack('<hh', value, value))
    PY
  '';
  qualify = pkgs.writeShellScript "gemini-audio-qualify" ''
    set -euo pipefail
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep config.systemd.package pkgs.util-linux pkgs.alsa-utils]}:$PATH
    export ALSA_CONFIG_UCM2=${config.environment.variables.ALSA_CONFIG_UCM2}
    grep -wFq GEMINI_A72_CI9_M26 /proc/cmdline
    systemctl is-active --quiet gemini-watchdog-takeover.service gemini-cellular.service gemini-gpu.service
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    test "$(cat /sys/class/watchdog/watchdog0/nowayout)" = 1
    test "$(cat /sys/class/watchdog/watchdog0/timeout)" = 31
    mkdir /run/gemini-audio
    cat /proc/sys/kernel/random/boot_id > /run/gemini-audio/boot-id
    cat /proc/asound/cards /proc/asound/pcm > /run/gemini-audio/topology
    dmesg > /run/gemini-audio/kernel-before.txt
    # Write boundaries synchronously to the kernel log before the ioctl. A
    # pipe reader might not run before a global stall. Remove only the kmsg
    # rate limit for this bounded diagnostic and restore it on every return.
    kmsg_mode=$(cat /proc/sys/kernel/printk_devkmsg)
    case "$kmsg_mode" in on|off|ratelimit) ;; *) exit 1 ;; esac
    restore_logging() {
      echo "$kmsg_mode" > /proc/sys/kernel/printk_devkmsg
      dmesg > /run/gemini-audio/stream.log
    }
    if test "$kmsg_mode" != on; then
      echo on > /proc/sys/kernel/printk_devkmsg
      trap restore_logging EXIT
    else
      trap 'dmesg > /run/gemini-audio/stream.log' EXIT
    fi
    test "$(cat /proc/sys/kernel/printk_devkmsg)" = on
    if timeout --signal=TERM --kill-after=5 15 ${playback}/bin/gemini-audio-playback --activate 2>/dev/kmsg; then
      dmesg > /run/gemini-audio/stream.log
      grep -Fq 'gemini-audio-playback: result=stream-and-route-restoration-passed' /run/gemini-audio/stream.log
    else
      echo 'gemini-audio: playback qualification failed' > /dev/kmsg
      exit 1
    fi
    if timeout --signal=TERM --kill-after=5 15 ${capture}/bin/gemini-audio-capture --stage capture --activate 2>/dev/kmsg; then
      dmesg > /run/gemini-audio/stream.log
      grep -Fq 'gemini-audio-capture: result=stream-and-route-restoration-passed' /run/gemini-audio/stream.log
      grep -Fq 'Gemini microphone gate after enable=1 readback=1' /run/gemini-audio/stream.log
      grep -Fq 'Gemini microphone gate after enable=0 readback=0' /run/gemini-audio/stream.log
    else
      echo 'gemini-audio: capture qualification failed' > /dev/kmsg
      exit 1
    fi
    # Exercise the public ALSA default, including its control-preservation
    # hooks and plug conversion. Captured sound is discarded, never saved.
    amixer -c mt6797mt6351 contents > /run/gemini-audio/controls-before.txt
    echo 'gemini-audio: default playback before' > /dev/kmsg
    timeout --signal=TERM --kill-after=5 10 aplay -q -D default ${tone}
    echo 'gemini-audio: default playback passed' > /dev/kmsg
    echo 'gemini-audio: default capture before' > /dev/kmsg
    timeout --signal=TERM --kill-after=5 10 arecord -q -D default -t raw -f S16_LE -r 48000 -c 2 -d 1 /dev/null
    echo 'gemini-audio: default capture passed' > /dev/kmsg
    amixer -c mt6797mt6351 contents > /run/gemini-audio/controls-after.txt
    cmp /run/gemini-audio/controls-before.txt /run/gemini-audio/controls-after.txt
    alsaucm -c hw:mt6797mt6351 list _verbs > /run/gemini-audio/ucm-verbs.txt
    alsaucm -c hw:mt6797mt6351 set _verb HiFi list _devices > /run/gemini-audio/ucm-devices.txt
    grep -Fq 'Headphones' /run/gemini-audio/ucm-devices.txt
    grep -Fq 'Mic' /run/gemini-audio/ucm-devices.txt
    dmesg > /run/gemini-audio/kernel-after.txt
    echo 'audio=playback-capture-and-route-restoration-passed' > /run/gemini-audio/result
  '';
in {
  imports = [./audio-routes.nix];
  systemd.services.gemini-audio = {
    description = "Qualify Gemini playback, capture and application audio routes";
    wantedBy = ["multi-user.target"];
    after = ["gemini-gpu.service"];
    requires = ["gemini-gpu.service"];
    before = ["gemini-connectivity.service" "gemini-baseline-self-accept.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "60s";
      UMask = "0077";
      ExecStart = qualify;
    };
  };
  systemd.services.gemini-connectivity = {
    after = ["gemini-audio.service"];
    requires = ["gemini-audio.service"];
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["gemini-audio.service"];
    requires = ["gemini-audio.service"];
  };
}
