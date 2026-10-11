# The normal Gemini system: one maintained kernel and one module composition.
{
  nixpkgs,
  linux-gemini,
  ixoo-kernel,
  u-boot-gemini,
  ...
}: let
  buildSystem = "x86_64-linux";
  targetSystem = "aarch64-linux";
  buildPkgs = import nixpkgs {
    system = buildSystem;
    config.allowUnfree = true;
  };
  crossPkgs = buildPkgs.pkgsCross.aarch64-multiplatform;
  kernelCompiler = crossPkgs.stdenv.cc;
  mainlineNixosLeaseSelfAcceptToken = "gemini-baseline-lease-v1-4e8e71c5b0c2aa1543c6fb079cc22964d0a7e25b942cb350f7a1e3d69b8c4052";
  userspace = import ./userspace.nix {inherit buildPkgs crossPkgs; ubootSource = u-boot-gemini;};
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
  kernel = import ./kernel.nix {
    inherit buildPkgs spmFirmware;
    compiler = kernelCompiler;
    source = linux-gemini;
  };
  esim = import ./esim {
    pkgs = system.pkgs;
    buildPkgs = system.pkgs.buildPackages;
  };
  dtb = import ./dtb.nix {inherit buildPkgs kernel;};
  system = nixpkgs.lib.nixosSystem {
    system = buildSystem;
    modules = [
      ../nixos/mainline-configuration.nix
      ../nixos/cellular.nix
      ../nixos/gpu.nix
      ../nixos/connectivity.nix
      ../nixos/bluetooth.nix
      ../nixos/networking.nix
      ../nixos/audio.nix
      ../nixos/power-policy.nix
      ../nixos/storage.nix
      ../nixos/boot.nix
      ../nixos/desktop.nix
      ../nixos/gnome.nix
      ../nixos/spm.nix
      ../nixos/core-parking.nix
      ../nixos/media.nix
      ({
        config,
        lib,
        pkgs,
        ...
      }: {
        _module.args.geminiBootJournaled = true;
        _module.args.geminiBootKernel = kernel;
        _module.args.geminiBootDtb = dtb;
        _module.args.geminiBootInitrd = image.initramfs;
        _module.args.geminiBootManager = buildPkgs.runCommand "gemini-systemd-bootaa64.efi" {} ''
          cp ${crossPkgs.systemd}/lib/systemd/boot/efi/systemd-bootaa64.efi "$out"
        '';
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
        _module.args.geminiEsim = esim;
        systemd.packages = [config.nix.package];
      })
      {
        nixpkgs.overlays = [ (import ./cross-fixes.nix) ];
        nixpkgs.hostPlatform = targetSystem;
        nixpkgs.buildPlatform = buildSystem;
      }
    ];
  };

  imageArgs = {
    inherit buildPkgs crossPkgs ixoo-kernel kernel;
    serviceabilityDtb = dtb;
    nixosToplevel = system.config.system.build.toplevel;
    authorizedKeys = ../nixos/authorized_keys;
    unattendedRecovery = true;
    stage1PersistentHostKey = true;
    displayActivation = true;
    watchdogLeaseSeconds = 720;
    kernelLeaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
    stage2BaselineAcceptScript = system.config.systemd.services.gemini-baseline-self-accept.script;
    leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
    persistentStorage = {inherit (system.config.gemini.storage) dataLabel;};
  };

  image = import ./mainline-nixos.nix imageArgs;
  efiBootFiles = import ./gemini-efi-boot-files.nix {
    inherit buildPkgs kernel;
    bootloader = crossPkgs.systemd;
    linuxBundle = image.bundle;
    versionedEntry = true;
    entryDtb = true;
  };
  uboot = import ./uboot.nix {
    inherit buildPkgs crossPkgs;
    source = u-boot-gemini;
  };
  bootloader = import ./uboot-carrier.nix {
    inherit buildPkgs uboot;
    linuxBundle = image.bundle;
  };

in {
  inherit buildPkgs crossPkgs kernelCompiler system kernel dtb image efiBootFiles uboot bootloader userspace esim;
  mtkclient = import ./mtkclient-rtc.nix {inherit buildPkgs;};
}
