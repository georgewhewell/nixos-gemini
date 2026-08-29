# NixOS configuration for Planet Computers Gemini PDA
#
# Stage 1 supplies the known-good Gemian kernel and mounts this system's Nix
# store read-only. Stage 2 is intentionally small and remains observable over
# ConnMan/Wi-Fi and SSH.
{
  config,
  pkgs,
  lib,
  ...
}: {
  # Several generic NixOS modules ask for the feature-rich util-linux package.
  # Its minimal variant has every tool this image needs and avoids pulling a
  # second, full systemd build into the target closure.
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
      wpa_supplicant = prev.wpa_supplicant.override {
        withPcsclite = false;
        withReadline = false;
      };
      # The 23.05 swraid module references mdadm unconditionally, even with
      # the custom initramfs disabled. This machine has no software RAID; a
      # deliberately failing executable satisfies udev's rule validation
      # without retaining mdadm and its full-systemd dependency.
      mdadm = prev.runCommand "mdadm-disabled" {} ''
        mkdir -p $out/sbin
        cp ${final.writeShellScript "mdadm-disabled" "exit 1"} $out/sbin/mdadm
        ln -s mdadm $out/sbin/mdmon
      '';
    })
  ];

  # The Android boot image supplies both kernel and initramfs.
  boot.kernel.enable = false;
  boot.initrd.enable = false;
  boot.hardwareScan = false;
  boot.bootspec.enable = false;
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = false;
  system.boot.loader.kernelFile = "Image.gz-dtb";

  # The initramfs has already mounted these before starting NixOS. Declaring
  # them keeps systemd's mount ordering and the generated filesystem model
  # honest.
  fileSystems."/" = {
    device = "tmpfs";
    fsType = "tmpfs";
    options = ["mode=0755" "size=768M"];
  };
  fileSystems."/gemian" = {
    device = "/dev/mmcblk0p29";
    fsType = "ext4";
    options = ["rw" "nofail"];
  };
  fileSystems."/system" = {
    # The stock WMT launcher is a 32 KiB Bionic executable. Mount the existing
    # Gemian Android system image read-only for its linker and five libraries;
    # no Android init, framework, application, or container is started.
    device = "/gemian/data/system.img";
    fsType = "ext4";
    options = ["loop" "ro" "nofail"];
    depends = ["/gemian"];
    noCheck = true;
  };
  # Gemian's host-side droid-hal-init mounts these calibration partitions
  # before enabling the MediaTek connectivity block.  They are hardware state,
  # not Android userspace, and the WMT/Wi-Fi path expects them at these names.
  fileSystems."/nvcfg" = {
    device = "/dev/disk/by-partlabel/nvcfg";
    fsType = "ext4";
    options = ["rw" "noatime" "nosuid" "nodev" "noauto_da_alloc" "commit=1" "nodelalloc"];
  };
  fileSystems."/nvdata" = {
    device = "/dev/disk/by-partlabel/nvdata";
    fsType = "ext4";
    options = ["rw" "noatime" "nosuid" "nodev" "noauto_da_alloc" "discard"];
  };
  # Bionic's linker and vendor helpers were built for Android's conventional
  # absolute paths. Keep the compatibility surface to two symlinks into the
  # already-mounted Gemian partition; Android init and services remain absent.
  systemd.tmpfiles.rules = [
    "L+ /vendor - - - - /system/vendor"
    "L+ /data - - - - /gemian/data"
  ];
  fileSystems."/var/lib/connman" = {
    device = "/gemian/var/lib/connman";
    fsType = "none";
    options = ["bind"];
  };

  # systemd 253 still runs on 3.18, but cgroup v2 does not exist there.
  # NixOS 23.05 unconditionally wires the logind/user-session units into its
  # generated unit set. Start with systemd-minimal, restore only logind and its
  # PAM-coupled user-sessions helper so that set is internally complete, and
  # continue omitting networkd, resolved, coredump, importd, machined, homed,
  # documentation, and the rest.
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

  # dbus is deliberately built without libsystemd support so that it does not
  # pull a second, full systemd into this tiny image.  That also means its
  # upstream socket-activated units are absent, so run the daemon directly and
  # order the two consumers that must not race it at boot.
  services.dbus.enable = true;
  services.dbus.packages = [config.services.connman.package];
  systemd.services.dbus = {
    description = "D-Bus System Message Bus";
    wantedBy = ["multi-user.target"];
    before = ["systemd-logind.service" "connman.service"];
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

  # Reuse Gemian's ConnMan state. This keeps the existing Wi-Fi credentials
  # out of both the Git tree and the world-readable Nix store.
  networking.hostName = "gemini-nixos";
  networking.useDHCP = false;
  networking.firewall.enable = false;
  networking.networkmanager.enable = false;
  services.connman = {
    enable = true;
    enableVPN = false;
    package = pkgs.connmanMinimal;
    # rndis0 is our deliberately static recovery link. ConnMan should manage
    # Wi-Fi and the right-port USB NIC, but must not rewrite the gadget address.
    networkInterfaceBlacklist = ["rndis0" "ifb" "ve"];
  };
  systemd.services.connman = {
    after = ["dbus.service" "var-lib-connman.mount"];
    requires = ["dbus.service" "var-lib-connman.mount"];
    # The dbus package has no socket-activation unit in this minimal build.
    # Type=simple keeps ConnMan ordered behind the always-running bus without
    # systemd adding an implicit dependency on the absent dbus.socket.
    serviceConfig.Type = lib.mkForce "simple";
  };

  # MT6797 connectivity is built into the kernel, but its command/firmware
  # handshake is completed by these two tiny vendor helpers. They execute from
  # the read-only /system image with the normal NixOS firmware directory.
  systemd.services.gemini-wmt = {
    description = "Diagnose the Gemini MT6797 connectivity subsystem";
    after = ["system.mount" "nvcfg.mount" "nvdata.mount" "systemd-tmpfiles-setup.service" "systemd-udevd.service"];
    requires = ["system.mount" "nvcfg.mount" "nvdata.mount"];
    unitConfig.ConditionPathExists = "/system/vendor/bin/wmt_launcher";
    environment = {
      ANDROID_ROOT = "/system";
      ANDROID_DATA = "/gemian/data";
      ANDROID_STORAGE = "/storage";
    };
    # Android's launcher waits forever for service.wcn.driver.ready when no
    # Android property service exists.  Copy it to /run and change its initial
    # branch from the property polling loop to the existing /dev/stpwmt open
    # path.  Both hashes pin this to the exact vendor binary and instruction.
    preStart = ''
      source=/system/vendor/bin/wmt_launcher
      target=/run/gemini-wmt-launcher
      echo "79ec10a6cc96642c042a6ae160d838e5b5a9cb63e6447f1761fc6a78000ac8bc  $source" \
        | ${pkgs.coreutils}/bin/sha256sum --check --status
      ${pkgs.coreutils}/bin/install -m 0755 "$source" "$target"
      ${pkgs.coreutils}/bin/printf '\032\000\000\024' \
        | ${pkgs.coreutils}/bin/dd of="$target" bs=1 seek=9816 conv=notrunc status=none
      echo "efee6b5da6cefea4f6dcc4728cc72f4894d6362257d7a9aa79ceb0849661ca4a  $target" \
        | ${pkgs.coreutils}/bin/sha256sum --check --status
      /system/vendor/bin/wmt_loader || true
    '';
    # This is deliberately opt-in: the launcher cannot find the vendor patch
    # through the Android-free handshake, leaves mtk_wmtd blocked in the
    # kernel, and never creates wlan0. Gemian next writes 1 to /dev/wmtWifi
    # after its Android container starts; without the rest of that Android-side
    # initialization the write reproducibly panics this vendor kernel. Keep the
    # diagnostic available as `systemctl start gemini-wmt`, but do not touch
    # the connectivity coprocessor during an ordinary boot.
    serviceConfig = {
      Type = "simple";
      ExecStart = "/run/gemini-wmt-launcher -p ${config.hardware.firmware}/lib/firmware/";
      Restart = "on-failure";
      RestartSec = "2s";
    };
  };

  # The left USB-C port is a legacy Android gadget controller; this kernel has
  # no configfs gadget support. RNDIS gives us a deterministic SSH recovery
  # path even when Wi-Fi and the right-port NIC are unavailable.
  environment.etc."udhcpd-gemini.conf".text = ''
    start 10.15.19.100
    end 10.15.19.254
    interface rndis0
    option subnet 255.255.255.0
    option router 10.15.19.82
    option dns 10.15.19.82
    max_leases 155
    lease_file /run/udhcpd-gemini.leases
    pidfile /run/udhcpd-gemini.pid
  '';
  systemd.services.gemini-usb-gadget = {
    description = "Configure the Gemini left-port RNDIS recovery gadget";
    wantedBy = ["multi-user.target"];
    before = ["gemini-usb-dhcp.service"];
    after = ["systemd-udevd.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      gadget=/sys/class/android_usb/android0
      attempt=0
      while [ ! -e "$gadget/enable" ] && [ "$attempt" -lt 15 ]; do
        attempt=$((attempt + 1))
        sleep 1
      done
      test -e "$gadget/enable"

      echo 0 > "$gadget/enable"
      echo 0fce > "$gadget/idVendor"
      echo 7169 > "$gadget/idProduct"
      echo "GNU/Linux Device" > "$gadget/iManufacturer"
      echo "Gemini NixOS" > "$gadget/iProduct"
      echo "0123456789ABCDEF" > "$gadget/iSerial"
      echo rndis > "$gadget/functions"
      echo 1 > "$gadget/enable"

      attempt=0
      while [ ! -e /sys/class/net/rndis0 ] && [ "$attempt" -lt 15 ]; do
        attempt=$((attempt + 1))
        sleep 1
      done
      test -e /sys/class/net/rndis0
      ${pkgs.iproute2}/bin/ip link set rndis0 up
      ${pkgs.iproute2}/bin/ip address replace 10.15.19.82/24 dev rndis0
    '';
  };
  systemd.services.gemini-usb-dhcp = {
    description = "Serve DHCP on the Gemini RNDIS recovery link";
    wantedBy = ["multi-user.target"];
    after = ["gemini-usb-gadget.service"];
    requires = ["gemini-usb-gadget.service"];
    serviceConfig = {
      Type = "simple";
      ExecStartPre = "${pkgs.busybox}/bin/busybox touch /run/udhcpd-gemini.leases";
      ExecStart = "${pkgs.busybox}/bin/busybox udhcpd -f /etc/udhcpd-gemini.conf";
      Restart = "on-failure";
    };
  };

  # Headless recovery access. The login key is public, and the existing
  # Gemian host keys keep SSH identity stable across the two systems.
  services.openssh = {
    enable = true;
    settings = {
      KbdInteractiveAuthentication = false;
      PasswordAuthentication = false;
      PermitRootLogin = "prohibit-password";
      # PAM permits public-key login to the deliberately password-locked root
      # account. PasswordAuthentication remains disabled, so this does not
      # expose password login.
      UsePAM = true;
    };
    hostKeys = [
      {
        type = "ed25519";
        path = "/gemian/etc/ssh/ssh_host_ed25519_key";
      }
      {
        type = "rsa";
        bits = 4096;
        path = "/gemian/etc/ssh/ssh_host_rsa_key";
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

  # Leave a durable success marker that is readable from Gemian after any
  # failed experiment.
  systemd.services.gemini-boot-success = {
    description = "Record a successful Gemini NixOS stage-2 boot";
    wantedBy = ["multi-user.target"];
    after = ["local-fs.target"];
    serviceConfig.Type = "oneshot";
    script = ''
      {
        echo "NixOS stage 2 reached multi-user.target"
        date -u
        uname -a
      } >> /gemian/nixos-boot.log
    '';
  };

  # Keep the cross-compiled closure deliberately small.
  security.audit.enable = false;
  security.sudo.enable = false;
  services.nscd.enable = false;
  services.logrotate.enable = false;
  services.udisks2.enable = false;
  services.lvm.enable = false;
  services.timesyncd.enable = false;
  services.journald.extraConfig = "Storage=volatile";
  services.resolved.enable = false;
  # systemd-minimal intentionally ships no upstream hwdb. The right-port
  # recovery NIC is an RTL8153 (0bda:8153); its r8152 driver is built into the
  # byte-exact Gemian kernel, so only userspace identification belongs here.
  # One real entry also keeps NixOS's generated hwdb valid without retaining
  # the multi-megabyte database.
  services.udev.extraHwdb = ''
    usb:v0BDAp8153*
     ID_MODEL_FROM_DATABASE=Realtek RTL8153 Gigabit Ethernet adapter
  '';
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
  environment.systemPackages = lib.mkForce [pkgs.busybox];
  # Keep NixOS's /bin/sh Bash-compatible without retaining the much larger
  # interactive Bash output; root's actual login shell is BusyBox ash above.
  environment.binsh = "${pkgs.bash}/bin/sh";
  environment.shells = lib.mkForce ["${pkgs.busybox}/bin/ash"];

  system.stateVersion = "23.05";
}
