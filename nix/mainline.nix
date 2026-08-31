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
  consysG2bOverlay ? false,
  consysG2cPatchOverlay ? false,
  consysG2dPostpatchOverlay ? false,
  consysG2gGnssEndpoint ? false,
  consysG2hBtEndpoint ? false,
  wifiW0Observe ? false,
  wifiW1FirmwareReadyProof ? false,
  wifiW1Forensic ? false,
  wifiW2NicCapability ? false,
  wifiW4Connect ? false,
  consysFirmware ? false,
  gpuStagedOverlay ? false,
  gpuFixedOppOverlay ? false,
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
  a72Cpu8SramDiagnostic ? false,
  a72Cpu8TraceOnly ? false,
  a72Cpu8Interactive ? false,
}: let
  lib = buildPkgs.lib;

  # A locked Git input carries rev; a deliberate local-path override carries
  # only its content hash.  Record whichever identity Nix actually consumed so
  # a local reviewed build can never masquerade as the old locked commit.
  kernelRevision =
    if linux-gemini ? rev
    then linux-gemini.rev
    else "nar:${linux-gemini.narHash}";
  p22BaselinePlatformRevision = "28c47150235be70cf5b19ea8d9ce7a5473ec23f2";
  # This candidate must use the profile that carries the DA9213 membership
  # owner.  The preceding read-only profile binds the regulator but leaves the
  # provider unpublished, which keeps the A72 binder at -EPROBE_DEFER and the
  # controller status at binder_snapshot_ret=-EAGAIN.
  ixooRevision = "4c1143012226586dc13b24eb1042422f1b4dfa69";
  candidateRevision = "4c1143012226586dc13b24eb1042422f1b4dfa69";
  profile = "a72-admission-live-trigger-candidate";

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
    ++ lib.optionals consysG2gGnssEndpoint [./mainline-consys-g2g-gnss.fragment]
    ++ lib.optionals consysG2hBtEndpoint [./mainline-consys-g2h-bt.fragment]
    ++ lib.optionals (wifiW0Observe || wifiW1FirmwareReadyProof || wifiW2NicCapability || wifiW4Connect) [./mainline-wifi-w0.fragment]
    ++ lib.optionals (wifiW1FirmwareReadyProof || wifiW2NicCapability || wifiW4Connect) [./mainline-wifi-w1-ready.fragment]
    ++ lib.optionals (wifiW2NicCapability || wifiW4Connect) [./mainline-wifi-w2-capability.fragment]
    ++ lib.optionals wifiW4Connect [./mainline-wifi-w4-connect.fragment]
    ++ lib.optionals gpuStagedOverlay [./mainline-gpu-staged.fragment]
    ++ lib.optionals gpuFixedOppOverlay [./mainline-gpu-fixed-opp.fragment]
    ++ lib.optionals platformEnablement [./mainline-platform-smoke.fragment]
    ++ lib.optionals powerObserveOverlay [./mainline-power-observe.fragment]
    ++ lib.optionals unattendedRecovery [./mainline-unattended-recovery.fragment]
    ++ lib.optionals inputObserveOverlay [./mainline-input-observe.fragment]
    ++ lib.optionals thermalHallObserveOverlay [./mainline-thermal-hall-observe.fragment]
    ++ lib.optionals touchscreenActivationOverlay [./mainline-touchscreen-activation.fragment]
    ++ lib.optionals fgadcActivationOverlay [./mainline-fgadc-activation.fragment]
    ++ lib.optionals deviceActivationOverlay [./mainline-device-activation.fragment]
    ++ lib.optionals a72Cpu8SramDiagnostic [./mainline-a72-cpu8-sram-diagnostic.fragment] 
    ++ lib.optionals deviceActivationOverlay [./mainline-device-activation.fragment];
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
  consysG2gGnssLabel =
    if consysG2gGnssEndpoint
    then "retained-full-stp-gpio69-func-ctrl-dev-gnss-v1"
    else "none";
  consysG2hBtLabel =
    if consysG2hBtEndpoint
    then "retained-full-stp-vcn33-bt-hci-v1"
    else "none";
  wifiW0Label = if wifiW0Observe then "gen3-cmd53-wcir-only-v1" else "none";
  wifiW1Label =
    if wifiW1FirmwareReadyProof
    then
      if wifiW1Forensic
      then "bounded-full-firmware-start-ready-forensic-no-irq-no-netdev-v1"
      else "bounded-full-firmware-start-ready-no-irq-no-netdev-v1"
    else "none";
  wifiW2Label =
    if wifiW2NicCapability
    then "bounded-nic-capability-fresh-rx1-irq-no-netdev-v1"
    else "none";
  wifiW4Label =
    if wifiW4Connect
    then "retained-controller-w3-irq-cfg80211-open-auth-assoc-netdev-v2"
    else "none";
  consysFirmwareAvailable =
    consysFirmware || consysG2cPatchOverlay || consysG2dPostpatchOverlay ||
    wifiW1FirmwareReadyProof;
  consysFirmwareLabel =
    if consysG2cPatchOverlay || consysG2dPostpatchOverlay || wifiW1FirmwareReadyProof
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
  a72Cpu8SramDiagnosticLabel =
    if a72Cpu8Interactive
    then "cpu8-interactive-idle-v1"
    else if a72Cpu8TraceOnly
    then "cpu8-trace-header-read-only-v1"
    else if a72Cpu8SramDiagnostic
    then "cpu8-one-shot-sram-p28-diagnostic-v1"
    else "none";
  md1LkHandoffLabel =
    if !md1LkHandoffProbe
    then "none"
    else if md1BootStatusObserve
    then "lk-v2-load-evidence-plus-boot-status-read-only-dt-and-cmdline-gated-v9-no-md1-control"
    else if md1RemapObserve
    then "lk-v2-load-evidence-plus-infracfg-remap-lock-five-read-observation-dt-and-cmdline-gated-v10-no-md1-control"
    else "lk-v2-load-evidence-and-rmpu-remap-plan-read-only-dt-and-cmdline-gated-v9-secure-mpu-status-fatal-latch-provider-backend-unselected";
  md1BootStatusLabel =
    if md1BootStatusObserve
    then "three-vendor-shaped-reads-per-ap-visible-status-word-plus-passive-ap-rchnum-raw-no-write-no-interpretation"
    else "none";
  md1RemapObserveLabel =
    if md1RemapObserve
    then "five-infracfg-ao-reads-after-validated-lk-plan-no-write-no-ownership"
    else "none";
  a72MaxCpus = if a72Cpu8SramDiagnostic then "9" else "8";
  panicCmdline = if unattendedRecovery then "panic=5" else "panic=0";
  gadgetProduct =
    if a72Cpu8SramDiagnostic
    then "Gemini-A72-CPU8-Admission"
    else "Gemini-L-DA921x-Bind";
  gadgetSerial =
    if a72Cpu8SramDiagnostic
    then "A72-89898a1-gatefix"
    else "GEMINI_DA921X_BIND_20260729";
  baseCmdline =
    if debugOverlay
    then "console=tty0 console=ttyS0,921600n8 earlycon maxcpus=${a72MaxCpus} nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init ${panicCmdline} g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=${gadgetProduct} g_ether.iSerialNumber=${gadgetSerial} clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused initcall_blacklist=mt6797_a72_power_driver_init fw_devlink=rpm"
    else "console=ttyS0,921600n8 earlycon maxcpus=${a72MaxCpus} nokaslr ignore_loglevel loglevel=8 log_buf_len=1M initcall_debug rdinit=/init ${panicCmdline} g_ether.dev_addr=42:00:15:19:82:01 g_ether.host_addr=42:00:15:19:82:00 g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=${gadgetProduct} g_ether.iSerialNumber=${gadgetSerial} clk_ignore_unused fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32 regulator_ignore_unused initcall_blacklist=mt6797_a72_power_driver_init fw_devlink=rpm";
  usbBuildTag =
    if consysG2hBtEndpoint
    then "radio-gnss-bt"
    else if consysG2gGnssEndpoint
    then "radio-gnss"
    else if wifiW4Connect
    then "wifi-w4"
    else if wifiW2NicCapability
    then "wifi-w2"
    else if wifiW1FirmwareReadyProof
    then "wifi-w1"
    else if consysG2dPostpatchOverlay
    then "consys-g2d"
    else if gpuFixedOppOverlay
    then "gpu-panfrost"
    else if platformEnablement
    then "platform"
    else "baseline";
  usbBuildSerial = "NIX-${builtins.substring 0 16 (builtins.hashString "sha256" "${kernelRevision}:${variantSuffix}")}";
  usbIdentityCmdline = "g_ether.iManufacturer=gemini-pda-mainline g_ether.iProduct=Gemini-${usbBuildTag} g_ether.iSerialNumber=${usbBuildSerial}";
  kernelCmdline =
    baseCmdline
    + lib.optionalString consysIdentityOverlay " mt6797_consys_live.identity_experiment=1"
    + lib.optionalString consysG2bOverlay " mt6797_consys_emi_mpu.enable_experimental_ownership=1 mt6797_consys_runtime.enable_experimental_runtime=1 mt6797_btif_pio_platform.enable_experimental_platform_adapter=1 mt6797_btif_stp_bootstrap.enable_experimental_stp_bootstrap=1 mt6797_consys_runtime_controller.enable_experimental_runtime_controller=1 mt6797_consys_g2b_owner.enable_experimental_g2b_owner=1"
    + lib.optionalString consysG2cPatchOverlay " mt6797_consys_emi_mpu.enable_experimental_ownership=1 mt6797_consys_runtime.enable_experimental_runtime=1 mt6797_btif_pio_platform.enable_experimental_platform_adapter=1 mt6797_btif_stp_bootstrap.enable_experimental_stp_bootstrap=1 mt6797_consys_runtime_controller.enable_experimental_runtime_controller=1 mt6797_consys_wmt_patch.enable_patch_download=1 mt6797_consys_g2c_patch_owner.enable_experimental_g2c_patch_owner=1"
    + lib.optionalString consysG2dPostpatchOverlay " mt6797_consys_emi_mpu.enable_experimental_ownership=1 mt6797_consys_runtime.enable_experimental_runtime=1 mt6797_btif_pio_platform.enable_experimental_platform_adapter=1 mt6797_btif_stp_bootstrap.enable_experimental_stp_bootstrap=1 mt6797_consys_runtime_controller.enable_experimental_runtime_controller=1 mt6797_consys_wmt_patch.enable_patch_download=1 mt6797_consys_g2d_postpatch_owner.enable_experimental_g2d_postpatch_owner=1"
    + lib.optionalString consysG2gGnssEndpoint " mt6797_consys_g2d_postpatch_owner.enable_experimental_g2g_gnss_endpoint=1"
    + lib.optionalString consysG2hBtEndpoint " mt6797_consys_g2d_postpatch_owner.enable_experimental_g2h_bt_endpoint=1"
    + lib.optionalString wifiW0Observe " mt6797_wifi_ahb_wcir.enable_experimental_wifi_wcir_observe=1"
    + lib.optionalString wifiW1FirmwareReadyProof " mt6797_wifi_ahb_w1_firmware.enable_experimental_wifi_w1_firmware_preflight=1"
    + lib.optionalString wifiW2NicCapability " mt6797_wifi_ahb_w1_firmware.enable_experimental_wifi_w2_nic_capability=1"
    + lib.optionalString wifiW4Connect " mt6797_consys_g2d_postpatch_owner.enable_experimental_wifi_w4_retained_owner=1 mt6797_wifi_ahb_w3_session.enable_experimental_wifi_w3_session=1 mt6797_wifi_ahb_w4_platform.enable_experimental_wifi_w4_platform=1"
    + lib.optionalString gpuStagedOverlay " mt6797_gpu_staged.enable_experimental_stages=1 mt6797_gpu_staged.stage=2 mt6797_gpu_staged.max_stage_ms=3000"
    + lib.optionalString unattendedRecovery " mtk_wdt.start_at_boot=1";
  variantSuffix =
    lib.optionalString storageOverlay "-emmc-probe"
    + lib.optionalString sshAccess "-ssh"
    + lib.optionalString rootfsProbe "-p29-ro"
    + lib.optionalString usbHostOverlay "-usb11-host"
    + lib.optionalString consysIdentityOverlay "-consys-identity"
    + lib.optionalString consysG2bOverlay "-consys-g2b"
    + lib.optionalString consysG2cPatchOverlay "-consys-g2c-patch"
    + lib.optionalString consysG2dPostpatchOverlay "-consys-g2d-postpatch"
    + lib.optionalString consysG2gGnssEndpoint "-consys-g2g-gnss"
    + lib.optionalString consysG2hBtEndpoint "-consys-g2h-bt"
    + lib.optionalString wifiW0Observe "-wifi-w0"
    + lib.optionalString wifiW1FirmwareReadyProof (
      if wifiW2NicCapability || wifiW4Connect then "" else if wifiW1Forensic then "-wifi-w1-forensic" else "-wifi-w1-ready"
    )
    + lib.optionalString wifiW2NicCapability "-wifi-w2-capability"
    + lib.optionalString wifiW4Connect "-wifi-w4-connect"
    + lib.optionalString consysFirmware "-consys-firmware"
    + lib.optionalString gpuStagedOverlay "-gpu-staged"
    + lib.optionalString gpuFixedOppOverlay "-gpu-fixed-opp"
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
    + lib.optionalString deviceActivationOverlay "-device-activation"
    + lib.optionalString a72Cpu8SramDiagnostic "-a72-cpu8-sram"
    + lib.optionalString a72Cpu8TraceOnly "-trace-only"
    + lib.optionalString a72Cpu8Interactive "-interactive";
  # These three inputs are generated from the same locked DTS and the same
  # unconditional provider/USB transforms for every exported profile.
  # The reviewed CPU8 chain replaces the deleted a72_power node with the
  # disabled a72_platform_state/DVFSP access-controller topology.  Pin the
  # resulting base DTB rather than accepting the retired topology's hash.
  baseDtbSha256 = "f1262332ce232dac56c78c9d3d3e1fa390ebfd2209540fa4ca023b89cb871250";
	# CPU8 diagnostic candidates reserve two exact private pages after ramoops.
	# These source-checked fingerprints intentionally differ only for that DT.
	admissionBaseDtbSha256 = "c113d7d5b121fbee4e8a1090d04f8fa9e1afd7981b8cbc3edac93555064fb646";
  # Same reviewed A72 topology after the existing, structurally validated
  # serviceability transform (CONSYS/BTIF remain disabled).
  serviceabilityBaseDtbSha256 = "22b7b4158f88a2ad8bb752dbf1d3cfbae4234efd95356b1c5dc044fd7824f613";
	admissionServiceabilityBaseDtbSha256 = "0e6cdd5edf677e992386ef501456d241d7e599054e1c38756c594836bdb19b24";
  usbPlatformDtbSha256 = "9aa05bcd7abea8b774ce17a33bc8625f13b72d5ffe2711c4ad76e488c456b815";
  profileCombinationValid =
    assert !(consysIdentityOverlay && (consysG2bOverlay || consysG2cPatchOverlay || consysG2dPostpatchOverlay));
    assert !(consysG2bOverlay && (consysG2cPatchOverlay || consysG2dPostpatchOverlay));
    assert !(consysG2cPatchOverlay && consysG2dPostpatchOverlay);
    assert !wifiW0Observe || consysG2dPostpatchOverlay;
    assert !consysG2gGnssEndpoint || consysG2dPostpatchOverlay;
    assert !consysG2hBtEndpoint || consysG2dPostpatchOverlay;
    assert !consysG2gGnssEndpoint || (!wifiW0Observe && !wifiW1FirmwareReadyProof && !wifiW2NicCapability && !wifiW4Connect);
    assert !wifiW1FirmwareReadyProof || (consysG2dPostpatchOverlay && wifiW0Observe);
    assert !wifiW1Forensic || wifiW1FirmwareReadyProof;
    assert !wifiW2NicCapability || (wifiW1FirmwareReadyProof && wifiW0Observe && consysG2dPostpatchOverlay);
    assert !wifiW4Connect || (wifiW2NicCapability && wifiW1FirmwareReadyProof && wifiW0Observe && consysG2dPostpatchOverlay);
    assert !consysFirmware || consysG2bOverlay;
    assert !(gpuStagedOverlay && gpuFixedOppOverlay);
    assert !((gpuStagedOverlay || gpuFixedOppOverlay) && (consysIdentityOverlay || consysG2bOverlay || consysG2cPatchOverlay || consysG2dPostpatchOverlay));
    assert !consysG2cPatchOverlay || unattendedRecovery;
    assert !consysG2dPostpatchOverlay || unattendedRecovery;
    assert !wifiW1FirmwareReadyProof || unattendedRecovery;
    assert !wifiW2NicCapability || unattendedRecovery;
    assert !wifiW4Connect || unattendedRecovery;
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
      || kernelRevision == p22BaselinePlatformRevision
      || a72Cpu8SramDiagnostic;
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
    assert
      !a72Cpu8SramDiagnostic
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
        && touchscreenActivationOverlay
        && fgadcActivationOverlay
        && !deviceActivationOverlay
        && !consysIdentityOverlay
      );
    assert !a72Cpu8TraceOnly || a72Cpu8SramDiagnostic;
    assert !a72Cpu8Interactive || (a72Cpu8SramDiagnostic && a72Cpu8TraceOnly && unattendedRecovery && sshAccess);
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
      + lib.optionalString wifiW0Observe "-wifi-w0"
      + lib.optionalString wifiW1FirmwareReadyProof (
        if wifiW2NicCapability || wifiW4Connect then "" else if wifiW1Forensic then "-wifi-w1-forensic" else "-wifi-w1-ready"
      )
      + lib.optionalString wifiW2NicCapability "-wifi-w2-capability"
      + lib.optionalString wifiW4Connect "-wifi-w4-connect"
      + lib.optionalString gpuStagedOverlay "-gpu-staged"
      + lib.optionalString gpuFixedOppOverlay "-gpu-fixed-opp"
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
      + lib.optionalString deviceActivationOverlay "-device-activation"
      + lib.optionalString a72Cpu8SramDiagnostic "-a72-cpu8-sram" 
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
        LOCALVERSION=
      )
      make "''${kernelMakeFlags[@]}" defconfig
      scripts/kconfig/merge_config.sh \
        -m -O . .config $fragmentInputs
      ${lib.optionalString (consysIdentityOverlay || consysG2bOverlay || consysG2cPatchOverlay || consysG2dPostpatchOverlay || gpuStagedOverlay || gpuFixedOppOverlay || unattendedRecovery) ''
        bash scripts/config --set-str CMDLINE \
          "${kernelCmdline}"
      ''}
      make "''${kernelMakeFlags[@]}" olddefconfig

      test -z "''${NIX_HARDENING_ENABLE:-}"
      # This composition carries a broad, evolving serviceability envelope.
      # Keep the build decisive on the A72 path rather than failing on an
      # unrelated optional collector that an upstream profile deliberately
      # omits.
      grep -Fqx 'CONFIG_ARM64_MT6797_A72_PROVIDER_OWNER=y' .config
      grep -Fqx 'CONFIG_REGULATOR_DA9213_LEGACY_PROVIDER=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_A72_DEFAULT_OFF_BINDER=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_A72_ADMISSION_CONTROLLER=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_A72_ADMISSION_LIVE_TRIGGER=y' .config
      set +e
      # The selected CPU8 profile ends with its own explicit local version;
      # accepting the read-only profile's old value here would reintroduce the
      # exact profile/config mismatch that caused binder -EAGAIN.
      grep -Fqx 'CONFIG_LOCALVERSION="-gemini-a72-admission-live"' .config
      grep -Fqx '# CONFIG_LOCALVERSION_AUTO is not set' .config
      grep -Fqx 'CONFIG_NVMEM_MTK_ATAG_DEVINFO=y' .config
      grep -Fqx 'CONFIG_REGULATOR_DA9213_LEGACY_PROVIDER=y' .config
      # The live-admission profile deliberately publishes the provider owner;
      # its read-only observer was only an old serviceability-profile aid and
      # is not part of the provider-to-binder readiness contract.
      grep -Fqx 'CONFIG_MTK_STP=y' .config
      ! grep -q '^CONFIG_MTK_STP_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_WMT=y' .config
      ! grep -q '^CONFIG_MTK_WMT_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_WMT_INITIAL=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_WMT_INITIAL_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_INVENTORY=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_CORE=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_CORE_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_STP_SESSION=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_CONSYS_STP_SESSION_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_BT_H4_COLLECTOR=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_BT_H4_COLLECTOR_KUNIT_TEST=' .config
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
      ${lib.optionalString consysG2gGnssEndpoint ''
        grep -Fqx 'CONFIG_GNSS=y' .config
        grep -Fqx 'CONFIG_GNSS_MTK_CONSYS=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2G_GNSS_ENDPOINT=y' .config
        ! grep -q '^CONFIG_GNSS_MTK_CONSYS_KUNIT_TEST=' .config
        ! grep -q '^CONFIG_MTK_MT6797_CONSYS_RUNTIME_CONTROLLER_KUNIT_TEST=' .config
      ''}
      ${lib.optionalString consysG2hBtEndpoint ''
        grep -Fqx 'CONFIG_BT=y' .config
        grep -Fqx 'CONFIG_BT_MTK_CONSYS=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2H_BT_ENDPOINT=y' .config
        grep -Fqx 'CONFIG_CRYPTO_CMAC=y' .config
        grep -Fqx 'CONFIG_CRYPTO_AES=y' .config
      ''}
      ${lib.optionalString wifiW0Observe ''
        grep -E '^CONFIG_MTK_MT6797_WIFI_AHB_[A-Z0-9_]+=' .config || true
        grep -Fqx 'CONFIG_MTK_MT6797_WIFI_AHB_WCIR_OBSERVE=y' .config
        ! grep -q '^CONFIG_MTK_MT6797_WIFI_AHB_WCIR_KUNIT_TEST=' .config
      ''}
      ${lib.optionalString wifiW1FirmwareReadyProof ''
        grep -E '^CONFIG_(MTK_MT6797_WIFI_AHB_[A-Z0-9_]+|CRYPTO_SHA256)=' .config || true
        grep -Fqx 'CONFIG_MTK_MT6797_WIFI_AHB_W1_FIRMWARE_PREFLIGHT=y' .config
        grep -Fqx 'CONFIG_CRYPTO_SHA256=y' .config
        ! grep -q '^CONFIG_MTK_MT6797_WIFI_AHB_W1_FIRMWARE_KUNIT_TEST=' .config
        ! grep -q '^CONFIG_MTK_MT6797_BTIF_TRANSPORT=' .config
      ''}
      ${lib.optionalString wifiW2NicCapability ''
        grep -Fqx 'CONFIG_MTK_MT6797_WIFI_AHB_W2_NIC_CAPABILITY=y' .config
        ! grep -q '^CONFIG_MTK_MT6797_WIFI_AHB_W1_FIRMWARE_KUNIT_TEST=' .config
        ! grep -q '^CONFIG_MTK_MT6797_BTIF_TRANSPORT=' .config
      ''}
      ${lib.optionalString wifiW4Connect ''
        grep -Fqx 'CONFIG_MTK_MT6797_WIFI_AHB_W3_SESSION=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_WIFI_AHB_W4_PLATFORM=y' .config
        grep -Fqx 'CONFIG_CFG80211=y' .config
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
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_INVENTORY=y' .config
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_PIO=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_BTIF_PIO_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_PIO_PLATFORM=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_BTIF_PIO_PLATFORM_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_MTK_MT6797_BTIF_STP_BOOTSTRAP=y' .config
      ! grep -q '^CONFIG_MTK_MT6797_BTIF_STP_BOOTSTRAP_KUNIT_TEST=' .config
      grep -Fqx 'CONFIG_GNSS=y' .config
      grep -Fqx 'CONFIG_GNSS_MTK_CONSYS=y' .config
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
      grep -A20 -F 'consys: consys@18070000 {' \
        arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts \
        | grep -Fq 'status = "disabled";'
      grep -A12 -F 'btif: serial@1100c000 {' \
        arch/arm64/boot/dts/mediatek/mt6797.dtsi \
        | grep -Fq 'compatible = "mediatek,mt6797-btif",'
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
      grep -Fqx '# CONFIG_MTK_MT6797_A72_POWER is not set' .config
      grep -Fqx '# CONFIG_MTK_MT6797_DVFSP_RESOURCE_OWNER is not set' .config
      ${lib.optionalString a72Cpu8SramDiagnostic ''
        grep -Fqx 'CONFIG_MEDIATEK_WATCHDOG_RECOVERY_TAKEOVER=y' .config
        grep -Fqx 'CONFIG_PSTORE_GEMINI_TRANSITION_LEDGER=y' .config
        grep -Fqx 'CONFIG_PSTORE_GEMINI_ADMISSION_TRACE=y' .config
        grep -Fqx 'CONFIG_CMDLINE_FORCE=y' .config
        grep -Fqx 'CONFIG_ARM64_MT6797_A72_PROVIDER_OWNER=y' .config
        grep -Fqx 'CONFIG_REGULATOR_DA9213_LEGACY_PROVIDER=y' .config
        grep -Fqx 'CONFIG_ARM64_MT6797_A72_CAPABILITY_PROFILE=y' .config
        grep -Fqx 'CONFIG_ARM64_MT6797_A72_P30_PROTOCOL_MODEL=y' .config
        grep -Fqx 'CONFIG_ARM64_MT6797_A72_P24_TRANSACTION_OWNER_MODEL=y' .config
        grep -Fqx 'CONFIG_ARM64_MT6797_A72_DERIVED_ADMISSION=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_PLATFORM_STATE=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_PLATFORM_SNAPSHOT_OBSERVER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_DVFSP_CLOCK_BACKEND=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_DVFSP_BIGIDVFS_BACKEND=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_BIGIDVFS_SRAM_OWNER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_TRANSITION_EXECUTOR=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_DEFAULT_OFF_BINDER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_PHYSICAL_SOURCE_OBSERVER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_ADMISSION_CONTROLLER=y' .config
        grep -Fqx 'CONFIG_MTK_MT6797_A72_ADMISSION_LIVE_TRIGGER=y' .config
        grep -Fqx '# CONFIG_KUNIT is not set' .config
        ! grep -Fqx 'CONFIG_HOTPLUG_SPLIT_STARTUP=y' .config
        grep -Fq '#define MT6797_A72_ADMISSION_CPU 8' \
          drivers/soc/mediatek/mt6797-a72-admission-controller.c
        ! grep -Fq 'CPU9 admission controller' \
          drivers/soc/mediatek/mt6797-a72-admission-controller.c
      ''}
      grep -Eq '^CONFIG_CMDLINE=".*maxcpus=${a72MaxCpus}( |")' .config
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
          grep -Fqx 'CONFIG_CMDLINE="${kernelCmdline}"' .config
        ''
        else ''
          grep -Fqx 'CONFIG_PSTORE_GEMINI_ARM64_ENTRY_LEDGER=y' .config
          grep -Fqx '# CONFIG_PSTORE_GEMINI_POST_RAMOOPS_CHECKPOINT is not set' .config
          grep -Fqx 'CONFIG_CMDLINE="${kernelCmdline}"' .config
        ''
      }
      set -e
      runHook postConfigure
    '';

    buildPhase = ''
      runHook preBuild
      export SOURCE_DATE_EPOCH=1783123200
      unset NIX_LDFLAGS
      kernelMakeFlags=(
        ARCH=arm64
        CROSS_COMPILE=aarch64-unknown-linux-gnu-
        LOCALVERSION=
      )
      make -j"$NIX_BUILD_CORES" "''${kernelMakeFlags[@]}" \
        Image Image.gz dtbs
      test "$(make "''${kernelMakeFlags[@]}" -s kernelrelease)" = \
        "7.1.3-gemini-a72-admission-live"
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
        test "$(sha256sum "$out/mt6797-gemini-pda-thermal-hall-observe.dtbo" | cut -d' ' -f1)" = \
          2fd591269a217634cc9bd6b1aa3afa7702f08c2bbef0dad2f673e278f2cda28d
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
      ${lib.optionalString a72Cpu8SramDiagnostic ''
        cp arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-a72-admission.dtbo \
          "$out/mt6797-gemini-pda-a72-admission.dtbo"
        test -s "$out/mt6797-gemini-pda-a72-admission.dtbo"
      ''}
      cp .config "$out/kernel.config"
      cp System.map vmlinux "$out/"

	  # Most variants retain ixoo's reviewed base DT byte-for-byte.  The A72
	  # candidate intentionally adds two private retained pages, so its source
	  # assertions replace that stale whole-DTB fingerprint.
	  ${lib.optionalString (!a72Cpu8SramDiagnostic) ''
	    test "$(sha256sum "$out/base.dtb" | cut -d' ' -f1)" = \
	      ${baseDtbSha256}
	  ''}
	  ${lib.optionalString a72Cpu8SramDiagnostic ''
	    grep -Fq 'a72-transition-ledger@444f1000' \
	      arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts
	    grep -Fq 'gemini,initialize-empty' \
	      arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts
	  ''}
      cp .config "$out/kernel.config"
      cp System.map vmlinux "$out/"

      # Device Tree output is compiler-independent and must match the reviewed
      # Reviewed tree: ixoo's hardware-passed DT plus dormant CONSYS and BTIF.
      test "$(sha256sum "$out/base.dtb" | cut -d' ' -f1)" = \
        ${baseDtbSha256}
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
    buildPkgs.runCommand "gemini-ixoo-serviceability-dtb${lib.optionalString usbHostOverlay "-usb11-host"}${lib.optionalString consysIdentityOverlay "-consys-identity"}${lib.optionalString platformEnablement "-platform"}${lib.optionalString displayOverlay "-display"}${lib.optionalString audioOverlay "-audio"}${lib.optionalString powerObserveOverlay "-power-observe"}${lib.optionalString powerObservePreflight "-power-preflight"}${lib.optionalString unattendedRecovery "-unattended-recovery"}${lib.optionalString inputObserveOverlay "-input-observe"}${lib.optionalString thermalHallObserveOverlay "-thermal-hall-observe"}${lib.optionalString touchscreenActivationOverlay "-touchscreen-active"}${lib.optionalString fgadcActivationOverlay "-fgadc-active"}${lib.optionalString deviceActivationOverlay "-device-activation"}" {
      nativeBuildInputs = [buildPkgs.bash buildPkgs.dtc buildPkgs.python3 buildPkgs.binutils];
    buildPkgs.runCommand "gemini-ixoo-serviceability-dtb${lib.optionalString usbHostOverlay "-usb11-host"}${lib.optionalString consysIdentityOverlay "-consys-identity"}${lib.optionalString consysG2bOverlay "-consys-g2b"}${lib.optionalString consysG2cPatchOverlay "-consys-g2c-patch"}${lib.optionalString consysG2dPostpatchOverlay "-consys-g2d-postpatch"}${lib.optionalString wifiW0Observe "-wifi-w0"}${lib.optionalString wifiW1FirmwareReadyProof (if wifiW2NicCapability || wifiW4Connect then "" else "-wifi-w1-ready")}${lib.optionalString wifiW2NicCapability "-wifi-w2-capability"}${lib.optionalString wifiW4Connect "-wifi-w4-connect"}${lib.optionalString gpuStagedOverlay "-gpu-staged"}${lib.optionalString gpuFixedOppOverlay "-gpu-fixed-opp"}${lib.optionalString platformEnablement "-platform"}${lib.optionalString displayOverlay "-display"}${lib.optionalString audioOverlay "-audio"}${lib.optionalString powerObserveOverlay "-power-observe"}${lib.optionalString powerObservePreflight "-power-preflight"}${lib.optionalString unattendedRecovery "-unattended-recovery"}${lib.optionalString inputObserveOverlay "-input-observe"}${lib.optionalString thermalHallObserveOverlay "-thermal-hall-observe"}${lib.optionalString touchscreenActivationOverlay "-touchscreen-active"}${lib.optionalString fgadcActivationOverlay "-fgadc-active"}${lib.optionalString deviceActivationOverlay "-device-activation"}" {
      nativeBuildInputs = [buildPkgs.bash buildPkgs.dtc];
    } ''
      mkdir -p "$out"
      cp -R ${ixoo-candidate} candidate
      chmod -R u+w candidate
      providerBuilder=candidate/experiments/2026-08-17-mainline-da921x-readonly-provider-baseline/scripts/build-provider-dtb.sh
      substituteInPlace "$providerBuilder" \
        --replace-fail \
          'BASE_DTB_SHA256=380205e0546c1b87f4ce6b4c34fcd734a22dc42e3b1c3145044d396a16e00709' \
	          'BASE_DTB_SHA256=${if a72Cpu8SramDiagnostic then admissionBaseDtbSha256 else baseDtbSha256}' \
        --replace-fail \
          'OUTPUT_DTB_SHA256=d7dba05efa272c8264c8ea15c776fb88c21a0012603214b49dfd9e2893e87d48' \
	          'OUTPUT_DTB_SHA256=${if a72Cpu8SramDiagnostic then admissionServiceabilityBaseDtbSha256 else serviceabilityBaseDtbSha256}'
      substituteInPlace "$providerBuilder" \
        --replace-fail \
          $'\tfdtput -d "$temporary" "$AW9523" "$property"' \
          $'\tif fdtget "$temporary" "$AW9523" "$property" >/dev/null 2>&1; then\n\t\tfdtput -d "$temporary" "$AW9523" "$property"\n\tfi'
      bash "$providerBuilder" \
        --base-dtb ${kernel}/base.dtb \
        --output "$out/gemini-base.dtb" \
        > "$out/VALIDATION"
      chmod 0644 "$out/gemini-base.dtb"
      test "$(sha256sum "$out/gemini-base.dtb" | cut -d' ' -f1)" = \
	        ${if a72Cpu8SramDiagnostic then admissionServiceabilityBaseDtbSha256 else serviceabilityBaseDtbSha256}
      test "$(fdtget "$out/gemini-base.dtb" /consys@18070000 status)" = disabled
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
          ${lib.optionalString consysG2gGnssEndpoint ''
            fdtput "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              mediatek,experimental-g2g-gnss-endpoint
            fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              | grep -Fqx 'mediatek,experimental-g2g-gnss-endpoint'
          ''}
          ${lib.optionalString consysG2hBtEndpoint ''
            fdtput "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              mediatek,experimental-g2h-bt-endpoint
            fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              | grep -Fqx 'mediatek,experimental-g2h-bt-endpoint'
          ''}
          ${lib.optionalString wifiW0Observe ''
            test "$(fdtget "$out/gemini-consys.dtb" /wifi@180f0000 compatible)" = \
              mediatek,wifi
            test "$(fdtget "$out/gemini-consys.dtb" /wifi@180f0000 status)" = disabled
            fdtget -p "$out/gemini-consys.dtb" /wifi@180f0000 | grep -Fqx interrupts
            fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              | grep -Fqx 'mediatek,experimental-wifi-wcir-observe'
          ''}
          ${lib.optionalString wifiW1FirmwareReadyProof ''
            fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              | grep -Fqx 'mediatek,experimental-wifi-w1-firmware-preflight'
          ''}
          ${lib.optionalString wifiW2NicCapability ''
            fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              | grep -Fqx 'mediatek,experimental-wifi-w2-nic-capability'
          ''}
          ${lib.optionalString wifiW4Connect ''
            # W0's overlay supplies the vendor HIF node/IRQ.  W4 is the only
            # profile that turns that exact portal into the retained owner.
            # Reuse the G2d controller and the explicitly named PALDO rails.
            # W4 binds on the first compatible; retain the vendor generic
            # compatible as a fallback because the G2d W0/W1 transaction
            # resolves this same live portal by "mediatek,wifi".
            fdtput -t s "$out/gemini-consys.dtb" /wifi@180f0000 compatible \
              mediatek,mt6797-wifi-ahb-w4-platform mediatek,wifi
            # G2d performs resource/EMI preflight only; W4 owns start, IRQ, and stop.
            fdtput "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
              mediatek,experimental-wifi-w4-retained-owner
            fdtput -t s "$out/gemini-consys.dtb" /wifi@180f0000 status okay
            fdtput -t s "$out/gemini-consys.dtb" /wifi@180f0000 interrupt-names wifi
            fdtput -t x "$out/gemini-consys.dtb" /wifi@180f0000 \
              mediatek,controller 0x90
	    # W1's EMI copy is issued by W4 in the retained path.  Give that
	    # actual consumer the same already-claimed provider as G2d; the EMI
	    # API deliberately resolves ownership from the calling DT node.
	    w4_emi_provider="$(fdtget -t x "$out/gemini-consys.dtb" \
	      /consys-g2d-postpatch-owner mediatek,emi-mpu)"
	    test -n "$w4_emi_provider"
	    fdtput -t x "$out/gemini-consys.dtb" /wifi@180f0000 \
	      mediatek,emi-mpu "$w4_emi_provider"
            fdtput -t x "$out/gemini-consys.dtb" /wifi@180f0000 \
              bt-paldo-supply 0x53
            fdtput -t x "$out/gemini-consys.dtb" /wifi@180f0000 \
              wifi-paldo-supply 0x54
            fdtput "$out/gemini-consys.dtb" /wifi@180f0000 \
              mediatek,experimental-wifi-w4-platform
            # W1/W2 execute with W4 as owner, and W3 gates the IRQ lifetime.
            fdtput "$out/gemini-consys.dtb" /wifi@180f0000 \
              mediatek,experimental-wifi-w1-firmware-preflight
            fdtput "$out/gemini-consys.dtb" /wifi@180f0000 \
              mediatek,experimental-wifi-w2-nic-capability
            fdtput "$out/gemini-consys.dtb" /wifi@180f0000 \
              mediatek,experimental-wifi-w3-session
            test "$(fdtget "$out/gemini-consys.dtb" /wifi@180f0000 compatible)" = \
              'mediatek,mt6797-wifi-ahb-w4-platform mediatek,wifi'
            test "$(fdtget "$out/gemini-consys.dtb" /wifi@180f0000 status)" = okay
            test "$(fdtget "$out/gemini-consys.dtb" /wifi@180f0000 interrupt-names)" = wifi
            test "$(fdtget -t x "$out/gemini-consys.dtb" /wifi@180f0000 reg)" = \
              '0 180f0000 0 1100'
	    test "$(fdtget -t x "$out/gemini-consys.dtb" /wifi@180f0000 \
	      mediatek,emi-mpu)" = "$w4_emi_provider"
            test "$(fdtget -t x "$out/gemini-consys.dtb" /wifi@180f0000 interrupts)" = \
              '0 11b 8'
            fdtget -p "$out/gemini-consys.dtb" /wifi@180f0000 | \
              grep -Fqx 'mediatek,experimental-wifi-w4-platform'
            fdtget -p "$out/gemini-consys.dtb" /wifi@180f0000 | \
              grep -Fqx 'mediatek,experimental-wifi-w1-firmware-preflight'
            fdtget -p "$out/gemini-consys.dtb" /wifi@180f0000 | \
              grep -Fqx 'mediatek,experimental-wifi-w2-nic-capability'
            fdtget -p "$out/gemini-consys.dtb" /wifi@180f0000 | \
              grep -Fqx 'mediatek,experimental-wifi-w3-session'
            fdtget -p "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner | \
              grep -Fqx 'mediatek,experimental-wifi-w4-retained-owner'
          ''}
          # PIO has no child endpoint and neither owner declares a function
          # client. The kernel config also excludes BTIF transport/HCI.
          test -z "$(fdtget -l "$out/gemini-consys.dtb" /serial@1100c000)"
          ! fdtget "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner \
            mediatek,function-control >/dev/null 2>&1
          echo 'consys-g2d-overlay=passed' >> "$out/VALIDATION"
          echo 'consys-g2d-owner=exclusive-g2c-disabled' >> "$out/VALIDATION"
          echo 'consys-g2d-radio-clients=disabled' >> "$out/VALIDATION"
          ${lib.optionalString wifiW0Observe "echo 'wifi-w0=cmd53-wcir-only' >> \"$out/VALIDATION\""}
          ${lib.optionalString wifiW1FirmwareReadyProof "echo 'wifi-w1=full-firmware-start-ready-irq-netdev-fenced' >> \"$out/VALIDATION\""}
          ${lib.optionalString wifiW2NicCapability "echo 'wifi-w2=nic-capability-fresh-rx1-irq-no-netdev' >> \"$out/VALIDATION\""}
          ${lib.optionalString wifiW4Connect "echo 'wifi-w4=retained-controller-w3-irq-cfg80211-open-auth-assoc-netdev' >> \"$out/VALIDATION\""}
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
            mediatek,mt6797-mt6351-sound
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
          # This source-locked overlay enables only the existing AUXADC,
          # thermal controller, and GPIO66 Hall key. It declares no external
          # sensor, power rail, wake source, or SCP path.
          fdtoverlay \
            -i "$out/gemini.dtb" \
            -o "$out/gemini-thermal-hall-observe.dtb" \
            ${kernel}/mt6797-gemini-pda-thermal-hall-observe.dtbo
          test "$(fdtget "$out/gemini-thermal-hall-observe.dtb" /adc@11001000 status)" = okay
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
      ${lib.optionalString md1LkHandoffProbe ''
        # The source overlay is deliberately disabled.  This profile makes one
        # explicit, reviewable transition to okay; its separate built-in
        # module parameter remains the second required gate.  The driver maps
        # only LK metadata and unmaps before any MD1 control operation.
        fdtoverlay \
          -i "$out/gemini.dtb" \
          -o "$out/gemini-md1-lk-handoff.dtb" \
          ${kernel}/mt6797-gemini-pda-md1-lk-handoff-probe.dtbo
        test "$(fdtget "$out/gemini-md1-lk-handoff.dtb" /modem-lk-handoff-probe status)" = disabled
        test "$(fdtget "$out/gemini-md1-lk-handoff.dtb" /modem-lk-handoff-probe compatible)" = \
          mediatek,mt6797-md1-lk-handoff-probe
        fdtget -p "$out/gemini-md1-lk-handoff.dtb" /modem-lk-handoff-probe \
          | grep -Fqx 'mediatek,experimental-md1-lk-handoff-probe'
        fdtget -p "$out/gemini-md1-lk-handoff.dtb" /modem-lk-handoff-probe \
          | grep -Fqx 'mediatek,stage-lk-handoff-read-only'
        fdtput -t s "$out/gemini-md1-lk-handoff.dtb" /modem-lk-handoff-probe status okay
        test "$(fdtget "$out/gemini-md1-lk-handoff.dtb" /modem-lk-handoff-probe status)" = okay
        cp "$out/gemini-md1-lk-handoff.dtb" "$out/gemini.dtb"
        echo 'md1-lk-handoff=dt-gate-okay cmdline-gate-required read-only-only' >> "$out/VALIDATION"
      ''}
      ${lib.optionalString md1BootStatusObserve ''
        # The source overlay is disabled too. This is a separate, visible
        # transition and the built-in parameter remains the second gate. The
        # driver does only the vendor's three AP-side reads of each word, then
        # captures AP CCIF RCHNUM raw beside the already passive BUSY/ACK read.
        fdtoverlay \
          -i "$out/gemini.dtb" \
          -o "$out/gemini-md1-boot-status.dtb" \
          ${kernel}/mt6797-gemini-pda-md1-boot-status-observe.dtbo
        test "$(fdtget "$out/gemini-md1-boot-status.dtb" /modem-boot-status@10201300 status)" = disabled
        test "$(fdtget "$out/gemini-md1-boot-status.dtb" /modem-boot-status@10201300 compatible)" = \
          mediatek,mt6797-md1-boot-status-observe
        fdtget -p "$out/gemini-md1-boot-status.dtb" /modem-boot-status@10201300 \
          | grep -Fqx 'mediatek,experimental-md1-boot-status'
        fdtput -t s "$out/gemini-md1-boot-status.dtb" /modem-boot-status@10201300 status okay
        test "$(fdtget "$out/gemini-md1-boot-status.dtb" /modem-boot-status@10201300 status)" = okay
        cp "$out/gemini-md1-boot-status.dtb" "$out/gemini.dtb"
        echo 'md1-boot-status=dt-gate-okay cmdline-gate-required three-reads-per-word passive-ap-rchnum-raw no-write-no-interpretation' >> "$out/VALIDATION"
      ''}
      ${lib.optionalString md1RemapObserve ''
        # The source overlay remains disabled.  Making it okay here is one
        # visible gate; the driver requires its separate default-false cmdline
        # parameter and accepts only the already validated LK plan.
        fdtoverlay \
          -i "$out/gemini.dtb" \
          -o "$out/gemini-md1-remap-observe.dtb" \
          ${kernel}/mt6797-gemini-pda-md1-remap-observe.dtbo
        test "$(fdtget "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 status)" = disabled
        test "$(fdtget "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 compatible)" = \
          mediatek,mt6797-md1-remap-observe
        test "$(fdtget -t x "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 reg)" = \
          '0 10001000 0 1000'
        fdtget -p "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 \
          | grep -Fqx 'mediatek,experimental-md1-remap-observe'
        fdtget -p "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 \
          | grep -Fqx 'mediatek,stage-lk-remap-observe-read-only'
        fdtput -t s "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 status okay
        test "$(fdtget "$out/gemini-md1-remap-observe.dtb" /modem-remap-observe@10001000 status)" = okay
        cp "$out/gemini-md1-remap-observe.dtb" "$out/gemini.dtb"
        echo 'md1-remap-observe=dt-gate-okay cmdline-gate-required five-infracfg-reads no-write-no-ownership' >> "$out/VALIDATION"
      ''}
      ${lib.optionalString (touchscreenActivationOverlay || fgadcActivationOverlay) ''
        # Explicit negative contracts: this full-NixOS baseline does not pull
        # in the later MicroSD, GPU, or radio bring-up experiments.
        test "$(fdtget "$out/gemini.dtb" /mmc@11240000 status)" = disabled
        test "$(fdtget "$out/gemini.dtb" /gpu@13040000 status)" = disabled
        test "$(fdtget "$out/gemini.dtb" /consys@18070000 status)" = disabled
        test "$(fdtget "$out/gemini.dtb" /serial@1100c000 status)" = disabled
      ''}
      ${lib.optionalString a72Cpu8SramDiagnostic ''
        fdtoverlay \
          -i "$out/gemini.dtb" \
          -o "$out/gemini-a72-cpu8-sram.dtb" \
          ${kernel}/mt6797-gemini-pda-a72-admission.dtbo
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /a72-binder compatible)" = \
          mediatek,mt6797-a72-binder
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /a72-binder status)" = okay
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /a72-admission-controller compatible)" = \
          mediatek,mt6797-a72-admission-controller
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /a72-admission-controller status)" = okay
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-admission-trace@444f0000 compatible)" = \
          planet,gemini-a72-admission-trace
        test "$(fdtget -t x "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/ramoops@44410000 reg)" = \
          '0 44410000 0 e0000'
        test "$(fdtget -t x "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-admission-trace@444f0000 reg)" = \
          '0 444f0000 0 1000'
	        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-transition-ledger@444f1000 compatible)" = \
	          planet,gemini-a72-transition-ledger
	        test "$(fdtget -t x "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-transition-ledger@444f1000 reg)" = \
	          '0 444f1000 0 1000'
	        test "$(fdtget -t x "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/memory@444f2000 reg)" = \
	          '0 444f2000 0 e000'
	        fdtget -p "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-admission-trace@444f0000 \
	          | grep -Fqx no-map
	        fdtget -p "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-transition-ledger@444f1000 \
	          | grep -Fqx no-map
	        fdtget -p "$out/gemini-a72-cpu8-sram.dtb" /reserved-memory/a72-transition-ledger@444f1000 \
	          | grep -Fqx gemini,initialize-empty
        ramoops_start=$((0x44410000))
        ramoops_size=$((0x000e0000))
        trace_start=$((0x444f0000))
        trace_size=$((0x00001000))
	        ledger_start=$((0x444f1000))
	        ledger_size=$((0x00001000))
	        remainder_start=$((0x444f2000))
	        test $((ramoops_start + ramoops_size)) -le "$trace_start"
	        test $((trace_start + trace_size)) -le "$ledger_start"
	        test $((ledger_start + ledger_size)) -le "$remainder_start"
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /consys@18070000 status)" = disabled
        test "$(fdtget "$out/gemini-a72-cpu8-sram.dtb" /serial@1100c000 status)" = disabled
        cp "$out/gemini-a72-cpu8-sram.dtb" "$out/gemini.dtb"
        # The architecture-owned late-CPU profile deliberately publishes no
        # token until this static record verifies the *running* IKCONFIG,
        # GNU build ID, and forced command line.  It is composed after every
        # diagnostic overlay, while the DTB is still static at boot.
        grep -Fq '0x5968c24f1904c055, 0x9dea25480c41fbc7,' \
          ${linux-gemini}/arch/arm64/kernel/mt6797_psci.c
        python3 ${./a72-provenance.py} \
          --dtb "$out/gemini.dtb" \
          --vmlinux ${kernel}/vmlinux \
          --kernel-config ${kernel}/kernel.config \
          --image ${kernel}/Image \
          --cmdline '${kernelCmdline}' \
          --source-revision '${kernelRevision}' \
          --fdtput "$(command -v fdtput)" \
          --fdtget "$(command -v fdtget)" \
          | tee -a "$out/VALIDATION"
        test "$(fdtget "$out/gemini.dtb" /chosen/gemini-late-cpu-provenance compatible)" = \
          planet,gemini-a72-runtime-binding-v1
        test "$(fdtget "$out/gemini.dtb" /chosen/gemini-late-cpu-provenance profile-id)" = \
          mt6797-a53-a72-a41-v7
        echo 'a72-cpu8-sram-diagnostic=overlay-composed cpu8-only cpu9-veto=maxcpus-9' \
          >> "$out/VALIDATION"
      ''}
      cat ${kernel}/Image.gz "$out/gemini.dtb" > "$out/Image.gz-dtb"
      (cd "$out" && sha256sum gemini-base.dtb gemini.dtb ${
        if thermalHallObserveOverlay
        then "gemini-keyboard.dtb gemini-input-observe.dtb gemini-thermal-hall-observe.dtb "
        else if inputObserveOverlay
        then "gemini-keyboard.dtb gemini-input-observe.dtb "
        else ""
      }${lib.optionalString touchscreenActivationOverlay "gemini-touchscreen-active.dtb "}${lib.optionalString fgadcActivationOverlay "gemini-fgadc-active.dtb "}${lib.optionalString deviceActivationOverlay "gemini-touchscreen-active.dtb gemini-fgadc-active.dtb gemini-device-activation.dtb "}${lib.optionalString a72Cpu8SramDiagnostic "gemini-a72-cpu8-sram.dtb "}Image.gz-dtb) > "$out/SHA256SUMS"
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
      // lib.optionalAttrs wifiW4Connect {
        iw = crossPkgs.pkgsStatic.iw;
        wpaSupplicant = crossPkgs.pkgsStatic.wpa_supplicant;
        iperf3 = crossPkgs.pkgsStatic.iperf3;
        wirelessRegdb = buildPkgs.wireless-regdb;
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
      ${lib.optionalString wifiW1FirmwareReadyProof ''
        # W1 requests precisely this bare vendor name. Pin before boot, then
        # make the initramfs fail to build if the staged bytes ever drift.
        cp ${../blobs/WIFI_RAM_CODE_6797} root/lib/firmware/WIFI_RAM_CODE_6797
        test "$(stat -c %s root/lib/firmware/WIFI_RAM_CODE_6797)" = 411632
        test "$(sha256sum root/lib/firmware/WIFI_RAM_CODE_6797 | cut -d' ' -f1)" = \
          a69383d74d829430487c39eef6b5e281b25f901595c903a632a10aa8631426dd
      ''}
      cp "$busybox/bin/busybox" root/bin/busybox
      ${lib.optionalString wifiW4Connect ''
        # Real static WLAN userspace for the boot-active W4 candidate.  The
        # signed regdb is firmware data, while iw/wpa_supplicant/iperf3 let the
        # next hardware pass scan, associate and measure without a new image.
        mkdir -p root/lib/firmware
        cp "$wirelessRegdb/lib/firmware/regulatory.db" root/lib/firmware/regulatory.db
        cp "$wirelessRegdb/lib/firmware/regulatory.db.p7s" root/lib/firmware/regulatory.db.p7s
        cp "$iw/bin/iw" root/bin/iw
        cp "$wpaSupplicant/bin/wpa_supplicant" root/bin/wpa_supplicant
        cp "$iperf3/bin/iperf3" root/bin/iperf3
        test -s root/lib/firmware/regulatory.db
        test -s root/lib/firmware/regulatory.db.p7s
        for tool in iw wpa_supplicant iperf3; do
          readelf -h "root/bin/$tool" | grep -Fq 'Machine:                           AArch64'
          ! readelf -l "root/bin/$tool" | grep -Fq 'Requesting program interpreter'
          ! readelf -d "root/bin/$tool" | grep -Fq '(NEEDED)'
        done
      ''}
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
      ${lib.optionalString a72Cpu8SramDiagnostic ''
        cat > root/bin/a72-cpu8-sram-diagnostic <<'A72_CPU8_SRAM_DIAGNOSTIC'
        #!/bin/busybox sh
        # One exact CPU8 request after the existing watchdog, gadget, RTL and
        # eMMC serviceability gates.  Every refusal is terminal: no retry,
        # CPU_OFF, rollback, reboot, radio action or watchdog lease extension.
        export PATH=/bin
        record() {
          line="$*"
          echo "GEMINI_A72_CPU8: $line" >> /run/a72-cpu8-sram-diagnostic.log
          echo "<6>GEMINI_A72_CPU8: $line" > /dev/kmsg 2>/dev/null || true
          echo "GEMINI_A72_CPU8: $line" >> /run/probe-status 2>/dev/null || true
        }
        fence() {
          record "result=fence reason=$1 retry=0 cpu_off=0 rollback=0 watchdog=existing-petter-lease-unchanged"
          exit 1
        }
        wait_for_serviceability() {
          attempt=0
          while [ "$attempt" -lt 65 ]; do
            if grep -Fq 'unattended_recovery=healthy watchdog_userspace=petting' /run/probe-status 2>/dev/null &&
               grep -Fq 'usb0=ready address=10.15.19.82/24 access=ssh:22' /run/probe-status 2>/dev/null &&
               grep -Fq 'usb-host-net=ready iface=' /run/probe-status 2>/dev/null &&
               grep -Fq 'emmc=present' /run/storage-probe 2>/dev/null; then
              return 0
            fi
            attempt=$((attempt + 1))
            sleep 1
          done
          return 1
        }
        cpu8_irq_total() {
          awk 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "CPU8") column = i; next }
               column && $1 ~ /:$/ { value = $column; gsub(/[^0-9]/, "", value); sum += value }
               END { if (!column) exit 1; print sum + 0 }' /proc/interrupts
        }

        record "stage=begin ixoo=4c114301 provider_owner=required sram_p28_diagnostic=enabled cpu8_only=1 cpu9_veto=maxcpus-9"
        wait_for_serviceability || fence serviceability-gate
        grep -Eq '(^| )maxcpus=9( |$)' /proc/cmdline || fence cmdline-maxcpus
        online=$(cat /sys/devices/system/cpu/online 2>/dev/null || true)
        [ "$online" = 0-7 ] || fence cpu-online-precondition
        if [ -e /sys/devices/system/cpu/cpu9/online ]; then
          [ "$(cat /sys/devices/system/cpu/cpu9/online 2>/dev/null || true)" = 0 ] || fence cpu9-not-offline
          cpu9_state=offline
        else
          cpu9_state=absent-by-maxcpus
        fi
        status=
        attempt=0
        while [ "$attempt" -lt 30 ] && [ -z "$status" ]; do
          for candidate in /sys/devices/platform/*/gemini_admission/status; do
            [ -r "$candidate" ] || continue
            status=$candidate
            break
          done
          [ -n "$status" ] || { attempt=$((attempt + 1)); sleep 1; }
        done
        [ -n "$status" ] || fence admission-status-missing
        trigger=$(dirname "$status")/trigger
        [ -w "$trigger" ] || fence admission-trigger-missing
        pre=$(cat "$status" 2>/dev/null || true)
        record "stage=pre online=$online cpu9=$cpu9_state status=$pre"
        # The kernel status ABI has a stable set of fields but does not promise
        # a field order.  Check each admission invariant independently so a
        # harmless telemetry reordering cannot suppress the sole live token.
        for required in \
          'state=armed' \
          'binder_snapshot_ret=0' \
          'trigger_consumed=0' \
          'trigger_executions=0' \
          'cpu_requests=0' \
          'cpu9_requests=0' \
          'cpu_off_requests=0 retries=0'; do
          printf '%s\n' "$pre" | grep -Fq "$required" || fence admission-not-armed
        done
        record "stage=pre-provider-binder-ready binder_snapshot_ret=0 trigger=not-consumed"
        # /sys is mounted read-only for the probe.  The admission ABI is a
        # deliberate exception: if that was its original state, make one
        # short rw window for the sole token and restore ro before examining
        # its terminal result.  No other sysfs write is in this program.
        sysfs_was_ro=0
        if awk '$2 == "/sys" && $3 == "sysfs" {
                  n = split($4, options, ",");
                  for (i = 1; i <= n; i++) if (options[i] == "ro") ro = 1;
                  exit
                }
                END { exit ro ? 0 : 1 }' /proc/mounts; then
          sysfs_was_ro=1
          mount -o remount,rw /sys || fence sysfs-remount-rw
        fi
        # This is the sole token write and the only CPU request path.
        write_rc=0
        printf 'run-a72-admission-20260828-a\n' > "$trigger" || write_rc=$?
        restore_rc=0
        if [ "$sysfs_was_ro" -eq 1 ]; then
          mount -o remount,ro /sys || restore_rc=$?
        fi
        post=$(cat "$status" 2>/dev/null || true)
        record "stage=terminal trigger_write_rc=$write_rc sysfs_restore_rc=$restore_rc status=$post"
        [ "$restore_rc" -eq 0 ] || fence sysfs-remount-ro
        [ "$write_rc" -eq 0 ] || fence trigger-write
        case "$post" in
          *'trigger_consumed=1'*'trigger_executions=1'*'core_consumed=1'*'cpu_requests=1'*'cpu9_requests=0'*'cpu_off_requests=0 retries=0'*) ;;
          *) fence terminal-accounting ;;
        esac
        case "$post" in
          *'operation_ret=0'*) ;;
          *)
            record "result=terminal-failure distinction=sram-p28-or-earlier cpu8_online=not-claimed no_auto_rollback=1"
            exit 1
            ;;
        esac
        online=$(cat /sys/devices/system/cpu/online 2>/dev/null || true)
        [ "$online" = 0-8 ] || fence cpu8-not-online
        [ ! -e /sys/devices/system/cpu/cpu9/online ] ||
          [ "$(cat /sys/devices/system/cpu/cpu9/online 2>/dev/null || true)" = 0 ] || fence cpu9-online-post
        midr_path=$(find /sys/devices/system/cpu/cpu8 -type f -name midr_el1 -print 2>/dev/null | head -n 1)
        [ -n "$midr_path" ] || fence cpu8-midr-missing
        midr=$(cat "$midr_path" 2>/dev/null || true)
        case "$midr" in
          *d08*|*D08*) ;;
          *) fence cpu8-not-cortex-a72 ;;
        esac
        irq_before=$(cpu8_irq_total) || fence cpu8-interrupt-column-missing
        timeout 5 taskset -c 8 sh -c 'i=0; value=0; while [ "$i" -lt 200000 ]; do value=$((value + i)); i=$((i + 1)); done; printf "%s\\n" "$value" > /run/a72-cpu8-stress.result' || fence cpu8-bounded-stress
        [ -s /run/a72-cpu8-stress.result ] || fence cpu8-stress-proof-missing
        irq_after=$(cpu8_irq_total) || fence cpu8-interrupt-post-missing
        [ "$irq_after" -gt "$irq_before" ] || fence cpu8-interrupt-stalled
        record "result=pass cpu8_online=1 midr=$midr online=$online cpu9=offline-or-absent cache_coherency=cpu8-affine-bounded-stress interrupt_cpu8_before=$irq_before interrupt_cpu8_after=$irq_after retry=0 cpu_off=0 rollback=0 watchdog=petting"
        A72_CPU8_SRAM_DIAGNOSTIC
        chmod 0755 root/bin/a72-cpu8-sram-diagnostic
      ''}
      ${lib.optionalString a72Cpu8Interactive ''
        cat > root/bin/a72-cpu8-control <<'A72_CPU8_CONTROL'
        #!/bin/busybox sh
        # The idle A72 profile never writes sysfs by itself.  This helper keeps
        # every readback in one place and makes the existing ledgered admission
        # ABI an explicit operator action.  P27, the vendor DA9214 BUCKB
        # transcript, P28, SRAM and CPU8 remain one atomic kernel transition.
        export PATH=/bin
        status_path() {
          for path in /sys/devices/platform/*/gemini_admission/status; do
            [ -r "$path" ] && { echo "$path"; return 0; }
          done
          return 1
        }
        dump() {
          status=$(status_path) || { echo "admission_status=missing"; return 1; }
          echo "a72-control=v1 action=read-only-dump"
          echo "cpu_online=$(cat /sys/devices/system/cpu/online 2>/dev/null || echo unknown)"
          echo "watchdog=$(cat /sys/class/watchdog/watchdog0/identity 2>/dev/null || echo unknown)"
          cat "$status"
          echo "provider=vendor-PSCI DA9214 BUCKB transcript ledger-gated; no generic raw-write interface"
          echo "ledger_and_trace=dmesg-following"
          dmesg 2>/dev/null | grep -E 'GEMINI_A72|GEMINI_A72_ADMISSION|a72-transition|CPU8:' | tail -n 80 || true
        }
        preflight() {
          dump || return
          status=$(status_path) || return 1
          status_text=$(cat "$status")
          case "$status_text" in
            *'ledger_state=retained-terminal'*)
              echo "preflight=blocked reason=retained-terminal-ledger action=ack-ledger"; return 1 ;;
            *'ledger_state=retained-incomplete'*)
              echo "preflight=blocked reason=retained-incomplete-ledger"; return 1 ;;
            *'ledger_state=unreadable'*)
              echo "preflight=blocked reason=retained-ledger-unreadable"; return 1 ;;
            *'state=armed'*'trigger_consumed=0'*'binder_snapshot_ret=0'*'ledger_state=empty'*)
              echo "preflight=ready next=admission-chain" ;;
            *) echo "preflight=blocked"; return 1 ;;
          esac
        }
        ack_ledger() {
          dump || return
          status=$(status_path) || return 1
          status_text=$(cat "$status")
          case "$status_text" in
            *'state=armed'*'trigger_consumed=0'*'ledger_state=retained-terminal'*) ;;
            *) echo "ack_ledger=blocked reason=terminal-ledger-not-present"; return 1 ;;
          esac
          recover=$(dirname "$status")/recover
          grep -q ' /sys sysfs ro,' /proc/mounts && {
            mount -o remount,rw /sys || return 1
            was_ro=1
          }
          printf 'ack-terminal-ledger-v1\n' > "$recover"
          ret=$?
          [ "''${was_ro:-0}" = 1 ] && mount -o remount,ro /sys
          echo "ack_ledger_write_ret=$ret"
          dump
          return "$ret"
        }
        advance() {
          preflight || return
          status=$(status_path) || return 1
          trigger=$(dirname "$status")/trigger
          grep -q ' /sys sysfs ro,' /proc/mounts && {
            mount -o remount,rw /sys || return 1
            was_ro=1
          }
          printf 'run-a72-admission-20260828-a\n' > "$trigger"
          ret=$?
          [ "''${was_ro:-0}" = 1 ] && mount -o remount,ro /sys
          echo "advance_write_ret=$ret"
          dump
          return "$ret"
        }
        case "''${1:-dump}" in
          dump|ledger|admission|provider|p27|p28|sram|cpu8) dump ;;
          preflight) preflight ;;
          recover|ack-ledger) ack_ledger ;;
          advance) advance ;;
          *) echo "usage: $0 {dump|preflight|ack-ledger|advance|ledger|admission|provider|p27|p28|sram|cpu8}"; exit 2 ;;
        esac
        A72_CPU8_CONTROL
        chmod 0755 root/bin/a72-cpu8-control
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
          ${lib.optionalString (!a72Cpu8Interactive) ''
          (
            sleep 90
            if [ "$(cat /run/unattended-recovery.accepted 2>/dev/null || true)" != "unattended_recovery=healthy" ]; then
              note "unattended_recovery=lease-expired watchdog_userspace=stopped watchdog_reset_expected=31s"
              kill -KILL "$watchdog_pid" 2>/dev/null || true
            fi
          ) &
          ''}
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
      ${lib.optionalString md1LkHandoffProbe ''
      # MD1 probe itself ran during platform population.  Collect only its
      # bounded kernel evidence; this initramfs code neither retriggers it nor
      # accesses modem partitions, reserved memory, clocks, resets, CCIF, or
      # any modem transport.
      md1_attempt=0
      while [ "$md1_attempt" -lt 3 ]; do
        dmesg 2>/dev/null | grep -F 'mt6797-md1-lk-handoff' \
          > /run/md1-lk-handoff.dmesg || true
        [ -s /run/md1-lk-handoff.dmesg ] && break
        md1_attempt=$((md1_attempt + 1))
        sleep 1
      done
      if grep -Fq 'verified LK hand-off:' /run/md1-lk-handoff.dmesg 2>/dev/null; then
        if grep -Fq 'LK MD1 load evidence:' /run/md1-lk-handoff.dmesg; then
          note "md1_lk_handoff=verified stage=lk-image-load-only execution=unknown evidence=/run/md1-lk-handoff.dmesg cold-owner=not-granted"
        elif grep -Fq 'RMPU/remap candidate encodings:' /run/md1-lk-handoff.dmesg; then
          note "md1_lk_handoff=verified stage=metadata-and-plan-only evidence=/run/md1-lk-handoff.dmesg next=mpu-remap-owner-and-mode-required"
        else
          note "md1_lk_handoff=verified stage=metadata-only evidence=/run/md1-lk-handoff.dmesg next=inspect-rmpu-plan-log"
        fi
      elif [ -s /run/md1-lk-handoff.dmesg ]; then
        note "md1_lk_handoff=rejected stage=metadata-only evidence=/run/md1-lk-handoff.dmesg action=inspect-exact-kernel-error"
      else
        note "md1_lk_handoff=not-observed after=3s action=inspect-cmdline-dt-and-dmesg"
      fi
      ''}
      ${lib.optionalString md1BootStatusObserve ''
      # The driver was populated exactly once by the DT. Collect its result;
      # never interpret a value as execution, ownership, or permission to
      # modify MD1 state.
      dmesg 2>/dev/null | grep -E 'MD1_BOOT_STATS|MD1 boot-status complete|passive MD1 CCIF snapshot' > /run/md1-boot-status.dmesg || true
      if grep -Fq 'MD1 boot-status complete:' /run/md1-boot-status.dmesg 2>/dev/null \
        && grep -Fq 'ap_rchnum=' /run/md1-boot-status.dmesg; then
        stats0_count=$(grep -Fc 'after MD1_BOOT_STATS0 sample' /run/md1-boot-status.dmesg || true)
        stats1_count=$(grep -Fc 'after MD1_BOOT_STATS1 sample' /run/md1-boot-status.dmesg || true)
        if [ "$stats0_count" -eq 3 ] && [ "$stats1_count" -eq 3 ]; then
          note "md1_boot_status=observed samples=3+3 ap_rchnum=raw evidence=/run/md1-boot-status.dmesg interpretation=none ownership=not-granted"
        else
          note "md1_boot_status=incomplete evidence=/run/md1-boot-status.dmesg action=inspect-before-after-boundary"
        fi
      else
        note "md1_boot_status=not-observed evidence=/run/md1-boot-status.dmesg action=inspect-cmdline-dt-and-dmesg"
      fi
      ''}
      ${lib.optionalString md1RemapObserve ''
      # Population runs the DT driver once. This just retains its bounded
      # five-read evidence and never touches any modem control resource.
      dmesg 2>/dev/null | grep -E 'MD1 remap observed|MD1 remap read|mt6797-md1-remap-observe' > /run/md1-remap-observe.dmesg || true
      if grep -Fq 'MD1 remap observed' /run/md1-remap-observe.dmesg 2>/dev/null; then
        note "md1_remap_observe=observed reads=5 evidence=/run/md1-remap-observe.dmesg classification=source-shaped-only ownership=not-granted"
      elif [ -s /run/md1-remap-observe.dmesg ]; then
        note "md1_remap_observe=rejected-or-incomplete evidence=/run/md1-remap-observe.dmesg action=inspect-plan-gates-and-dmesg"
      else
        note "md1_remap_observe=not-observed evidence=/run/md1-remap-observe.dmesg action=inspect-cmdline-dt-and-lk-plan"
      fi
      ''}
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
      ${lib.optionalString a72Cpu8SramDiagnostic ''
      ${lib.optionalString a72Cpu8Interactive ''
      note "a72_cpu8=interactive-idle trigger=disabled watchdog_userspace=persistent control=/bin/a72-cpu8-control"
      ''}
      ${lib.optionalString a72Cpu8TraceOnly ''
      note "a72_cpu8=trace-header-snapshot-only trigger=disabled no-sysfs-write"
      ''}
      ${lib.optionalString (!a72Cpu8TraceOnly) ''
      /bin/a72-cpu8-sram-diagnostic &
      note "a72_cpu8=armed trigger=one-exact-token serviceability-gated no-retry-no-rollback"
      ''}
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
      echo "nix-consys-g2g-gnss=${consysG2gGnssLabel}"
      echo "nix-wifi-w0=${wifiW0Label}"
      echo "nix-wifi-w1=${wifiW1Label}"
      echo "nix-wifi-w2=${wifiW2Label}"
      echo "nix-wifi-w4=${wifiW4Label}"
      echo "wifi-userspace=${if wifiW4Connect then "iw+wpa_supplicant+iperf3+regulatory.db-static" else "none"}"
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
      echo "nix-a72-cpu8-sram-diagnostic=${a72Cpu8SramDiagnosticLabel}"
      echo "a72-cpu8-request=initramfs exact-token once after watchdog+gadget+rtl+emmc gates; cpu9=maxcpus-9 veto; retry=0 cpu_off=0 rollback=0"
      echo "nix-md1-lk-handoff=${md1LkHandoffLabel}"
      echo "nix-md1-boot-status=${md1BootStatusLabel}"
      echo "nix-md1-remap-observe=${md1RemapObserveLabel}"
      echo "md1-lk-handoff-contract=${
        if md1LkHandoffProbe
        then "DT-status=okay plus built-in parameter; LK flag is accepted only as image-load evidence and execution remains unknown; metadata table and diagnostic RMPU/remap plan read-only; fence/secure-MPU-provider/backend source is explicitly unselected and has no hardware run path; public LK remap-lock/refusal evidence is source-only; mandatory unmap before partition-I/O/MPU/remap writes/power/reset/CCIF/CLDMA/DMA"
        else "none"
      }"
      echo "md1-boot-status-contract=${
        if md1BootStatusObserve
        then "second DT-status=okay plus separate built-in parameter; exactly three reads of each AP-visible vendor status word followed by one passive raw AP-CCIF RCHNUM read after LK load evidence; no write/poll/retry/value interpretation, ACK, IRQ request, or ownership grant"
        else "none"
      }"
      echo "md1-remap-observe-contract=${
        if md1RemapObserve
        then "third DT-status=okay plus separate built-in parameter; exactly five infracfg-AO reads after validated LK plan: bank0 0x300/0x304, bank4 0x310/0x314, lock 0xf80; source-shaped classifier result is evidence only, never remap/MPU/WDT/release/CCIF/CLDMA/DMA authority"
        else "none"
      }"
      echo "md1-lk-handoff-runtime-evidence=${
        if md1LkHandoffProbe
        then "/run/md1-lk-handoff.dmesg and GEMINI_NIX_IXOO_PROBE md1_lk_handoff=*"
        else "none"
      }"
      echo "md1-boot-status-runtime-evidence=${
        if md1BootStatusObserve
        then "/run/md1-boot-status.dmesg and GEMINI_NIX_IXOO_PROBE md1_boot_status=*"
        else "none"
      }"
      echo "md1-remap-observe-runtime-evidence=${
        if md1RemapObserve
        then "/run/md1-remap-observe.dmesg and GEMINI_NIX_IXOO_PROBE md1_remap_observe=*"
        else "none"
      }"
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
      ${lib.optionalString wifiW1FirmwareReadyProof ''
        sha256sum ${../blobs/WIFI_RAM_CODE_6797}
        stat -c '%n size=%s' ${../blobs/WIFI_RAM_CODE_6797}
      ''}
      ${lib.optionalString audioHeadphoneTest ''
        sha256sum ${audioHeadphoneExercise}/bin/gemini-audio-headphone
      ''}
      stat -c '%n size=%s' ${probeBootImg} ${probeBoot2Img}
      } > "$out/MANIFEST"
  '';
in {
  inherit audioHeadphoneExercise kernel serviceabilityDtb probeInitramfs probeBootImg probeBoot2Img bundle;
}
