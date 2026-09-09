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
  qualify = pkgs.writeShellScript "gemini-audio-qualify" ''
    set -euo pipefail
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep config.systemd.package pkgs.util-linux]}:$PATH
    grep -wFq GEMINI_A72_CI9_M25 /proc/cmdline
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
    dmesg > /run/gemini-audio/kernel-after.txt
    echo 'audio=pcm-playback-and-route-restoration-passed' > /run/gemini-audio/result
  '';
in {
  systemd.services.gemini-audio = {
    description = "Qualify Gemini PCM playback and restore its audio routes";
    wantedBy = ["multi-user.target"];
    after = ["gemini-gpu.service"];
    requires = ["gemini-gpu.service"];
    before = ["gemini-connectivity.service" "gemini-baseline-self-accept.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "30s";
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
