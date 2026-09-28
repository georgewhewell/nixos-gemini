{
  buildPkgs,
  oldPkgs,
  crossPkgs,
  ixoo-kernel,
  linux-gemini,
  ixoo-candidate,
  extendedPlatformDtb ? false,
  debugOverlay ? true,
  storageOverlay ? false,
  sshAccess ? false,
  rootfsProbe ? false,
  usbHostOverlay ? false,
  consysIdentityOverlay ? false,
  consysG2bOverlay ? false,
  consysG2cPatchOverlay ? false,
  consysG2dPostpatchOverlay ? false,
  consysFirmware ? false,
  gpuStagedOverlay ? false,
  gpuFixedOppOverlay ? false,
  gpuDeferredBind ? false,
  pdIgnoreUnused ? false,
  legacyConsysPlatform ? true,
  microsdOverlay ? false,
  platformEnablement ? false,
  displayOverlay ? false,
  audioOverlay ? false,
  audioHeadphoneTest ? false,
  powerObserveOverlay ? false,
  powerObservePreflight ? false,
  unattendedRecovery ? false,
  inputObserveOverlay ? false,
  thermalHallObserveOverlay ? false,
  touchscreenActivationOverlay ? false,
  fgadcActivationOverlay ? false,
  deviceActivationOverlay ? false,
  cellularOverlay ? false,
  a72Overlay ? false,
  gpuOwnerOverlay ? false,
  desktopScanout ? false,
  connectivityModules ? false,
  rtcPowerKeyOverlay ? false,
  leaseSelfAcceptToken ? null,
}:
assert leaseSelfAcceptToken == null || builtins.match "gemini-baseline-lease-v1-[0-9a-f]{64}" leaseSelfAcceptToken != null;
assert leaseSelfAcceptToken == null || unattendedRecovery;
assert !desktopScanout || (gpuOwnerOverlay && displayOverlay);
let
  lib = buildPkgs.lib;

  # A locked Git input carries rev; a deliberate local-path override carries
  # only its content hash.  Record whichever identity Nix actually consumed so
  # a local reviewed build can never masquerade as the old locked commit.
  kernelRevision =
    if linux-gemini ? rev
    then linux-gemini.rev
    else "nar:${linux-gemini.narHash}";
  # 28c47150 plus the commits that poll for MicroSD presence instead of
  # trusting GPIO67, and then move the MicroSD hardware description
  # (pinmux, mmc0/mmc1 aliases, &mmc1 bus-width/max-frequency/no-1-8-v/
  # broken-cd/supplies) out of mt6797-gemini-pda-microsd-bringup.dtso and
  # into the base mt6797-gemini-pda.dts, leaving that overlay as activation
  # only (&mmc1 { status = "okay"; }).  This moves gemini-base.dtb itself, so
  # the reviewed touchscreen/FGADC activation paths this pin guards are
  # re-verified against the new base DT, not left untouched: the accepted
  # baseline now produces
  # 2ae4edd4be1d4484729c3b6fd4eba8dcb08d70527d8ee02275d6470f3e174958.
  # M12 adds the proven polled MicroSD overlay to the ten-CPU image.
  # Base board DT,
  # input and PMIC drivers remain unchanged; the separate A72 overlay path
  # verifies its complete property delta before publishing the candidate DT.
  p22BaselinePlatformRevision = "ed239daac8c71587d90a8333eb9baf59c46ec48e";
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
    ++ lib.optionals consysG2bOverlay [./mainline-consys-g2b.fragment]
    ++ lib.optionals consysG2cPatchOverlay [./mainline-consys-g2c-patch.fragment]
    ++ lib.optionals consysG2dPostpatchOverlay [./mainline-consys-g2d-postpatch.fragment]
    ++ lib.optionals gpuStagedOverlay [./mainline-gpu-staged.fragment]
    ++ lib.optionals gpuFixedOppOverlay [./mainline-gpu-fixed-opp.fragment]
    ++ lib.optionals (!legacyConsysPlatform) [./mainline-reworked-consys.fragment]
    ++ lib.optionals platformEnablement [./mainline-platform-smoke.fragment]
    ++ lib.optionals powerObserveOverlay [./mainline-power-observe.fragment]
    ++ lib.optionals unattendedRecovery [./mainline-unattended-recovery.fragment]
    ++ lib.optionals inputObserveOverlay [./mainline-input-observe.fragment]
    ++ lib.optionals thermalHallObserveOverlay [./mainline-thermal-hall-observe.fragment]
    ++ lib.optionals touchscreenActivationOverlay [./mainline-touchscreen-activation.fragment]
    ++ lib.optionals fgadcActivationOverlay [./mainline-fgadc-activation.fragment]
    ++ lib.optionals deviceActivationOverlay [./mainline-device-activation.fragment]
    ++ lib.optionals cellularOverlay [./mainline-cellular-integration.fragment]
    ++ lib.optionals a72Overlay [./mainline-a72-integration.fragment]
    ++ lib.optionals gpuOwnerOverlay [./mainline-gpu-owner.fragment]
    ++ lib.optionals desktopScanout [./mainline-desktop.fragment]
    ++ lib.optionals connectivityModules [./mainline-connectivity-modules.fragment]
    ++ lib.optionals rtcPowerKeyOverlay [./mainline-rtc-power-key.fragment];
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
  consysG2bLabel =
    if consysG2bOverlay
    then
      if consysFirmware
      then "emi-identity-postid-raw-mandatory-full-wmt-firmware-packaged-no-patch-v1"
      else "emi-identity-postid-raw-mandatory-full-no-firmware-v1"
    else "none";
  consysG2cPatchLabel =
    if consysG2cPatchOverlay
    then "emi-identity-postid-raw-mandatory-full-hash-pinned-patch-only-v1"
    else "none";
  consysG2dPostpatchLabel =
    if consysG2dPostpatchOverlay
    then "emi-identity-postid-full-wmt-hash-pinned-patch-postpatch-no-radio-client-v1"
    else "none";
  consysFirmwareAvailable = consysFirmware || consysG2cPatchOverlay || consysG2dPostpatchOverlay;
  consysFirmwareLabel =
    if consysG2cPatchOverlay || consysG2dPostpatchOverlay
    then "three-blob-exact-size-sha256-patch-manifest-enabled-v1"
    else if consysFirmware
    then "tracked-production-wmt-patch-preflight-only-v1"
    else "none";
  gpuStagedLabel =
    if gpuStagedOverlay
    then "rt5735-mfg-four-domain-bg3d-readonly-id-stage2-v1"
    else "none";
  gpuFixedOppLabel =
    if gpuFixedOppOverlay
    then "panfrost-single-500500000hz-975000uv-type12-v1"
    else "none";
  displayLabel =
    if displayOverlay
    then "nt36672-lp3101-smi-bypass-recovery-smoke-v2"
    else "none";
  audioLabel =
    if audioOverlay
    then "mt6797-mt6351-enumeration-only-v1"
    else "none";
  audioHeadphoneTestLabel =
    if audioHeadphoneTest
    then "manual-staged-alsa-boundary-diagnostic-v2"
    else "none";
  powerObserveLabel =
    if powerObserveOverlay
    then "bq2589x-i2c0-no-write-no-irq-v1"
    else "none";
  powerObservePreflightLabel =
    if powerObservePreflight
    then "bq2589x-sysfs-dmesg-no-write-watchdog-markers-v1"
    else "none";
  unattendedRecoveryLabel =
    if unattendedRecovery
    then "mtk-wdt-probe-start-90s-open-timeout-initramfs-pet-v2"
    else "none";
  inputObserveLabel =
    if inputObserveOverlay && thermalHallObserveOverlay
    then "aw9523-matrix-poll-nt36772-i2c4-client-disabled-mt6797-thermal-hall-observe-v2"
    else if inputObserveOverlay
    then "aw9523-matrix-poll-and-nt36772-i2c4-client-disabled-v1"
    else "none";
  deviceActivationLabel =
    if deviceActivationOverlay
    then "nt36772-fgadc-microsd-3v-live-proven-v1"
    else "none";
  touchscreenActivationLabel =
    if touchscreenActivationOverlay
    then "nt36772-i2c4-0x62-live-proven-v1"
    else "none";
  fgadcActivationLabel =
    if fgadcActivationOverlay
    then "mt6351-exact-0x28-osr8-live-proven-v1"
    else "none";
  panicCmdline = if unattendedRecovery then "panic=5" else "panic=0";
  baseCmdline =
    if debugOverlay
    then "console=tty0 console=ttyS0,921600n8 earlycon maxcpus=8 nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init ${panicCmdline} g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=Gemini-L-DA921x-Bind g_ether.iSerialNumber=GEMINI_DA921X_BIND_20260729 clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused ${lib.optionalString (!a72Overlay) "initcall_blacklist=mt6797_a72_power_driver_init "}fw_devlink=rpm"
    else "console=ttyS0,921600n8 earlycon maxcpus=8 nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init ${panicCmdline} g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=Gemini-L-DA921x-Bind g_ether.iSerialNumber=GEMINI_DA921X_BIND_20260729 clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused ${lib.optionalString (!a72Overlay) "initcall_blacklist=mt6797_a72_power_driver_init "}fw_devlink=rpm";
  kernelCmdline =
    baseCmdline
    + lib.optionalString gpuOwnerOverlay " mtk_scpsys.mt6797_gpuldo_owner=1"
    + lib.optionalString connectivityModules " mt6797_consys_emi_mpu.enable_experimental_ownership=1"
    + lib.optionalString cellularOverlay " GEMINI_A72_CI9_M39 mt6797_md1_lk_handoff_probe.enable_experimental_md1_lk_handoff_probe=1 mt6797_md1_boot_status_observe.enable_experimental_boot_status=1 mt6797_md1_remap_observe.enable_experimental_md1_remap_observe=1 mt6797_md1_emi_mpu.enable_experimental_md1_emi_mpu=1 mt6797_md1_cold_owner_driver.enable_experimental_md1_cold_owner=1 mt6797_md1_cold_owner_driver.enable_experimental_md1_boot_vector_release=1 mtk_mt6797_ccci.enable=1 mt6797_md1_fs_provider.enable=1 mt6797_md1_fs_provider.enable_volatile=1"
    + lib.optionalString consysIdentityOverlay " mt6797_consys_live.identity_experiment=1"
    + lib.optionalString consysG2bOverlay " mt6797_consys_emi_mpu.enable_experimental_ownership=1 mt6797_consys_runtime.enable_experimental_runtime=1 mt6797_btif_pio_platform.enable_experimental_platform_adapter=1 mt6797_btif_stp_bootstrap.enable_experimental_stp_bootstrap=1 mt6797_consys_runtime_controller.enable_experimental_runtime_controller=1 mt6797_consys_g2b_owner.enable_experimental_g2b_owner=1"
    + lib.optionalString consysG2cPatchOverlay " mt6797_consys_emi_mpu.enable_experimental_ownership=1 mt6797_consys_runtime.enable_experimental_runtime=1 mt6797_btif_pio_platform.enable_experimental_platform_adapter=1 mt6797_btif_stp_bootstrap.enable_experimental_stp_bootstrap=1 mt6797_consys_runtime_controller.enable_experimental_runtime_controller=1 mt6797_consys_wmt_patch.enable_patch_download=1 mt6797_consys_g2c_patch_owner.enable_experimental_g2c_patch_owner=1"
    + lib.optionalString consysG2dPostpatchOverlay " mt6797_consys_emi_mpu.enable_experimental_ownership=1 mt6797_consys_runtime.enable_experimental_runtime=1 mt6797_btif_pio_platform.enable_experimental_platform_adapter=1 mt6797_btif_stp_bootstrap.enable_experimental_stp_bootstrap=1 mt6797_consys_runtime_controller.enable_experimental_runtime_controller=1 mt6797_consys_wmt_patch.enable_patch_download=1 mt6797_consys_g2d_postpatch_owner.enable_experimental_g2d_postpatch_owner=1"
    + lib.optionalString gpuStagedOverlay " mt6797_gpu_staged.enable_experimental_stages=1 mt6797_gpu_staged.stage=2 mt6797_gpu_staged.max_stage_ms=3000"
    + lib.optionalString gpuDeferredBind " initcall_blacklist=panfrost_driver_init"
    + lib.optionalString pdIgnoreUnused " pd_ignore_unused"
    + lib.optionalString unattendedRecovery " mtk_wdt.start_at_boot=1"
    + lib.optionalString (leaseSelfAcceptToken != null) " gemini.baseline_lease_capability=${leaseSelfAcceptToken}";
  variantSuffix =
    lib.optionalString storageOverlay "-emmc-probe"
    + lib.optionalString sshAccess "-ssh"
    + lib.optionalString rootfsProbe "-p29-ro"
    + lib.optionalString usbHostOverlay "-usb11-host"
    + lib.optionalString consysIdentityOverlay "-consys-identity"
    + lib.optionalString consysG2bOverlay "-consys-g2b"
    + lib.optionalString consysG2cPatchOverlay "-consys-g2c-patch"
    + lib.optionalString consysG2dPostpatchOverlay "-consys-g2d-postpatch"
    + lib.optionalString consysFirmware "-consys-firmware"
    + lib.optionalString gpuStagedOverlay "-gpu-staged"
    + lib.optionalString gpuFixedOppOverlay "-gpu-fixed-opp"
    + lib.optionalString gpuDeferredBind "-deferred-bind"
    + lib.optionalString pdIgnoreUnused "-pd-ignore-unused"
    + lib.optionalString (!legacyConsysPlatform) "-reworked-consys"
    + lib.optionalString microsdOverlay "-microsd"
    + lib.optionalString platformEnablement "-platform"
    + lib.optionalString displayOverlay "-display"
    + lib.optionalString audioOverlay "-audio"
    + lib.optionalString audioHeadphoneTest "-audio-headphone-test"
    + lib.optionalString powerObserveOverlay "-power-observe"
    + lib.optionalString powerObservePreflight "-power-preflight"
    + lib.optionalString unattendedRecovery "-unattended-recovery"
    + lib.optionalString inputObserveOverlay "-input-observe"
    + lib.optionalString thermalHallObserveOverlay "-thermal-hall-observe"
    + lib.optionalString touchscreenActivationOverlay "-touchscreen-active"
    + lib.optionalString fgadcActivationOverlay "-fgadc-active"
    + lib.optionalString deviceActivationOverlay "-device-activation";
  # linux-gemini-next adds the VCN33 and GPU-devinfo nodes. Keep exact hashes
  # for both pinned DT layouts instead of applying the newer hash to the
  # accepted baseline source.
  # The reworked-CONSYS lineage folded the observation overlays into its board
  # DT and enables CONSYS there, so its base.dtb is a different artifact again.
  baseDtbSha256 =
    if !legacyConsysPlatform
    then "01b4866c736ce8b452c8489c273478827a9dd2c944954021e347a2147a7ab2a5"
    else if extendedPlatformDtb
    then "64e088457d8232b6db1bd194919558049988abf340802fe576f194656a58dc9c"
    else "48d9d9c6ee3c526f2139edd7c14cfb31cb6a7ed2381f4f436188582851be84c3";
  serviceabilityBaseDtbSha256 =
    if !legacyConsysPlatform
    then "0000000000000000000000000000000000000000000000000000000000000000"
    else if extendedPlatformDtb
    then "f87b1100ef770abd07efe3d5424fb7de1c9aee65ec09cddd740525f192d082f8"
    else "64a77eb34247b325b50abdf4562e49172e87c8c07cab13c4c80fbeeb95776c27";
  usbPlatformDtbSha256 =
    if extendedPlatformDtb
    then "b775cf001abf978c8e82a62e764d2bd53c744b90fd382ab7ee78b21d4a648610"
    else "c17e7606ac6cbae3f606cd5c4f2188c8e10304a8de9d60fcc62362c60b6aed50";
  profileCombinationValid =
    assert !gpuOwnerOverlay || (a72Overlay && !gpuFixedOppOverlay && !gpuStagedOverlay && !gpuDeferredBind);
    assert !a72Overlay || (cellularOverlay && unattendedRecovery && !gpuFixedOppOverlay);
    assert !(consysIdentityOverlay && (consysG2bOverlay || consysG2cPatchOverlay || consysG2dPostpatchOverlay));
    assert !(consysG2bOverlay && (consysG2cPatchOverlay || consysG2dPostpatchOverlay));
    assert !(consysG2cPatchOverlay && consysG2dPostpatchOverlay);
    assert !consysFirmware || consysG2bOverlay;
    assert !(gpuStagedOverlay && gpuFixedOppOverlay);
    assert !gpuDeferredBind || gpuFixedOppOverlay;
    assert !pdIgnoreUnused || gpuFixedOppOverlay;
    assert !microsdOverlay || (fgadcActivationOverlay && !deviceActivationOverlay);
    assert !((gpuStagedOverlay || gpuFixedOppOverlay) && (consysIdentityOverlay || consysG2bOverlay || consysG2cPatchOverlay || consysG2dPostpatchOverlay));
    assert !consysG2cPatchOverlay || unattendedRecovery;
    assert !consysG2dPostpatchOverlay || unattendedRecovery;
    assert
      !powerObservePreflight
      || (powerObserveOverlay && unattendedRecovery);
    assert
      (!displayOverlay && !audioOverlay)
      || (platformEnablement && displayOverlay && audioOverlay && !consysIdentityOverlay);
    assert
      !audioHeadphoneTest
      || (
        platformEnablement
        && displayOverlay
        && audioOverlay
        && sshAccess
        && !consysIdentityOverlay
      );
    assert
      !powerObserveOverlay
      || (platformEnablement && displayOverlay && audioOverlay && !consysIdentityOverlay);
    assert
      !inputObserveOverlay
      || (
        platformEnablement
        && displayOverlay
        && audioOverlay
        && powerObserveOverlay
        && powerObservePreflight
        && unattendedRecovery
        && !consysIdentityOverlay
      );
    assert
      !thermalHallObserveOverlay || inputObserveOverlay;
    assert
      !touchscreenActivationOverlay
      || (
        storageOverlay
        && sshAccess
        && usbHostOverlay
        && platformEnablement
        && displayOverlay
        && audioOverlay
        && powerObserveOverlay
        && powerObservePreflight
        && unattendedRecovery
        && inputObserveOverlay
        && thermalHallObserveOverlay
        && !consysIdentityOverlay
      );
    assert
      !fgadcActivationOverlay
      || (
        storageOverlay
        && sshAccess
        && usbHostOverlay
        && platformEnablement
        && displayOverlay
        && audioOverlay
        && powerObserveOverlay
        && powerObservePreflight
        && unattendedRecovery
        && inputObserveOverlay
        && thermalHallObserveOverlay
        && !consysIdentityOverlay
      );
    assert
      !(touchscreenActivationOverlay || fgadcActivationOverlay)
      || kernelRevision == p22BaselinePlatformRevision;
    assert
      !(touchscreenActivationOverlay || fgadcActivationOverlay)
      || !deviceActivationOverlay;
    assert
      !deviceActivationOverlay
      || (
        storageOverlay
        && sshAccess
        && usbHostOverlay
        && platformEnablement
        && displayOverlay
        && audioOverlay
        && powerObserveOverlay
        && powerObservePreflight
        && unattendedRecovery
        && inputObserveOverlay
        && thermalHallObserveOverlay
        && !consysIdentityOverlay
      );
    true;
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
      + lib.optionalString consysG2bOverlay "-consys-g2b"
      + lib.optionalString consysG2cPatchOverlay "-consys-g2c-patch"
      + lib.optionalString consysG2dPostpatchOverlay "-consys-g2d-postpatch"
      + lib.optionalString gpuStagedOverlay "-gpu-staged"
      + lib.optionalString gpuFixedOppOverlay "-gpu-fixed-opp"
    + lib.optionalString gpuDeferredBind "-deferred-bind"
    + lib.optionalString pdIgnoreUnused "-pd-ignore-unused"
    + lib.optionalString (!legacyConsysPlatform) "-reworked-consys"
    + lib.optionalString microsdOverlay "-microsd"
      + lib.optionalString platformEnablement "-platform"
      + lib.optionalString displayOverlay "-display"
      + lib.optionalString audioOverlay "-audio"
      + lib.optionalString powerObserveOverlay "-power-observe"
      + lib.optionalString powerObservePreflight "-power-preflight"
      + lib.optionalString unattendedRecovery "-unattended-recovery"
      + lib.optionalString inputObserveOverlay "-input-observe"
      + lib.optionalString thermalHallObserveOverlay "-thermal-hall-observe"
      + lib.optionalString touchscreenActivationOverlay "-touchscreen-active"
      + lib.optionalString fgadcActivationOverlay "-fgadc-active"
      + lib.optionalString deviceActivationOverlay "-device-activation";
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
        python3
        rsync
      ])
      ++ [gcc12Cross];
    depsBuildBuild = [buildPkgs.stdenv.cc];

    configurePhase = ''
      runHook preConfigure
      ${lib.optionalString a72Overlay ''
        python3 ${./a72-profile-build.py} inputs --fragments $fragmentInputs
      ''}
      export SOURCE_DATE_EPOCH=1783123200
      unset NIX_LDFLAGS
      ${lib.optionalString a72Overlay ''
        CC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-a72-hotplug-attribute.py
        CC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-cpuclk-observation.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-cpuclk-core-host.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-a72-power-core-host.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-sram-core-host.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-sram-boot-api.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-a72-vproc-votes.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-a72-online-commit.py
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-mt6797-cpuclk-boot-api.py
      ''}
      kernelMakeFlags=(
        ARCH=arm64
        CROSS_COMPILE=aarch64-unknown-linux-gnu-
      )
      make "''${kernelMakeFlags[@]}" defconfig
      scripts/kconfig/merge_config.sh \
        -m -O . .config $fragmentInputs
      ${lib.optionalString (consysIdentityOverlay || consysG2bOverlay || consysG2cPatchOverlay || consysG2dPostpatchOverlay || gpuStagedOverlay || gpuFixedOppOverlay || unattendedRecovery) ''
        bash scripts/config --set-str CMDLINE \
          "${kernelCmdline}"
      ''}
      make "''${kernelMakeFlags[@]}" olddefconfig
      ${lib.optionalString desktopScanout ''
        grep -Fqx 'CONFIG_CMA_SIZE_MBYTES=64' .config
        grep -Fqx 'CONFIG_CMA_SIZE_SEL_MBYTES=y' .config
      ''}
      ${lib.optionalString cellularOverlay ''
        for symbol in WWAN MTK_MT6797_CCCI MTK_MT6797_MD1_COLD_OWNER MTK_MT6797_MD1_FS_PROVIDER TMPFS; do
          grep -Fqx "CONFIG_$symbol=y" .config
        done
      ''}

      ${lib.optionalString a72Overlay ''
        for symbol in COMMON_CLK_MT6797_CPU REGULATOR_DA9213_LEGACY REGULATOR_MT6797_BIGIDVFS_SRAM MTK_MT6797_A72_POWER; do
          grep -Fqx "CONFIG_$symbol=y" .config
        done
        for symbol in CPU_FREQ ARM64_MT6797_A72_CAPABILITY_PROFILE ARM64_MT6797_A72_P32_ROLLBACK; do
          ! grep -Eq "^CONFIG_$symbol=(y|m)$" .config
        done
      ''}
      test -z "''${NIX_HARDENING_ENABLE:-}"
      grep -Fqx 'CONFIG_LOCALVERSION="-gemini-da921x-lkro"' .config
      grep -Fqx '# CONFIG_LOCALVERSION_AUTO is not set' .config
      grep -Fqx 'CONFIG_NVMEM_MTK_ATAG_DEVINFO=y' .config
      ${lib.optionalString legacyConsysPlatform ''
        # gemini-mainline-integration 60c0a7b48d314 ("regulator: da9213-legacy:
        # provide transactional buck ownership") deleted the read-only
        # REGULATOR_DA9213_LEGACY_PROVIDER/_OBSERVER symbols that the accepted
        # 28c47150 baseline asserted; the DA921x contract now lives in
        # REGULATOR_DA9213_LEGACY itself.  The board DT keeps the
        # dlg,da9214-legacy node status = "disabled", so this image never
        # probes it.  Assert the surviving symbol and that the deleted ones do
        # not silently return with different semantics.
        grep -Fqx 'CONFIG_REGULATOR_DA9213_LEGACY=y' .config
        ! grep -q '^CONFIG_REGULATOR_DA9213_LEGACY_PROVIDER=' .config
        ! grep -q '^CONFIG_REGULATOR_DA9213_LEGACY_OBSERVER=' .config
      ''}${lib.optionalString (!legacyConsysPlatform) ''
        grep -Fqx 'CONFIG_REGULATOR_DA9211=y' .config
      ''}
      grep -Fqx 'CONFIG_MTK_STP=y' .config
      ! grep -q '^CONFIG_MTK_STP_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_WMT=y' .config
      ! grep -q '^CONFIG_MTK_WMT_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_WMT_INITIAL=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_WMT_INITIAL_KUNIT_TEST=' .config
      ${lib.optionalString (legacyConsysPlatform && !connectivityModules) ''
        # 28c47150 built MTK_MT6797_CONSYS_INVENTORY as a resource-only
        # inventory driver.  gemini-mainline-integration 6948ed143475a ("soc:
        # mediatek: tighten MT6797 CONSYS resource ownership") and
        # b0bfeff274adc ("soc: mediatek: activate the MT6797 CONSYS aggregate")
        # repurposed the same symbol into the CONSYS lifecycle owner: it now
        # depends on MTK_MT6797_CONSYS_FW_HANDOFF and selects POSTID, EMI_MPU
        # and WMT_PATCH_DOWNLOAD.  The baseline never enables FW_HANDOFF, so
        # Kconfig drops the fragment's =y; assert that explicitly instead of
        # letting the lifecycle owner into a no-radio image.
        # Kconfig omits a symbol whose dependency is unmet, so accept absent or
        # "is not set", never =y/=m.
        ! grep -q '^CONFIG_MTK_MT6797_CONSYS_INVENTORY=' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_FW_HANDOFF is not set' .config
      ''}
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_CORE=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_CORE_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_STP_SESSION=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_STP_SESSION_KUNIT_TEST=' .config
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
      ${lib.optionalString consysG2bOverlay ''
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_POSTID=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_EMI_MPU=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_FIRMWARE_PREFLIGHT=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_WMT_PATCH_DOWNLOAD=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME_CONTROLLER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2B_OWNER=y' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_AFE_GPS_REGISTER_SETTING is not set' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_LIVE is not set' .config
      ''}
      ${lib.optionalString consysG2cPatchOverlay ''
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_POSTID=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_EMI_MPU=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_FIRMWARE_PREFLIGHT=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_WMT_PATCH_DOWNLOAD=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME_CONTROLLER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2C_PATCH_OWNER=y' .config
        ! grep -q '^CONFIG_MTK_MT6797_CONSYS_G2B_OWNER=' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_AFE_GPS_REGISTER_SETTING is not set' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_LIVE is not set' .config
      ''}
      ${lib.optionalString consysG2dPostpatchOverlay ''
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_POSTID=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_EMI_MPU=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_FIRMWARE_PREFLIGHT=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_WMT_PATCH_DOWNLOAD=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_RUNTIME_CONTROLLER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2C_PATCH_OWNER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2D_POSTPATCH_OWNER=y' .config
        ! grep -q '^CONFIG_MTK_MT6797_CONSYS_G2B_OWNER=' .config
        ! grep -q '^CONFIG_MTK_MT6797_BTIF_TRANSPORT=' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_AFE_GPS_REGISTER_SETTING is not set' .config
        grep -Fqx '# CONFIG_MTK_MT6797_CONSYS_LIVE is not set' .config
      ''}
      ${lib.optionalString gpuStagedOverlay ''
        grep -Fqx 'CONFIG_REGULATOR_RT5735=y' .config
        grep -Fqx 'CONFIG_MTK_SCPSYS=y' .config
        grep -Fqx 'CONFIG_COMMON_CLK_MT6797_MFGSYS=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_GPU_STAGED_DIAGNOSTIC=y' .config
        ! grep -q '^CONFIG_DRM_PANFROST=' .config
      ''}
      ${lib.optionalString gpuFixedOppOverlay ''
        grep -Fqx 'CONFIG_REGULATOR_RT5735=y' .config
        grep -Fqx 'CONFIG_MTK_SCPSYS=y' .config
        grep -Fqx 'CONFIG_COMMON_CLK_MT6797_MFGSYS=y' .config
        grep -Fqx 'CONFIG_DRM=y' .config
        grep -Fqx 'CONFIG_DRM_PANFROST=y' .config
        grep -Fqx 'CONFIG_PM_DEVFREQ=y' .config
        grep -Fqx 'CONFIG_DEVFREQ_GOV_SIMPLE_ONDEMAND=y' .config
        ! grep -q '^CONFIG_MTK_MT6797_GPU_STAGED_DIAGNOSTIC=' .config
      ''}
      ${lib.optionalString legacyConsysPlatform ''
        grep -Fqx 'CONFIG_MTK_MT6797_BTIF_INVENTORY=y' .config
      ''}
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_PIO=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_BTIF_PIO_KUNIT_TEST=' .config
      # gemini-mainline-integration bbf50831f52fd ("soc: mediatek: attach
      # MT6797 BTIF transport component") made MTK_MT6797_BTIF_PIO_PLATFORM
      # depend on the repurposed MTK_MT6797_CONSYS_INVENTORY owner above, so
      # it is unavailable to the no-radio baseline.  28c47150 built it as a
      # dormant adapter matched by no Gemini DT node.
      ${lib.optionalString (!connectivityModules) ''
        ! grep -q '^CONFIG_MTK_MT6797_BTIF_PIO_PLATFORM=' .config
      ''}
      ! grep -q '^CONFIG_MTK_MT6797_BTIF_PIO_PLATFORM_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_STP_BOOTSTRAP=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_BTIF_STP_BOOTSTRAP_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_GNSS=y' .config
      ${lib.optionalString legacyConsysPlatform ''
        grep -Fqx 'CONFIG_GNSS_MTK_CONSYS=y' .config
      ''}
      ! grep -q '^CONFIG_GNSS_MTK_CONSYS_KUNIT_TEST=' .config
      ${lib.optionalString platformEnablement ''
        grep -Fqx 'CONFIG_DRM=y' .config
        grep -Fqx 'CONFIG_DRM_MEDIATEK=y' .config
        grep -Fqx 'CONFIG_DRM_PANEL_NOVATEK_NT36672E=y' .config
        grep -Fqx 'CONFIG_COMMON_CLK_MT6797_MMSYS=y' .config
        grep -Fqx 'CONFIG_MTK_SCPSYS=y' .config
        grep -Fqx 'CONFIG_MTK_SMI=y' .config
        grep -Fqx '# CONFIG_MTK_IOMMU is not set' .config
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
      ${lib.optionalString powerObserveOverlay ''
        grep -Fqx 'CONFIG_POWER_SUPPLY=y' .config
        grep -Fqx 'CONFIG_CHARGER_BQ25890=y' .config
      ''}
      ${lib.optionalString inputObserveOverlay ''
        grep -Fqx 'CONFIG_INPUT=y' .config
        grep -Fqx 'CONFIG_INPUT_EVDEV=y' .config
        grep -Fqx 'CONFIG_INPUT_KEYBOARD=y' .config
        grep -Fqx 'CONFIG_KEYBOARD_MATRIX=y' .config
        grep -Fqx 'CONFIG_PINCTRL_AW9523=y' .config
        grep -Fqx 'CONFIG_I2C=y' .config
        grep -Fqx 'CONFIG_I2C_MT65XX=y' .config
        grep -Fqx 'CONFIG_THERMAL=y' .config
        grep -Fqx 'CONFIG_THERMAL_OF=y' .config
      ''}
      ${lib.optionalString thermalHallObserveOverlay ''
        grep -Fqx 'CONFIG_MTK_THERMAL=y' .config
        grep -Fqx 'CONFIG_MTK_SOC_THERMAL=y' .config
        grep -Fqx 'CONFIG_IIO=y' .config
        grep -Fqx 'CONFIG_MEDIATEK_MT6577_AUXADC=y' .config
        grep -Fqx 'CONFIG_KEYBOARD_GPIO=y' .config
      ''}
      ${lib.optionalString touchscreenActivationOverlay ''
        grep -Fqx 'CONFIG_INPUT=y' .config
        grep -Fqx 'CONFIG_INPUT_EVDEV=y' .config
        grep -Fqx 'CONFIG_INPUT_TOUCHSCREEN=y' .config
        grep -Fqx 'CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX=y' .config
        ! grep -q '^CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX_KUNIT_TEST=' .config
      ''}
      ${lib.optionalString fgadcActivationOverlay ''
        grep -Fqx 'CONFIG_POWER_SUPPLY=y' .config
        grep -Fqx 'CONFIG_BATTERY_MT6351_FGADC=y' .config
        ! grep -q '^CONFIG_BATTERY_MT6351_FGADC_KUNIT_TEST=' .config
      ''}
      ${lib.optionalString legacyConsysPlatform ''
        # The legacy platform keeps CONSYS off in the board DT and releases it
        # only through an overlay.  The reworked-CONSYS lineage enables it in
        # the board DT instead, so this assertion describes the old platform,
        # not a requirement of the image.  Leaving it unconditional made that
        # lineage fail its build silently: grep -Fq prints nothing and set -e
        # aborts configurePhase, so the builder exited 1 with no diagnostic and
        # make never ran.
        #
        # gemini-mainline-integration 969a7aa097a50 ("arm64: dts: mediatek:
        # complete Gemini CONSYS resources") and d8ea00f5395dc added rail,
        # emi-mpu, infracfg, spm and btif phandles to the node, pushing its
        # own status line to 28 lines below the opening brace; the node is
        # still status = "disabled" (and the composed DTB is checked with
        # fdtget below), so only the window widens.
        grep -A32 -F 'consys: consys@18070000 {' \
          arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts \
          | grep -Fq 'status = "disabled";'
      ''}
      # 28c47150 described BTIF as a disabled 8250 UART
      # ("mediatek,mt6797-btif", "mediatek,mtk-btif").  gemini-mainline-
      # integration d8ea00f5395dc ("arm64: dts: mediatek: describe MT6797 BTIF
      # PIO supplier") renamed it to "mediatek,mt6797-btif-pio", matched only
      # by mt6797-btif-pio-platform.c (MTK_MT6797_BTIF_PIO_PLATFORM, asserted
      # absent above).  The node stays disabled.
      grep -A12 -F 'btif: serial@1100c000 {' \
        arch/arm64/boot/dts/mediatek/mt6797.dtsi \
        | grep -Fq 'compatible = "mediatek,mt6797-btif-pio";'
      grep -A12 -F 'btif: serial@1100c000 {' \
        arch/arm64/boot/dts/mediatek/mt6797.dtsi \
        | grep -Fq 'status = "disabled";'
      ${lib.optionalString unattendedRecovery ''
        grep -Fqx 'CONFIG_WATCHDOG=y' .config
        grep -Fqx 'CONFIG_WATCHDOG_CORE=y' .config
        grep -Fqx 'CONFIG_WATCHDOG_NOWAYOUT=y' .config
        grep -Fqx 'CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED=y' .config
        grep -Fqx 'CONFIG_WATCHDOG_OPEN_TIMEOUT=90' .config
        grep -Fqx 'CONFIG_WATCHDOG_SYSFS=y' .config
        grep -Fqx 'CONFIG_MEDIATEK_WATCHDOG=y' .config
        grep -Fqx 'CONFIG_PANIC_ON_OOPS=y' .config
        grep -Fqx 'CONFIG_PANIC_TIMEOUT=5' .config
      ''}
      ${lib.optionalString (!a72Overlay) ''
        grep -Fqx '# CONFIG_MTK_MT6797_A72_POWER is not set' .config
      ''}
      ${lib.optionalString legacyConsysPlatform ''
        grep -Fqx '# CONFIG_MTK_MT6797_DVFSP_RESOURCE_OWNER is not set' .config
      ''}
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
          ${lib.optionalString legacyConsysPlatform ''
            grep -Fqx '# CONFIG_PSTORE_GEMINI_ARM64_ENTRY_LEDGER is not set' .config
            grep -Fqx 'CONFIG_PSTORE_GEMINI_POST_RAMOOPS_CHECKPOINT=y' .config
          ''}
          grep -Fqx 'CONFIG_CMDLINE="${kernelCmdline}"' .config
        ''
        else ''
          grep -Fqx 'CONFIG_PSTORE_GEMINI_ARM64_ENTRY_LEDGER=y' .config
          grep -Fqx '# CONFIG_PSTORE_GEMINI_POST_RAMOOPS_CHECKPOINT is not set' .config
          grep -Fqx 'CONFIG_CMDLINE="${kernelCmdline}"' .config
        ''
      }
      ${lib.optionalString a72Overlay ''
        python3 ${./a72-profile-build.py} bind --config .config
      ''}
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
      ${lib.optionalString connectivityModules ''
        for symbol in MTK_MT6797_CONSYS_INVENTORY MTK_MT6797_BTIF_PIO_PLATFORM MTK_MT6797_WIFI; do
          grep -Fqx "CONFIG_$symbol=m" .config || { echo "Expected module CONFIG_$symbol=m"; grep -E "^(CONFIG_$symbol=|# CONFIG_$symbol )" .config || true; exit 1; }
        done
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_EMI_MPU=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_FW_HANDOFF=y' .config
        grep -Fqx 'CONFIG_CFG80211=m' .config
        grep -Fqx 'CONFIG_MTK_MT6797_WIFI_RADIO=y' .config
        for symbol in NET_SCHED NET_SCH_FQ_CODEL NET_SCH_DEFAULT DEFAULT_FQ_CODEL; do
          grep -Fqx "CONFIG_$symbol=y" .config
        done
        grep -Fqx 'CONFIG_DEFAULT_NET_SCH="fq_codel"' .config
        CC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-wifi-radio-admission-host.py
        CC=${buildPkgs.stdenv.cc}/bin/cc python3 tools/gemini/test-wifi-radio-tx-host.py
      ''}
      ${lib.optionalString gpuOwnerOverlay ''
        export HOSTCC=${buildPkgs.stdenv.cc}/bin/cc
        python3 tools/gemini/test-regulator-exclusive-state.py
        for suite in acquire integration provider registration pm; do
          python3 drivers/pmdomain/mediatek/test-gpuldo-$suite.py
        done
        "$HOSTCC" -std=c11 -Wall -Wextra -Werror drivers/pmdomain/mediatek/test-gpuldo-owner.c -o gpuldo-owner-test
        ./gpuldo-owner-test
        grep -Fqx 'CONFIG_REGULATOR_RT5735=y' .config
        grep -Fqx 'CONFIG_DRM_PANFROST=m' .config
      ''}
      python3 tools/gemini/test-media-clock-bounds.py
      python3 tools/gemini/test-drm-synchronous-bind.py
      make -j"$NIX_BUILD_CORES" "''${kernelMakeFlags[@]}" \
        Image Image.gz dtbs ${lib.optionalString gpuOwnerOverlay "modules"}
      test "$(make "''${kernelMakeFlags[@]}" -s kernelrelease)" = \
        "7.1.3-gemini-da921x-lkro"
      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      ${lib.optionalString a72Overlay ''
        cp a72-build-provenance.json "$out/"
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-a72-resource-preflight.dtbo "$out/a72-resource.dtbo"
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-a72-cpu-on-gate.dtbo "$out/a72-cpu8.dtbo"
      ''}
      ${lib.optionalString gpuOwnerOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-gpu-preflight.dtbo "$out/"
        make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- INSTALL_MOD_PATH="$out" DEPMOD=true modules_install
        # Out-of-tree build links are not runtime module dependencies.
        rm -f "$out/lib/modules/7.1.3-gemini-da921x-lkro/build" "$out/lib/modules/7.1.3-gemini-da921x-lkro/source"
        ${buildPkgs.kmod}/bin/depmod -b "$out" 7.1.3-gemini-da921x-lkro
      ''}
      ${lib.optionalString connectivityModules ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-wifi.dtbo "$out/"
      ''}
      cp arch/arm64/boot/Image "$out/Image"
      cp arch/arm64/boot/Image.gz "$out/Image.gz"
      ${lib.optionalString cellularOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-cellular.dtbo "$out/"
      ''}
      cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dtb "$out/base.dtb"
      ${lib.optionalString consysIdentityOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-consys-identity.dtbo \
          "$out/mt6797-gemini-consys-identity.dtbo"
      ''}
      ${lib.optionalString consysG2bOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-consys-g2b-no-firmware.dtbo \
          "$out/mt6797-gemini-consys-g2b-no-firmware.dtbo"
        test -s "$out/mt6797-gemini-consys-g2b-no-firmware.dtbo"
      ''}
      ${lib.optionalString consysG2cPatchOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-consys-g2c-patch-only.dtbo \
          "$out/mt6797-gemini-consys-g2c-patch-only.dtbo"
        test -s "$out/mt6797-gemini-consys-g2c-patch-only.dtbo"
      ''}
      ${lib.optionalString consysG2dPostpatchOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-consys-g2c-patch-only.dtbo \
          "$out/mt6797-gemini-consys-g2c-patch-only.dtbo"
        test -s "$out/mt6797-gemini-consys-g2c-patch-only.dtbo"
      ''}
      ${lib.optionalString gpuStagedOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-gpu-staged.dtbo \
          "$out/mt6797-gemini-pda-gpu-staged.dtbo"
        test -s "$out/mt6797-gemini-pda-gpu-staged.dtbo"
      ''}
      ${lib.optionalString gpuFixedOppOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-gpu-fixed-opp.dtbo \
          "$out/mt6797-gemini-pda-gpu-fixed-opp.dtbo"
        test -s "$out/mt6797-gemini-pda-gpu-fixed-opp.dtbo"
      ''}
      ${lib.optionalString microsdOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-microsd-bringup.dtbo \
          "$out/mt6797-gemini-pda-microsd-bringup.dtbo"
        test -s "$out/mt6797-gemini-pda-microsd-bringup.dtbo"
      ''}
      ${lib.optionalString usbHostOverlay ''
        # This overlay is built and reviewed with the locked kernel source.
        # Do not replace it with a repository-local DTS: the retired version
        # asserted GPIO72 at probe time and used the wrong regulator sequence.
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtbo \
          "$out/mt6797-gemini-pda-usb11-host.dtbo"
        test "$(sha256sum "$out/mt6797-gemini-pda-usb11-host.dtbo" | cut -d' ' -f1)" = \
          a341e238e2479c6ac3f633c4262f170c6b53dbeec7867b2956fd80f656ff3469
      ''}
      ${lib.optionalString displayOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-display.dtbo \
          "$out/mt6797-gemini-pda-display.dtbo"
      ''}
      ${lib.optionalString audioOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-audio.dtbo \
          "$out/mt6797-gemini-pda-audio.dtbo"
      ''}
      ${lib.optionalString powerObserveOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-power-observe.dtbo \
          "$out/mt6797-gemini-pda-power-observe.dtbo"
      ''}
      ${lib.optionalString inputObserveOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-keyboard.dtbo \
          "$out/mt6797-gemini-pda-keyboard.dtbo"
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-touchscreen-observe.dtbo \
          "$out/mt6797-gemini-pda-touchscreen-observe.dtbo"
        test -s "$out/mt6797-gemini-pda-keyboard.dtbo"
        test -s "$out/mt6797-gemini-pda-touchscreen-observe.dtbo"
      ''}
      ${lib.optionalString thermalHallObserveOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-thermal-hall-observe.dtbo \
          "$out/mt6797-gemini-pda-thermal-hall-observe.dtbo"
        # gemini-mainline-integration aff9464721c12 ("arm64: dts: keep
        # standalone ADC closed in Gemini thermal overlays") flips the
        # overlay's &auxadc from okay to disabled: the thermal driver maps
        # AUXADC itself, so the standalone IIO device no longer binds.  The
        # composed DT is checked below; only this fingerprint moves.
        test "$(sha256sum "$out/mt6797-gemini-pda-thermal-hall-observe.dtbo" | cut -d' ' -f1)" = \
          f85fe5360c40159968d05945b586d223ebed0bf0686ba5aaa1a9d7234a635abd
      ''}
      ${lib.optionalString deviceActivationOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-touchscreen-activation.dtbo \
          "$out/mt6797-gemini-pda-touchscreen-activation.dtbo"
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-fuel-gauge-active.dtbo \
          "$out/mt6797-gemini-pda-fuel-gauge-active.dtbo"
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-microsd-bringup.dtbo \
          "$out/mt6797-gemini-pda-microsd-bringup.dtbo"
        test -s "$out/mt6797-gemini-pda-touchscreen-activation.dtbo"
        test -s "$out/mt6797-gemini-pda-fuel-gauge-active.dtbo"
        test -s "$out/mt6797-gemini-pda-microsd-bringup.dtbo"
      ''}
      ${lib.optionalString touchscreenActivationOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-touchscreen-activation.dtbo \
          "$out/mt6797-gemini-pda-touchscreen-activation.dtbo"
        test -s "$out/mt6797-gemini-pda-touchscreen-activation.dtbo"
      ''}
      ${lib.optionalString fgadcActivationOverlay ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-fuel-gauge-active.dtbo \
          "$out/mt6797-gemini-pda-fuel-gauge-active.dtbo"
        test -s "$out/mt6797-gemini-pda-fuel-gauge-active.dtbo"
      ''}
      cp .config "$out/kernel.config"
      cp System.map vmlinux "$out/"

      # Device Tree output is compiler-independent and must match the reviewed
      # Reviewed tree: ixoo's hardware-passed DT plus dormant CONSYS and BTIF.
      actual_base_dtb_sha256=$(sha256sum "$out/base.dtb" | cut -d' ' -f1)
      if [ "$actual_base_dtb_sha256" != ${baseDtbSha256} ]; then
        echo "base DT hash mismatch: expected=${baseDtbSha256} actual=$actual_base_dtb_sha256" >&2
        exit 1
      fi
      # The full p22 candidate depends on the DSI pre-host-registration IRQ
      # ordering.  Keep this source-level guard adjacent to the locked kernel
      # revision so a future platform refresh cannot silently reintroduce the
      # synchronous panel-probe race.
      ${lib.optionalString displayOverlay ''
        dsi_irq_line=$(grep -n -F 'ret = devm_request_irq(&pdev->dev, irq_num, mtk_dsi_irq,' \
          drivers/gpu/drm/mediatek/mtk_dsi.c | cut -d: -f1)
        dsi_host_line=$(grep -n -F 'ret = mipi_dsi_host_register(&dsi->host);' \
          drivers/gpu/drm/mediatek/mtk_dsi.c | cut -d: -f1)
        test -n "$dsi_irq_line"
        test -n "$dsi_host_line"
        test "$dsi_irq_line" -lt "$dsi_host_line"
        grep -Fq 'The panel may issue DSI transfers before' \
          drivers/gpu/drm/mediatek/mtk_dsi.c
      ''}

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
  serviceabilityDtb = assert profileCombinationValid;
    buildPkgs.runCommand "gemini-ixoo-serviceability-dtb${lib.optionalString usbHostOverlay "-usb11-host"}${lib.optionalString consysIdentityOverlay "-consys-identity"}${lib.optionalString consysG2bOverlay "-consys-g2b"}${lib.optionalString consysG2cPatchOverlay "-consys-g2c-patch"}${lib.optionalString consysG2dPostpatchOverlay "-consys-g2d-postpatch"}${lib.optionalString gpuStagedOverlay "-gpu-staged"}${lib.optionalString gpuFixedOppOverlay "-gpu-fixed-opp"}${lib.optionalString platformEnablement "-platform"}${lib.optionalString displayOverlay "-display"}${lib.optionalString audioOverlay "-audio"}${lib.optionalString powerObserveOverlay "-power-observe"}${lib.optionalString powerObservePreflight "-power-preflight"}${lib.optionalString unattendedRecovery "-unattended-recovery"}${lib.optionalString inputObserveOverlay "-input-observe"}${lib.optionalString thermalHallObserveOverlay "-thermal-hall-observe"}${lib.optionalString touchscreenActivationOverlay "-touchscreen-active"}${lib.optionalString fgadcActivationOverlay "-fgadc-active"}${lib.optionalString deviceActivationOverlay "-device-activation"}" {
      nativeBuildInputs = [buildPkgs.bash buildPkgs.dtc buildPkgs.python3];
    } ''
      mkdir -p "$out"
      ${
        if !legacyConsysPlatform
        then ''
          # The legacy DA921x provider-DTB step rewrites /dvfsp-handoff@11015000,
          # which the reworked lineage does not have -- it dropped every DVFSP_*
          # symbol and the node with them, and carries DA9214 inside the upstream
          # da9211 driver instead.  Running it there dies with
          #   Error at '/dvfsp-handoff@11015000': FDT_ERR_NOTFOUND
          # so take the kernel's base DT unmodified and record that choice.
          cp ${kernel}/base.dtb "$out/gemini-base.dtb"
          chmod 0644 "$out/gemini-base.dtb"
          echo 'provider-dtb=skipped-no-dvfsp-handoff-on-reworked-consys' > "$out/VALIDATION"
        ''
        else ''
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
      substituteInPlace "$providerBuilder" \
        --replace-fail \
          $'\tfdtput -d "$temporary" "$AW9523" "$property"' \
          $'\tif fdtget "$temporary" "$AW9523" "$property" >/dev/null 2>&1; then\n\t\tfdtput -d "$temporary" "$AW9523" "$property"\n\tfi'
      # ixoo's builder validated a childless, implicitly enabled DA921x node
      # that its read-only provider bound.  gemini-mainline-integration
      # 60c0a7b48d314 turned that driver into a transactional buck owner and
      # its board DTS at 74726a17 describes BUCKA/BUCKB
      # children under a status = "disabled" node, so nothing binds it.  Keep
      # the child check for an enabled node, tolerate children only while the
      # node is disabled, and assert that state explicitly afterwards.
      substituteInPlace "$providerBuilder" \
        --replace-fail \
          $'\t[[ -z "$(fdtget -l "$dtb" "$DA921X")" ]] ||' \
          $'\t[[ -z "$(fdtget -l "$dtb" "$DA921X")" || "$(fdtget -ts "$dtb" "$DA921X" status)" == disabled ]] ||'
      bash "$providerBuilder" \
        --base-dtb ${kernel}/base.dtb \
        --output "$out/gemini-base.dtb" \
        > "$out/VALIDATION"
      chmod 0644 "$out/gemini-base.dtb"
      test "$(sha256sum "$out/gemini-base.dtb" | cut -d' ' -f1)" = \
        ${serviceabilityBaseDtbSha256}
      test "$(fdtget "$out/gemini-base.dtb" /consys@18070000 status)" = disabled
      test "$(fdtget "$out/gemini-base.dtb" /i2c@1100e000/regulator@68 status)" = disabled
      echo 'da921x-node=disabled-transactional-driver-unbound' >> "$out/VALIDATION"
        ''
      }
      ${
        if usbHostOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-base.dtb" \
            -o "$out/gemini-platform.dtb" \
            ${kernel}/mt6797-gemini-pda-usb11-host.dtbo
          test "$(fdtget "$out/gemini-platform.dtb" /t-phy@11210000 status)" = okay
          test "$(fdtget -t x "$out/gemini-platform.dtb" /t-phy@11210000 reg)" = \
            '0 11210000 0 800'
          test "$(fdtget "$out/gemini-platform.dtb" /t-phy@11210000/usb-phy@11210800 status)" = okay
          fdtget -p "$out/gemini-platform.dtb" /t-phy@11210000/usb-phy@11210800 \
            | grep -Fqx 'mediatek,force-a-session-valid'
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11200000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11200000 dr_mode)" = host
          test "$(fdtget "$out/gemini-platform.dtb" /i2c@11007000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /i2c@11007000/typec@25 compatible)" = onsemi,fusb301a
          test "$(fdtget -t x "$out/gemini-platform.dtb" /i2c@11007000/typec@25 reg)" = 25
          test "$(fdtget "$out/gemini-platform.dtb" /i2c@11007000/typec@25/connector power-role)" = source
          fdtget -p "$out/gemini-platform.dtb" /i2c@11007000/typec@25 \
            | grep -Fqx 'vbus-supply'
          test "$(fdtget "$out/gemini-platform.dtb" /regulator-usb11-drvvbus regulator-name)" = usb11-drvvbus
          test "$(fdtget "$out/gemini-platform.dtb" /regulator-usb11-vbus regulator-name)" = usb11-vbus
          fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-drvvbus \
            | grep -Fqx 'gpio'
          fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-vbus \
            | grep -Fqx 'gpio'
          fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-vbus \
            | grep -Fqx 'vin-supply'
          ! fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-drvvbus \
            | grep -Fqx 'regulator-always-on'
          ! fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-vbus \
            | grep -Fqx 'regulator-always-on'
          ! fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-drvvbus \
            | grep -Fqx 'regulator-boot-on'
          ! fdtget -p "$out/gemini-platform.dtb" /regulator-usb11-vbus \
            | grep -Fqx 'regulator-boot-on'
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11271000 status)" = okay
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11271000 dr_mode)" = peripheral
          test "$(fdtget "$out/gemini-platform.dtb" /usb@11271000/usb@11270000 status)" = disabled
          test "$(fdtget "$out/gemini-platform.dtb" /consys@18070000 status)" = disabled
          echo 'usb11-host-overlay=passed' >> "$out/VALIDATION"
          echo 'usb11-overlay-source=locked-kernel-dtbo' >> "$out/VALIDATION"
          echo 'usb11-session=kernel-musb-host-with-fusb301a-cc-gating' >> "$out/VALIDATION"
          echo 'usb11-typec=i2c0-fusb301a-source-eint3' >> "$out/VALIDATION"
          echo 'usb11-vbus=gpio94-parent-gpio72-child-cc-attach-controlled' >> "$out/VALIDATION"
          echo 'usb11-route=gpio70-high-gpio71-low-regulators-default-off' >> "$out/VALIDATION"
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
        else if consysG2bOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-platform.dtb" \
            -o "$out/gemini-consys.dtb" \
            ${kernel}/mt6797-gemini-consys-g2b-no-firmware.dtbo
          test "$(fdtget "$out/gemini-consys.dtb" /consys@18070000 compatible)" = \
            mediatek,mt6797-consys-runtime
          test "$(fdtget "$out/gemini-consys.dtb" /consys@18070000 status)" = okay
          test "$(fdtget "$out/gemini-consys.dtb" /serial@1100c000 compatible)" = \
            mediatek,mt6797-btif-pio
          test "$(fdtget "$out/gemini-consys.dtb" /serial@1100c000 status)" = okay
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2b-controller compatible)" = \
            mediatek,mt6797-consys-runtime-controller
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2b-owner compatible)" = \
            mediatek,mt6797-consys-g2b-owner
          fdtget -p "$out/gemini-consys.dtb" /consys-g2b-controller \
            | grep -Fqx 'mediatek,experimental-bootstrap-no-patch'
          fdtget -p "$out/gemini-consys.dtb" /consys-g2b-owner \
            | grep -Fqx 'mediatek,experimental-g2b-no-firmware'
          echo 'consys-g2b-overlay=passed' >> "$out/VALIDATION"
          echo 'consys-g2b-firmware=disabled' >> "$out/VALIDATION"
          echo 'consys-g2b-radio-clients=disabled' >> "$out/VALIDATION"
        ''
        else if consysG2cPatchOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-platform.dtb" \
            -o "$out/gemini-consys.dtb" \
            ${kernel}/mt6797-gemini-consys-g2c-patch-only.dtbo
          test "$(fdtget "$out/gemini-consys.dtb" /consys@18070000 compatible)" = \
            mediatek,mt6797-consys-runtime
          test "$(fdtget "$out/gemini-consys.dtb" /serial@1100c000 compatible)" = \
            mediatek,mt6797-btif-pio
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2c-controller compatible)" = \
            mediatek,mt6797-consys-runtime-controller
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2c-patch-owner compatible)" = \
            mediatek,mt6797-consys-g2c-patch-owner
          fdtget -p "$out/gemini-consys.dtb" /consys-g2c-controller \
            | grep -Fqx 'mediatek,experimental-bootstrap'
          ! fdtget -p "$out/gemini-consys.dtb" /consys-g2c-controller \
            | grep -Fqx 'mediatek,experimental-bootstrap-no-patch'
          fdtget -p "$out/gemini-consys.dtb" /consys-g2c-patch-owner \
            | grep -Fqx 'mediatek,experimental-g2c-patch-owner'
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner status)" = disabled
          echo 'consys-g2c-overlay=passed' >> "$out/VALIDATION"
          echo 'consys-g2c-manifest=hash-pinned-after-full-stp-only' >> "$out/VALIDATION"
          echo 'consys-g2c-radio-clients=disabled' >> "$out/VALIDATION"
        ''
        else if consysG2dPostpatchOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-platform.dtb" \
            -o "$out/gemini-consys.dtb" \
            ${kernel}/mt6797-gemini-consys-g2c-patch-only.dtbo
          # The shared overlay declares both owners.  This profile has exactly
          # one live owner: G2c remains disabled and receives no boot gate.
          fdtput -t s "$out/gemini-consys.dtb" /consys-g2c-patch-owner status disabled
          fdtput -t s "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner status okay
          test "$(fdtget "$out/gemini-consys.dtb" /consys@18070000 compatible)" = \
            mediatek,mt6797-consys-runtime
          test "$(fdtget "$out/gemini-consys.dtb" /serial@1100c000 compatible)" = \
            mediatek,mt6797-btif-pio
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2c-controller compatible)" = \
            mediatek,mt6797-consys-runtime-controller
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2c-patch-owner status)" = disabled
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner compatible)" = \
            mediatek,mt6797-consys-g2d-postpatch-owner
          test "$(fdtget "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner status)" = okay
          fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
            | grep -Fqx 'mediatek,experimental-g2d-postpatch-owner'
          # PIO has no child endpoint and neither owner declares a function
          # client. The kernel config also excludes BTIF transport/HCI.
          test -z "$(fdtget -l "$out/gemini-consys.dtb" /serial@1100c000)"
          ! fdtget "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
            mediatek,function-control >/dev/null 2>&1
          echo 'consys-g2d-overlay=passed' >> "$out/VALIDATION"
          echo 'consys-g2d-owner=exclusive-g2c-disabled' >> "$out/VALIDATION"
          echo 'consys-g2d-radio-clients=disabled' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-platform.dtb" "$out/gemini-consys.dtb"
        ''
      }
      ${
        if gpuStagedOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-consys.dtb" \
            -o "$out/gemini-gpu.dtb" \
            ${kernel}/mt6797-gemini-pda-gpu-staged.dtbo
          test "$(fdtget "$out/gemini-gpu.dtb" /i2c@11010000 status)" = okay
          test "$(fdtget "$out/gemini-gpu.dtb" /i2c@11010000/regulator@1c status)" = okay
          test "$(fdtget "$out/gemini-gpu.dtb" /i2c@11010000/regulator@1c compatible)" = \
            richtek,rt5735
          test "$(fdtget "$out/gemini-gpu.dtb" /syscon@13000000 status)" = okay
          test "$(fdtget "$out/gemini-gpu.dtb" /gpu@13040000 status)" = disabled
          test "$(fdtget "$out/gemini-gpu.dtb" /gpu-staged status)" = okay
          test "$(fdtget "$out/gemini-gpu.dtb" /gpu-staged compatible)" = \
            mediatek,mt6797-gpu-staged
          fdtget -p "$out/gemini-gpu.dtb" /gpu-staged | grep -Fqx 'vgpu-supply'
          fdtget -p "$out/gemini-gpu.dtb" /gpu-staged | grep -Fqx 'power-domains'
          echo 'gpu-staged-overlay=rt5735-mfg-bg3d-readonly-id-passed' >> "$out/VALIDATION"
          echo 'gpu-target=disabled-no-panfrost-bind' >> "$out/VALIDATION"
        ''
        else if gpuFixedOppOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-consys.dtb" \
            -o "$out/gemini-gpu.dtb" \
            ${kernel}/mt6797-gemini-pda-gpu-fixed-opp.dtbo
          test "$(fdtget "$out/gemini-gpu.dtb" /i2c@11010000 status)" = okay
          test "$(fdtget "$out/gemini-gpu.dtb" /i2c@11010000/regulator@1c status)" = okay
          test "$(fdtget -t u "$out/gemini-gpu.dtb" /i2c@11010000/regulator@1c regulator-min-microvolt)" = 975000
          test "$(fdtget -t u "$out/gemini-gpu.dtb" /i2c@11010000/regulator@1c regulator-max-microvolt)" = 975000
          fdtget -p "$out/gemini-gpu.dtb" /i2c@11010000/regulator@1c \
            | grep -Fqx 'regulator-boot-on'
          test "$(fdtget "$out/gemini-gpu.dtb" /syscon@13000000 status)" = okay
          test "$(fdtget "$out/gemini-gpu.dtb" /gpu@13040000 status)" = okay
          fdtget -p "$out/gemini-gpu.dtb" /gpu@13040000 \
            | grep -Fqx 'operating-points-v2'
          test "$(fdtget -t x "$out/gemini-gpu.dtb" /gpu-opp-table/opp-500500000 opp-hz)" = \
            '0 1dd50620'
          test "$(fdtget -t u "$out/gemini-gpu.dtb" /gpu-opp-table/opp-500500000 opp-microvolt)" = 975000
          echo 'gpu-fixed-opp=panfrost-500500000hz-975000uv-passed' >> "$out/VALIDATION"
          echo 'gpu-dvfs=disabled-single-opp' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-consys.dtb" "$out/gemini-gpu.dtb"
        ''
      }
      ${
        if displayOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-gpu.dtb" \
            -o "$out/gemini-display.dtb" \
            ${kernel}/mt6797-gemini-pda-display.dtbo
          test "$(fdtget "$out/gemini-display.dtb" /dsi@1401c000/panel@0 compatible)" = \
            planet,gemini-pda-nt36672
          test "$(fdtget "$out/gemini-display.dtb" /i2c@11008000/regulator@3e compatible)" = \
            mediatek,i2c_lcd_bias
          test "$(fdtget "$out/gemini-display.dtb" /smi@14022000 status)" = okay
          test "$(fdtget "$out/gemini-display.dtb" /larb@14020000 status)" = okay
          test "$(fdtget "$out/gemini-display.dtb" /ovl@1400d000 mediatek,larb)" = \
            "$(fdtget "$out/gemini-display.dtb" /larb@14020000 phandle)"
          test "$(fdtget "$out/gemini-display.dtb" /ovl@1400e000 mediatek,larb)" = \
            "$(fdtget "$out/gemini-display.dtb" /larb@14020000 phandle)"
          ! fdtget "$out/gemini-display.dtb" /iommu@10205000 status \
            2>/dev/null | grep -Fqx okay
          ! fdtget "$out/gemini-display.dtb" /ovl@1400d000 iommus >/dev/null 2>&1
          ! fdtget "$out/gemini-display.dtb" /ovl@1400e000 iommus >/dev/null 2>&1
          echo 'display-overlay=passed' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-gpu.dtb" "$out/gemini-display.dtb"
        ''
      }
      ${
        if audioOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-display.dtb" \
            -o "$out/gemini-audio.dtb" \
            ${kernel}/mt6797-gemini-pda-audio.dtbo
          test "$(fdtget "$out/gemini-audio.dtb" /audio-controller@11220000 status)" = okay
          test "$(fdtget "$out/gemini-audio.dtb" /sound compatible)" = \
            planet,gemini-mt6797-mt6351
          echo 'audio-overlay=passed' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-display.dtb" "$out/gemini-audio.dtb"
        ''
      }
      ${
        if powerObserveOverlay
        then ''
          fdtoverlay \
            -i "$out/gemini-audio.dtb" \
            -o "$out/gemini.dtb" \
            ${kernel}/mt6797-gemini-pda-power-observe.dtbo
          test "$(fdtget "$out/gemini.dtb" /i2c@11007000 status)" = okay
          test "$(fdtget "$out/gemini.dtb" /i2c@11007000/charger@6b status)" = okay
          test "$(fdtget "$out/gemini.dtb" /i2c@11007000/charger@6b compatible)" = \
            'ti,bq25896 ti,bq25890'
          fdtget -p "$out/gemini.dtb" /i2c@11007000/charger@6b \
            | grep -Fqx 'ti,read-only'
          ! fdtget "$out/gemini.dtb" /i2c@11007000/charger@6b interrupts \
            >/dev/null 2>&1
          echo 'power-observe-overlay=passed' >> "$out/VALIDATION"
        ''
        else ''
          cp "$out/gemini-audio.dtb" "$out/gemini.dtb"
        ''
      }
      ${
        if inputObserveOverlay
        then ''
          # Keep the native reviewed keyboard overlay in the composition even
          # though the frozen serviceability transform already carries its
          # exact polling state.  Validate the properties that make the
          # overlay safe instead of pinning a hash of every overlay composed
          # before it.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-keyboard.dtb" \
            ${kernel}/mt6797-gemini-pda-keyboard.dtbo
          test "$(fdtget "$out/gemini-keyboard.dtb" /i2c@1101c000 status)" = okay
          test "$(fdtget "$out/gemini-keyboard.dtb" /i2c@1101c000/gpio-expander@5b status)" = okay
          test "$(fdtget "$out/gemini-keyboard.dtb" /keyboard-matrix status)" = okay
          test "$(fdtget -t i "$out/gemini-keyboard.dtb" /keyboard-matrix poll-interval)" = 20
          test "$(fdtget -t i "$out/gemini-keyboard.dtb" /keyboard-matrix col-scan-delay-us)" = 2

          # This observer enables only I2C4.  The client remains disabled, so
          # kernel probe cannot issue a touchscreen I2C transfer or request
          # GPIO85/EINT8; VTOUCH and GPIO68 reset stay entirely untouched.
          fdtoverlay \
            -i "$out/gemini-keyboard.dtb" \
            -o "$out/gemini-input-observe.dtb" \
            ${kernel}/mt6797-gemini-pda-touchscreen-observe.dtbo
          test "$(fdtget "$out/gemini-input-observe.dtb" /i2c@11011000 status)" = okay
          test "$(fdtget "$out/gemini-input-observe.dtb" /i2c@11011000/touchscreen@62 status)" = disabled
          ! fdtget -p "$out/gemini-input-observe.dtb" /i2c@11011000/touchscreen@62 \
            | grep -Fqx 'reset-gpios'
          cp "$out/gemini-input-observe.dtb" "$out/gemini.dtb"
          echo 'keyboard-overlay=polling-only-aw9523-matrix-passed' >> "$out/VALIDATION"
          echo 'touchscreen-observer=i2c4-only-client-disabled-no-transfer-passed' >> "$out/VALIDATION"
        ''
        else ""
      }
      ${
        if thermalHallObserveOverlay
        then ''
          # Thermal owns indirect AUXADC sampling and its clock. Keep the
          # standalone ADC disabled, as required by integration aff9464721c12;
          # enable the thermal controller and GPIO66 Hall key only.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-thermal-hall-observe.dtb" \
            ${kernel}/mt6797-gemini-pda-thermal-hall-observe.dtbo
          test "$(fdtget "$out/gemini-thermal-hall-observe.dtb" /adc@11001000 status)" = disabled
          test "$(fdtget "$out/gemini-thermal-hall-observe.dtb" /thermal@1100b000 status)" = okay
          test "$(fdtget -t u "$out/gemini-thermal-hall-observe.dtb" /thermal-zones/soc-thermal polling-delay)" = 1000
          test "$(fdtget -t u "$out/gemini-thermal-hall-observe.dtb" /thermal-zones/soc-thermal polling-delay-passive)" = 1000
          test "$(fdtget -t x "$out/gemini-thermal-hall-observe.dtb" /thermal-zones/soc-thermal thermal-sensors)" = \
            "$(fdtget -t x "$out/gemini-thermal-hall-observe.dtb" /thermal@1100b000 phandle)"
          test -z "$(fdtget -l "$out/gemini-thermal-hall-observe.dtb" /thermal-zones/soc-thermal)"
          test "$(fdtget "$out/gemini-thermal-hall-observe.dtb" /gpio-keys status)" = okay
          ! fdtget -p "$out/gemini-thermal-hall-observe.dtb" /gpio-keys \
            | grep -Fqx 'wakeup-source'
          cp "$out/gemini-thermal-hall-observe.dtb" "$out/gemini.dtb"
          echo 'thermal-hall-observer=auxadc-soc-zone-no-trips-gpio66-no-wake-passed' >> "$out/VALIDATION"
        ''
        else ""
      }
      ${
        if touchscreenActivationOverlay
        then ''
          # This is the active NT36772 component, separate from the inert
          # I2C4 observer.  The source-locked overlay deliberately does not
          # claim VTOUCH or GPIO68 reset ownership.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-touchscreen-active.dtb" \
            ${kernel}/mt6797-gemini-pda-touchscreen-activation.dtbo
          test "$(fdtget "$out/gemini-touchscreen-active.dtb" /i2c@11011000 status)" = okay
          test "$(fdtget "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 status)" = okay
          test "$(fdtget "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 compatible)" = \
            novatek,nt36xxx
          ! fdtget -p "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 \
            | grep -Fqx 'reset-gpios'
          ! fdtget -p "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 \
            | grep -Fqx 'novatek,identity-only'
          cp "$out/gemini-touchscreen-active.dtb" "$out/gemini.dtb"
          echo 'touchscreen-activation=nt36772-i2c4-0x62-live-proven-passed' >> "$out/VALIDATION"
        ''
        else ""
      }
      ${
        if fgadcActivationOverlay
        then ''
          # FGADC owns only the calibrated PMIC monitor transaction.  It does
          # not turn on capacity, charger, OTG, interrupt, or MicroSD policy.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-fgadc-active.dtb" \
            ${kernel}/mt6797-gemini-pda-fuel-gauge-active.dtbo
          test "$(fdtget "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge status)" = disabled
          test "$(fdtget "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active status)" = okay
          test "$(fdtget -t x "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active mediatek,fgadc-init-control)" = 28
          test "$(fdtget -t i "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active mediatek,fgadc-osr)" = 8
          fdtget -p "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active \
            | grep -Fqx 'mediatek,initialize-fgadc'
          cp "$out/gemini-fgadc-active.dtb" "$out/gemini.dtb"
          echo 'fgadc-activation=mt6351-exact-0x28-osr8-live-proven-passed' >> "$out/VALIDATION"
        ''
        else ""
      }
      ${
        if microsdOverlay
        then ''
          # MSDC1 uses the proven polled-presence path at 3 V / 25 MHz.
          # GPIO67 is not a working generic card-detect input on this board.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-microsd.dtb" \
            ${kernel}/mt6797-gemini-pda-microsd-bringup.dtbo
          test "$(fdtget "$out/gemini-microsd.dtb" /mmc@11240000 status)" = okay
          test "$(fdtget -t i "$out/gemini-microsd.dtb" /mmc@11240000 bus-width)" = 4
          test "$(fdtget -t i "$out/gemini-microsd.dtb" /mmc@11240000 max-frequency)" = 25000000
          fdtget -p "$out/gemini-microsd.dtb" /mmc@11240000 | grep -Fqx 'no-1-8-v'
          # Presence is polled: GPIO67 carries no card-detect signal on this
          # board and the vendor handles insertion via a separate device, so
          # assert the absence of a cd line as much as the presence of polling.
          fdtget -p "$out/gemini-microsd.dtb" /mmc@11240000 | grep -Fqx 'broken-cd'
          ! fdtget -p "$out/gemini-microsd.dtb" /mmc@11240000 | grep -Fqx 'cd-gpios'
          test "$(fdtget "$out/gemini-microsd.dtb" /aliases mmc0)" = /mmc@11230000
          test "$(fdtget "$out/gemini-microsd.dtb" /aliases mmc1)" = /mmc@11240000
          for rail in vmch vmc; do
            test "$(fdtget -t i "$out/gemini-microsd.dtb" /pwrap@1000d000/pmic/regulators/ldo-$rail regulator-min-microvolt)" = 3000000
            test "$(fdtget -t i "$out/gemini-microsd.dtb" /pwrap@1000d000/pmic/regulators/ldo-$rail regulator-max-microvolt)" = 3000000
          done
          cp "$out/gemini-microsd.dtb" "$out/gemini.dtb"
          echo 'microsd-activation=mmc1-4bit-25mhz-3v-no-uhs-composed' >> "$out/VALIDATION"
        ''
        else ""
      }
      ${
        if deviceActivationOverlay
        then ''
          # These three activation overlays were proved independently against
          # the running Gemini rescue kernel.  Compose them only after the
          # existing unattended observation chain has completed, so this
          # profile has one clear, auditable ownership transition per device.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-touchscreen-active.dtb" \
            ${kernel}/mt6797-gemini-pda-touchscreen-activation.dtbo
          test "$(fdtget "$out/gemini-touchscreen-active.dtb" /i2c@11011000 status)" = okay
          test "$(fdtget "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 status)" = okay
          ! fdtget -p "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 \
            | grep -Fqx 'reset-gpios'
          ! fdtget -p "$out/gemini-touchscreen-active.dtb" /i2c@11011000/touchscreen@62 \
            | grep -Fqx 'novatek,identity-only'

          fdtoverlay \
            -i "$out/gemini-touchscreen-active.dtb" \
            -o "$out/gemini-fgadc-active.dtb" \
            ${kernel}/mt6797-gemini-pda-fuel-gauge-active.dtbo
          test "$(fdtget "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge status)" = disabled
          test "$(fdtget "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active status)" = okay
          test "$(fdtget -t x "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active mediatek,fgadc-init-control)" = 28
          test "$(fdtget -t i "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active mediatek,fgadc-osr)" = 8
          fdtget -p "$out/gemini-fgadc-active.dtb" /pwrap@1000d000/pmic/fuel-gauge-active \
            | grep -Fqx 'mediatek,initialize-fgadc'

          fdtoverlay \
            -i "$out/gemini-fgadc-active.dtb" \
            -o "$out/gemini-device-activation.dtb" \
            ${kernel}/mt6797-gemini-pda-microsd-bringup.dtbo
          test "$(fdtget "$out/gemini-device-activation.dtb" /mmc@11240000 status)" = okay
          test "$(fdtget -t i "$out/gemini-device-activation.dtb" /mmc@11240000 bus-width)" = 4
          test "$(fdtget -t i "$out/gemini-device-activation.dtb" /mmc@11240000 max-frequency)" = 25000000
          fdtget -p "$out/gemini-device-activation.dtb" /mmc@11240000 \
            | grep -Fqx 'no-1-8-v'
          test "$(fdtget "$out/gemini-device-activation.dtb" /pwrap@1000d000/pmic/regulators/ldo-vmch regulator-name)" = vmch
          test "$(fdtget "$out/gemini-device-activation.dtb" /pwrap@1000d000/pmic/regulators/ldo-vmc regulator-name)" = vmc
          cp "$out/gemini-device-activation.dtb" "$out/gemini.dtb"
          echo 'touchscreen-activation=nt36772-i2c4-0x62-live-proven-passed' >> "$out/VALIDATION"
          echo 'fgadc-activation=mt6351-exact-0x28-osr8-live-proven-passed' >> "$out/VALIDATION"
          echo 'microsd-activation=mmc1-4bit-25mhz-3v-no-uhs-live-proven-passed' >> "$out/VALIDATION"
          echo 'display-activation=deferred-until-userspace-writes-activate_drm' >> "$out/VALIDATION"
        ''
        else ""
      }
      ${lib.optionalString (touchscreenActivationOverlay || fgadcActivationOverlay) ''
        # Explicit negative contracts: this full-NixOS baseline does not pull
        # in the later MicroSD, GPU, or radio bring-up experiments.
        test "$(fdtget "$out/gemini.dtb" /mmc@11240000 status)" = ${
          if microsdOverlay then "okay" else "disabled"
        }
        test "$(fdtget "$out/gemini.dtb" /gpu@13040000 status)" = disabled
        test "$(fdtget "$out/gemini.dtb" /consys@18070000 status)" = disabled
        test "$(fdtget "$out/gemini.dtb" /serial@1100c000 status)" = disabled
      ''}
      ${lib.optionalString cellularOverlay ''
        python3 ${./test-cellular-integration-dt.py} "$out/gemini.dtb" \
          ${kernel}/mt6797-gemini-pda-cellular.dtbo ${./cellular-integration-dt.py} >> "$out/VALIDATION"
        python3 ${./cellular-integration-dt.py} "$out/gemini.dtb" \
          ${kernel}/mt6797-gemini-pda-cellular.dtbo >> "$out/VALIDATION"
      ''}
      ${lib.optionalString gpuOwnerOverlay ''
        cp "$out/gemini.dtb" "$out/gpu-carrier.dtb"
        python3 ${./gpu-integration-dt.py} "$out/gpu-carrier.dtb" ${kernel}/mt6797-gemini-pda-gpu-preflight.dtbo "$out/gpu-owner.dtb" >> "$out/VALIDATION"
        HOSTCC=${buildPkgs.stdenv.cc}/bin/cc python3 ${linux-gemini}/drivers/pmdomain/mediatek/test-gpuldo-dt.py "$out/gpu-carrier.dtb" "$out/gpu-owner.dtb" >> "$out/VALIDATION"
        cp "$out/gpu-owner.dtb" "$out/gemini.dtb"
      ''}
      ${lib.optionalString connectivityModules ''
        python3 ${./wifi-integration-dt.py} "$out/gemini.dtb" ${kernel}/mt6797-gemini-pda-wifi.dtbo "$out/wifi-owner.dtb" >> "$out/VALIDATION"
        cp "$out/wifi-owner.dtb" "$out/gemini.dtb"
      ''}
      ${lib.optionalString a72Overlay ''
        dtc -q -@ -I dts -O dtb -o a72-cpu9.dtbo ${./mt6797-gemini-a72-cpu9-on.dtso}
        python3 ${./test-a72-integration-dt.py} "$out/gemini.dtb" ${kernel}/a72-resource.dtbo ${kernel}/a72-cpu8.dtbo a72-cpu9.dtbo ${./a72-integration-dt.py} >> "$out/VALIDATION"
        python3 ${./a72-integration-dt.py} "$out/gemini.dtb" ${kernel}/a72-resource.dtbo ${kernel}/a72-cpu8.dtbo a72-cpu9.dtbo >> "$out/VALIDATION"
        python3 ${./a72-profile-package.py} ${kernel} "$out/gemini.dtb" ${./generate-late-cpu-provenance.py} >> "$out/VALIDATION"
      ''}
      cat ${kernel}/Image.gz "$out/gemini.dtb" > "$out/Image.gz-dtb"
      (cd "$out" && sha256sum gemini-base.dtb gemini.dtb ${
        if thermalHallObserveOverlay
        then "gemini-keyboard.dtb gemini-input-observe.dtb gemini-thermal-hall-observe.dtb "
        else if inputObserveOverlay
        then "gemini-keyboard.dtb gemini-input-observe.dtb "
        else ""
      }${lib.optionalString touchscreenActivationOverlay "gemini-touchscreen-active.dtb "}${lib.optionalString fgadcActivationOverlay "gemini-fgadc-active.dtb "}${lib.optionalString deviceActivationOverlay "gemini-touchscreen-active.dtb gemini-fgadc-active.dtb gemini-device-activation.dtb "}Image.gz-dtb) > "$out/SHA256SUMS"
    '';

  # This is deliberately a small standalone ALSA-UAPI client, not a partial
  # userspace audio stack.  Its default is observation-only; a manually chosen
  # activation stage exercises one control or PCM boundary and records before
  # and after every ALSA ioctl.  Keeping it static avoids adding a dynamic
  # loader or libasound to the diagnostic initramfs.
  audioHeadphoneExercise = crossPkgs.pkgsStatic.stdenv.mkDerivation {
    pname = "gemini-audio-headphone";
    version = "2";
    src = ./gemini-audio-headphone.c;
    dontUnpack = true;
    dontPatchELF = true;
    hardeningDisable = ["all"];
    nativeBuildInputs = [buildPkgs.binutils];
    buildPhase = ''
      runHook preBuild
      "$CC" -std=c11 -Wall -Wextra -Werror -Wpedantic -O2 -static \
        "$src" -o gemini-audio-headphone
      # Cross binaries cannot execute on the build host. Assert the safety
      # contract directly from the source after the warning-clean static build.
      grep -Fq 'STAGE_OBSERVE' "$src"
      grep -Fq 'SNDRV_PCM_IOCTL_HW_FREE' "$src"
      ! grep -Fq 'SNDRV_PCM_IOCTL_DRAIN' "$src"
      ! grep -Fq 'SNDRV_PCM_IOCTL_WRITEI_FRAMES' "$src"
      ! grep -Fq 'SNDRV_PCM_IOCTL_PREPARE' "$src"
      ! grep -Fq 'SNDRV_PCM_IOCTL_START' "$src"
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      install -Dm0755 gemini-audio-headphone "$out/bin/gemini-audio-headphone"
      readelf -h "$out/bin/gemini-audio-headphone" | \
        grep -Fq 'Machine:                           AArch64'
      ! readelf -l "$out/bin/gemini-audio-headphone" | \
        grep -Fq 'Requesting program interpreter'
      ! readelf -d "$out/bin/gemini-audio-headphone" | grep -Fq '(NEEDED)'
      runHook postInstall
    '';
  };

  # This is intentionally smaller and less privileged than a NixOS stage 1.
  # The baseline has no storage drivers at all.  The storage variant adds only
  # ixoo's already hardware-passed 25 MHz eMMC enumeration fragment: userspace
  # reads sysfs metadata but never opens or mounts a block device.  SSH is
  # public-key-only; the old unauthenticated TCP shell is omitted whenever SSH
  # is present so a later host-network experiment cannot accidentally expose it.
  probeInitramfs =
    buildPkgs.runCommand "gemini-ixoo-probe-initramfs${variantSuffix}.cpio.gz" (
      {
        nativeBuildInputs = [buildPkgs.binutils buildPkgs.cpio buildPkgs.gzip];
        busybox = crossPkgs.pkgsStatic.busybox;
        rtlFirmware = buildPkgs.linux-firmware;
      }
      // lib.optionalAttrs audioHeadphoneTest {
        inherit audioHeadphoneExercise;
      }
      // lib.optionalAttrs sshAccess {
        dropbear = crossPkgs.pkgsStatic.dropbear;
        authorizedKeys = ../nixos/authorized_keys;
      }
    ) ''
      mkdir -p root/bin root/dev root/etc root/mnt/linux root/proc root/run root/sys/fs/pstore
      ${lib.optionalString usbHostOverlay ''
        mkdir -p root/lib/firmware/rtl_nic
        cp "$rtlFirmware/lib/firmware/rtl_nic/rtl8156b-2.fw" \
          root/lib/firmware/rtl_nic/rtl8156b-2.fw
        test "$(sha256sum root/lib/firmware/rtl_nic/rtl8156b-2.fw | cut -d' ' -f1)" = \
          5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f
      ''}
      ${lib.optionalString consysFirmwareAvailable ''
        # The staged MT6797 patch controller accepts only these bare names and
        # complete-image digests. Packaging is not activation: the G2b command
        # line only enables the patch gate in the explicit G2c profile; every
        # radio function remains disabled in every profile.
        mkdir -p root/lib/firmware
        cp ${../blobs/WMT_SOC.cfg} root/lib/firmware/WMT_SOC.cfg
        cp ${../blobs/ROMv3_patch_1_1_hdr.bin} \
          root/lib/firmware/ROMv3_patch_1_1_hdr.bin
        cp ${../blobs/ROMv3_patch_1_0_hdr.bin} \
          root/lib/firmware/ROMv3_patch_1_0_hdr.bin
        test "$(stat -c %s root/lib/firmware/WMT_SOC.cfg)" = 80
        test "$(sha256sum root/lib/firmware/WMT_SOC.cfg | cut -d' ' -f1)" = \
          f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880
        test "$(stat -c %s root/lib/firmware/ROMv3_patch_1_1_hdr.bin)" = 46472
        test "$(sha256sum root/lib/firmware/ROMv3_patch_1_1_hdr.bin | cut -d' ' -f1)" = \
          5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e
        test "$(stat -c %s root/lib/firmware/ROMv3_patch_1_0_hdr.bin)" = 210904
        test "$(sha256sum root/lib/firmware/ROMv3_patch_1_0_hdr.bin | cut -d' ' -f1)" = \
          450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630
      ''}
      cp "$busybox/bin/busybox" root/bin/busybox
      ${lib.optionalString audioHeadphoneTest ''
        cp "$audioHeadphoneExercise/bin/gemini-audio-headphone" \
          root/bin/gemini-audio-headphone
        readelf -h root/bin/gemini-audio-headphone | \
          grep -Fq 'Machine:                           AArch64'
        ! readelf -l root/bin/gemini-audio-headphone | \
          grep -Fq 'Requesting program interpreter'
        ! readelf -d root/bin/gemini-audio-headphone | grep -Fq '(NEEDED)'
      ''}
      ${lib.optionalString powerObservePreflight ''
        cp ${./bq2589x-preflight.sh} root/bin/bq2589x-preflight
        chmod 0755 root/bin/bq2589x-preflight
      ''}
      ${lib.optionalString unattendedRecovery ''
        # busybox is an aarch64 target binary; inspect it, never execute it on
        # the x86_64 builder.  The applet is then exposed by --install below.
        grep -a -Fq watchdog "$busybox/bin/busybox"
      ''}
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
        note "watchdog0=present identity=$(cat /sys/class/watchdog/watchdog0/identity 2>/dev/null || echo unknown) timeout=$(cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null || echo unknown)"
      else
        note "watchdog0=missing"
      fi
      ${lib.optionalString unattendedRecovery ''
      watchdog_device=
      for candidate in /dev/watchdog /dev/watchdog0; do
        if [ -c "$candidate" ]; then
          watchdog_device=$candidate
          break
        fi
      done
      if [ -n "$watchdog_device" ]; then
        /bin/watchdog -F -t 10 -T 31 "$watchdog_device" >/run/watchdog.log 2>&1 &
        watchdog_pid=$!
        sleep 1
        if kill -0 "$watchdog_pid" 2>/dev/null; then
          note "unattended_recovery=healthy watchdog_userspace=petting watchdog_device=$watchdog_device watchdog_pid=$watchdog_pid watchdog_lifecycle=initramfs-through-ssh"
          (
            sleep 90
            if [ "$(cat /run/unattended-recovery.accepted 2>/dev/null || true)" != "unattended_recovery=healthy" ]; then
              note "unattended_recovery=lease-expired watchdog_userspace=stopped watchdog_reset_expected=31s"
              kill -KILL "$watchdog_pid" 2>/dev/null || true
            fi
          ) &
        else
          note "unattended_recovery=failed watchdog_userspace=open-failed"
        fi
      else
        note "unattended_recovery=failed watchdog_userspace=device-missing"
      fi
      ''}
      ${lib.optionalString powerObservePreflight ''
      # Runs asynchronously after the watchdog petter is established.  Its
      # result intentionally cannot extend the watchdog lease; a reviewer must
      # inspect /run/bq2589x-preflight.{status,dmesg,pass|fail} and decide.
      /bin/bq2589x-preflight &
      note "power_observe_preflight=started mode=sysfs-and-dmesg-only watchdog_lease=unchanged"
      ''}
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
      ${lib.optionalString usbHostOverlay ''
      /bin/usb-host-net &
      ''}
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

      ${lib.optionalString usbHostOverlay ''
      cat > root/bin/usb-host-net-udhcpc <<'USB_HOST_NET_UDHCPC'
      #!/bin/busybox sh
      export PATH=/bin
      # udhcpc supplies these values as environment variables.  This script
      # deliberately does not eval/source them: only the values accepted by
      # ip(8) are passed to the kernel, and interface names are constrained.
      interface=''${interface:-}
      [ -n "$interface" ] || exit 1
      case "$interface" in
        *[!A-Za-z0-9._-]*) exit 1 ;;
      esac
      ip_value=''${ip:-}
      [ -n "$ip_value" ] || exit 1
      case "$ip_value" in
        *[!0-9./]*) exit 1 ;;
      esac
      subnet=''${subnet:-24}
      case "$subnet" in
        *[!0-9.]*) exit 1 ;;
      esac
      case "''${1:-}" in
        deconfig)
          ip addr flush dev "$interface" 2>/dev/null || true
          echo "usb-host-net=deconfigured iface=$interface" >> /run/probe-status 2>/dev/null || true
          ;;
        bound|renew)
          ip link set "$interface" up 2>/dev/null || exit 1
          ip addr flush dev "$interface" 2>/dev/null || true
          ip addr replace "$ip_value/$subnet" dev "$interface" || exit 1
          for gateway in ''${router:-}; do
            case "$gateway" in
              *[!0-9.]*) continue ;;
            esac
            ip route replace default via "$gateway" dev "$interface" || exit 1
            break
          done
          echo "usb-host-net=ready iface=$interface address=$ip_value/$subnet action=$1 usb=''${USB_HOST_USB:-unknown}" >> /run/probe-status 2>/dev/null || true
          ;;
        *)
          echo "usb-host-net=ignored iface=$interface action=''${1:-missing}" >> /run/probe-status 2>/dev/null || true
          ;;
      esac
      USB_HOST_NET_UDHCPC

      cat > root/bin/usb-host-net <<'USB_HOST_NET'
      #!/bin/busybox sh
      export PATH=/bin
      attempt=0
      host_if=
      usb_vid=
      usb_pid=
      while [ "$attempt" -lt 60 ] && [ -z "$host_if" ]; do
        for net in /sys/class/net/*; do
          [ -e "$net" ] || continue
          name=''${net##*/}
          [ "$name" != usb0 ] || continue
          driver=$(readlink -f "$net/device/driver" 2>/dev/null || true)
          case "$driver" in
            */r8152)
              host_if=$name
              usb_path=$(readlink -f "$net/device" 2>/dev/null || true)
              while [ -n "$usb_path" ] && [ "$usb_path" != / ]; do
                if [ -r "$usb_path/idVendor" ] && [ -r "$usb_path/idProduct" ]; then
                  usb_vid=$(cat "$usb_path/idVendor")
                  usb_pid=$(cat "$usb_path/idProduct")
                  break
                fi
                parent=''${usb_path%/*}
                [ "$parent" != "$usb_path" ] || break
                usb_path=$parent
              done
              break ;;
          esac
        done
        [ -n "$host_if" ] || { attempt=$((attempt + 1)); sleep 1; }
      done
      if [ -z "$host_if" ]; then
        echo "<3>GEMINI_NIX_IXOO_PROBE: usb-host-net=missing after=60s driver=r8152" > /dev/kmsg 2>/dev/null || true
        echo "usb-host-net=missing after=60s driver=r8152" >> /run/probe-status 2>/dev/null || true
        exit 1
      fi
      if [ "$usb_vid" != 0bda ] || [ "$usb_pid" != 8156 ]; then
        echo "usb-host-net=failed iface=$host_if driver=r8152 usb=''${usb_vid:-unknown}:''${usb_pid:-unknown}" >> /run/probe-status 2>/dev/null || true
        exit 1
      fi
      ip link set "$host_if" up 2>/dev/null || {
        echo "usb-host-net=failed iface=$host_if stage=link-up" >> /run/probe-status 2>/dev/null || true
        exit 1
      }
      echo "usb-host-net=waiting iface=$host_if driver=r8152 usb=$usb_vid:$usb_pid" >> /run/probe-status 2>/dev/null || true
      export USB_HOST_USB=$usb_vid:$usb_pid
      # Foreground mode keeps DHCP renewals alive for the whole probe life.
      # No -q/-n: losing the host cable is recorded, while gadget SSH remains.
      exec udhcpc -f -t 5 -T 3 -A 10 -i "$host_if" -s /bin/usb-host-net-udhcpc
      USB_HOST_NET
      ''}

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

        # Resolve the data eMMC by the board's fixed controller lineage.  The
        # block class also exposes boot0/boot1/RPMB and partitions; only the
        # whole disk (mmcblkN) is accepted.
        resolve_emmc_device() {
          controller=
          for candidate in \
            /sys/devices/platform/11230000.mmc \
            /sys/devices/platform/*/11230000.mmc \
            /sys/devices/platform/*/*/11230000.mmc; do
            [ -d "$candidate" ] || continue
            resolved=$(readlink -f "$candidate" 2>/dev/null || true)
            [ -n "$resolved" ] || continue
            if [ -n "$controller" ] && [ "$controller" != "$resolved" ]; then
              return 1
            fi
            controller=$resolved
          done
          [ -n "$controller" ] || return 1
          found=
          for node in /sys/class/block/mmcblk*; do
            [ -e "$node" ] || continue
            name=''${node##*/}
            case "$name" in
              mmcblk[0-9]*)
                suffix=''${name#mmcblk}
                case "$suffix" in *[!0-9]*|"") continue ;; esac
                ;;
              *) continue ;;
            esac
            [ ! -e "$node/partition" ] || continue
            parent=$(readlink -f "$node/device" 2>/dev/null || true)
            matched=no
            while [ -n "$parent" ] && [ "$parent" != / ]; do
              if [ "$parent" = "$controller" ]; then
                matched=yes
                break
              fi
              next_parent=''${parent%/*}
              [ "$next_parent" != "$parent" ] || break
              parent=$next_parent
            done
            if [ "$matched" = yes ]; then
              [ -z "$found" ] || return 1
              found=$name
            fi
          done
          [ -n "$found" ] || return 1
          printf '%s\n' "$found"
        }

        attempt=0
        emmc=
        while [ "$attempt" -lt 30 ]; do
          emmc=$(resolve_emmc_device 2>/dev/null || true)
          [ -n "$emmc" ] && break
          attempt=$((attempt + 1))
          sleep 1
        done
        if [ -z "$emmc" ]; then
          record "emmc=missing after=30s userspace_block_io=none"
          dmesg 2>/dev/null | grep -Ei '1000d000|pwrap|mt6351|11230000|msdc|mmc[0-9]|mmcblk' >> /run/storage-probe 2>/dev/null || true
          exit 1
        fi
        printf '%s\n' "$emmc" > /run/emmc-block-device

        if grep -Eq '^[^ ]*mmcblk' /proc/mounts 2>/dev/null; then
          record "guard=failed unexpected_mmc_mount=yes"
          exit 1
        fi
        sectors=$(cat "/sys/class/block/$emmc/size" 2>/dev/null || echo unknown)
        device=$(readlink -f "/sys/class/block/$emmc/device" 2>/dev/null || echo unknown)
        partitions=
        for node in /sys/class/block/"$emmc"p*; do
          [ -e "$node" ] || continue
          partitions="''${partitions} ''${node##*/}"
        done
        record "emmc=present block=$emmc sectors=$sectors host=$device partitions=''${partitions# } userspace_block_reads=none userspace_block_writes=none mounts=none"
        for uevent in /sys/class/block/mmcblk*/uevent; do
          [ -r "$uevent" ] || continue
          echo "--- $uevent" >> /run/storage-probe
          cat "$uevent" >> /run/storage-probe
        done
        dmesg 2>/dev/null | grep -Ei '1000d000|pwrap|mt6351|11230000|msdc|mmc[0-9]|mmcblk' >> /run/storage-probe 2>/dev/null || true
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

        emmc=$(cat /run/emmc-block-device 2>/dev/null || true)
        case "$emmc" in
          ""|mmcblk*[!0-9]*)
            record "mount=skipped reason=invalid-emmc-device value=''${emmc:-missing}"
            exit 1
            ;;
        esac
        source=/dev/''${emmc}p29
        if ! mount -t ext4 -o ro,noload,nosuid,nodev,noexec "$source" /mnt/linux; then
          record "mount=failed source=$source requested=ro,noload"
          dmesg 2>/dev/null | grep -Ei "EXT4-fs|''${emmc}p29" >> /run/rootfs-probe 2>/dev/null || true
          exit 1
        fi
        mounted=$(awk '$2 == "/mnt/linux" { print $1 ":" $3 ":" $4; exit }' /proc/mounts)
        record "mount=success source=$source observed=''${mounted:-unknown} access=directory-metadata-only writes=none"
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
        dmesg 2>/dev/null | grep -Ei "EXT4-fs|''${emmc}p29" >> /run/rootfs-probe 2>/dev/null || true
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
      ${lib.optionalString usbHostOverlay ''
        chmod 0755 root/bin/usb-host-net root/bin/usb-host-net-udhcpc
      ''}
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
    ${lib.optionalString audioHeadphoneTest ''
      ln -s ${audioHeadphoneExercise}/bin/gemini-audio-headphone \
        "$out/gemini-audio-headphone"
    ''}
    ${lib.optionalString unattendedRecovery ''
      ln -s ${probeBoot2Img} "$out/boot-padded-p22.img"
    ''}
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
      echo "nix-consys-g2b=${consysG2bLabel}"
      echo "nix-consys-g2c-patch=${consysG2cPatchLabel}"
      echo "nix-consys-g2d-postpatch=${consysG2dPostpatchLabel}"
      echo "nix-consys-firmware=${consysFirmwareLabel}"
      echo "nix-gpu-staged=${gpuStagedLabel}"
      echo "nix-gpu-fixed-opp=${gpuFixedOppLabel}"
      echo "nix-platform-enablement=${if platformEnablement then "reviewed-dormant-v1" else "none"}"
      echo "nix-display=${displayLabel}"
      echo "nix-audio=${audioLabel}"
      echo "nix-audio-headphone-test=${audioHeadphoneTestLabel}"
      echo "nix-power-observe=${powerObserveLabel}"
      echo "nix-power-observe-preflight=${powerObservePreflightLabel}"
      echo "nix-input-observe=${inputObserveLabel}"
      echo "nix-thermal-hall-observe=${if thermalHallObserveOverlay then "auxadc-thermal-gpio66-no-wake-v1" else "none"}"
      echo "nix-touchscreen-activation=${touchscreenActivationLabel}"
      echo "nix-fgadc-activation=${fgadcActivationLabel}"
      echo "nix-device-activation=${deviceActivationLabel}"
      echo "display-activation=${if deviceActivationOverlay then "deferred: write 1 to 14000000.syscon/activate_drm only after SSH/watchdog validation" else "none"}"
      echo "nix-unattended-recovery=${unattendedRecoveryLabel}"
      echo "watchdog-config=${
        if unattendedRecovery
        then "CONFIG_MEDIATEK_WATCHDOG=y CONFIG_WATCHDOG_OPEN_TIMEOUT=90 CONFIG_PANIC_ON_OOPS=y CONFIG_PANIC_TIMEOUT=5"
        else "none"
      }"
      echo "watchdog-userspace=${
        if unattendedRecovery
        then "initramfs-/dev/watchdog-open-and-pet-through-ssh"
        else "none"
      }"
      echo "unattended-recovery-residual=${
        if unattendedRecovery
        then "pre-mtk-wdt-probe-unprotected; kernel-probe-observed-at-about-1.07s-on-live-baseline"
        else "none"
      }"
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
      echo "usb-host-net=${
        if usbHostOverlay
        then "r8152-0bda:8156-dhcp-renewal-required firmware=rtl_nic/rtl8156b-2.fw"
        else "none"
      }"
      echo "usb-host-firmware-sha256=${
        if usbHostOverlay
        then "5a3b21e27305876af8eac4b9bd11a821487b338e4ac1b58b8be8d23467d3f91f"
        else "none"
      }"
      echo "usb-host-dtbo-sha256=${
        if usbHostOverlay
        then "a341e238e2479c6ac3f633c4262f170c6b53dbeec7867b2956fd80f656ff3469"
        else "none"
      }"
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
      ${lib.optionalString audioHeadphoneTest ''
        sha256sum ${audioHeadphoneExercise}/bin/gemini-audio-headphone
      ''}
      stat -c '%n size=%s' ${probeBootImg} ${probeBoot2Img}
      } > "$out/MANIFEST"
  '';
in {
  inherit audioHeadphoneExercise kernel leaseSelfAcceptToken serviceabilityDtb probeInitramfs probeBootImg probeBoot2Img bundle;
}
