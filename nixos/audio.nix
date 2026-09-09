{ config, pkgs, ... }:
let
  controlSnapshot = pkgs.writeShellScriptBin "gemini-audio-controls" ''
    set -euo pipefail
    ${pkgs.alsa-utils}/bin/amixer -c mt6797mt6351 contents |
      ${pkgs.gawk}/bin/awk -f ${../nix/audio-controls.awk}
  '';
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
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.diffutils pkgs.gnugrep config.systemd.package pkgs.util-linux pkgs.alsa-utils]}:$PATH
    export ALSA_CONFIG_UCM2=${config.environment.variables.ALSA_CONFIG_UCM2}
    grep -wFq GEMINI_A72_CI9_M33 /proc/cmdline
    systemctl is-active --quiet gemini-watchdog-takeover.service gemini-cellular.service gemini-gpu.service
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    test "$(cat /sys/class/watchdog/watchdog0/nowayout)" = 1
    test "$(cat /sys/class/watchdog/watchdog0/timeout)" = 31
    mkdir /run/gemini-audio
    cat /proc/sys/kernel/random/boot_id > /run/gemini-audio/boot-id
    cat /proc/asound/cards /proc/asound/pcm > /run/gemini-audio/topology
    dmesg > /run/gemini-audio/kernel-before.txt
    # Capture teardown must not remove the right USB Ethernet adapter or
    # release the regulator claims held by the two USB consumers.
    right_net=
    for net in /sys/class/net/*; do
      if test "$(readlink -f "$net/device/driver")" = /sys/bus/usb/drivers/r8152; then
        test -z "$right_net"
        right_net=$net
      fi
    done
    test -n "$right_net"
    right_device=$(readlink -f "$right_net/device")
    right_ifindex=$(cat "$right_net/ifindex")
    shared_rail=
    for rail in /sys/class/regulator/*; do
      if test "$(cat "$rail/name")" = vusb33; then
        test -z "$shared_rail"
        shared_rail=$rail
      fi
    done
    test -n "$shared_rail"
    usb_users=$(cat "$shared_rail/num_users")
    test "$usb_users" -ge 2
    check_usb() {
      test "$(readlink -f "$right_net/device")" = "$right_device"
      test "$(cat "$right_net/ifindex")" = "$right_ifindex"
      test "$(cat "$right_net/carrier")" = 1
      test "$(cat "$shared_rail/state")" = enabled
      test "$(cat "$shared_rail/num_users")" = "$usb_users"
    }
    check_usb
    cat /sys/kernel/debug/regulator/regulator_summary > /run/gemini-audio/regulators-before.txt
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
    amixer -c mt6797mt6351 cget "name='Speaker Switch'" | grep -Fq ': values=off'
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
    check_usb
    # DPCM must see a backend at open, earlier than ctl_elems hooks run.
    # Keep these four digital interconnects as the normal application
    # baseline; stream close still powers down the analog paths.
    ${config.system.build.geminiAudioDigitalRoutes}
    echo 'gemini-audio: digital routes ready' > /dev/kmsg
    # Exercise the public ALSA default, including its control-preservation
    # hooks and plug conversion. Captured sound is discarded, never saved.
    # Jack detection is asynchronous; wait for its first physical report.
    for attempt in $(seq 1 30); do
      dmesg > /run/gemini-audio/jack-startup.txt
      if grep -Fq 'MT6351 headset report present=' /run/gemini-audio/jack-startup.txt; then break; fi
      sleep 0.1
    done
    grep -Fq 'MT6351 headset report present=' /run/gemini-audio/jack-startup.txt
    if grep -Fq 'headset detector stopped after register error' /run/gemini-audio/jack-startup.txt; then exit 1; fi
    amixer -c mt6797mt6351 cget "iface=CARD,name='Headphone Jack'" > /run/gemini-audio/headphone-jack-before.txt
    amixer -c mt6797mt6351 cget "iface=CARD,name='Headset Mic Jack'" > /run/gemini-audio/headset-mic-jack-before.txt
    ${controlSnapshot}/bin/gemini-audio-controls > /run/gemini-audio/controls-before.txt
    echo 'gemini-audio: default playback before' > /dev/kmsg
    timeout --signal=TERM --kill-after=5 10 aplay -q -D default ${tone}
    echo 'gemini-audio: default playback passed' > /dev/kmsg
    dmesg > /run/gemini-audio/speaker-playback.txt
    amixer -c mt6797mt6351 cget "name='Speaker Switch'" | grep -Fq ': values=off'
    speaker_starts=$(grep -Fc 'Gemini speaker amplifiers before enable=1' /run/gemini-audio/speaker-playback.txt || :)
    echo 'gemini-audio: named headphone playback before' > /dev/kmsg
    timeout --signal=TERM --kill-after=5 10 aplay -q -D gemini_headphones ${tone}
    dmesg > /run/gemini-audio/headphone-playback.txt
    test "$(grep -Fc 'Gemini speaker amplifiers before enable=1' /run/gemini-audio/headphone-playback.txt || :)" = "$speaker_starts"
    echo 'gemini-audio: named headphone playback kept speakers off' > /dev/kmsg
    echo 'gemini-audio: default capture before' > /dev/kmsg
    timeout --signal=TERM --kill-after=5 10 arecord -q -D default -t raw -f S16_LE -r 48000 -c 2 -d 1 /dev/null
    echo 'gemini-audio: default capture passed' > /dev/kmsg
    ${controlSnapshot}/bin/gemini-audio-controls > /run/gemini-audio/controls-after.txt
    cmp /run/gemini-audio/controls-before.txt /run/gemini-audio/controls-after.txt
    alsaucm -c hw:mt6797mt6351 list _verbs > /run/gemini-audio/ucm-verbs.txt
    alsaucm -c hw:mt6797mt6351 set _verb HiFi list _devices > /run/gemini-audio/ucm-devices.txt
    grep -Fq 'Headphones' /run/gemini-audio/ucm-devices.txt
    grep -Fq 'Speaker' /run/gemini-audio/ucm-devices.txt
    grep -Fq 'Mic' /run/gemini-audio/ucm-devices.txt
    alsaucm -c hw:mt6797mt6351 set _verb HiFi \
      set _enadev Speaker set _disdev Speaker \
      set _enadev Headphones set _disdev Headphones \
      set _enadev Mic set _disdev Mic
    ${controlSnapshot}/bin/gemini-audio-controls > /run/gemini-audio/controls-after-ucm.txt
    cmp /run/gemini-audio/controls-before.txt /run/gemini-audio/controls-after-ucm.txt
    # Disabling UCM devices must preserve the digital backend defaults for
    # the next ordinary ALSA open. Empty input tests this without a new tone.
    timeout --signal=TERM --kill-after=5 10 aplay -q -D default \
      -t raw -f S16_LE -r 48000 -c 2 /dev/null
    echo 'gemini-audio: UCM enable-disable and subsequent default open passed' > /dev/kmsg
    check_usb
    cat /sys/kernel/debug/regulator/regulator_summary > /run/gemini-audio/regulators-after.txt
    echo 'gemini-audio: USB device, carrier and shared regulator claims preserved' > /dev/kmsg
    dmesg > /run/gemini-audio/kernel-after.txt
    speaker_starts=$(grep -Fc 'Gemini speaker amplifiers before enable=1' /run/gemini-audio/kernel-after.txt || :)
    if test "$speaker_starts" = 0; then
      # A physical jack legitimately suppresses the speaker route. Record
      # this separately; it is not a successful amplifier-cycle measurement.
      grep -Fq 'MT6351 headset report present=1' /run/gemini-audio/kernel-after.txt
      echo 'speaker-amplifier-test=muted-for-headphones' > /run/gemini-audio/speaker-result
    else
      echo 'speaker-amplifier-test=cycles-passed' > /run/gemini-audio/speaker-result
    fi
    test "$(grep -Fc 'Gemini speaker amplifiers after enable=1 readback=1,1' /run/gemini-audio/kernel-after.txt || :)" = "$speaker_starts"
    test "$(grep -Fc 'Gemini speaker amplifiers after enable=0 readback=0,0' /run/gemini-audio/kernel-after.txt || :)" = "$speaker_starts"
    amixer -c mt6797mt6351 cget "name='Speaker Switch'" | grep -Fq ': values=off'
    if grep -Fq 'headset detector stopped after register error' /run/gemini-audio/kernel-after.txt; then exit 1; fi
    amixer -c mt6797mt6351 cget "iface=CARD,name='Headphone Jack'" > /run/gemini-audio/headphone-jack-after.txt
    amixer -c mt6797mt6351 cget "iface=CARD,name='Headset Mic Jack'" > /run/gemini-audio/headset-mic-jack-after.txt
    echo 'gemini-audio: speaker amplifier accounting and shutdown passed' > /dev/kmsg
    echo 'gemini-audio: PMIC jack reporting and stable mixer restoration passed' > /dev/kmsg
    echo 'audio=playback-capture-and-route-restoration-passed' > /run/gemini-audio/result
  '';
in {
  imports = [./audio-routes.nix];
  system.build.geminiAudioControls = controlSnapshot;
  environment.systemPackages = [controlSnapshot];
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
