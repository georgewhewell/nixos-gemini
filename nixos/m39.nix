# M39: record the MT6351 RTC, hwclock, s2idle availability and the PMIC
# power key.  Read-only: it never writes the RTC, never arms an alarm and
# never requests suspend.
{ pkgs, ... }:
let
  check = pkgs.writeShellScript "gemini-m39-check" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.util-linux]}:$PATH
    grep -wFq GEMINI_A72_CI9_M39 /proc/cmdline
    out=/run/gemini-m39
    mkdir "$out"
    cat /proc/sys/kernel/random/boot_id > "$out/boot-id"
    step=start
    finish() {
      rc=$?
      if [ "$rc" != 0 ]; then
        echo "m39=failed step=$step" > "$out/result"
      fi
    }
    trap finish EXIT
    report() { printf '%s\n' "$*" >> "$out/report"; }

    step=rtc-class
    rtc=/sys/class/rtc/rtc0
    test -d "$rtc"
    report "rtc0=present"
    report "rtc0_name=$(cat "$rtc/name")"
    report "rtc0_date=$(cat "$rtc/date")"
    report "rtc0_time=$(cat "$rtc/time")"
    report "rtc0_since_epoch=$(cat "$rtc/since_epoch")"
    report "rtc0_hctosys=$(cat "$rtc/hctosys")"
    report "system_time_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    grep -q mt6397-rtc "$rtc/name" || grep -q mt6351-rtc "$rtc/name"
    test -c /dev/rtc0

    step=hwclock
    hwclock --show --utc --rtc=/dev/rtc0 > "$out/hwclock.txt" 2>&1
    report "hwclock_show=$(head -n1 "$out/hwclock.txt")"

    step=power-state
    report "power_state=$(cat /sys/power/state)"
    report "mem_sleep=$(cat /sys/power/mem_sleep 2>/dev/null || echo absent)"
    grep -qw freeze /sys/power/state

    step=power-key
    key=
    for dev in /sys/class/input/input*; do
      if [ "$(cat "$dev/name")" = mtk-pmic-keys ]; then
        test -z "$key"
        key=$dev
      fi
    done
    test -n "$key"
    set -- "$key"/event*
    test "$#" = 1
    test -d "$1"
    event=/dev/input/$(basename "$1")
    test -c "$event"
    report "power_key_name=$(cat "$key/name")"
    report "power_key_input=$(basename "$key")"
    report "power_key_event=$event"
    report "power_key_phys_driver=$(basename "$(readlink -f "$key/device/driver" 2>/dev/null || echo none)")"

    step=done
    echo 'm39=rtc-hwclock-freeze-powerkey-present' > "$out/result"
  '';
in {
  systemd.services.gemini-m39 = {
    description = "Record M39 RTC, hwclock, s2idle and power-key presence";
    wantedBy = ["multi-user.target"];
    after = ["systemd-udev-settle.service" "systemd-udevd.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "60s";
      ExecStart = check;
    };
  };

  # M39 adds a KEY_POWER input device and CONFIG_SUSPEND.  logind's defaults
  # would power off on a key press and suspend on the hall (SW_LID) switch,
  # so keep both inert: suspend is only ever requested by hand.
  services.logind.lidSwitch = "ignore";
  services.logind.lidSwitchDocked = "ignore";
  services.logind.lidSwitchExternalPower = "ignore";
  services.logind.extraConfig = ''
    HandlePowerKey=ignore
    HandlePowerKeyLongPress=ignore
    HandleSuspendKey=ignore
    HandleHibernateKey=ignore
    IdleAction=ignore
  '';
}
