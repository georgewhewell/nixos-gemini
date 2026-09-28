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
  start = pkgs.writeShellScript "gemini-bluetooth-start" ''
    set -eu
    export PATH=${pkgs.lib.makeBinPath [pkgs.coreutils pkgs.kmod pkgs.util-linux]}:$PATH
    test -d /sys/bus/platform/drivers/mt6797-consys
    modprobe -d ${geminiConnectivityKernel} hci_mt6797
    for _ in $(seq 1 50); do
      test -e /sys/class/bluetooth/hci0 && break
      sleep 0.2
    done
    test -e /sys/class/bluetooth/hci0
  '';
in {
  # bluetoothd and bluetoothctl; the adapter stays off until asked.
  hardware.bluetooth = {
    enable = true;
    package = bluez;
    powerOnBoot = false;
  };
  systemd.services.gemini-bluetooth = {
    description = "Register the MT6797 CONSYS Bluetooth HCI endpoint";
    after = ["gemini-connectivity.service"];
    requires = ["gemini-connectivity.service"];
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
