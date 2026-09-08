# Load Panfrost only after the watchdog, A72 and modem startup have completed.
{ pkgs, geminiGpuKernel, geminiGpuSmoke, ... }:
let
  qualify = pkgs.writeShellScript "gemini-gpu-qualify" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.kmod pkgs.systemd pkgs.util-linux pkgs.gawk]}:$PATH
    grep -wFq GEMINI_A72_CI9_M13 /proc/cmdline
    test "$(cat /sys/devices/system/cpu/online)" = 0-9
    systemctl is-active --quiet gemini-watchdog-takeover.service gemini-cellular.service
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    mkdir /run/gemini-gpu
    cat /proc/sys/kernel/random/boot_id > /run/gemini-gpu/boot-id
    capture_final() {
      dmesg > /run/gemini-gpu/kernel-final.txt || :
      cat /proc/interrupts > /run/gemini-gpu/interrupts-final.txt || :
      cat /sys/kernel/debug/pm_genpd/pm_genpd_summary > /run/gemini-gpu/domains-final.txt || :
    }
    trap capture_final EXIT
    modprobe -d ${geminiGpuKernel} panfrost
    gpu=/sys/bus/platform/devices/13040000.gpu
    test "$(basename "$(readlink -f "$gpu/driver")")" = panfrost
    set -- "$gpu"/drm/renderD*
    test "$#" -eq 1
    node=/dev/dri/$(basename "$1")
    test -c "$node"
    irq_count() {
      awk -v name="$1" '$NF == name { found++; for (i=2; i<=NF && $i ~ /^[0-9]+$/; i++) total += $i } END { if (found != 1) exit 1; print total+0 }' "$2"
    }
    cat /proc/interrupts > /run/gemini-gpu/interrupts-before.txt
    previous_irqs=/run/gemini-gpu/interrupts-before.txt
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
      cat /sys/kernel/debug/pm_genpd/pm_genpd_summary > /run/gemini-gpu/domains-$pass.txt
      for domain in mfg_async mfg mfg_core0 mfg_core1 mfg_core2 mfg_core3; do
        awk -v domain="$domain" '$1 == domain && $2 ~ /^off/ { ok=1 } END { exit !ok }' /run/gemini-gpu/domains-$pass.txt
      done
      current_irqs=/run/gemini-gpu/interrupts-$pass.txt
      cat /proc/interrupts > "$current_irqs"
      jobs_before=$(irq_count panfrost-job "$previous_irqs")
      jobs_after=$(irq_count panfrost-job "$current_irqs")
      test "$jobs_after" -gt "$jobs_before"
      echo "job_irq_progress=$((jobs_after - jobs_before))"
      previous_irqs=$current_irqs
      echo "autosuspend=$pass pass=yes domains=all-six-off"
    done
    dmesg > /run/gemini-gpu/kernel.txt
    grep -Ev 'panfrost 13040000\.gpu: \[drm:panfrost_devfreq_init \[panfrost\]\] Failed to register cooling device$' /run/gemini-gpu/kernel.txt > /run/gemini-gpu/kernel-scoped.txt || test "$?" -eq 1
    if grep -Ei '(panfrost|13040000\.gpu|mfg|rt5735|vgpu).*(fault|error|timeout|timed out|failed|stuck)|(^|[[:space:]])(BUG:|Oops:|Call trace:)' /run/gemini-gpu/kernel-scoped.txt; then exit 1; fi
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
