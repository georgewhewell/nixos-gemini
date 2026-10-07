{
  description = "NixOS for Planet Computers Gemini PDA";

  inputs = {
    linux-gemini = {
      url = "git+file:///mnt/Home/src/nixos-gemini/linux?ref=gemini&rev=18db31826ba9985899b4f13d59f14d5201ec2fe7";
      flake = false;
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-old.url = "github:NixOS/nixpkgs/nixos-23.05";
    vendor-kernel = {
      url = "github:gemian/gemini-linux-kernel-3.18/51e705e4e7b1e52a31a79985f7fbbc9e98b59c8c";
      flake = false;
    };
    ixoo-kernel = {
      url = "github:ixoo/gemini-pda-mainline/7199e8229c6a805a941e33a6862956949dfebd3a";
      flake = false;
    };
    linux-gemini-recovery = {
      url = "git+file:///mnt/Home/src/nixos-gemini/linux?ref=gemini&rev=c0dbf01b2bdaa9cc741582ae0c88df3daac74285";
      flake = false;
    };
    linux-gemini-next = {
      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-platform&rev=da6e93b0bce1b62e0e38425938efe3ceba7cfc09";
      flake = false;
    };
    ixoo-candidate = {
      url = "github:ixoo/gemini-pda-mainline/a24b2d264844ee2bb50e77dc7aceaa6b902c7b6a";
      flake = false;
    };
    u-boot-gemini-src = {
      url = "git+file:///mnt/Home/src/nixos-gemini/u-boot-consolidation?ref=gemini-boot-consolidation&rev=3da3110deebdb351eff0cd48d76271596dfa407d&shallow=1";
      flake = false;
    };
    u-boot-gemini-dt-src = {
      url = "git+file:///mnt/Home/src/nixos-gemini/u-boot-consolidation?ref=gemini-boot-consolidation&rev=c50f76ab4995037008b4b5ab37a828bd23e3373c&shallow=1";
      flake = false;
    };
    u-boot-gemini-keys-src = {
      url = "git+file:///mnt/Home/src/nixos-gemini/u-boot-consolidation?ref=gemini-boot-consolidation&rev=1ff66d0a9749021124badd964b2cd2497cff6d21&shallow=1";
      flake = false;
    };
    u-boot-src = {
      url = "github:u-boot/u-boot/cc8c034e78eba6b2a3845783889b80753bb1af1e";
      flake = false;
    };
  };

  outputs = inputs @ {self, ...}: let
    host = "x86_64-linux";
    gemini = import ./nix/gemini.nix inputs;
    historical =
      (import ./legacy.nix)
      (builtins.removeAttrs (inputs
        // {
          linux-gemini = inputs.linux-gemini-recovery;
        }) ["linux-gemini-recovery"]);
  in {
    packages.${host} = {
      default = gemini.image.bundle;
      kernel = gemini.kernel;
      dtb = gemini.dtb;
      bootImg = gemini.image.paddedBootImg;
      initramfs = gemini.image.initramfs;
      squashfs = gemini.squashfs;
      toplevel = gemini.system.config.system.build.toplevel;
      deploy = gemini.image.bundle;
      efiBootFiles = gemini.efiBootFiles;
      uboot = gemini.uboot;
      mtkclient = gemini.mtkclient;
      recovery = historical.packages.${host}.mainlineNixosBundle;
      # Existing normal-build names remain aliases of the current system.
      mainlineNixosBundle = gemini.image.bundle;
      mainlineNixosKernel = gemini.kernel;
      mainlineNixosDtb = gemini.dtb;
      mainlineNixosInitramfs = gemini.image.initramfs;
      mainlineNixosSquashfs = gemini.squashfs;
    };
    nixosConfigurations = {
      gemini = gemini.system;
      gemini-mainline = gemini.system;
    };
    checks.${host} = {
      desktop = gemini.userspace.desktopProtocolCheck;
      keyboard = gemini.userspace.desktopKeyboardProtocolCheck;
      ssh = gemini.buildPkgs.runCommand "mainline-sshd-pam-session-check" {} ''
        grep -Fqx 'session required pam_unix.so' ${gemini.system.config.environment.etc."pam.d/sshd".source}
        ! grep -Fq 'pam_systemd.so' ${gemini.system.config.environment.etc."pam.d/sshd".source}
        touch "$out"
      '';
    };
    # Historical experiments are explicit; they are not normal build targets.
    legacyPackages.${host} = historical.packages.${host};
    legacyConfigurations = historical.nixosConfigurations;
    devShells.${host}.default = gemini.buildPkgs.mkShell {
      packages = with gemini.buildPkgs; [
        android-tools
        dtc
        ncurses
        bc
        flex
        bison
        openssl
        perl
        elfutils
        pkgsCross.aarch64-multiplatform.stdenv.cc
      ];
      shellHook = ''
        export ARCH=arm64
        export CROSS_COMPILE=aarch64-unknown-linux-gnu-
        echo "Gemini: nix build (system bundle), nix build .#kernel, nix build .#recovery"
      '';
    };
  };
}
