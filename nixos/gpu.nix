# Load Panfrost only after the watchdog, A72 and modem startup have completed.
{ pkgs, geminiGpuKernel, geminiGpuSmoke, ... }:
let
  qualify = pkgs.writeShellScript "gemini-gpu-qualify" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.kmod pkgs.systemd pkgs.util-linux]}:$PATH
    grep -wFq GEMINI_A72_CI9_M13 /proc/cmdline
    test "$(cat /sys/devices/system/cpu/online)" = 0-9
    systemctl is-active --quiet gemini-watchdog-takeover.service gemini-cellular.service
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    mkdir /run/gemini-gpu
    cat /proc/sys/kernel/random/boot_id > /run/gemini-gpu/boot-id
    modprobe -d ${geminiGpuKernel} panfrost
    gpu=/sys/bus/platform/devices/13040000.gpu
    test "$(basename "$(readlink -f "$gpu/driver")")" = panfrost
    set -- "$gpu"/drm/renderD*
    test "$#" -eq 1
    node=/dev/dri/$(basename "$1")
    test -c "$node"
    for pass in 1 2; do
      timeout --signal=TERM --kill-after=3 30 ${geminiGpuSmoke}/bin/gpu-render-smoke "$node" > /run/gemini-gpu/render-$pass.txt 2>&1
      cat /run/gemini-gpu/render-$pass.txt
      grep -Fxq 'GPU_RENDER_PASS backend=panfrost draws=2 pixels=8192' /run/gemini-gpu/render-$pass.txt
      count=0
      while test "$(cat "$gpu/power/runtime_status")" != suspended; do
        count=$((count + 1))
        test "$count" -lt 50
        sleep 0.1
      done
      echo "autosuspend=$pass pass=yes"
    done
    dmesg > /run/gemini-gpu/kernel.txt
    if grep -Ei 'GPULDO_FIRST_FAILURE|GPU_RENDER_FAIL|rcu.*detected stalls|Kernel panic|BUG:|Unable to handle kernel' /run/gemini-gpu/kernel.txt; then exit 1; fi
    echo 'gpu=render-and-autosuspend-pass' > /run/gemini-gpu/result
  '';
in {
  environment.etc."gemini/gpu-render".source = "${geminiGpuSmoke}/bin/gpu-render-smoke";
  systemd.services.gemini-gpu = {
    description = "Qualify Panfrost rendering and runtime autosuspend";
    wantedBy = ["multi-user.target"];
    after = ["gemini-cellular.service" "gemini-watchdog-takeover.service"];
    requires = ["gemini-cellular.service" "gemini-watchdog-takeover.service"];
    before = ["gemini-baseline-self-accept.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "100s";
      UMask = "0077";
      ExecStart = qualify;
    };
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["gemini-gpu.service"];
    requires = ["gemini-gpu.service"];
  };
}
