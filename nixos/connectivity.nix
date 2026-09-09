# Stage-2 firmware/HIF and passive-scan qualification. Connection tests are explicit.
{ pkgs, geminiConnectivityKernel, geminiConnectivityFirmware, ... }:
let
  firmwareBundle = pkgs.symlinkJoin {
    name = "gemini-connectivity-and-regulatory-firmware";
    paths = [geminiConnectivityFirmware pkgs.wireless-regdb];
  };
  qualify = pkgs.writeShellScript "gemini-connectivity-qualify" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.kmod pkgs.systemd pkgs.util-linux pkgs.iproute2 pkgs.iw]}:$PATH
    grep -wFq GEMINI_A72_CI9_M31 /proc/cmdline
    test "$(cat /sys/devices/system/cpu/online)" = 0-9
    systemctl is-active --quiet gemini-watchdog-takeover.service gemini-cellular.service gemini-gpu.service
    test "$(cat /sys/class/watchdog/watchdog0/state)" = active
    test "$(cat /sys/class/watchdog/watchdog0/timeout)" = 31
    test "$(cat /sys/module/mt6797_consys_emi_mpu/parameters/enable_experimental_ownership)" = Y
    mkdir /run/gemini-connectivity
    cat /proc/sys/kernel/random/boot_id > /run/gemini-connectivity/boot-id
    capture_final() {
      dmesg > /run/gemini-connectivity/kernel-final.txt || :
      cat /proc/interrupts > /run/gemini-connectivity/interrupts-final.txt || :
    }
    trap capture_final EXIT
    # request_firmware_direct must see the verified package before probe.
    firmware=${firmwareBundle}/lib/firmware
    test -r "$firmware/WMT_SOC.cfg"
    test -r "$firmware/WIFI_RAM_CODE_6797"
    echo "$firmware" > /sys/module/firmware_class/parameters/path
    test "$(cat /sys/module/firmware_class/parameters/path)" = "$firmware"
    modprobe -d ${geminiConnectivityKernel} mt6797-btif-pio-platform
    modprobe -d ${geminiConnectivityKernel} mt6797-wifi
    test "$(basename "$(readlink -f /sys/bus/platform/devices/180f0000.wifi/driver)")" = mt6797-wifi
    dmesg > /run/gemini-connectivity/kernel-ready.txt
    grep -Eq 'mt6797-wifi 180f0000.wifi: WLAN .* HIF_EVENT_PUMP_READY irq=' /run/gemini-connectivity/kernel-ready.txt
    sleep 10
    set -- /sys/bus/platform/devices/180f0000.wifi/net/*
    test "$#" = 1
    test -d "$1"
    interface=$(basename "$1")
    printf '%s\n' "$interface" > /run/gemini-connectivity/interface
    ip link set dev "$interface" up
    for pass in 1 2; do
      timeout --signal=TERM --kill-after=3 65 iw dev "$interface" scan passive > /run/gemini-connectivity/scan-$pass.txt
      count=$(awk '/^BSS / { count++ } END { print count+0 }' /run/gemini-connectivity/scan-$pass.txt)
      printf 'scan=%s bss_count=%s\n' "$pass" "$count" > /run/gemini-connectivity/scan-$pass-summary.txt
      test "$count" -gt 0
    done
    dmesg > /run/gemini-connectivity/kernel-steady.txt
    if grep -Ei '(mt6797-wifi|mt6797-consys|mt6797-btif).* (fault|fatal|failed|timeout|timed out|fenced)([^[:alnum:]_]|$)' /run/gemini-connectivity/kernel-steady.txt; then
      exit 1
    fi
    test "$(basename "$(readlink -f /sys/bus/platform/devices/180f0000.wifi/driver)")" = mt6797-wifi
    systemctl is-active --quiet gemini-watchdog-takeover.service gemini-cellular.service gemini-gpu.service
    echo 'connectivity=passive-scans-ready' > /run/gemini-connectivity/result
  '';
in {
  # Udev must not load these via modalias before the ordered service runs.
  environment.etc."modprobe.d/gemini-connectivity.conf".text = ''
    blacklist mt6797-consys
    blacklist mt6797-btif-pio-platform
    blacklist mt6797-wifi
  '';
  systemd.services.gemini-connectivity = {
    description = "Start verified MT6797 connectivity firmware and WLAN HIF";
    wantedBy = ["multi-user.target"];
    after = ["gemini-watchdog-takeover.service" "gemini-cellular.service" "gemini-gpu.service"];
    requires = ["gemini-watchdog-takeover.service" "gemini-cellular.service" "gemini-gpu.service"];
    before = ["gemini-baseline-self-accept.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "180s";
      UMask = "0077";
      ExecStart = qualify;
    };
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["gemini-connectivity.service"];
    requires = ["gemini-connectivity.service"];
  };
}
