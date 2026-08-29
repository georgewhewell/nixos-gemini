# Minimal NixOS stage 2 for the mainline MT6797 kernel.  Stage 1 supplies a
# tmpfs root, a read-only SquashFS /nix/store, and p29 at /gemian with ext4
# journal replay disabled.  Nothing in this configuration writes persistent
# storage.
{
  config,
  pkgs,
  lib,
  ...
}: {
  nixpkgs.overlays = [
    (final: prev: {
      util-linux = prev.util-linux.override {
        nlsSupport = false;
        ncursesSupport = false;
        systemdSupport = false;
        translateManpages = false;
      };
      dbus = prev.dbus.override {
        enableSystemd = false;
      };
      # NixOS 23.05's swraid module references these paths even though this
      # system has no software RAID and the initramfs is supplied separately.
      mdadm = prev.runCommand "mdadm-disabled" {} ''
        mkdir -p $out/sbin
        cp ${final.writeShellScript "mdadm-disabled" "exit 1"} $out/sbin/mdadm
        ln -s mdadm $out/sbin/mdmon
      '';
    })
  ];

  # LK supplies the Android-v0 container; the custom stage 1 supplies the
  # kernel, DTB, and initramfs.
  boot.kernel.enable = false;
  boot.initrd.enable = false;
  boot.hardwareScan = false;
  boot.bootspec.enable = false;
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = false;
  system.boot.loader.kernelFile = "Image.gz-dtb";

  fileSystems."/" = {
    device = "tmpfs";
    fsType = "tmpfs";
    options = ["mode=0755" "size=768M"];
  };
  fileSystems."/gemian" = {
    device = "/dev/mmcblk0p29";
    fsType = "ext4";
    options = ["ro" "noload" "nosuid" "nodev" "noexec" "nofail"];
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

  # NixOS 23.05's generated unit set expects logind and its PAM helper.  Keep
  # those small pieces plus a standalone D-Bus daemon, while omitting the rest
  # of the full systemd feature set.
  systemd.package = pkgs.systemdMinimal.override {
    bashInteractive = pkgs.bash;
    withLogind = true;
    withPam = true;
    withKexectools = false;
  };
  systemd.enableUnifiedCgroupHierarchy = false;
  systemd.coredump.enable = false;
  systemd.oomd.enable = false;
  systemd.shutdownRamfs.enable = false;
  systemd.services.prepare-kexec.enable = false;
  services.dbus.enable = true;
  systemd.services.dbus = {
    description = "D-Bus System Message Bus";
    wantedBy = ["multi-user.target"];
    before = ["systemd-logind.service"];
    serviceConfig = {
      Type = lib.mkForce "simple";
      ExecStart = lib.mkForce "${pkgs.dbus}/bin/dbus-daemon --system --nofork --nopidfile";
      RuntimeDirectory = "dbus";
      RuntimeDirectoryMode = "0755";
      Restart = "on-failure";
    };
  };
  systemd.services."systemd-logind" = {
    after = ["dbus.service"];
    requires = ["dbus.service"];
  };
  systemd.services.sshd = {
    after = ["gemini-mainline-usb.service" "gemian.mount"];
    requires = ["gemini-mainline-usb.service"];
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
      } > /run/gemini-mainline-success
    '';
  };

  security.audit.enable = false;
  security.polkit.enable = false;
  security.sudo.enable = false;
  services.nscd.enable = false;
  services.logrotate.enable = false;
  services.udisks2.enable = false;
  services.lvm.enable = false;
  services.timesyncd.enable = false;
  services.journald.extraConfig = "Storage=volatile";
  services.resolved.enable = false;
  systemd.packages = lib.mkForce [];
  boot.enableContainers = false;
  programs.command-not-found.enable = false;
  programs.less.enable = lib.mkForce false;
  programs.nano.syntaxHighlight = false;
  environment.noXlibs = true;
  documentation.enable = false;
  documentation.man.enable = false;
  documentation.nixos.enable = false;
  nix.enable = false;
  system.disableInstallerTools = true;
  xdg.icons.enable = false;
  xdg.mime.enable = false;
  xdg.sounds.enable = false;
  fonts.fontconfig.enable = false;
  i18n.defaultLocale = "C";
  i18n.supportedLocales = lib.mkForce [];
  i18n.glibcLocales = pkgs.runCommand "empty-locale-archive" {} ''
    mkdir -p $out/lib/locale
    touch $out/lib/locale/locale-archive
  '';
  system.nssModules = lib.mkForce [];
  environment.defaultPackages = lib.mkForce [];
  # Keep the runtime small, but retain the tools needed to diagnose this
  # bring-up without building another single-purpose image. The selected
  # systemd package is already in the closure for PID 1; adding it here merely
  # exposes systemctl/journalctl through the system profile.
  environment.systemPackages = lib.mkForce [
    pkgs.busybox
    config.systemd.package
    pkgs.iproute2
    pkgs.usbutils
    pkgs.ethtool
  ];
  environment.binsh = "${pkgs.bash}/bin/sh";
  environment.shells = lib.mkForce ["${pkgs.busybox}/bin/ash"];

  system.stateVersion = "23.05";
}
