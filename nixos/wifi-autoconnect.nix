{ pkgs, ... }:
{
  # wpa_supplicant 2.10 omits NL80211_ATTR_SOCKET_OWNER from CONNECT unless the
  # driver offers control-port RX, so the kernel refuses SAE external
  # authentication for mt6797-wifi. Backport the 2.11 behaviour; WPA2-PSK
  # connects never use the connect handle and are unchanged.
  nixpkgs.overlays = [
    (final: prev: {
      wpa_supplicant = prev.wpa_supplicant.overrideAttrs (old: {
        patches = (old.patches or []) ++ [../patches/wpa_supplicant-2.10-sae-connect-owner.patch];
      });
    })
  ];

  # Type=simple becomes active while the worker waits for acceptance. An
  # After=baseline-self-accept edge would cycle with its boot-health check.
  systemd.services.gemini-wifi = {
    description = "Connect Gemini Wi-Fi using its saved automatic profile";
    wantedBy = ["multi-user.target"];
    after = ["gemini-connectivity.service"];
    # WPA2-PSK by default. `systemctl set-environment GEMINI_WIFI_SAE=prefer`
    # then a restart uses WPA3-SAE (PMF required) for APs offering SAE when the
    # saved profile holds a passphrase; unset-environment reverts.
    serviceConfig = {
      Type = "simple";
      ExecStart = "${pkgs.python3}/bin/python3 ${../nix/wifi-autoconnect.py}";
      Restart = "on-failure";
      RestartSec = "30s";
      RuntimeDirectory = "gemini-wifi";
      RuntimeDirectoryMode = "0700";
      UMask = "0077";
      TimeoutStopSec = "90s";
      # The worker stops and reaps its child on TERM, including disconnect.
      KillMode = "mixed";
    };
    path = [pkgs.iw pkgs.wpa_supplicant];
  };
}
