# M42: MT6797 SPM PCM programs and read-only SPM/CPU idle status.
#
# mt6797-spm is blacklisted on the kernel command line and never autoloads.
# gemini-spm-load points the firmware loader at the SPM images only while the
# module probes, then restores the previous path (gemini-connectivity owns it
# for Wi-Fi), and prints what the driver accepted.  The driver never writes
# SPM registers.
{ pkgs, geminiSpmKernel, geminiSpmFirmware, ... }:
let
  load = pkgs.writeShellScriptBin "gemini-spm-load" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.kmod pkgs.util-linux]}:$PATH
    param=/sys/module/firmware_class/parameters/path
    previous=$(cat "$param")
    restore() { printf '%s' "$previous" > "$param"; }
    trap restore EXIT
    printf '%s' ${geminiSpmFirmware}/lib/firmware > "$param"
    modprobe -d ${geminiSpmKernel} mt6797-spm
    restore
    trap - EXIT
    mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug
    dir=/sys/kernel/debug/spm
    cat "$dir/firmware"
    test "$(grep -c ' status=0 ' "$dir/firmware")" = 9
    echo 'spm=loaded-9-of-9-pcm-images'
  '';
in {
  environment.systemPackages = [load];
}
