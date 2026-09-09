# A local Wayland session, qualified before the guarded boot is accepted.
{ pkgs, lib, geminiDesktop, ... }:
let
  inherit (geminiDesktop) weston mesa seatd presentationCheck;
  sessionEnvironment = {
    XDG_RUNTIME_DIR = "/run/gemini-desktop";
    WAYLAND_DISPLAY = "wayland-0";
    HOME = "/home/gemini";
    SHELL = "${pkgs.busybox}/bin/ash";
    LIBSEAT_BACKEND = "seatd";
    SEATD_SOCK = "/run/gemini-seatd/seatd.sock";
    __EGL_VENDOR_LIBRARY_FILENAMES = "${mesa}/share/glvnd/egl_vendor.d/50_mesa.json";
    LIBGL_DRIVERS_PATH = "${mesa}/lib/dri";
    GBM_BACKENDS_PATH = "${mesa}/lib/gbm";
    # Mesa must detect mediatek-drm and use kmsro to reach the separate
    # Panfrost render node. Forcing "panfrost" would misidentify the KMS FD.
    MESA_SHADER_CACHE_DISABLE = "true";
    FONTCONFIG_FILE = fontConfig;
    XCURSOR_PATH = "${geminiDesktop.vanilla-dmz}/share/icons";
    XCURSOR_THEME = "DMZ-White";
  };
  fontConfig = pkgs.writeText "gemini-fonts.conf" ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
    <fontconfig>
      <dir>${geminiDesktop.dejavu_fonts}/share/fonts/truetype</dir>
      <cachedir>/home/gemini/.cache/fontconfig</cachedir>
      <alias><family>sans-serif</family><prefer><family>DejaVu Sans</family></prefer></alias>
      <alias><family>monospace</family><prefer><family>DejaVu Sans Mono</family></prefer></alias>
    </fontconfig>
  '';
  terminal = pkgs.writeShellScript "gemini-desktop-terminal" ''
    export PATH=/run/current-system/sw/bin:${pkgs.busybox}/bin
    cd "$HOME"
    exec ${weston}/bin/weston-terminal --shell=${pkgs.busybox}/bin/ash
  '';
  westonConfig = pkgs.writeText "gemini-weston.ini" ''
    [core]
    shell=desktop
    idle-time=0
    gbm-format=xrgb8888
    pageflip-timeout=2000

    [output]
    name=DSI-1
    mode=current
    transform=rotate-270
    scale=2

    [keyboard]
    keymap_layout=us

    [shell]
    background-color=0xff18374b
    panel-color=0xff102936
    locking=false

    [terminal]
    font=DejaVu Sans Mono
    font-size=14
    term=xterm-256color

    [autolaunch]
    path=${terminal}
    watch=false
  '';
  start = pkgs.writeShellScript "gemini-desktop-start" ''
    set -eu
    unset MESA_LOADER_DRIVER_OVERRIDE
    export PATH=${lib.makeBinPath [pkgs.coreutils]}:$PATH
    mkdir -p "$HOME/.cache/fontconfig"
    card=
    for candidate in /sys/class/drm/card[0-9]*; do
      test -e "$candidate/device/driver" || continue
      test "$(basename "$(readlink -f "$candidate/device/driver")")" = mediatek-drm || continue
      test -z "$card"
      card=$(basename "$candidate")
    done
    test -n "$card"
    exec ${weston}/bin/weston --backend=drm --renderer=gl --drm-device="$card" \
      --current-mode --socket=wayland-0 --config=${westonConfig} \
      --modules=systemd-notify.so --log=/run/gemini-desktop/weston.log
  '';
  seatReady = pkgs.writeShellScript "gemini-seatd-ready" ''
    set -eu
    count=0
    until test -S /run/gemini-seatd/seatd.sock; do
      count=$((count + 1))
      test "$count" -lt 50
      ${pkgs.coreutils}/bin/sleep 0.1
    done
  '';
  qualify = pkgs.writeShellScript "gemini-desktop-qualify" ''
    test -s ${geminiDesktop.protocolCheck} || exit 1
    export PATH=${lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.systemd pkgs.busybox]}:$PATH
    export GEMINI_WESTON_TERMINAL=${weston}/bin/weston-terminal
    export GEMINI_GPU_LOG_CHECK=${../nix/gpu-kernel-log-check.sh}
    ${builtins.readFile ../nix/desktop-qualify.sh}
  '';
