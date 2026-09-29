# MT6797 CONSYS Bluetooth over the aggregate's full-STP channel 0 (M41).
{ lib, pkgs, geminiConnectivityKernel, ... }:
let
  # nixpkgs 23.05 wraps bluez's Python D-Bus test scripts with dbus-python and
  # pygobject3. Their cross build needs gobject-introspection under qemu and a
  # build-platform dbus that fails to link here. bluetoothd, bluetoothctl,
  # btmgmt and the deprecated hci tools use none of them, so skip the wrap.
  # libical's GObject introspection likewise needs qemu to cross-build, and
  # bluez only links its C library.
  bluez = (pkgs.bluez.override {
    libical = pkgs.libical.override {withIntrospection = false;};
  }).overrideAttrs (old: {
    buildInputs = lib.remove pkgs.python3 old.buildInputs;
    nativeBuildInputs =
      lib.filter (p: !(lib.hasPrefix "wrap-python" (p.name or ""))) old.nativeBuildInputs;
    postInstall = ''
      mkdir -p $test
      mkdir $out/sbin
      ln -s ../libexec/bluetooth/bluetoothd $out/sbin/bluetoothd
      ln -s ../libexec/bluetooth/obexd $out/sbin/obexd
      mkdir $out/etc/bluetooth
      ln -s /etc/bluetooth/main.conf $out/etc/bluetooth/main.conf
      ln -s /etc/bluetooth/input.conf $out/etc/bluetooth/input.conf
      ln -s /etc/bluetooth/network.conf $out/etc/bluetooth/network.conf
      for files in `find tools/ -type f -perm -755`; do
        filename=$(basename $files)
        install -Dm755 tools/$filename $out/bin/$filename
      done
      install -Dm755 attrib/gatttool $out/bin/gatttool
    '';
  });
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
    # bluez 5.66's shell quits at once when stdin cannot be polled, which
    # is the case for systemd's /dev/null; give btmgmt an idle pipe.
    mgmt() { timeout 10 btmgmt "$@" < <(sleep 10); }
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
  # bluetoothd and bluetoothctl; the adapter stays off until asked.
  hardware.bluetooth = {
    enable = true;
    package = bluez;
    powerOnBoot = false;
  };
  # HCI trace of every Bluetooth bring-up while the controller is being
  # qualified (read with: btmon -r /run/gemini-bluetooth/hci.btsnoop).
  systemd.services.gemini-bluetooth-trace = {
    description = "Capture MT6797 Bluetooth HCI traffic";
    serviceConfig = {
      Type = "simple";
      RuntimeDirectory = "gemini-bluetooth";
      RuntimeDirectoryPreserve = true;
      ExecStartPre = "${pkgs.kmod}/bin/modprobe -d ${geminiConnectivityKernel} bluetooth";
      ExecStart = "${bluez}/bin/btmon -w /run/gemini-bluetooth/hci.btsnoop";
      ExecStartPost = "${pkgs.coreutils}/bin/sleep 1";
    };
  };
  systemd.services.gemini-bluetooth = {
    description = "Register the MT6797 CONSYS Bluetooth HCI endpoint";
    after = ["gemini-connectivity.service" "gemini-bluetooth-trace.service"];
    requires = ["gemini-connectivity.service"];
    wants = ["gemini-bluetooth-trace.service"];
    # Deliberately not wanted at boot: hci_register_dev() runs setup at once,
    # and a failed WMT Bluetooth transaction fences the shared CONSYS radio,
    # which would also stop Wi-Fi. Start it explicitly until qualified.
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      Restart = "no";
      TimeoutStartSec = "60s";
      ExecStart = start;
    };
  };
}
