# Lid and suspend policy. Normal paging is RAM-only; hibernation is disabled.
#
# - Lid closed: Weston forces the internal DSI output off at once (patched
#   libweston, nix/desktop-userspace.nix); the panel, its backlight and the
#   touch controller that follows it all power down.
# - Lid closed for lidSuspendDelaySec: gemini-sleep-inhibit asks logind to
#   sleep.  logind itself ignores the lid (HandleLidSwitch=ignore), so if the
#   daemon is not running nothing sleeps.  An earlier design let logind act
#   on the lid behind a "handle-lid-switch" inhibitor; on this board the
#   daemon starts with multi-user.target (~300 s), after logind's 2 min
#   holdoff, and a closed lid suspended the device mid-qualification.
# - Sleep is s2idle ("freeze"), the only state PSCI v0.2 offers here.
# - Opening the lid wakes the system (gpio-keys wakeup-source, lid-open edge
#   only).  The power key and the RTC alarm are the other wake sources.
# - No sleep while a USB host is attached to the MTU3 gadget (the recovery
#   link; the controller vetoes suspend with -EBUSY while connected) or
#   before the unattended-recovery lease has been accepted.  Both are
#   conditions the daemon checks before asking, and "sleep" block
#   inhibitors it holds so that other sleep requests are refused too.
{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.gemini.powerPolicy;

  sleepInhibit = pkgs.stdenv.mkDerivation {
    pname = "gemini-sleep-inhibit";
    version = "1";
    src = ../nix/gemini-sleep-inhibit.c;
    dontUnpack = true;
    nativeBuildInputs = [pkgs.buildPackages.pkg-config];
    buildInputs = [config.systemd.package];
    buildPhase = ''
      $CC -std=gnu11 -O2 -Wall -Wextra -Werror -Wshadow -Wformat=2 "$src" \
        $($PKG_CONFIG --cflags --libs libsystemd) -o gemini-sleep-inhibit
    '';
    installPhase = ''
      install -Dm0755 gemini-sleep-inhibit "$out/bin/gemini-sleep-inhibit"
    '';
  };
in {
  options.gemini.powerPolicy = {
    lidSuspendDelaySec = lib.mkOption {
      type = lib.types.ints.between 0 86400;
      default = 900;
      description = ''
        How long the lid must stay closed (awake time plus sleep time)
        before logind's lid action runs.  The display turns off at once.
      '';
    };
    usbDeviceController = lib.mkOption {
      type = lib.types.str;
      default = "11271000.usb";
      description = ''
        UDC whose attached host blocks sleep (the MTU3 left-port gadget).
      '';
    };
  };

  config = {
    services.logind = {
      settings.Login = {
        HandleLidSwitch = "ignore";
        HandleLidSwitchExternalPower = "ignore";
        HandleLidSwitchDocked = "ignore";
        HoldoffTimeoutSec = "2min";
      };
    };

    systemd.sleep.settings.Sleep = {
      AllowSuspend = true;
      AllowHibernation = false;
      AllowSuspendThenHibernate = false;
      AllowHybridSleep = false;
      SuspendState = "freeze";
    };


    systemd.services.gemini-sleep-inhibit = {
      description = "Gemini lid grace, USB-host and recovery-lease sleep inhibitors";
      wantedBy = ["multi-user.target"];
      wants = ["systemd-logind.service"];
      after = ["systemd-logind.service" "dbus.service"];
      serviceConfig = {
        Type = "simple";
        ExecStart = lib.escapeShellArgs [
          "${sleepInhibit}/bin/gemini-sleep-inhibit"
          "--lid-grace"
          (toString cfg.lidSuspendDelaySec)
          "--sleep-action"
          "Suspend"
          "--udc"
          cfg.usbDeviceController
          "--accepted-file"
          "/run/unattended-recovery.accepted"
          "--accepted-content"
          "unattended_recovery=healthy"
        ];
        Restart = "on-failure";
        RestartSec = "5s";
      };
    };
  };
}
