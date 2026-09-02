{
  buildPkgs,
  oldPkgs,
  ixoo-kernel,
  linux-gemini,
}:
let
  gcc12Cross = oldPkgs.pkgsCross.aarch64-multiplatform.buildPackages.gcc12;
  fragments = [
    (ixoo-kernel + "/configs/gemini-handoff.fragment")
    (ixoo-kernel + "/configs/gemini-usbdiag.fragment")
    (ixoo-kernel + "/configs/gemini-clk-ignore-unused.fragment")
    (ixoo-kernel + "/configs/gemini-observability.fragment")
    (ixoo-kernel + "/configs/gemini-fbcon-rotation.fragment")
    (ixoo-kernel + "/configs/gemini-keyboard.fragment")
    (ixoo-kernel + "/configs/gemini-keyboard-wrrd.fragment")
    (ixoo-kernel + "/configs/gemini-keyboard-manual-reboot.fragment")
    (ixoo-kernel + "/configs/gemini-smp8.fragment")
    (ixoo-kernel + "/configs/gemini-emmc-development.fragment")
    ./mainline-production.fragment
  ];

  kernel = buildPkgs.stdenv.mkDerivation {
    pname = "linux-gemini-production";
    version = "7.1.3";
    src = linux-gemini;
    fragmentInputs = fragments;
    hardeningDisable = ["all"];

    KBUILD_BUILD_TIMESTAMP = "2026-09-02 00:00:00 UTC";
    KBUILD_BUILD_VERSION = "1";
    KBUILD_BUILD_USER = "gemini-pda";
    KBUILD_BUILD_HOST = "trex";
    KCONFIG_NOTIMESTAMP = "1";
    SOURCE_DATE_EPOCH = "1788307200";

    nativeBuildInputs = (with buildPkgs; [
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
      rsync
    ]) ++ [gcc12Cross];
    depsBuildBuild = [buildPkgs.stdenv.cc];

    configurePhase = ''
      runHook preConfigure
      unset NIX_LDFLAGS
      make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- defconfig
      scripts/kconfig/merge_config.sh -m -O . .config $fragmentInputs
      make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig

      grep -Fqx 'CONFIG_LOCALVERSION="-gemini-production"' .config
      grep -Fqx '# CONFIG_MODULES is not set' .config
      grep -Fqx 'CONFIG_CMDLINE_FORCE=y' .config
      grep -Eq '^CONFIG_CMDLINE="console=tty0 .*maxcpus=8 .*rdinit=/init' .config
      grep -Fq ' watchdog.stop_on_reboot=0 ' .config
      grep -Fqx 'CONFIG_WATCHDOG_NOWAYOUT=y' .config
      grep -Fqx 'CONFIG_SUSPEND=y' .config
      grep -Fqx 'CONFIG_KEXEC=y' .config
      grep -Fqx 'CONFIG_KEXEC_FILE=y' .config
      grep -Fqx 'CONFIG_MMC_MTK=y' .config
      grep -Fqx 'CONFIG_USB_MTU3_GADGET=y' .config
      grep -Fqx 'CONFIG_USB_ETH_RNDIS=y' .config
      grep -Fqx 'CONFIG_USB_MUSB_HOST=y' .config
      grep -Fqx 'CONFIG_USB_MUSB_MEDIATEK=y' .config
      grep -Fqx 'CONFIG_USB_RTL8152=y' .config
      grep -Fqx 'CONFIG_TYPEC_FUSB301=y' .config
      grep -Fqx 'CONFIG_CHARGER_BQ25890=y' .config
      grep -Fqx 'CONFIG_BATTERY_MT6351_FGADC=y' .config
      grep -Fqx 'CONFIG_DRM_MEDIATEK=y' .config
      grep -Fqx 'CONFIG_DRM_PANEL_NOVATEK_NT36672E=y' .config
      grep -Fqx 'CONFIG_MTK_IOMMU=y' .config
      grep -Fqx 'CONFIG_REGULATOR_LP3101=y' .config
      grep -Fqx 'CONFIG_PINCTRL_AW9523=y' .config
      grep -Fqx 'CONFIG_KEYBOARD_MATRIX=y' .config
      grep -Fqx 'CONFIG_ARM64_MT6797_A72_SMPEN=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_A72_POWER=y' .config
      grep -Fqx 'CONFIG_NVMEM_MTK_ATAG_DEVINFO=y' .config
      grep -Fqx 'CONFIG_VIDEO_MTK_MT6797_SENINF=y' .config
      grep -Fqx 'CONFIG_VIDEO_MTK_MT6797_CAMSV=y' .config
      grep -Fqx 'CONFIG_COMMON_CLK_MT6797_CAMSYS=y' .config
      grep -Fqx 'CONFIG_MTK_SCP=y' .config
      grep -Fqx 'CONFIG_VIDEO_MEDIATEK_VCODEC=y' .config
      grep -Fqx 'CONFIG_CFG80211=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME_CONTROLLER=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_EMI_MPU=y' .config
      grep -Fqx 'CONFIG_MT6797_WIFI=y' .config
      grep -Fqx 'CONFIG_BT_MTK6797_STP=y' .config
      grep -Fqx 'CONFIG_GNSS_MTK_CONSYS=y' .config
      grep -Fqx 'CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX=y' .config
      grep -Fqx 'CONFIG_BMI160_I2C=y' .config
      grep -Fqx 'CONFIG_INPUT_REGULATOR_HAPTIC=y' .config
      grep -Fqx 'CONFIG_SND_SOC_MT6797=y' .config
      grep -Fqx 'CONFIG_SND_SOC_MT6797_MT6351=y' .config
      grep -Fqx 'CONFIG_REGULATOR_RT5735=y' .config
      grep -Fqx 'CONFIG_COMMON_CLK_MT6797_MFGSYS=y' .config
      grep -Fqx 'CONFIG_DRM_PANFROST=y' .config
      grep -Fqx 'CONFIG_PM_DEVFREQ=y' .config
      grep -Fqx 'CONFIG_DEVFREQ_GOV_SIMPLE_ONDEMAND=y' .config
      grep -Fqx 'CONFIG_SQUASHFS_ZLIB=y' .config
      grep -Fqx 'CONFIG_FW_LOADER_COMPRESS_XZ=y' .config
      runHook postConfigure
    '';

    buildPhase = ''
      runHook preBuild
      unset NIX_LDFLAGS
      make -j"$NIX_BUILD_CORES" \
        ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- \
        Image Image.gz mediatek/mt6797-gemini-pda.dtb
      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp arch/arm64/boot/Image "$out/Image"
      cp arch/arm64/boot/Image.gz "$out/Image.gz"
      cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dtb "$out/gemini.dtb"
      cp .config "$out/kernel.config"
      cp System.map vmlinux "$out/"
      for cpu_clock in \
        0:1391000000 1:1391000000 2:1391000000 3:1391000000 \
        100:1950000000 101:1950000000 102:1950000000 103:1950000000 \
        200:2288000000 201:2288000000; do
        cpu="''${cpu_clock%%:*}"
        expected="''${cpu_clock#*:}"
        test "$(fdtget -t u "$out/gemini.dtb" "/cpus/cpu@$cpu" clock-frequency)" = \
          "$expected"
      done
      test "$(make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- -s kernelrelease)" = \
        "7.1.3-gemini-production"
      runHook postInstall
    '';

    dontStrip = true;
    dontPatchELF = true;
  };
in {
  inherit kernel;
  serviceabilityDtb = kernel;
}
