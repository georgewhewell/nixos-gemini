# Experimental volatile cellular service for the CI9 full NixOS image.
{ pkgs, lib, geminiCellularHelper, ... }:
let
  runtimePath = lib.makeBinPath [pkgs.coreutils pkgs.diffutils pkgs.gnugrep pkgs.gnused pkgs.util-linux pkgs.systemd];
  restore = pkgs.writeShellScript "gemini-cellular-restore" ''
    exec ${pkgs.python3}/bin/python3 ${geminiCellularHelper}/share/gemini/mt6797_fs_restore_register.py "$@"
  '';
  rawRunner = pkgs.writeShellScript "gemini-cellular-stage2" ''
    export PATH=${runtimePath}:$PATH
    export GEMINI_CELLULAR_RESTORE=${restore}
    export GEMINI_CELLULAR_HELPER=${geminiCellularHelper}/bin/mt6797-fs-register
    export GEMINI_CELLULAR_BUSYBOX=${pkgs.busybox}/bin/busybox
    exec ${pkgs.busybox}/bin/busybox sh ${../nix/cellular-stage2.sh} "$@"
  '';
  runner = pkgs.runCommand "gemini-cellular-stage2-checked" {} ''
    for command in cat grep systemctl tr readlink wc sed sha256sum mkdir timeout mount cp sleep dmesg cmp mv; do
      found=no
      for directory in ${lib.replaceStrings [":"] [" "] runtimePath}; do
        if test -x "$directory/$command"; then found=yes; break; fi
      done
      test "$found" = yes || { echo "missing cellular runtime command: $command"; exit 1; }
    done
    cp ${rawRunner} "$out"
    chmod 0555 "$out"
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
      TimeoutStartSec = "310s";
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
