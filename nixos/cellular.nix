# M5: accepted CI9 cellular service plus read-only A72 admission preflight.
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
  a72Preflight = pkgs.writeShellScript "gemini-a72-preflight" ''
    set -eu
    export PATH=${lib.makeBinPath [pkgs.coreutils pkgs.findutils pkgs.gawk pkgs.gnugrep pkgs.gnused pkgs.util-linux pkgs.systemd]}:$PATH
    grep -wFq GEMINI_A72_CI9_M5 /proc/cmdline
    systemctl is-active --quiet gemini-watchdog-takeover.service
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    test "$(cat /sys/class/watchdog/watchdog0/nowayout)" = 1
    test "$(cat /sys/class/watchdog/watchdog0/timeout)" = 31
    mkdir /run/gemini-a72-preflight
    exec > /run/gemini-a72-preflight/result 2>&1
    export EXPECTED_CPU8_STATUS=okay EXPECTED_CPU9_STATUS=okay
    exec ${pkgs.busybox}/bin/busybox sh ${geminiCellularHelper}/share/gemini/mt6797-a72-resource-preflight.sh
  '';
in {
  systemd.services.gemini-a72-preflight = {
    description = "Read-only Gemini A72 resource and admission preflight";
    after = ["gemini-watchdog-takeover.service"];
    requires = ["gemini-watchdog-takeover.service"];
    before = ["gemini-cellular.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "30s";
      UMask = "0077";
      ExecStart = a72Preflight;
    };
  };
  systemd.services.gemini-cellular = {
    description = "Qualify Gemini cellular HS2 and AT on bounded volatile storage";
    wantedBy = ["multi-user.target"];
    after = ["gemini-watchdog-takeover.service" "gemini-mainline-usb.service" "gemian.mount" "gemini-a72-preflight.service"];
    requires = ["gemini-watchdog-takeover.service" "gemian.mount" "gemini-a72-preflight.service"];
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
