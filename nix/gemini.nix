# The normal Gemini system: one maintained kernel and one module composition.
{
  nixpkgs,
  nixpkgs-old,
  linux-gemini,
  ixoo-kernel,
  ixoo-candidate,
  u-boot-gemini-keys-src,
  ...
}: let
  buildSystem = "x86_64-linux";
  targetSystem = "aarch64-linux";
  buildPkgs = import nixpkgs {
    system = buildSystem;
    config.allowUnfree = true;
  };
  oldPkgs = import nixpkgs-old {system = buildSystem;};
  crossPkgs = buildPkgs.pkgsCross.aarch64-multiplatform;
  mainlineNixosLeaseSelfAcceptToken = "gemini-baseline-lease-v1-4e8e71c5b0c2aa1543c6fb079cc22964d0a7e25b942cb350f7a1e3d69b8c4052";
  userspace = import ./userspace.nix {inherit buildPkgs crossPkgs u-boot-gemini-keys-src;};
  inherit
    (userspace)
    gpuUserspace
    desktopUserspace
    desktopProtocolCheck
    desktopKeyboard
    desktopKeyboardProtocolCheck
    ;
  spmFirmware = import ./spm-firmware.nix {inherit buildPkgs;};
  cellularFsRegister = import ./cellular-helper.nix {inherit buildPkgs crossPkgs linux-gemini;};
  board = import ./mainline.nix {
    kernelName = "linux-gemini";
    kernelPostBuild = ''
      python3 tools/testing/selftests/watchdog/mtk-wdt-pm-host.py
      python3 tools/testing/selftests/rtc/mt6397-alarm-host.py
      python3 tools/testing/selftests/rtc/mt6351-calendar-host.py
    '';
    inherit
      buildPkgs
      oldPkgs
      crossPkgs
      ixoo-kernel
      linux-gemini
      ixoo-candidate
      ;
    kernelConfig = [./gemini.fragment];
    kernelCommandLine = ["efi=debug"];
    debugOverlay = true;
    storageOverlay = true;
    sshAccess = true;
    usbHostOverlay = true;
    platformEnablement = true;
    displayOverlay = true;
    audioOverlay = true;
    powerObserveOverlay = true;
    powerObservePreflight = true;
    chargerActive = true;
    hapticsOverlay = true;
    cameraOverlay = true;
    mediaOverlay = true;
    unattendedRecovery = true;
    inputObserveOverlay = true;
    thermalHallObserveOverlay = true;
    touchscreenActivationOverlay = true;
    fgadcActivationOverlay = true;
    leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
    cellularOverlay = true;
    a72Overlay = true;
    gpuOwnerOverlay = true;
    desktopScanout = true;
    connectivityModules = true;
    microsdOverlay = true;
    rtcPowerKeyOverlay = true;
    cpufreqOverlay = true;
    spmOverlay = true;
    inherit spmFirmware;
  };

  kernel = board.kernel;
  system = nixpkgs-old.lib.nixosSystem {
    system = buildSystem;
    modules = [
      ../nixos/mainline-configuration.nix
      ../nixos/cellular.nix
      ../nixos/gpu.nix
      ../nixos/connectivity.nix
      ../nixos/bluetooth.nix
      ../nixos/wifi-autoconnect.nix
      ../nixos/audio.nix
      ../nixos/power-policy.nix
      ../nixos/storage.nix
      ../nixos/desktop.nix
      ../nixos/m39.nix
      ../nixos/spm.nix
      ../nixos/core-parking.nix
      ../nixos/media.nix
      ({
        config,
        lib,
        pkgs,
        ...
      }: {
        _module.args.geminiLeaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
        _module.args.geminiCellularHelper = cellularFsRegister;
        _module.args.geminiGpuKernel = kernel;
        _module.args.geminiConnectivityKernel = kernel;
        _module.args.geminiConnectivityFirmware = import ./connectivity-firmware.nix {inherit buildPkgs;};
        _module.args.geminiSpmKernel = kernel;
        _module.args.geminiCpufreqKernel = kernel;
        _module.args.geminiSpmFirmware = spmFirmware;
        _module.args.geminiGpuSmoke = gpuUserspace.smoke;
        _module.args.geminiDesktop = desktopUserspace // {protocolCheck = desktopProtocolCheck;};
        _module.args.geminiDesktopKeyboard = {
          inherit (desktopKeyboard) data check;
          protocolCheck = desktopKeyboardProtocolCheck;
        };
        systemd.packages = lib.mkOverride 40 [pkgs.dbus config.nix.package];
        gemini.powerPolicy.hibernation.enable = lib.mkForce false;
      })
      {
        nixpkgs.hostPlatform = targetSystem;
        nixpkgs.buildPlatform = buildSystem;
      }
    ];
  };

  squashfs = import ./squashfs.nix {
    inherit buildPkgs;
    system = system.config.system.build.toplevel;
  };
  imageArgs = {
    inherit buildPkgs crossPkgs ixoo-kernel kernel squashfs;
    serviceabilityDtb = board.serviceabilityDtb;
    nixosToplevel = system.config.system.build.toplevel;
    authorizedKeys = ../nixos/authorized_keys;
    bq2589xPreflight = buildPkgs.runCommand "bq2589x-preflight-charger" {} ''
      sed 's/^EXPECTED_MODE=''${GEMINI_PREFLIGHT_EXPECTED_MODE:-observe}$/EXPECTED_MODE=''${GEMINI_PREFLIGHT_EXPECTED_MODE:-charger}/' \
        ${./bq2589x-preflight.sh} > "$out"
      grep -Fqx 'EXPECTED_MODE=''${GEMINI_PREFLIGHT_EXPECTED_MODE:-charger}' "$out"
      chmod 0755 "$out"
    '';
    unattendedRecovery = true;
    inputDiagnostics = true;
    stage1PersistentHostKey = true;
    displayActivation = true;
    provisionStore = true;
    provisionWaitSeconds = 600;
    watchdogLeaseSeconds = 720;
    kernelLeaseSelfAcceptToken = board.leaseSelfAcceptToken;
    stage2BaselineAcceptScript = system.config.systemd.services.gemini-baseline-self-accept.script;
    leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
    persistentStorage = let
      storage = system.config.gemini.storage;
    in
      if storage.enable
      then {inherit (storage) dataLabel;}
      else null;
  };

  image = import ./mainline-nixos.nix imageArgs;
  efiBootFiles = import ./gemini-efi-boot-files.nix {
    inherit buildPkgs kernel;
    bootloader = crossPkgs.systemd;
    linuxBundle = image.bundle;
    versionedEntry = true;
    entryDtb = true;
  };
  uboot = import ./uboot-handoff.nix {
    inherit buildPkgs crossPkgs;
    source = u-boot-gemini-keys-src;
    efiLinux = true;
    efiConsole = true;
    efiKeyboard = true;
    efiMmc = true;
    efiStorage = true;
    efiManager = true;
    efiDtFixup = true;
    efiKeyEvents = true;
  };
in {
  inherit buildPkgs crossPkgs system kernel squashfs image efiBootFiles uboot userspace;
  dtb = board.serviceabilityDtb;
  mtkclient = import ./mtkclient-rtc.nix {inherit buildPkgs;};
}
