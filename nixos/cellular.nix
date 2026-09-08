# Experimental volatile cellular service for the CI1 full NixOS image.
{ pkgs, lib, geminiCellularHelper, ... }:
let
  runner = pkgs.writeShellScript "gemini-cellular-stage2" ''
    export PATH=${lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gnused pkgs.util-linux pkgs.systemd]}:$PATH
    export GEMINI_CELLULAR_HELPER=${geminiCellularHelper}/bin/mt6797-fs-register
    export GEMINI_CELLULAR_BUSYBOX=${pkgs.busybox}/bin/busybox
    exec ${pkgs.busybox}/bin/busybox sh ${../nix/cellular-stage2.sh} "$@"
  '';
in {
  systemd.services.gemini-cellular = {
    description = "Qualify Gemini cellular HS2 and AT on bounded volatile storage";
    wantedBy = ["multi-user.target"];
    after = ["gemini-watchdog-takeover.service" "gemini-mainline-usb.service" "gemian.mount"];
    requires = ["gemini-watchdog-takeover.service" "gemian.mount"];
    before = ["gemini-baseline-self-accept.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "190s";
      ExecStart = runner;
      UMask = "0077";
    };
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["gemini-cellular.service"];
    requires = ["gemini-cellular.service"];
    # The ordinary baseline gate retains final lease locking/publication.
    # Recheck actual same-boot protocol evidence and live state before it runs.
    script = lib.mkBefore ''
      ${pkgs.systemd}/bin/systemctl is-active --quiet gemini-cellular.service
      ${runner} --verify
    '';
  };
}