in {
  users.users.gemini = {
    isNormalUser = true;
    hashedPassword = "!";
    home = "/home/gemini";
    createHome = true;
    shell = "${pkgs.busybox}/bin/ash";
    extraGroups = ["video" "render" "audio"];
  };
  users.groups.render = {};
  environment.etc."gemini/weston.ini".source = westonConfig;
  # The kernel reports (y, 1-x) after its touchscreen swap/invert flags.
  # Undo that normalization here: Weston applies the output transform itself.
  # This mapping is inferred from the driver; physical alignment still needs
  # an on-device touch observation.
  services.udev.extraRules = ''
    SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="Novatek NT36xxx touchscreen", ENV{WL_OUTPUT}="DSI-1", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 -1 1 1 0 0"
  '';
  systemd.services.gemini-seatd = {
    description = "Seat access for the Gemini local desktop";
    after = ["systemd-udevd.service"];
    serviceConfig = {
      Type = "simple";
      RuntimeDirectory = "gemini-seatd";
      RuntimeDirectoryMode = "0755";
      ExecStart = "${seatd.bin}/bin/seatd -s /run/gemini-seatd/seatd.sock -g video";
      ExecStartPost = seatReady;
      TimeoutStartSec = "10s";
      Restart = "no";
    };
  };
  systemd.services.gemini-desktop = {
    description = "Gemini accelerated Wayland desktop";
    after = ["gemini-seatd.service" "gemini-gpu.service" "gemini-audio.service" "gemini-connectivity.service"];
    requires = ["gemini-seatd.service" "gemini-gpu.service" "gemini-audio.service" "gemini-connectivity.service"];
    environment = sessionEnvironment;
    serviceConfig = {
      User = "gemini";
      Type = "notify";
      NotifyAccess = "main";
      RuntimeDirectory = "gemini-desktop";
      RuntimeDirectoryMode = "0700";
      ExecStartPre = "+${pkgs.busybox}/bin/busybox chvt 7";
      ExecStart = start;
      ExecStopPost = "+${pkgs.busybox}/bin/busybox chvt 1";
      TimeoutStartSec = "30s";
      TimeoutStopSec = "15s";
      KillMode = "control-group";
      Restart = "no";
      UMask = "0077";
    };
  };
  systemd.services.gemini-desktop-presentation = {
    description = "Verify Gemini display presentation and input capabilities";
    after = ["gemini-desktop.service"];
    requires = ["gemini-desktop.service"];
    environment = sessionEnvironment;
    serviceConfig = {
      User = "gemini";
      Type = "oneshot";
      ExecStart = pkgs.writeShellScript "gemini-desktop-presentation" ''
        exec ${presentationCheck}/bin/gemini-desktop-presentation-check > /run/gemini-desktop/presentation.txt 2>&1
      '';
      TimeoutStartSec = "20s";
      UMask = "0077";
    };
  };
  systemd.services.gemini-desktop-qualify = {
    description = "Qualify Gemini desktop presentation and console restoration";
    wantedBy = ["multi-user.target"];
    after = ["gemini-gpu.service" "gemini-audio.service" "gemini-connectivity.service"];
    requires = ["gemini-gpu.service" "gemini-audio.service" "gemini-connectivity.service"];
    before = ["gemini-baseline-self-accept.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "150s";
      ExecStart = qualify;
      UMask = "0077";
      Restart = "no";
    };
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["gemini-desktop-qualify.service"];
    requires = ["gemini-desktop-qualify.service"];
  };
}
