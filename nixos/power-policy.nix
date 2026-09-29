# Lid, suspend and hibernation policy (handoff/power-policy.md).
#
# - Lid closed: Weston forces the internal DSI output off at once (patched
#   libweston, nix/desktop-userspace.nix); the panel, its backlight and the
#   touch controller that follows it all power down.
# - Lid closed for lidSuspendDelaySec: logind carries out HandleLidSwitch=.
#   gemini-sleep-inhibit holds logind's "handle-lid-switch" inhibitor while
#   the lid is open and for the grace period after it closes.
# - Sleep is s2idle ("freeze"), the only state PSCI v0.2 offers here.  With
#   hibernation enabled the lid action is suspend-then-hibernate: an RTC alarm
#   after HibernateDelaySec wakes the system, which then hibernates.
# - Opening the lid wakes the system (gpio-keys wakeup-source, lid-open edge
#   only).  The power key and the RTC alarm are the other wake sources.
# - No sleep while a USB host is attached to the MTU3 gadget (the recovery
#   link; the controller vetoes suspend with -EBUSY while connected) or
#   before the unattended-recovery lease has been accepted.  Both are
#   "sleep" block inhibitors, which the lid action honours because
#   LidSwitchIgnoreInhibited=no.
{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.gemini.powerPolicy;
  hib = cfg.hibernation;

  # Partitions that must never be used as swap: firmware, calibration,
  # NVRAM, protect*, the boot images and rescue slots, the modem images,
  # Android system (vendor firmware source) and the p29 store.  Only an
  # explicitly approved partition may be named.
  forbiddenPartitions = [
    "recovery" "para" "expdb" "frp" "nvcfg" "nvdata" "metadata" "protect1"
    "protect2" "seccfg" "oemkeystore" "proinfo" "md1img" "md1dsp" "md1arm7"
    "md3img" "scp1" "scp2" "nvram" "lk" "lk2" "boot" "logo" "tee1" "tee2"
    "keystore" "system" "linux" "boot2" "boot3" "flashinfo"
  ];

  lidAction =
    if hib.enable
    then "suspend-then-hibernate"
    else "suspend";

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
    hibernation = {
      enable = lib.mkEnableOption ''
        suspend-then-hibernate on the lid, with the swap partition named by
        partitionLabel, and resume from it in Stage 1.  The partition must
        already carry a swap signature (mkswap) before this is enabled'';
      partitionLabel = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        example = "userdata";
        description = ''
          GPT partition name (PARTNAME) of the swap partition used for the
          hibernation image.  Stage 1 resumes from the same partition.
        '';
      };
      delay = lib.mkOption {
        type = lib.types.str;
        default = "24h";
        description = "HibernateDelaySec= for suspend-then-hibernate.";
      };
    };
  };

  config = {
    assertions = [
      {
        assertion = !hib.enable || hib.partitionLabel != null;
        message = "gemini.powerPolicy.hibernation.enable needs partitionLabel";
      }
      {
        assertion = hib.partitionLabel == null || builtins.match "[A-Za-z0-9_.-]+" hib.partitionLabel != null;
        message = "gemini.powerPolicy.hibernation.partitionLabel must be a plain GPT partition name";
      }
      {
        assertion = hib.partitionLabel == null || !(builtins.elem hib.partitionLabel forbiddenPartitions);
        message = "gemini.powerPolicy.hibernation.partitionLabel names a protected Gemini partition";
      }
    ];

    # suspend-then-hibernate needs systemd v254's battery handling: v253
    # treats "no battery with a readable capacity" as a low battery and
    # hibernates at once.  The MT6351 fuel gauge reports no capacity.
    nixpkgs.overlays = [
      (final: prev: {
        systemdMinimal = prev.systemdMinimal.overrideAttrs (old: {
          patches = (old.patches or []) ++ [
            ../patches/systemd/0001-sleep-config-do-not-treat-an-unreadable-or-absent-ba.patch
          ];
        });
      })
    ];

    services.logind = {
      lidSwitch = lidAction;
      lidSwitchExternalPower = lidAction;
      # "Docked" means an external display or dock; the Gemini has neither.
      lidSwitchDocked = "ignore";
      extraConfig = ''
        # Honour "sleep" block inhibitors (USB host attached, recovery lease
        # pending) for the lid too.
        LidSwitchIgnoreInhibited=no
        # Covers boot until gemini-sleep-inhibit holds its inhibitors, and
        # spaces out retries after a failed sleep.  CLOCK_MONOTONIC keeps
        # running in s2idle here, so it rarely delays a re-suspend.
        HoldoffTimeoutSec=2min
      '';
    };

    systemd.sleep.extraConfig = ''
      AllowSuspend=yes
      AllowHibernation=${lib.boolToString hib.enable}
      AllowSuspendThenHibernate=${lib.boolToString hib.enable}
      AllowHybridSleep=no
      SuspendState=freeze
      # arm64 has no platform hibernation mode.
      HibernateMode=shutdown
      HibernateDelaySec=${hib.delay}
    '';

    swapDevices = lib.optional hib.enable {
      device = "/dev/disk/by-partlabel/${hib.partitionLabel}";
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
