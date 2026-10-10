{ lib, pkgs, ... }: {
  networking.networkmanager = {
    enable = true;
    dhcp = "internal";
    # Stage 1 and gemini-mainline-usb own the static rescue address.
    unmanaged = ["interface-name:usb0"];
    wifi = {
      macAddress = "preserve";
      scanRandMacAddress = false;
    };
    # The root filesystem is volatile; desktop-saved profiles must survive boot.
    settings.keyfile.path = "/persist/NetworkManager/system-connections";
    # Stage 1 leaves the wired link up. NM must take ownership and run DHCP,
    # rather than assume a link-local-only configuration is already complete.
    settings."device-wired" = {
      match-device = "type:ethernet";
      keep-configuration = false;
    };
    ensureProfiles.profiles.gemini-wired = {
      connection = {
        id = "Gemini wired";
        uuid = "24c64b22-7dd5-4d37-b7b0-4ae543d60264";
        type = "ethernet";
        autoconnect = true;
        autoconnect-priority = 10;
      };
      ipv4.method = "auto";
      ipv6.method = "auto";
    };
  };
  networking.modemmanager.enable = true;
  networking.dhcpcd.enable = false;
  users.users.gemini.extraGroups = ["networkmanager"];

  systemd.services.gemini-network-profiles = {
    description = "Import saved Gemian Wi-Fi profiles into NetworkManager";
    wantedBy = ["multi-user.target"];
    before = ["NetworkManager.service"];
    after = ["gemian.mount"];
    requires = ["gemian.mount"];
    unitConfig.ConditionPathIsMountPoint = "/persist";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      UMask = "0077";
      ExecStart = "${pkgs.python3}/bin/python3 ${../nix/networkmanager-import-wifi.py}";
    };
  };
  systemd.services.NetworkManager = {
    after = ["gemini-connectivity.service" "gemini-network-profiles.service"];
    requires = ["gemini-connectivity.service" "gemini-network-profiles.service"];
  };
  # Opening the desktop does not depend on finding an access point or a SIM.
  systemd.services.NetworkManager-wait-online.enable = false;
  # This kernel has no /dev/rfkill. Keep the supplicant's sandbox, with that
  # device optional so the same unit also works when rfkill is available.
  systemd.services.wpa_supplicant.serviceConfig.BindPaths = lib.mkForce [
    "/etc/wpa_supplicant"
    "/run/wpa_supplicant"
    "/proc/sys/net"
    "-/dev/rfkill"
    "/run/dbus"
  ];
  systemd.services.ModemManager = {
    wantedBy = ["multi-user.target"];
    after = ["gemini-cellular.service"];
    requires = ["gemini-cellular.service"];
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["NetworkManager.service" "ModemManager.service"];
    requires = ["NetworkManager.service" "ModemManager.service"];
  };
}
