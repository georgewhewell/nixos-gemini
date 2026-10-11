{
  buildPkgs,
  compiler,
  source,
  spmFirmware,
}:
  buildPkgs.stdenv.mkDerivation {
    pname = "linux-gemini";
    version = "7.2.9";
    src = source;
    hardeningDisable = ["all"];
    nativeBuildInputs =
      (with buildPkgs; [
        bc
        bison
        dtc
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
      ++ [compiler];
    depsBuildBuild = [buildPkgs.stdenv.cc];
    passthru = {inherit compiler;};

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
      test "$(make -s "''${kernelMakeFlags[@]}" kernelversion)" = "$version"
      # Kconfig can silently drop a requested symbol when a dependency
      # changes. Both parts are required before late A72 startup is usable.
      grep -Fqx CONFIG_ARM64_MT6797_A72_CAPABILITY_PROFILE=y .config
      grep -Fqx CONFIG_ARM64_LATE_CPU_PROFILE=y .config
      grep -Fqx CONFIG_DYNAMIC_FTRACE=y .config
      grep -Fqx CONFIG_EVENT_TRACING=y .config
      grep -Fqx CONFIG_IPV6=y .config
      grep -Fqx CONFIG_FUSE_FS=y .config
      # GNOME's radio controls discover Bluetooth through the standard
      # HCI rfkill endpoint as well as BlueZ's Adapter1 object.
      grep -Fqx CONFIG_RFKILL=y .config
      grep -Fqx CONFIG_GNSS=y .config
      grep -Fqx CONFIG_GNSS_MTK_CONSYS=m .config
      grep -Fqx CONFIG_REGULATOR_FIXED_VOLTAGE=y .config
      ! grep -Eq '^CONFIG_GNSS_MTK_SERIAL=[ym]$' .config
      grep -Fqx CONFIG_ZRAM=y .config
      grep -Fqx CONFIG_ZRAM_BACKEND_LZ4=y .config
      ! grep -Fqx CONFIG_ZRAM_WRITEBACK=y .config
      ! grep -Fqx CONFIG_ZSWAP=y .config
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
        mt6797-a72-hotplug-attribute mt6797-cpuclk-observation mt6797-cpuclk-snapshot-host mt6797-cpuclk-core-host \
        mt6797-a72-power-core-host mt6797-a72-off-host \
        mt6797-sram-core-host mt6797-sram-boot-api \
        a72-vproc-votes a72-online-commit a72-hotplug-lifecycle mt6797-cpuclk-boot-api \
        mt6797-cpuclk-fhctl-host mt6797-cpuclk-transition-host mt6797-topckgen-cpu-host \
        mt6797-cpuclk-registration-host \
        mt6797-cpu-rail-admission-host \
        mt6797-cpu-rail-plan-host \
        mt6797-cpu-coupler-host \
        mt6797-cci-policy-host \
        mt6797-cci-runtime-host \
        mt6797-cpu-sram-host \
        da9214-settling-host \
        opp-of-sharing-cpus-host mt6797-spm-fw-host mt6351-fgadc-supplier-host \
        mt6351-fgadc-conversion-host gemini-battery-profile-host \
        mt6351-fgadc-model-host mt6351-fgadc-model-lifecycle-host \
        gnss-rx-atomic gnss-provider-host mt6797-mmc0-pinctrl-host msdc-clock-host proc-stat-host mtk-sysirq-write-host \
        bt-hci-mt6797-host wifi-radio-admission-host wifi-radio-station-host wifi-radio-tx-host \
        wifi-radio-worker-host wifi-radio-connect-host wifi-radio-scan-cancel-host wifi-scan-probe-host wifi-hif-recovery-host \
        regulator-exclusive-state dma-direct-sg-host media-clock-bounds drm-synchronous-bind cellular-integration cellular-runtime-wire64 cellular-live-smem cellular-first-fatal cellular-rx-rejected cellular-napi-mask cellular-at-terminal cellular-dbm-host \
        fusb301-role-host mt6797-tphy-power-host mtu3-fallback-host; do
        python3 "tools/gemini/test-$test.py"
      done
      for test in acquire integration provider registration pm dvfs; do
        python3 "drivers/pmdomain/mediatek/test-gpuldo-$test.py"
      done
      python3 drivers/pmdomain/mediatek/test-gpuldo-dt.py \
        arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dtb
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
      cp arch/arm64/boot/Image arch/arm64/boot/Image.gz System.map vmlinux Module.symvers "$out/"
      cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dtb "$out/base.dtb"
      cp .config "$out/kernel.config"
      release=$(make -s "''${kernelMakeFlags[@]}" kernelrelease)
      make "''${kernelMakeFlags[@]}" INSTALL_MOD_PATH="$out" DEPMOD=true modules_install
      rm -f "$out/lib/modules/$release/build" "$out/lib/modules/$release/source"
      ${buildPkgs.kmod}/bin/depmod -b "$out" "$release"
      {
        echo "source-revision=${source.rev or source.narHash}"
        echo "kernel-release=$release"
        (cd "$out" && sha256sum Image Image.gz base.dtb kernel.config System.map vmlinux Module.symvers)
      } > "$out/BUILD-MANIFEST"
      runHook postInstall
    '';

    dontStrip = true;
    dontPatchELF = true;
  }
