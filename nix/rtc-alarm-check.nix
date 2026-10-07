{ buildPkgs, crossPkgs, source, baseKernel }:
buildPkgs.stdenv.mkDerivation {
  pname = "gemini-rtc-alarm-check";
  version = "1";
  src = source;
  patches = [ ../patches/rtc/0001-mt6397-alarm-irq-enable.patch ];
  nativeBuildInputs = with buildPkgs; [
    bc bison flex gnumake perl python3 pkg-config
    crossPkgs.buildPackages.gcc
  ];
  buildInputs = with buildPkgs; [ openssl elfutils ];
  hardeningDisable = [ "all" ];
  dontPatchELF = true;
  dontStrip = true;
  dontConfigure = true;
  buildPhase = ''
    cp ${baseKernel}/kernel.config .config
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- -j$NIX_BUILD_CORES W=1 drivers/rtc/rtc-mt6397.o
    python3 tools/testing/selftests/rtc/mt6397-alarm-host.py | tee host-test.log
  '';
  installPhase = ''
    mkdir -p "$out"
    cp drivers/rtc/rtc-mt6397.o drivers/rtc/rtc-mt6397.c host-test.log "$out/"
    cp .config "$out/kernel.config"
  '';
}
