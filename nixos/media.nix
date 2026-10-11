# Hardware JPEG codec (mtk-jpeg) behind the MT6797 M4U.
#
# Keep codec registration after watchdog takeover; the existing service
# loads mtk_jpeg explicitly and checks both codec nodes.
{ pkgs, geminiGpuKernel, ... }:
let
  load = pkgs.writeShellScript "gemini-jpeg-load" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.kmod]}:$PATH
    modprobe -d ${geminiGpuKernel} mtk_jpeg
    for name in mtk-jpeg-dec mtk-jpeg-enc; do
      grep -qxF "$name" /sys/class/video4linux/video*/name
    done
    echo 'jpeg=mtk-jpeg-dec,mtk-jpeg-enc'
  '';
in {
  boot.blacklistedKernelModules = ["mtk_jpeg"];
  systemd.services.gemini-jpeg = {
    description = "Gemini hardware JPEG codec";
    wantedBy = ["multi-user.target"];
    after = ["gemini-watchdog-takeover.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = load;
    };
  };
}
