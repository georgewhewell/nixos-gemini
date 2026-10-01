# Hardware JPEG codec (mtk-jpeg) behind the MT6797 M4U.
#
# Modules are loaded explicitly on this image (no udev autoload from the
# kernel closure); load mtk_jpeg once boot recovery has settled and check
# that both codec nodes registered.
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
