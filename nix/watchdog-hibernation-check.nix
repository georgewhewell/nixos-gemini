{ buildPkgs, crossPkgs, source, baseKernel }:
buildPkgs.stdenv.mkDerivation {
  pname = "gemini-watchdog-hibernation-check";
  version = "1";
  src = source;
  patches = [ ../patches/watchdog/0001-mtk-wdt-pause-for-hibernation-io.patch ];
  nativeBuildInputs = with buildPkgs; [
    bc bison flex gnumake perl python3 pkg-config
    crossPkgs.buildPackages.gcc
  ];
  buildInputs = with buildPkgs; [ openssl elfutils ];
  hardeningDisable = [ "all" ];
  # These artifacts are relocatable kernel objects, not userspace executables.
  dontPatchELF = true;
  dontStrip = true;
  dontConfigure = true;
  buildPhase = ''
    runHook preBuild
    cp ${baseKernel}/kernel.config .config
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    grep -qx 'CONFIG_HIBERNATION=y' .config
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- -j$NIX_BUILD_CORES W=1 drivers/watchdog/mtk_wdt.o
    cp drivers/watchdog/mtk_wdt.o mtk-wdt-hibernation.o
    cp .config hibernation.config
    python3 tools/testing/selftests/watchdog/mtk-wdt-pm-host.py | tee host-test.log

    bash scripts/config --disable HIBERNATION
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    grep -qx '# CONFIG_HIBERNATION is not set' .config
    grep -qx 'CONFIG_PM_SLEEP=y' .config
    rm drivers/watchdog/mtk_wdt.o
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- -j$NIX_BUILD_CORES W=1 drivers/watchdog/mtk_wdt.o
    cp drivers/watchdog/mtk_wdt.o mtk-wdt-suspend-only.o
    cp .config suspend-only.config
    runHook postBuild
  '';
  installPhase = ''
    mkdir -p "$out"
    cp mtk-wdt-*.o hibernation.config suspend-only.config host-test.log "$out/"
    cp drivers/watchdog/mtk_wdt.c "$out/"
  '';
}
