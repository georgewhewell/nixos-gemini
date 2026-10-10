# MT6797 CONSYS Bluetooth over the aggregate's full-STP channel 0 (M41).
{ lib, pkgs, geminiConnectivityKernel, ... }:
let
  bluez = pkgs.bluez;
  tools = pkgs.lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gnused pkgs.kmod pkgs.util-linux bluez];
  start = pkgs.writeShellScript "gemini-bluetooth-start" ''
    set -eu
    export PATH=${tools}:$PATH
    state=/run/gemini-bluetooth
    mkdir -p "$state"
    test -d /sys/bus/platform/drivers/mt6797-consys
    modprobe -d ${geminiConnectivityKernel} hci_mt6797
    for _ in $(seq 1 50); do
      test -e /sys/class/bluetooth/hci0 && break
      sleep 0.2
    done
    test -e /sys/class/bluetooth/hci0
    # The current BlueZ handles a command with systemd's /dev/null stdin.
    # The old 5.66 idle-pipe workaround added ten seconds to each query.
    mgmt() { timeout 10 btmgmt "$@" </dev/null; }
    configured() { mgmt info 2>&1 | grep -q '^hci0:'; }
    sleep 1
    if ! configured; then
      # The eFUSE address is blank (hci_mt6797 logs it) and the vendor
      # NVRAM record is on nvdata; derive a stable, locally administered
      # unicast address from the eMMC CID instead.
      cid=
      for d in /sys/bus/mmc/devices/*; do
        if [ "$(cat "$d/type" 2>/dev/null)" = MMC ]; then cid=$(cat "$d/cid"); fi
      done
      test -n "$cid"
      h=$(printf 'gemini-bluetooth:%s' "$cid" | sha256sum | cut -c1-12)
      first=$(printf '%02x' $(( (0x''${h%??????????} & 0xfc) | 0x02 )))
      rest=$(printf '%s' "''${h#??}" | sed 's/../&:/g; s/:$//')
      addr="$first:$rest"
      echo "$addr" > "$state/public-addr"
      mgmt --index 0 public-addr "$addr" | tee "$state/public-addr.log"
      for _ in $(seq 1 25); do
        configured && break
        sleep 0.2
      done
    fi
    configured
  '';
in {
  # Register and configure the HCI endpoint before BlueZ powers it on.
  hardware.bluetooth = {
    enable = true;
    package = bluez;
    powerOnBoot = true;
  };
  # Explicit diagnostic: start this before gemini-bluetooth when an HCI
  # trace is needed (read with: btmon -r /run/gemini-bluetooth/hci.btsnoop).
  # Normal desktop use must not continuously record HCI traffic.
  systemd.services.gemini-bluetooth-trace = {
    description = "Capture MT6797 Bluetooth HCI traffic";
    serviceConfig = {
      Type = "simple";
      RuntimeDirectory = "gemini-bluetooth";
      RuntimeDirectoryPreserve = true;
      UMask = "0077";
      ExecStartPre = "${pkgs.kmod}/bin/modprobe -d ${geminiConnectivityKernel} bluetooth";
      ExecStart = "${bluez}/bin/btmon -w /run/gemini-bluetooth/hci.btsnoop";
      ExecStartPost = "${pkgs.coreutils}/bin/sleep 1";
    };
  };
  systemd.services.gemini-bluetooth = {
    description = "Register the MT6797 CONSYS Bluetooth HCI endpoint";
    wantedBy = ["multi-user.target"];
    after = ["gemini-connectivity.service" "gemini-bluetooth-trace.service"];
    requires = ["gemini-connectivity.service"];
    before = ["bluetooth.service"];
    # This uses the shared CONSYS firmware initialized by connectivity;
    # it must not race that owner or power the adapter with a blank address.
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "60s";
      UMask = "0077";
      ExecStart = start;
    };
  };
  systemd.services.bluetooth = {
    requires = ["gemini-bluetooth.service"];
    after = ["gemini-bluetooth.service"];
  };
  systemd.services.gemini-baseline-self-accept = {
    requires = ["bluetooth.service"];
    after = ["bluetooth.service"];
  };
}
