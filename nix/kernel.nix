{
  buildPkgs,
  oldPkgs,
  source,
  spmFirmware,
}: let
  gcc = oldPkgs.pkgsCross.aarch64-multiplatform.buildPackages.gcc12;
in
  buildPkgs.stdenv.mkDerivation {
    pname = "linux-gemini";
    version = "7.1.3";
    src = source;
    hardeningDisable = ["all"];
    nativeBuildInputs =
      (with buildPkgs; [
        bc
        bison
        elfutils
        flex
        git
        hostname
        ncurses
        openssl
        perl
        pkg-config
        python3
        rsync
      ])
      ++ [gcc];
    depsBuildBuild = [buildPkgs.stdenv.cc];

    KBUILD_BUILD_TIMESTAMP = "2026-07-04 00:00:00 UTC";
    KBUILD_BUILD_VERSION = "1";
    KBUILD_BUILD_USER = "gemini-pda";
    KBUILD_BUILD_HOST = "devvm";
    KCONFIG_NOTIMESTAMP = "1";
    SOURCE_DATE_EPOCH = "1783123200";

    configurePhase = ''
      runHook preConfigure
      unset NIX_LDFLAGS
      kernelMakeFlags=(ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu-)
      make "''${kernelMakeFlags[@]}" gemini_defconfig
      # Kconfig can silently drop a requested symbol when a dependency
      # changes. Both parts are required before late A72 startup is usable.
      grep -Fqx CONFIG_ARM64_MT6797_A72_CAPABILITY_PROFILE=y .config
      grep -Fqx CONFIG_ARM64_LATE_CPU_PROFILE=y .config
      runHook postConfigure
    '';

    buildPhase = ''
      runHook preBuild
      make -j"$NIX_BUILD_CORES" "''${kernelMakeFlags[@]}" \
        Image Image.gz mediatek/mt6797-gemini-pda.dtb modules
      runHook postBuild
    '';

    doCheck = true;
    checkPhase = ''
      runHook preCheck
      export CC=${buildPkgs.stdenv.cc}/bin/cc HOSTCC=${buildPkgs.stdenv.cc}/bin/cc
      export MT6797_SPM_FIRMWARE_DIR=${spmFirmware}/lib/firmware/mediatek/mt6797
      for test in \
        mt6797-a72-hotplug-attribute mt6797-cpuclk-observation mt6797-cpuclk-core-host \
        mt6797-a72-power-core-host mt6797-sram-core-host mt6797-sram-boot-api \
        a72-vproc-votes a72-online-commit mt6797-cpuclk-boot-api \
        mt6797-cpuclk-fhctl-host opp-of-sharing-cpus-host mt6797-spm-fw-host \
        bt-hci-mt6797-host wifi-radio-admission-host wifi-radio-tx-host \
        regulator-exclusive-state media-clock-bounds drm-synchronous-bind cellular-integration \
        fusb301-role-host mt6797-tphy-power-host mtu3-fallback-host; do
        python3 "tools/gemini/test-$test.py"
      done
      for test in acquire integration provider registration pm; do
        python3 "drivers/pmdomain/mediatek/test-gpuldo-$test.py"
      done
      "$HOSTCC" -std=c11 -Wall -Wextra -Werror \
        drivers/pmdomain/mediatek/test-gpuldo-owner.c -o gpuldo-owner-test
      ./gpuldo-owner-test
      python3 tools/testing/selftests/watchdog/mtk-wdt-pm-host.py
      python3 tools/testing/selftests/rtc/mt6397-alarm-host.py
      python3 tools/testing/selftests/rtc/mt6351-calendar-host.py
      runHook postCheck
    '';

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp arch/arm64/boot/Image arch/arm64/boot/Image.gz System.map vmlinux "$out/"
      cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dtb "$out/base.dtb"
      cp .config "$out/kernel.config"
      release=$(make -s "''${kernelMakeFlags[@]}" kernelrelease)
      make "''${kernelMakeFlags[@]}" INSTALL_MOD_PATH="$out" DEPMOD=true modules_install
      rm -f "$out/lib/modules/$release/build" "$out/lib/modules/$release/source"
      ${buildPkgs.kmod}/bin/depmod -b "$out" "$release"
      {
        echo "source-revision=${source.rev or source.narHash}"
        echo "kernel-release=$release"
        (cd "$out" && sha256sum Image Image.gz base.dtb kernel.config System.map vmlinux)
      } > "$out/BUILD-MANIFEST"
      runHook postInstall
    '';

    dontStrip = true;
    dontPatchELF = true;
  }
