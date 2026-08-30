{
  buildPkgs,
  oldPkgs,
  crossPkgs,
  ixoo-kernel,
  linux-gemini,
  ixoo-candidate,
  debugOverlay ? true,
  storageOverlay ? false,
  sshAccess ? false,
  rootfsProbe ? false,
  usbHostOverlay ? false,
  consysIdentityOverlay ? false,
  platformEnablement ? false,
  displayOverlay ? false,
  audioOverlay ? false,
}: let
  lib = buildPkgs.lib;

  # A locked Git input carries rev; a deliberate local-path override carries
  # only its content hash.  Record whichever identity Nix actually consumed so
  # a local reviewed build can never masquerade as the old locked commit.
  kernelRevision =
    if linux-gemini ? rev
    then linux-gemini.rev
    else "nar:${linux-gemini.narHash}";
  ixooRevision = "7199e8229c6a805a941e33a6862956949dfebd3a";
  candidateRevision = "a24b2d264844ee2bb50e77dc7aceaa6b902c7b6a";
  profile = "da921x-lk-clock-readonly-provider";
  ixooManifest = builtins.fromJSON (builtins.readFile (ixoo-kernel + "/kernel/manifest.json"));
  profileDefinition = ixooManifest.config.profiles.${profile};

  profileFragments = assert ixooManifest.architecture == "arm64";
  assert ixooManifest.kernel.version == "7.1.3";
  assert profileDefinition.base == "defconfig";
    profileDefinition.fragments;
  fragmentFiles = map (name: ixoo-kernel + "/${name}") profileFragments;
  finalFragmentFiles =
    fragmentFiles
    ++ [./mainline-connectivity-m0.fragment]
    ++ lib.optionals debugOverlay [./mainline-debug.fragment]
    ++ lib.optionals storageOverlay [
      (ixoo-kernel + "/configs/gemini-emmc-development.fragment")
    ]
    ++ lib.optionals usbHostOverlay [./mainline-usb11-host.fragment]
    ++ lib.optionals consysIdentityOverlay [./mainline-consys-identity.fragment]
    ++ lib.optionals platformEnablement [./mainline-platform-smoke.fragment];
  overlayLabel =
    if debugOverlay
    then "ordinary-ramoops-framebuffer-v1"
    else "none-ixoo-config-control";
  storageLabel =
    if storageOverlay
    then "ixoo-emmc-25mhz-enumeration-only"
    else "none";
  accessLabel =
    if sshAccess
    then "dropbear-key-only-all-ipv4-interfaces"
    else "tcp2323-direct-gadget-shell-only";
  rootfsLabel =
    if rootfsProbe
    then "p29-ext4-readonly-noload-directory-metadata-only"
    else "none";
  usbHostLabel =
    if usbHostOverlay
    then "right-port-usb11-musb-host-pio-multipoint-fusb301-vbus-rtl815x"
    else "none";
  consysIdentityLabel =
    if consysIdentityOverlay
    then "bounded-0x0279-reset-held-v1"
    else "none";
  displayLabel =
    if displayOverlay
    then "nt36672-lp3101-recovery-smoke-v1"
    else "none";
  audioLabel =
    if audioOverlay
    then "mt6797-mt6351-enumeration-only-v1"
    else "none";
  variantSuffix =
    lib.optionalString storageOverlay "-emmc-probe"
    + lib.optionalString sshAccess "-ssh"
    + lib.optionalString rootfsProbe "-p29-ro"
    + lib.optionalString usbHostOverlay "-usb11-host"
    + lib.optionalString consysIdentityOverlay "-consys-identity"
    + lib.optionalString platformEnablement "-platform"
    + lib.optionalString displayOverlay "-display"
    + lib.optionalString audioOverlay "-audio";
  baseDtbSha256 =
    if platformEnablement
    then "87cbce082c7a6d6f67fab47527ed45b148647dd01e178864c618665af8af6d58"
    else if consysIdentityOverlay
    then "e6aa4b9d20360c260f313292be41f92df2deb8613ca6c665a9f045b6b4d880e7"
    else "1ea78817645989e45c9466209a2a0f7b6ee1cbdf342675a5d650f0fd4e25c21c";
  serviceabilityBaseDtbSha256 =
    if platformEnablement
    then "4f537ab13a1aa8f14ff96d03fd068ab552c1b0f50a8cf4bc724c939ed5b49d09"
    else if consysIdentityOverlay
    then "753bf1fba79ac26c401a8d7de3482ea8c91041663ec19b2254aba909dc7d8297"
    else "e0b8294f79f78d4a9c62d8449a5e59cd2a783b37f9ea9bc33bde59b3e593d3d7";
  usbPlatformDtbSha256 =
    if platformEnablement
    then "14b8126b0c46e3cc2370721ae040ac6cdb59e60b206b4031753c856aaa14038d"
    else "9316c45f7c79fe5e9d3b6320c88f45aee68d7f34e14385a1a7bbc7efcfcf9eff";
  finalDtbSha256 =
    assert
      (!displayOverlay && !audioOverlay)
      || (platformEnablement && displayOverlay && audioOverlay && !consysIdentityOverlay);
    if platformEnablement && displayOverlay && audioOverlay && !consysIdentityOverlay
    then "6b42aca0194c399c939bcb8bcada3c770e0b1a5c10954c90bca29dbe77ae0cde"
    else if platformEnablement && consysIdentityOverlay && !displayOverlay && !audioOverlay
    then "e3be740108d83c15829e7772bef06a19a2ff85aed68195c0b229852d956e35d0"
    else if consysIdentityOverlay && !platformEnablement
    then "70c1b17ec8d5744ff5ac60bc7250c958dc99708e4afd463f632e45823ff1eeea"
    else if usbHostOverlay
    then usbPlatformDtbSha256
    else serviceabilityBaseDtbSha256;
  # ixoo's Buildbox used GCC 12.2.0.  The 23.05 cross set gives us the same
  # compiler release while keeping the build inside Nix.
  gcc12Cross = oldPkgs.pkgsCross.aarch64-multiplatform.buildPackages.gcc12;

  kernel = buildPkgs.stdenv.mkDerivation {
    pname =
      "linux-gemini-ixoo-lkro"
      + lib.optionalString (!debugOverlay) "-config-control"
      + lib.optionalString storageOverlay "-emmc-probe"
      + lib.optionalString usbHostOverlay "-usb11-host"
      + lib.optionalString consysIdentityOverlay "-consys-identity"
      + lib.optionalString platformEnablement "-platform"
      + lib.optionalString displayOverlay "-display"
      + lib.optionalString audioOverlay "-audio";
    version = "7.1.3";
    src = linux-gemini;
    # Keep every fragment in the derivation input closure.  Rendering paths
    # through escapeShellArg preserves their spelling but loses Nix string
    # context, which made a fresh sandbox unable to see this repository's
    # connectivity fragment.
    fragmentInputs = finalFragmentFiles;
    # Kbuild is not userspace.  The modern stdenv exposed stack-clash and
    # zero-call-used-register policy to the compiler wrapper, unlike ixoo's
    # plain GCC 12.2 build.  Eliminate that uncontrolled input and let the
    # kernel config/Makefiles own every compiler security option.  The explicit
    # config-control build later proved this cleanup does not alter Image.
    hardeningDisable = ["all"];

    KBUILD_BUILD_TIMESTAMP = "2026-07-04 00:00:00 UTC";
    KBUILD_BUILD_VERSION = "1";
    KBUILD_BUILD_USER = "gemini-pda";
    KBUILD_BUILD_HOST = "devvm";
    KCONFIG_NOTIMESTAMP = "1";
    SOURCE_DATE_EPOCH = "1783123200";

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
        rsync
      ])
      ++ [gcc12Cross];
    depsBuildBuild = [buildPkgs.stdenv.cc];

    configurePhase = ''
      runHook preConfigure
      export SOURCE_DATE_EPOCH=1783123200
      unset NIX_LDFLAGS
      kernelMakeFlags=(
        ARCH=arm64
        CROSS_COMPILE=aarch64-unknown-linux-gnu-
      )
      make "''${kernelMakeFlags[@]}" defconfig
      scripts/kconfig/merge_config.sh \
        -m -O . .config $fragmentInputs
      ${lib.optionalString consysIdentityOverlay ''
        bash scripts/config --set-str CMDLINE \
          "console=tty0 console=ttyS0,921600n8 earlycon maxcpus=8 nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init panic=0 g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=Gemini-L-DA921x-Bind g_ether.iSerialNumber=GEMINI_DA921X_BIND_20260729 clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused initcall_blacklist=mt6797_a72_power_driver_init fw_devlink=rpm mt6797_consys_live.identity_experiment=1"
      ''}
      make "''${kernelMakeFlags[@]}" olddefconfig

      test -z "''${NIX_HARDENING_ENABLE:-}"
      grep -Fqx 'CONFIG_LOCALVERSION="-gemini-da921x-lkro"' .config
      grep -Fqx '# CONFIG_LOCALVERSION_AUTO is not set' .config
      grep -Fqx 'CONFIG_NVMEM_MTK_ATAG_DEVINFO=y' .config
      grep -Fqx 'CONFIG_REGULATOR_DA9213_LEGACY_PROVIDER=y' .config
      grep -Fqx 'CONFIG_REGULATOR_DA9213_LEGACY_OBSERVER=y' .config
      grep -Fqx 'CONFIG_MTK_STP=y' .config
      ! grep -q '^CONFIG_MTK_STP_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_WMT=y' .config
      ! grep -q '^CONFIG_MTK_WMT_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_INVENTORY=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_CORE=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_CORE_KUNIT_TEST=' .config
      ${
        if consysIdentityOverlay
        then ''
          grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_LIVE=y' .config
          grep -Fqx 'CONFIG_MFD_SYSCON=y' .config
          grep -Fqx 'CONFIG_PM_GENERIC_DOMAINS=y' .config
          grep -Fqx 'CONFIG_PM_GENERIC_DOMAINS_OF=y' .config
          grep -Fqx 'CONFIG_REGULATOR_MT6351=y' .config
          grep -Fqx 'CONFIG_MTK_SCPSYS=y' .config
        ''
        else ''
          ! grep -q '^CONFIG_MTK_MT6797_CONSYS_LIVE=' .config
        ''
      }
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_INVENTORY=y' .config
      ${lib.optionalString platformEnablement ''
        grep -Fqx 'CONFIG_DRM=y' .config
        grep -Fqx 'CONFIG_DRM_MEDIATEK=y' .config
        grep -Fqx 'CONFIG_DRM_PANEL_NOVATEK_NT36672E=y' .config
        grep -Fqx 'CONFIG_PHY_MTK_MIPI_DSI=y' .config
        grep -Fqx 'CONFIG_REGULATOR_LP3101=y' .config
        grep -Fqx 'CONFIG_SND=y' .config
        grep -Fqx 'CONFIG_SND_SOC=y' .config
        grep -Fqx 'CONFIG_SND_SOC_MT6797=y' .config
        grep -Fqx 'CONFIG_SND_SOC_MT6797_MT6351=y' .config
        grep -Fqx 'CONFIG_SND_SOC_MT6351=y' .config
        grep -Fqx 'CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX=y' .config
        ! grep -q '^CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX_KUNIT_TEST=' .config
      ''}
      grep -A20 -F 'consys: consys@18070000 {' \
        arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts \
        | grep -Fq 'status = "disabled";'
      grep -A12 -F 'btif: serial@1100c000 {' \
        arch/arm64/boot/dts/mediatek/mt6797.dtsi \
        | grep -Fq 'compatible = "mediatek,mt6797-btif",'
      grep -A12 -F 'btif: serial@1100c000 {' \
        arch/arm64/boot/dts/mediatek/mt6797.dtsi \
        | grep -Fq 'status = "disabled";'
      grep -Fqx '# CONFIG_MTK_MT6797_A72_POWER is not set' .config
      grep -Fqx '# CONFIG_MTK_MT6797_DVFSP_RESOURCE_OWNER is not set' .config
      grep -Eq '^CONFIG_CMDLINE=".*maxcpus=8( |")' .config
      grep -Fqx '# CONFIG_SCSI is not set' .config
      grep -Fqx '# CONFIG_ATA is not set' .config
      grep -Fqx '# CONFIG_USB_CONFIGFS is not set' .config
      grep -Fqx '# CONFIG_USB_GADGETFS is not set' .config
      grep -Fqx '# CONFIG_USB_MASS_STORAGE is not set' .config
      ! grep -q '^CONFIG_USB_STORAGE=' .config
      grep -Eq '^[[:space:]]*\.multipoint = true,$' drivers/usb/musb/mediatek.c
      grep -Fq 'mediatek,force-a-session-valid' drivers/phy/mediatek/phy-mtk-tphy.c
      grep -Fq 'devm_regulator_get_optional(dev, "vbus")' drivers/usb/typec/fusb301.c
      ${
        if usbHostOverlay
        then ''
          grep -Fqx 'CONFIG_USB=y' .config
          grep -Fqx 'CONFIG_USB_MUSB_HDRC=y' .config
          grep -Fqx 'CONFIG_USB_MUSB_HOST=y' .config
          grep -Fqx '# CONFIG_USB_MUSB_DUAL_ROLE is not set' .config
          grep -Fqx 'CONFIG_USB_MUSB_MEDIATEK=y' .config
          grep -Fqx 'CONFIG_MUSB_PIO_ONLY=y' .config
          grep -Fqx 'CONFIG_NOP_USB_XCEIV=y' .config
          grep -Fqx 'CONFIG_PACKET=y' .config
          grep -Fqx 'CONFIG_USB_NET_DRIVERS=y' .config
          grep -Fqx 'CONFIG_USB_USBNET=y' .config
          grep -Fqx 'CONFIG_USB_RTL8152=y' .config
          grep -Fqx 'CONFIG_USB_MON=y' .config
          grep -Fqx 'CONFIG_DYNAMIC_DEBUG=y' .config
          grep -Fqx 'CONFIG_DYNAMIC_DEBUG_CORE=y' .config
          grep -Fqx 'CONFIG_I2C_MT65XX=y' .config
          grep -Fqx 'CONFIG_TYPEC=y' .config
          grep -Fqx 'CONFIG_TYPEC_FUSB301=y' .config
          grep -Fqx 'CONFIG_REGULATOR_FIXED_VOLTAGE=y' .config
        ''
        else ''
          grep -Fqx '# CONFIG_USB is not set' .config
          grep -Fqx '# CONFIG_USB_MUSB_HDRC is not set' .config
        ''
      }
      ${
        if storageOverlay
        then ''
          grep -Fqx 'CONFIG_MTK_PMIC_WRAP=y' .config
          grep -Fqx 'CONFIG_MFD_MT6397=y' .config
          grep -Fqx 'CONFIG_REGULATOR_MT6351=y' .config
          grep -Fqx 'CONFIG_MMC=y' .config
          grep -Fqx 'CONFIG_MMC_BLOCK=y' .config
          grep -Fqx 'CONFIG_MMC_MTK=y' .config
        ''
        else ''
          grep -Fqx '# CONFIG_MMC is not set' .config
        ''
      }
      ${
        if debugOverlay
        then ''
          grep -Fqx '# CONFIG_PSTORE_GEMINI_ARM64_ENTRY_LEDGER is not set' .config
          grep -Fqx 'CONFIG_PSTORE_GEMINI_POST_RAMOOPS_CHECKPOINT=y' .config
          grep -Fqx 'CONFIG_CMDLINE="console=tty0 console=ttyS0,921600n8 earlycon maxcpus=8 nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init panic=0 g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=Gemini-L-DA921x-Bind g_ether.iSerialNumber=GEMINI_DA921X_BIND_20260729 clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused initcall_blacklist=mt6797_a72_power_driver_init fw_devlink=rpm${lib.optionalString consysIdentityOverlay " mt6797_consys_live.identity_experiment=1"}"' .config
        ''
        else ''
          grep -Fqx 'CONFIG_PSTORE_GEMINI_ARM64_ENTRY_LEDGER=y' .config
          grep -Fqx '# CONFIG_PSTORE_GEMINI_POST_RAMOOPS_CHECKPOINT is not set' .config
          grep -Fqx 'CONFIG_CMDLINE="console=ttyS0,921600n8 earlycon maxcpus=8 nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init panic=0 g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=Gemini-L-DA921x-Bind g_ether.iSerialNumber=GEMINI_DA921X_BIND_20260729 clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused initcall_blacklist=mt6797_a72_power_driver_init fw_devlink=rpm"' .config
        ''
      }
      runHook postConfigure
    '';

    buildPhase = ''
      runHook preBuild
      export SOURCE_DATE_EPOCH=1783123200
      unset NIX_LDFLAGS
      kernelMakeFlags=(
        ARCH=arm64
        CROSS_COMPILE=aarch64-unknown-linux-gnu-
      )
      make -j"$NIX_BUILD_CORES" "''${kernelMakeFlags[@]}" \
        Image Image.gz dtbs
      test "$(make "''${kernelMakeFlags[@]}" -s kernelrelease)" = \
        "7.1.3-gemini-da921x-lkro"
      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp arch/arm64/boot/Image "$out/Image"
      cp arch/arm64/boot/Image.gz "$out/Image.gz"
      cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dtb "$out/base.dtb"
      ${lib.optionalString consysIdentityOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-consys-identity.dtbo \
          "$out/mt6797-gemini-consys-identity.dtbo"
      ''}
      ${lib.optionalString displayOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-display.dtbo \
          "$out/mt6797-gemini-pda-display.dtbo"
      ''}
      ${lib.optionalString audioOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-audio.dtbo \
          "$out/mt6797-gemini-pda-audio.dtbo"
      ''}
      cp .config "$out/kernel.config"
      cp System.map vmlinux "$out/"

      # Device Tree output is compiler-independent and must match the reviewed
      # Reviewed tree: ixoo's hardware-passed DT plus dormant CONSYS and BTIF.
      test "$(sha256sum "$out/base.dtb" | cut -d' ' -f1)" = \
        ${baseDtbSha256}

      if strings "$out/Image" | grep -Fq /nix/store/; then
        echo "Nix store path leaked into mainline Image" >&2
        exit 1
      fi

      {
        echo "source-version=7.1.3"
        echo "linux-gemini-revision=${kernelRevision}"
        echo "ixoo-baseline-revision=${ixooRevision}"
        echo "ixoo-candidate-revision=${candidateRevision}"
        echo "ixoo-profile=${profile}"
        echo "nix-debug-overlay=${overlayLabel}"
        echo "nix-hardening=disabled-all"
        echo "source-patch-mode=preapplied-git-tree"
        echo "ixoo-patchset-sha256=ac1e5da43d6694178058c8a623405b2c53d8bd2782d5f1d3a23e05368dc18ae8"
        echo "ixoo-hardware-image-sha256=c5d73e077165f0f22b0d8ff109661edc29763c12f4ed6fbd64b2d0fef910e1cc"
        echo "ixoo-hardware-image-gz-sha256=086d109464533194abed2c19fa56e647033edd957dafb2ee2512acd3100ed9f1"
        printf 'compiler='
        aarch64-unknown-linux-gnu-gcc --version | head -n 1
        printf 'linker='
        aarch64-unknown-linux-gnu-ld --version | head -n 1
        (cd "$out" && sha256sum Image Image.gz base.dtb kernel.config System.map vmlinux)
        (cd "$out" && stat -c '%n size=%s' Image Image.gz base.dtb vmlinux)
      } > "$out/BUILD-MANIFEST"
      runHook postInstall
    '';

    dontStrip = true;
    dontPatchELF = true;
  };

  # Reuse ixoo's frozen candidate DT transformation, changing only its exact
  # input/output fingerprints for the reviewed disabled CONSYS inventory node.
  # It enables the
  # hardware-passed USB peripheral, I2C5/AW9523 keyboard, watchdog-without-IRQ,
  # and read-only I2C6/DA921x serviceability group, while keeping xHCI and SCP
  # disabled.  Its own fixed hashes make any source or output drift fatal.
  serviceabilityDtb =
    buildPkgs.runCommand "gemini-ixoo-serviceability-dtb${lib.optionalString usbHostOverlay "-usb11-host"}${lib.optionalString consysIdentityOverlay "-consys-identity"}${lib.optionalString platformEnablement "-platform"}${lib.optionalString displayOverlay "-display"}${lib.optionalString audioOverlay "-audio"}" {
      nativeBuildInputs = [buildPkgs.bash buildPkgs.dtc];
    } ''
      mkdir -p "$out"
      cp -R ${ixoo-candidate} candidate
      chmod -R u+w candidate
      providerBuilder=candidate/experiments/2026-08-17-mainline-da921x-readonly-provider-baseline/scripts/build-provider-dtb.sh
      substituteInPlace "$providerBuilder" \
        --replace-fail \
          'BASE_DTB_SHA256=380205e0546c1b87f4ce6b4c34fcd734a22dc42e3b1c3145044d396a16e00709' \
          'BASE_DTB_SHA256=${baseDtbSha256}' \
        --replace-fail \
          'OUTPUT_DTB_SHA256=d7dba05efa272c8264c8ea15c776fb88c21a0012603214b49dfd9e2893e87d48' \
          'OUTPUT_DTB_SHA256=${serviceabilityBaseDtbSha256}'
      bash "$providerBuilder" \
        --base-dtb ${kernel}/base.dtb \
        --output "$out/gemini-base.dtb" \
        > "$out/VALIDATION"
      test "$(sha256sum "$out/gemini-base.dtb" | cut -d' ' -f1)" = \
        ${serviceabilityBaseDtbSha256}
      test "$(fdtget "$out/gemini-base.dtb" /consys@18070000 status)" = disabled
      ${
        if usbHostOverlay
        then ''
          dtc -@ -I dts -O dtb \
            -o "$out/gemini-usb11-host.dtbo" \
            ${./mainline-usb11-host-overlay.dts}
          fdtoverlay \
            -i "$out/gemini-base.dtb" \
            -o "$out/gemini-platform.dtb" \
            "$out/gemini-usb11-host.dtbo"
          test "$(fdtget "$out/gemini-platform.dtb" /t-phy@11210000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /t-phy@11210000/usb-phy@11210800 status)" = okay
          test "$(fdtget -t x "$out/gemini-platform.dtb" /t-phy@11210000 reg)" = '0 11210000 0 800'
          fdtget -p "$out/gemini-platform.dtb" /t-phy@11210000/usb-phy@11210800 \
            | grep -Fqx 'mediatek,force-a-session-valid'
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11200000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11200000 dr_mode)" = host
          test "$(fdtget -t x "$out/gemini-base.dtb" /pinctrl@10005000 phandle)" = 9
          test "$(fdtget "$out/gemini-platform.dtb" /i2c@11007000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /i2c@11007000/typec@25 compatible)" = onsemi,fusb301a
          test "$(fdtget -t x "$out/gemini-platform.dtb" /i2c@11007000/typec@25 reg)" = 25
          test "$(fdtget "$out/gemini-platform.dtb" /i2c@11007000/typec@25/connector power-role)" = source
          fdtget -p "$out/gemini-platform.dtb" /i2c@11007000/typec@25 \
            | grep -Fqx 'vbus-supply'
          test "$(fdtget "$out/gemini-platform.dtb" /regulator-usb11-vbus regulator-name)" = usb11-vbus
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11271000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11271000 dr_mode)" = peripheral
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11271000/usb@11270000 status)" = disabled
          test "$(fdtget "$out/gemini-platform.dtb" /consys@18070000 status)" = disabled
          echo 'usb11-host-overlay=passed' >> "$out/VALIDATION"
          echo 'usb11-session=forced-valid-A-device-matching-vendor-sequence' >> "$out/VALIDATION"
          echo 'usb11-typec=i2c0-fusb301a-source-eint3' >> "$out/VALIDATION"
          echo 'usb11-vbus=gpio94-regulator-cc-attach-controlled' >> "$out/VALIDATION"
          echo 'usb11-route=gpio70-high-gpio71-low-gpio72-high-fixed-usb-mode' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-base.dtb" "$out/gemini-platform.dtb"
        ''
      }
      ${
        if consysIdentityOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-platform.dtb" \
            -o "$out/gemini-consys.dtb" \
            ${kernel}/mt6797-gemini-consys-identity.dtbo
          test "$(fdtget "$out/gemini-consys.dtb" /consys@18070000 compatible)" = \
            mediatek,mt6797-consys-identity
          test "$(fdtget "$out/gemini-consys.dtb" /consys@18070000 status)" = okay
          fdtget -p "$out/gemini-consys.dtb" /consys@18070000 \
            | grep -Fqx 'mediatek,conn-power-domain'
          fdtget -p "$out/gemini-consys.dtb" /consys@18070000 \
            | grep -Fqx 'mediatek,infracfg'
          fdtget -p "$out/gemini-consys.dtb" /consys@18070000 \
            | grep -Fqx 'mediatek,spm'
          ! fdtget "$out/gemini-consys.dtb" /consys@18070000 power-domains \
            >/dev/null 2>&1
          test "$(sha256sum "$out/gemini-platform.dtb" | cut -d' ' -f1)" = \
            ${usbPlatformDtbSha256}
          echo 'consys-identity-overlay=passed' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-platform.dtb" "$out/gemini-consys.dtb"
        ''
      }
      ${
        if displayOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-consys.dtb" \
            -o "$out/gemini-display.dtb" \
            ${kernel}/mt6797-gemini-pda-display.dtbo
          test "$(fdtget "$out/gemini-display.dtb" /dsi@1401c000/panel@0 compatible)" = \
            planet,gemini-pda-nt36672
          test "$(fdtget "$out/gemini-display.dtb" /i2c@11008000/regulator@3e compatible)" = \
            mediatek,i2c_lcd_bias
          echo 'display-overlay=passed' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-consys.dtb" "$out/gemini-display.dtb"
        ''
      }
      ${
        if audioOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-display.dtb" \
            -o "$out/gemini.dtb" \
            ${kernel}/mt6797-gemini-pda-audio.dtbo
          test "$(fdtget "$out/gemini.dtb" /audio-controller@11220000 status)" = okay
          test "$(fdtget "$out/gemini.dtb" /sound compatible)" = \
            mediatek,mt6797-mt6351-sound
          echo 'audio-overlay=passed' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-display.dtb" "$out/gemini.dtb"
        ''
      }
      test "$(sha256sum "$out/gemini.dtb" | cut -d' ' -f1)" = \
        ${finalDtbSha256}
      cat ${kernel}/Image.gz "$out/gemini.dtb" > "$out/Image.gz-dtb"
      (cd "$out" && sha256sum gemini-base.dtb gemini.dtb Image.gz-dtb) > "$out/SHA256SUMS"
    '';

  # This is intentionally smaller and less privileged than a NixOS stage 1.
  # The baseline has no storage drivers at all.  The storage variant adds only
  # ixoo's already hardware-passed 25 MHz eMMC enumeration fragment: userspace
  # reads sysfs metadata but never opens or mounts a block device.  SSH is
  # public-key-only; the old unauthenticated TCP shell is omitted whenever SSH
  # is present so a later host-network experiment cannot accidentally expose it.
  probeInitramfs =
    buildPkgs.runCommand "gemini-ixoo-probe-initramfs${variantSuffix}.cpio.gz" (
      {
        nativeBuildInputs = [buildPkgs.cpio buildPkgs.gzip];
        busybox = crossPkgs.pkgsStatic.busybox;
      }
      // lib.optionalAttrs sshAccess {
        dropbear = crossPkgs.pkgsStatic.dropbear;
        authorizedKeys = ../nixos/authorized_keys;
      }
    ) ''
      mkdir -p root/bin root/dev root/etc root/mnt/linux root/proc root/run root/sys/fs/pstore
      cp "$busybox/bin/busybox" root/bin/busybox
      ${lib.optionalString sshAccess ''
        mkdir -p root/etc/dropbear root/root/.ssh
        cp "$dropbear/bin/dropbear" root/bin/dropbear
        cp "$dropbear/bin/dropbearkey" root/bin/dropbearkey
        cp "$authorizedKeys" root/root/.ssh/authorized_keys
        chmod 0700 root/root root/root/.ssh
        chmod 0600 root/root/.ssh/authorized_keys
        cat > root/etc/passwd <<'PASSWD'
        root:*:0:0:root:/root:/bin/sh
        PASSWD
        cat > root/etc/group <<'GROUP'
        root:x:0:
        GROUP
        cat > root/etc/shells <<'SHELLS'
        /bin/sh
        SHELLS
        cat > root/etc/hostname <<'HOSTNAME'
        gemini-mainline-probe
        HOSTNAME
      ''}

      cat > root/init <<'INIT'
      #!/bin/busybox sh
      export PATH=/bin
      /bin/busybox --install -s /bin

      mount -t devtmpfs -o nosuid,mode=0755 devtmpfs /dev
      mkdir -p /dev/pts
      mount -t devpts -o nosuid,noexec,mode=0620 devpts /dev/pts 2>/dev/null || true
      mount -t proc -o ro,nosuid,nodev,noexec proc /proc 2>/dev/null || true
      mount -t sysfs -o ro,nosuid,nodev,noexec sysfs /sys 2>/dev/null || true
      mount -t tmpfs -o nosuid,nodev,mode=0755 tmpfs /run 2>/dev/null || true

      exec </dev/console >/dev/console 2>&1

      note() {
        echo "GEMINI_NIX_IXOO_PROBE: $*"
        echo "<6>GEMINI_NIX_IXOO_PROBE: $*" > /dev/kmsg 2>/dev/null || true
        echo "GEMINI_NIX_IXOO_PROBE: $*" >> /run/probe-status 2>/dev/null || true
      }

      note "stage=initramfs-entered storage_access=${
        if storageOverlay
        then "enumeration-only userspace_block_io=none"
        else "none"
      }"
      note "kernel=$(uname -r 2>/dev/null || echo unknown)"
      if [ -c /dev/watchdog0 ]; then
        note "watchdog0=present identity=$(cat /sys/class/watchdog/watchdog0/identity 2>/dev/null || echo unknown) timeout=$(cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null || echo unknown) userspace_open=none"
      else
        note "watchdog0=missing userspace_open=none"
      fi
      udc_names=
      for udc in /sys/class/udc/*; do
        [ -e "$udc" ] || continue
        udc_names="''${udc_names}''${udc##*/} "
      done
      note "udc=''${udc_names:-missing}"
      if mount -t pstore -o ro,nosuid,nodev,noexec pstore /sys/fs/pstore 2>/dev/null; then
        note "pstore=mounted records=$(find /sys/fs/pstore -maxdepth 1 -type f 2>/dev/null | wc -l)"
      else
        note "pstore=unavailable"
      fi
      /bin/usb-net &
      /bin/tty-shell &
      ${lib.optionalString storageOverlay ''
      /bin/storage-probe &
      ''}
      ${lib.optionalString rootfsProbe ''
      /bin/rootfs-probe &
      ''}
      ${lib.optionalString sshAccess ''
      /bin/ssh-server &
      note "ssh=dropbear key_only=yes listen=all_ipv4 port=22 forwarding=disabled"
      ''}

      while :; do
        sleep 3600
      done
      INIT

      cat > root/bin/tty-shell <<'TTY_SHELL'
      #!/bin/busybox sh
      export PATH=/bin
      attempt=0
      while [ ! -c /dev/tty1 ] && [ "$attempt" -lt 60 ]; do
        attempt=$((attempt + 1))
        sleep 1
      done
      if [ ! -c /dev/tty1 ]; then
        echo "tty1=missing after=60s" >> /run/probe-status 2>/dev/null || true
        echo "<3>GEMINI_NIX_IXOO_PROBE: tty1=missing after=60s" > /dev/kmsg 2>/dev/null || true
        exit 1
      fi
      exec setsid sh -c '
        exec </dev/tty1 >/dev/tty1 2>&1
        echo GEMINI_NIX_IXOO_PROBE
        echo stage=interactive-initramfs transport=tty1
        echo "kernel=$(uname -r 2>/dev/null || echo unknown)"
        echo "cmdline=$(cat /proc/cmdline 2>/dev/null || echo unknown)"
        cat /run/probe-status 2>/dev/null || true
        echo pstore-records:
        find /sys/fs/pstore -maxdepth 1 -type f -print 2>/dev/null || true
        echo dmesg-tail:
        dmesg 2>/dev/null | tail -n 80 || true
        exec sh
      '
      TTY_SHELL

      cat > root/bin/usb-net <<'USB_NET'
      #!/bin/busybox sh
      attempt=0
      while [ ! -d /sys/class/net/usb0 ] && [ "$attempt" -lt 30 ]; do
        attempt=$((attempt + 1))
        sleep 1
      done
      if [ ! -d /sys/class/net/usb0 ]; then
        echo "<3>GEMINI_NIX_IXOO_PROBE: usb0=missing" > /dev/kmsg 2>/dev/null || true
        echo "usb0=missing after=30s" >> /run/probe-status 2>/dev/null || true
        for udc in /sys/class/udc/*; do
          [ -e "$udc" ] || continue
          echo "udc=$(basename "$udc") state=$(cat "$udc/state" 2>/dev/null || echo unknown)" >> /run/probe-status 2>/dev/null || true
        done
        exit 1
      fi
      ip link set usb0 up
      ip address add 10.15.19.82/24 dev usb0
      echo "<6>GEMINI_NIX_IXOO_PROBE: usb0=ready address=10.15.19.82/24 access=${
        if sshAccess then "ssh:22" else "tcp:2323"
      }" > /dev/kmsg 2>/dev/null || true
      echo "usb0=ready address=10.15.19.82/24 access=${
        if sshAccess then "ssh:22" else "tcp:2323"
      }" >> /run/probe-status
      ${
        if sshAccess
        then "exit 0"
        else "exec nc -lk -p 2323 -e /bin/usb-shell"
      }
      USB_NET

      cat > root/bin/usb-shell <<'USB_SHELL'
      #!/bin/busybox sh
      export PATH=/bin
      echo 'GEMINI_NIX_IXOO_PROBE'
      echo 'stage=interactive-initramfs'
      echo 'warning=unauthenticated-direct-usb-root-shell'
      echo "kernel=$(uname -r 2>/dev/null || echo unknown)"
      echo "cpu_online=$(cat /sys/devices/system/cpu/online 2>/dev/null || echo unknown)"
      echo "cmdline=$(cat /proc/cmdline 2>/dev/null || echo unknown)"
      cat /run/probe-status 2>/dev/null || true
      echo 'pstore-records:'
      find /sys/fs/pstore -maxdepth 1 -type f -print 2>/dev/null || true
      echo 'dmesg-tail:'
      dmesg 2>/dev/null | tail -n 80 || true
      exec /bin/sh
      USB_SHELL

      ${lib.optionalString storageOverlay ''
        cat > root/bin/storage-probe <<'STORAGE_PROBE'
        #!/bin/busybox sh
        export PATH=/bin
        record() {
          echo "GEMINI_NIX_IXOO_STORAGE: $*" >> /run/storage-probe 2>/dev/null || true
          echo "GEMINI_NIX_IXOO_STORAGE: $*" >> /run/probe-status 2>/dev/null || true
          echo "<6>GEMINI_NIX_IXOO_STORAGE: $*" > /dev/kmsg 2>/dev/null || true
        }

        attempt=0
        while [ ! -e /sys/class/block/mmcblk0 ] && [ "$attempt" -lt 30 ]; do
          attempt=$((attempt + 1))
          sleep 1
        done
        if [ ! -e /sys/class/block/mmcblk0 ]; then
          record "emmc=missing after=30s userspace_block_io=none"
          dmesg 2>/dev/null | grep -Ei '1000d000|pwrap|mt6351|11230000|msdc|mmc0|mmcblk' >> /run/storage-probe 2>/dev/null || true
          exit 1
        fi

        if grep -Eq '^[^ ]*mmcblk' /proc/mounts 2>/dev/null; then
          record "guard=failed unexpected_mmc_mount=yes"
          exit 1
        fi
        sectors=$(cat /sys/class/block/mmcblk0/size 2>/dev/null || echo unknown)
        device=$(readlink -f /sys/class/block/mmc0/device 2>/dev/null || echo unknown)
        partitions=
        for node in /sys/class/block/mmcblk0p*; do
          [ -e "$node" ] || continue
          partitions="''${partitions} ''${node##*/}"
        done
        record "emmc=present sectors=$sectors host=$device partitions=''${partitions# } userspace_block_reads=none userspace_block_writes=none mounts=none"
        for uevent in /sys/class/block/mmcblk*/uevent; do
          [ -r "$uevent" ] || continue
          echo "--- $uevent" >> /run/storage-probe
          cat "$uevent" >> /run/storage-probe
        done
        dmesg 2>/dev/null | grep -Ei '1000d000|pwrap|mt6351|11230000|msdc|mmc0|mmcblk' >> /run/storage-probe 2>/dev/null || true
        STORAGE_PROBE
      ''}

      ${lib.optionalString rootfsProbe ''
        cat > root/bin/rootfs-probe <<'ROOTFS_PROBE'
        #!/bin/busybox sh
        export PATH=/bin
        record() {
          echo "GEMINI_NIX_IXOO_ROOTFS: $*" >> /run/rootfs-probe 2>/dev/null || true
          echo "GEMINI_NIX_IXOO_ROOTFS: $*" >> /run/probe-status 2>/dev/null || true
          echo "<6>GEMINI_NIX_IXOO_ROOTFS: $*" > /dev/kmsg 2>/dev/null || true
        }

        # Preserve the storage probe's stronger no-userspace-block-I/O result
        # before this separate stage deliberately performs read-only ext4 I/O.
        attempt=0
        while ! grep -q 'emmc=present' /run/storage-probe 2>/dev/null && [ "$attempt" -lt 35 ]; do
          attempt=$((attempt + 1))
          sleep 1
        done
        if ! grep -q 'emmc=present' /run/storage-probe 2>/dev/null; then
          record "mount=skipped reason=storage-enumeration-not-proven"
          exit 1
        fi

        if ! mount -t ext4 -o ro,noload,nosuid,nodev,noexec /dev/mmcblk0p29 /mnt/linux; then
          record "mount=failed source=/dev/mmcblk0p29 requested=ro,noload"
          dmesg 2>/dev/null | grep -Ei 'EXT4-fs|mmcblk0p29' >> /run/rootfs-probe 2>/dev/null || true
          exit 1
        fi
        mounted=$(awk '$2 == "/mnt/linux" { print $1 ":" $3 ":" $4; exit }' /proc/mounts)
        record "mount=success source=/dev/mmcblk0p29 observed=''${mounted:-unknown} access=directory-metadata-only writes=none"
        if [ -d /mnt/linux/nixos ]; then
          record "nixos-directory=present"
          for entry in /mnt/linux/nixos/*; do
            [ -e "$entry" ] || continue
            size=$(stat -c %s "$entry" 2>/dev/null || echo unknown)
            kind=file
            [ -d "$entry" ] && kind=directory
            [ -L "$entry" ] && kind=symlink
            record "entry=''${entry##*/} kind=$kind size=$size"
          done
        else
          record "nixos-directory=missing"
        fi
        dmesg 2>/dev/null | grep -Ei 'EXT4-fs|mmcblk0p29' >> /run/rootfs-probe 2>/dev/null || true
        ROOTFS_PROBE
      ''}

      ${lib.optionalString sshAccess ''
        cat > root/bin/ssh-server <<'SSH_SERVER'
        #!/bin/busybox sh
        export PATH=/bin
        hostname gemini-mainline-probe 2>/dev/null || true
        key=/run/dropbear-ed25519-host-key
        if ! dropbearkey -t ed25519 -f "$key" > /run/dropbear-keygen.log 2>&1; then
          echo "<3>GEMINI_NIX_IXOO_PROBE: ssh=failed stage=host-key" > /dev/kmsg 2>/dev/null || true
          echo "ssh=failed stage=host-key" >> /run/probe-status 2>/dev/null || true
          exit 1
        fi
        echo "<6>GEMINI_NIX_IXOO_PROBE: ssh=starting key_only=yes listen=all_ipv4 port=22 forwarding=disabled" > /dev/kmsg 2>/dev/null || true
        exec dropbear \
          -F -E -s -j -k -m -K 30 -T 4 \
          -P /run/dropbear.pid \
          -p 22 \
          -r "$key" \
          >> /run/dropbear.log 2>&1
        SSH_SERVER
      ''}

      chmod 0755 root/init root/bin/tty-shell root/bin/usb-net root/bin/usb-shell
      ${lib.optionalString storageOverlay ''
        chmod 0755 root/bin/storage-probe
      ''}
      ${lib.optionalString rootfsProbe ''
        chmod 0755 root/bin/rootfs-probe
      ''}
      ${lib.optionalString sshAccess ''
        chmod 0755 root/bin/dropbear root/bin/dropbearkey root/bin/ssh-server
      ''}
      find root -exec touch -h -d @0 {} +
      (
        cd root
        find . -print0 | sort -z | cpio --null --create --format=newc \
          --owner=0:0 --reproducible --quiet
      ) | gzip -n -9 > "$out"
    '';

  probeBootImg =
    buildPkgs.runCommand "gemini-ixoo-mainline-probe${variantSuffix}.boot.img" {
      nativeBuildInputs = [buildPkgs.python3];
    } ''
      python3 ${ixoo-kernel}/experiments/2026-07-12-boot-contract-recovery/scripts/build-android-boot-v0.py \
        --kernel ${kernel}/Image.gz \
        --ramdisk ${probeInitramfs} \
        --dtb ${serviceabilityDtb}/gemini.dtb \
        --dtb-mode append \
        --lk-android8 \
        --page-size 2048 \
        --kernel-addr 0x40200000 \
        --ramdisk-addr 0x45000000 \
        --second-addr 0x40f00000 \
        --tags-addr 0x44000000 \
        --cmdline "bootopt=64S3,32N2,64N2" \
        --output "$out"

      readLe32() {
        od -An -tu4 -j "$1" -N 4 "$out" | tr -d '[:space:]'
      }
      test "$(od -An -tx1 -N 8 "$out" | tr -d '[:space:]')" = \
        414e44524f494421
      test "$(readLe32 12)" = 1075838976
      test "$(readLe32 20)" = 1157627904
      test "$(readLe32 24)" = 0
      test "$(readLe32 28)" = 1089470464
      test "$(readLe32 32)" = 1140850688
      test "$(readLe32 36)" = 2048
      test "$(readLe32 40)" = 0
      test "$(dd if="$out" bs=1 skip=64 count=512 status=none | tr -d '\000')" = \
        "bootopt=64S3,32N2,64N2"
      test "$(stat -c %s "$out")" -le 16777216
    '';

  probeBoot2Img = buildPkgs.runCommand "gemini-ixoo-mainline-probe${variantSuffix}-padded.img" {} ''
    cp --no-preserve=mode ${probeBootImg} "$out"
    truncate -s 16777216 "$out"
    test "$(stat -c %s "$out")" -eq 16777216
  '';

  bundle = buildPkgs.runCommand "gemini-ixoo-mainline-probe${variantSuffix}-bundle" {} ''
    mkdir -p "$out"
    ln -s ${kernel} "$out/kernel"
    ln -s ${serviceabilityDtb}/gemini.dtb "$out/gemini-serviceability.dtb"
    ln -s ${probeInitramfs} "$out/probe-initramfs.cpio.gz"
    ln -s ${probeBootImg} "$out/probe-raw.boot.img"
    ln -s ${probeBoot2Img} "$out/probe-padded-boot2.img"
    {
      echo "linux-gemini-revision=${kernelRevision}"
      echo "ixoo-baseline-revision=${ixooRevision}"
      echo "ixoo-candidate-revision=${candidateRevision}"
      echo "ixoo-profile=${profile}"
      echo "nix-debug-overlay=${overlayLabel}"
      echo "nix-storage-overlay=${storageLabel}"
      echo "nix-access=${accessLabel}"
      echo "nix-rootfs-probe=${rootfsLabel}"
      echo "nix-usb-host=${usbHostLabel}"
      echo "nix-consys-identity=${consysIdentityLabel}"
      echo "nix-platform-enablement=${if platformEnablement then "reviewed-dormant-v1" else "none"}"
      echo "nix-display=${displayLabel}"
      echo "nix-audio=${audioLabel}"
      echo "nix-hardening=disabled-all"
      echo "hardware-proof=ixoo-Buildbox-artifact-only"
      echo "nix-kernel-byte-match-ixoo=no"
      echo "target=slot-independent 16MiB Android-v0 boot partition"
      echo "storage-access=${
        if storageOverlay
        then "enumeration-only; userspace opens no block device"
        else "none"
      }"
      echo "rootfs-access=${
        if rootfsProbe
        then "p29 ext4 ro,noload; directory metadata only; no writes"
        else "none"
      }"
      echo "android-header-version=0"
      echo "android-page-size=2048"
      echo "kernel-address=0x40200000"
      echo "ramdisk-address=0x45000000"
      echo "second-address=0x40f00000"
      echo "tags-address=0x44000000"
      echo "android-cmdline=bootopt=64S3,32N2,64N2"
      echo "usb-device-address=10.15.19.82/24"
      echo "usb-host-address=10.15.19.1/24"
      ${
        if sshAccess
        then ''
          echo "ssh=dropbear key-only listen-all-ipv4 port=22 forwarding-disabled"
          echo "usb-tcp-shell=disabled"
          sha256sum \
            ${crossPkgs.pkgsStatic.dropbear}/bin/dropbear \
            ${crossPkgs.pkgsStatic.dropbear}/bin/dropbearkey \
            ${../nixos/authorized_keys}
        ''
        else ''
          echo "ssh=disabled"
          echo "usb-tcp-shell=2323 unauthenticated direct-link-only"
        ''
      }
      sha256sum \
        ${kernel}/Image \
        ${kernel}/Image.gz \
        ${serviceabilityDtb}/gemini.dtb \
        ${probeInitramfs} \
        ${probeBootImg} \
        ${probeBoot2Img}
      stat -c '%n size=%s' ${probeBootImg} ${probeBoot2Img}
    } > "$out/MANIFEST"
  '';
in {
  inherit kernel serviceabilityDtb probeInitramfs probeBootImg probeBoot2Img bundle;
}
