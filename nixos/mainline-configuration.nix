# NixOS stage 2 for the maintained MT6797 kernel. Stage 1 mounts persistent
# home and the registered Nix store; the boot volume stays read-only until
# the boot installer runs. Historical recovery uses its own frozen module.
{
  config,
  pkgs,
  lib,
  geminiLeaseSelfAcceptToken ? null,
  geminiBootJournaled ? false,
  ...
}: {
  _module.args.geminiBootJournaled = lib.mkDefault false;
  assertions = [
    {
      assertion = geminiLeaseSelfAcceptToken == null || builtins.match "gemini-baseline-lease-v1-[0-9a-f]{64}" geminiLeaseSelfAcceptToken != null;
      message = "geminiLeaseSelfAcceptToken must be a versioned 64-hex baseline capability";
    }
  ];
  # LK supplies the Android-v0 container; the custom stage 1 supplies the
  # kernel, DTB, and initramfs.
  boot.kernel.enable = false;
  boot.initrd.enable = false;
  boot.hardwareScan = false;
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = false;
  system.boot.loader.kernelFile = "Image.gz-dtb";

  fileSystems."/" = {
    device = "tmpfs";
    fsType = "tmpfs";
    options = ["mode=0755" "size=768M"];
  };
  fileSystems."/gemian" = {
    # p29 is GPT PARTLABEL=linux; the initramfs resolves its mmcblk index by
    # controller lineage before moving this already-mounted filesystem here.
    device = "/dev/disk/by-partlabel/linux";
    fsType = "ext4";
    options = ["ro"] ++ lib.optional (!geminiBootJournaled) "noload" ++ ["nosuid" "nodev" "noexec" "nofail"];
    noCheck = true;
    neededForBoot = true;
  };

  swapDevices = [];
  networking.hostName = "gemini-mainline-nixos";
  networking.useDHCP = true;
  networking.interfaces.usb0.useDHCP = false;
  networking.dhcpcd.extraConfig = "denyinterfaces usb0";
  networking.firewall.enable = false;
  networking.networkmanager.enable = false;

  # The kernel's built-in g_ether driver and stage 1 create usb0.  Reassert
  # its static address after systemd/udev settle; the operation is idempotent.
  systemd.services.gemini-mainline-usb = {
    description = "Configure the Gemini mainline USB gadget address";
    wantedBy = ["multi-user.target"];
    before = ["sshd.service"];
    after = ["systemd-udevd.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      attempt=0
      while [ ! -e /sys/class/net/usb0 ] && [ "$attempt" -lt 30 ]; do
        attempt=$((attempt + 1))
        sleep 1
      done
      test -e /sys/class/net/usb0
      ${pkgs.busybox}/bin/busybox ip link set usb0 up
      ${pkgs.busybox}/bin/busybox ip address replace 10.15.19.82/24 dev usb0
    '';
  };

  # Keep the already-proven Gemian host identity while p29 remains read-only.
  services.openssh = {
    enable = true;
    settings = {
      KbdInteractiveAuthentication = false;
      PasswordAuthentication = false;
      PermitRootLogin = "prohibit-password";
      UsePAM = true;
      ListenAddress = "0.0.0.0";
    };
    hostKeys = [
      {
        type = "ed25519";
        path = "/gemian/etc/ssh/ssh_host_ed25519_key";
      }
    ];
  };
  programs.ssh.package = pkgs.openssh.override {
    withFIDO = false;
    withKerberos = false;
  };

  users.mutableUsers = false;
  users.users.root = {
    hashedPassword = "!";
    shell = "${pkgs.busybox}/bin/ash";
    openssh.authorizedKeys.keyFiles = [./authorized_keys];
  };
  services.getty.autologinUser = "root";

  # Stock LK prepends the vendor kernel's "slub_max_order=0 slub_debug=OFZPU".
  # Later arguments win: no SLUB debugging and the default maximum order.
  boot.kernelParams = [ "slub_debug=-" "slub_max_order=3" ];
  systemd.coredump.enable = false;
  systemd.oomd.enable = false;
  systemd.shutdownRamfs.enable = false;
  systemd.services.prepare-kexec.enable = false;
  services.dbus.enable = true;
  # PID 1 checks both dbus.socket and dbus.service before connecting its
  # manager API. Keep the package's socket-activated, notify-ready units.
  systemd.services.gemini-manager-bus-check = {
    description = "Verify PID 1 owns the system D-Bus manager API";
    wantedBy = ["multi-user.target"];
    after = ["dbus.service"];
    requires = ["dbus.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "35s";
    };
    script = ''
      for attempt in $(${pkgs.busybox}/bin/busybox seq 1 10); do
        if ${config.systemd.package}/bin/busctl --system --timeout=2 call \
          org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus \
          GetConnectionUnixProcessID s org.freedesktop.systemd1 \
          | ${pkgs.busybox}/bin/busybox grep -Fxq 'u 1'; then
          echo 'manager-system-bus=pid1' > /run/gemini-manager-bus
          exit 0
        fi
        ${pkgs.busybox}/bin/busybox sleep 1
      done
      exit 1
    '';
  };
  systemd.services.sshd = {
    # Order after both recovery paths have had a chance to configure, but do
    # not make the independent right-port Ethernet SSH path depend on usb0.
    # A failed gadget address must not suppress sshd on an RTL815x DHCP lease.
    after = [
      "gemini-mainline-usb.service"
      "gemini-unattended-recovery-lease-enforcer.service"
      "gemini-watchdog-takeover.service"
      "gemian.mount"
    ];
    requires = [
      "gemini-watchdog-takeover.service"
    ];
  };

  # Stage 1 writes a monotonic deadline into /run before switch_root.  This
  # service owns no watchdog descriptor, so it survives the Stage-2 takeover
  # and can independently stop whichever atomically-published PID owns it.
  # The only bypass is the exact external acceptance marker in volatile /run.
  systemd.services.gemini-unattended-recovery-lease-enforcer = {
    description = "Enforce the Gemini unattended recovery watchdog deadline";
    wantedBy = ["multi-user.target"];
    before = ["gemini-watchdog-takeover.service" "sshd.service" "gemini-mainline-success.service"];
    serviceConfig = {
      Type = "simple";
      Restart = "on-failure";
      RestartSec = "1s";
      KillMode = "process";
    };
    script = ''
      # The activated NixOS root only guarantees /bin/sh.  Keep the helper's
      # internal BusyBox invocations on the same store path as this wrapper.
      export GEMINI_LEASE_BUSYBOX=${pkgs.busybox}/bin/busybox
      exec ${pkgs.busybox}/bin/busybox sh ${../nix/unattended-recovery-lease-enforcer.sh}
    '';
  };

  # Stage 1 keeps the nowayout watchdog alive while systemd starts.  Replace
  # that petter before exposing SSH.  The independent lease enforcer is
  # ordered first, so it can publish expiry before this service opens a new
  # watchdog descriptor.
  systemd.services.gemini-watchdog-takeover = {
    description = "Take over the Gemini unattended recovery watchdog";
    wantedBy = ["multi-user.target"];
    before = ["sshd.service" "gemini-mainline-success.service"];
    after = ["gemini-unattended-recovery-lease-enforcer.service"];
    requires = ["gemini-unattended-recovery-lease-enforcer.service"];
    serviceConfig = {
      Type = "forking";
      PIDFile = "/run/unattended-recovery.watchdog-owner";
      Restart = "no";
      TimeoutStartSec = "20s";
      KillSignal = "SIGKILL";
    };
    script = ''
      owner_file=/run/unattended-recovery.watchdog-owner
      expired=/run/unattended-recovery.lease-expired
      test ! -e "$expired"
      old_pid=$(${pkgs.busybox}/bin/busybox cat "$owner_file")
      test -n "$old_pid"
      case "$old_pid" in
        *[!0-9]*) exit 1 ;;
      esac

      owns_watchdog=
      for fd in /proc/"$old_pid"/fd/*; do
        target=$(${pkgs.busybox}/bin/busybox readlink "$fd" 2>/dev/null || true)
        case "$target" in
          /dev/watchdog|/dev/watchdog0) owns_watchdog=yes ;;
        esac
      done
      test "$owns_watchdog" = yes
      ${pkgs.busybox}/bin/busybox kill -KILL "$old_pid" 2>/dev/null || true
      attempt=0
      while [ -d /proc/"$old_pid" ] && [ "$attempt" -lt 50 ]; do
        attempt=$((attempt + 1))
        ${pkgs.busybox}/bin/busybox sleep 0.1
      done
      test ! -d /proc/"$old_pid"
      test ! -e "$expired"

      ${pkgs.busybox}/bin/busybox watchdog \
        -F -t 10 -T 31 /dev/watchdog \
        > /run/watchdog-stage2.log 2>&1 &
      new_pid=$!
      ${pkgs.busybox}/bin/busybox sleep 1
      ${pkgs.busybox}/bin/busybox kill -0 "$new_pid"

      owns_watchdog=
      for fd in /proc/"$new_pid"/fd/*; do
        target=$(${pkgs.busybox}/bin/busybox readlink "$fd" 2>/dev/null || true)
        case "$target" in
          /dev/watchdog|/dev/watchdog0) owns_watchdog=yes ;;
        esac
      done
      if [ "$owns_watchdog" != yes ] || [ -e "$expired" ]; then
        ${pkgs.busybox}/bin/busybox kill -KILL "$new_pid" 2>/dev/null || true
        exit 1
      fi
      echo "$new_pid" > "$owner_file.new"
      test ! -e "$expired"
      ${pkgs.busybox}/bin/busybox mv "$owner_file.new" "$owner_file"
    '';
  };

  # The Stage-1 copy runs before the root handoff.  Repeat only the same
  # sysfs metadata inventory after systemd has settled, so a remote reviewer
  # can compare input, I2C-adapter, and thermal-zone presence without opening
  # an event/I2C device or changing the touchscreen's disabled-client gate.
  systemd.services.gemini-input-observe = {
    description = "Record Gemini input-board metadata without bus transfers";
    wantedBy = ["multi-user.target"];
    after = ["gemini-watchdog-takeover.service" "systemd-udevd.service"];
    before = ["sshd.service" "gemini-mainline-success.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      ${pkgs.busybox}/bin/busybox sh ${../nix/input-observe.sh} stage2
    '';
  };

  systemd.services.gemini-mainline-success = {
    description = "Record mainline NixOS stage-2 success in volatile state";
    wantedBy = ["multi-user.target"];
    after = ["sshd.service"];
    serviceConfig.Type = "oneshot";
    script = ''
      {
        echo "mainline NixOS reached multi-user.target"
        uname -a
        ${pkgs.gnugrep}/bin/grep -F ' /gemian ' /proc/mounts
        echo "watchdog-owner=$(${pkgs.busybox}/bin/busybox cat /run/unattended-recovery.watchdog-owner)"
        echo "watchdog-state=$(${pkgs.busybox}/bin/busybox cat /sys/class/watchdog/watchdog0/state)"
      } > /run/gemini-mainline-success
      echo "GEMINI_MAINLINE_NIXOS: stage2=multi-user watchdog=petting acceptance=${if geminiLeaseSelfAcceptToken == null then "external" else "baseline-self-accept-pending"}" \
        >> /run/stage1.log
    '';
  };

  # This intentionally exists only in the full known-good baseline.  A token
  # is an explicit build-time capability carried by the Android boot cmdline;
  # it is not a secret.  The helper refuses to create the existing acceptance
  # marker unless the cmdline, Stage-1-pinned Stage-2 identity, both network
  # paths, read-only mounts, watchdog owner, power preflight and unit health
  # all match.  Images without this module argument retain external-only,
  # fail-closed acceptance.
  systemd.services.gemini-baseline-self-accept = lib.mkIf (geminiLeaseSelfAcceptToken != null) {
    description = "Self-accept the reviewed Gemini full-NixOS watchdog lease";
    requires = ["gemini-manager-bus-check.service"];
    wantedBy = ["multi-user.target"];
    after = [
      "gemini-mainline-success.service"
      "gemini-manager-bus-check.service"
      "gemini-watchdog-takeover.service"
      "gemini-mainline-usb.service"
      "gemini-input-observe.service"
      "sshd.service"
      "gemian.mount"
    ];
    serviceConfig = {
      Type = "oneshot";
      Restart = "on-failure";
      RestartSec = "2s";
    };
    script = ''
      export GEMINI_BASELINE_ACCEPT_BUSYBOX=${pkgs.busybox}/bin/busybox
      export GEMINI_BASELINE_ACCEPT_TOKEN=${lib.escapeShellArg geminiLeaseSelfAcceptToken}
      export GEMINI_BASELINE_ACCEPT_STORE=persistent
      exec ${pkgs.busybox}/bin/busybox sh ${../nix/unattended-recovery-baseline-self-accept.sh}
    '';
  };

  # Diagnostics only (never gates, always exits 0): records what the gate
  # above is waiting on in /run/gemini-baseline-self-accept.watch, and one
  # kmsg/pmsg line per change, so a gate that never runs is explained.
  systemd.services.gemini-baseline-self-accept-watch = lib.mkIf (geminiLeaseSelfAcceptToken != null) {
    description = "Record why the Gemini baseline self-accept has not happened";
    wantedBy = ["multi-user.target"];
    serviceConfig = {
      Type = "simple";
      Restart = "no";
    };
    script = ''
      export GEMINI_SELF_ACCEPT_WATCH_BUSYBOX=${pkgs.busybox}/bin/busybox
      export GEMINI_SELF_ACCEPT_WATCH_SYSTEMCTL=${config.systemd.package}/bin/systemctl
      export GEMINI_SELF_ACCEPT_WATCH_JOURNALCTL=${config.systemd.package}/bin/journalctl
      exec ${pkgs.busybox}/bin/busybox sh ${../nix/unattended-recovery-self-accept-watch.sh}
    '';
  };

  security.audit.enable = false;
  security.sudo.enable = false;
  services.logrotate.enable = false;
  services.lvm.enable = false;
  services.timesyncd.enable = true;
  services.journald.extraConfig = "Storage=volatile";
  services.resolved.enable = false;
  systemd.packages = [pkgs.dbus];
  systemd.sockets.dbus.wantedBy = ["sockets.target"];
  boot.enableContainers = false;
  programs.command-not-found.enable = false;
  programs.less.enable = lib.mkForce false;
  programs.nano.syntaxHighlight = false;
  documentation.enable = false;
  documentation.man.enable = false;
  documentation.nixos.enable = false;
  # Nix itself is enabled by storage.nix (writable store on p32).
  system.disableInstallerTools = true;
  fonts.fontconfig.enable = true;
  i18n.defaultLocale = "en_US.UTF-8";
  environment.defaultPackages = [];
  # Diagnostic tools are ordinary additions to the shared system profile.
  environment.systemPackages = [
    pkgs.busybox
    pkgs.btop
    config.systemd.package
    pkgs.iproute2
    pkgs.usbutils
    pkgs.ethtool
    pkgs.iw
    pkgs.wpa_supplicant
    # The MT6797/MT6351 ASoC card already registers with a full AFE -- three
    # playback, four capture and two hostless PCMs, all bound -- but the image
    # had no ALSA userspace at all, so none of it could be exercised.  aplay,
    # arecord, amixer and speaker-test are what turn "the card enumerates" into
    # "audio works".
    pkgs.alsa-utils
    config.system.build.geminiAudioControls
    # M42: load the SPM driver with its firmware path (nixos/spm.nix).
    config.system.build.geminiSpmLoad
    # Core parking daemon, for --dry-run and --help by hand.
    config.system.build.geminiCoreParking
    # Touch/I2C debugging: i2ctransfer/i2cget need CONFIG_I2C_CHARDEV.
    pkgs.i2c-tools
    pkgs.evtest
  ]
  # bluetoothctl, btmgmt, btmon and the hci tools when Bluetooth is enabled.
  ++ lib.optional config.hardware.bluetooth.enable config.hardware.bluetooth.package;
  environment.binsh = "${pkgs.bash}/bin/sh";
  environment.shells = ["${pkgs.busybox}/bin/ash"];

  system.stateVersion = "23.05";
}
