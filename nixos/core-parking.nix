# A53 cpufreq at boot, and load-driven core parking (CPU hotplug).
#
# MT6797 has no per-core power-down idle state: BL31 removes core power only
# through PSCI CPU_OFF, i.e. CPU hotplug (handoff/m42-spm-idle.md,
# handoff/atf-custom-20260928.md).  The vendor kernel's HPS parked cores in
# the kernel; upstream Linux has no in-kernel hotplug governors, so this is a
# small userspace daemon (nix/core-parking.c, design in
# handoff/core-parking.md).
#
# - gemini-cpufreq loads cpufreq-dt (hardware-verified on M42c) once the
#   A72s are up and selects schedutil; the kernel default governor is
#   performance.
# - gemini-core-parking parks CPUs 9..1 (A72 cluster, then L, then extra LL
#   cores) and brings them back on load and input. CPU0 is never written.
#   Native A72 shutdown/restart and the shared-rail low-voltage transitions
#   passed bounded hardware probes (a72-native-trial-07). CPU8 starts after
#   CPU4, and CPU9 after CPU8; shutdown uses the reverse order.
# - /run/gemini-core-parking/hold onlines everything and stops parking (tests,
#   benchmarks); /run/gemini-core-parking/pause freezes the topology (set for
#   the duration of system sleep).
{ config, lib, pkgs, geminiCpufreqKernel, ... }:
let
  hostCheck = pkgs.runCommand "gemini-core-parking-host-check" {
    nativeBuildInputs = [pkgs.buildPackages.python3];
  } ''
    cc=${pkgs.buildPackages.stdenv.cc}/bin/cc
    cp ${../nix/core-parking.c} core-parking.c
    cp ${../nix/test-core-parking-policy.c} test-core-parking-policy.c
    $cc -std=gnu11 -Wall -Wextra -Werror -Wpedantic -O2 core-parking.c -o gemini-core-parking
    $cc -std=gnu11 -Wall -Wextra -Werror -O2 test-core-parking-policy.c -o policy-test
    ./policy-test
    python3 ${../nix/test-core-parking.py} ./gemini-core-parking
    touch "$out"
  '';
  daemon = pkgs.pkgsStatic.stdenv.mkDerivation {
    pname = "gemini-core-parking";
    version = "1";
    src = ../nix/core-parking.c;
    dontUnpack = true;
    buildPhase = ''
      test -e ${hostCheck}
      $CC -std=gnu11 -Wall -Wextra -Werror -Wpedantic -O2 -static "$src" -o gemini-core-parking
    '';
    installPhase = ''
      install -Dm0755 gemini-core-parking "$out/bin/gemini-core-parking"
    '';
  };
  # Unpark order: extra LL cores, L cluster, then A72s.
  # CPU8 needs CPU4 online to start; CPU9 needs CPU8.
  args = lib.escapeShellArgs [
    "--order" "1,2,3,4,5,6,7,8,9"
    "--requires" "8:4"
    "--requires" "9:8"
    "--period-ms" "50"
    "--up-pct" "80"
    "--up-samples" "2"
    "--rush-pct" "95"
    "--down-pct" "60"
    "--down-samples" "4"
    "--down-hold-ms" "1000"
    "--min" "0"
    "--boost" "3"
    "--boost-hold-ms" "1500"
    "--thermal-type" "soc-thermal"
    "--thermal-hot" "95000"
    "--thermal-clear" "90000"
    "--thermal-max" "3"
  ];
  cpufreqLoad = pkgs.writeShellScript "gemini-cpufreq-load" ''
    set -eu
    export PATH=${lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.kmod]}:$PATH
    grep -q '^cpufreq_dt ' /proc/modules || modprobe -d ${geminiCpufreqKernel} cpufreq-dt
    test -d /sys/devices/system/cpu/cpufreq/policy0
    test -d /sys/devices/system/cpu/cpufreq/policy4
    for policy in /sys/devices/system/cpu/cpufreq/policy*; do
      echo schedutil > "$policy/scaling_governor"
      echo "$(basename "$policy"): cpus=$(cat "$policy/related_cpus") governor=$(cat "$policy/scaling_governor") cur=$(cat "$policy/scaling_cur_freq")"
    done
  '';
  onlineAll = pkgs.writeShellScript "gemini-core-parking-online-all" ''
    test -e /run/gemini-core-parking/pause && exit 0
    for cpu in 1 2 3 4 5 6 7 8 9; do
      echo 1 > /sys/devices/system/cpu/cpu$cpu/online || :
    done
  '';
in {
  boot.blacklistedKernelModules = ["cpufreq_dt"];
  system.build.geminiCoreParking = daemon;

  systemd.services.gemini-cpufreq = {
    description = "Gemini A53 frequency scaling (cpufreq-dt, schedutil)";
    wantedBy = ["multi-user.target"];
    # CPU8 starts under the A72 owner's clock checks; change clocks after.
    after = ["gemini-a72-preflight.service"];
    # Inside the boot lease: a bad load is rolled back by the watchdog.
    before = ["gemini-baseline-self-accept.service" "gemini-core-parking.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "30s";
      ExecStart = cpufreqLoad;
    };
  };

  systemd.services.gemini-core-parking = {
    description = "Gemini load-driven core parking";
    wantedBy = ["multi-user.target"];
    # Leave the startup topology stable until the recovery lease is accepted.
    after = ["gemini-cpufreq.service" "gemini-baseline-self-accept.service" "gemini-a72-preflight.service"];
    wants = ["gemini-cpufreq.service"];
    serviceConfig = {
      Type = "simple";
      ExecStart = "${daemon}/bin/gemini-core-parking ${args}";
      # A crash must not leave cores parked.
      ExecStopPost = onlineAll;
      Restart = "on-failure";
      RestartSec = "2s";
      Nice = -15;
      RuntimeDirectory = "gemini-core-parking";
      RuntimeDirectoryPreserve = "yes";
    };
  };

  # Do not change the topology while the system goes to sleep or resumes.
  # sleep.target stops after resume, which stops this unit and removes pause.
  systemd.services.gemini-core-parking-sleep = {
    description = "Pause core parking across system sleep";
    wantedBy = ["sleep.target"];
    before = ["sleep.target"];
    unitConfig.StopWhenUnneeded = true;
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "gemini-core-parking-pause" ''
        ''${pkgs.coreutils}/bin/mkdir -p /run/gemini-core-parking
        ''${pkgs.coreutils}/bin/touch /run/gemini-core-parking/pause
      '';
      ExecStop = "${pkgs.coreutils}/bin/rm -f /run/gemini-core-parking/pause";
    };
  };
}
