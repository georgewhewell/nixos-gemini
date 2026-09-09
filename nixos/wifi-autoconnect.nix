{ pkgs, ... }:
{
  # Type=simple becomes active while the worker waits for acceptance. An
  # After=baseline-self-accept edge would cycle with its boot-health check.
  systemd.services.gemini-wifi = {
    description = "Connect Gemini Wi-Fi using its saved automatic profile";
    wantedBy = ["multi-user.target"];
    after = ["gemini-connectivity.service"];
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
