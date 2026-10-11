{
  description = "NixOS for Planet Computers Gemini PDA";

  inputs = {
    linux-gemini = {
      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-7.2.9&rev=e5a33df4127ac41d09c0237e33c9b44d5f5798c7&shallow=1";
      flake = false;
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-old.url = "github:NixOS/nixpkgs/nixos-23.05";
    recovery-packaging = {
      url = "git+file:///mnt/Home/src/nixos-gemini/repo?rev=35130680e46a2b3f9c6694338fb880dc77d40fa4";
      flake = false;
    };
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
    u-boot-gemini = {
      url = "git+file:///mnt/Home/src/nixos-gemini/u-boot-consolidation?ref=gemini-boot-consolidation&rev=4ea946a87c5e8b625fea0e6b2fc9f454b26e1b0f&shallow=1";
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
      (import "${inputs.recovery-packaging}/legacy.nix")
      (builtins.removeAttrs (inputs
        // {
          linux-gemini = inputs.linux-gemini-recovery;
        }) ["linux-gemini-recovery" "u-boot-gemini" "recovery-packaging"]);
  in {
    packages.${host} = {
      default = gemini.image.bundle;
      kernel = gemini.kernel;
      dtb = gemini.dtb;
      bootImg = gemini.image.paddedBootImg;
      initramfs = gemini.image.initramfs;
      toplevel = gemini.system.config.system.build.toplevel;
      deploy = gemini.image.bundle;
      efiBootFiles = gemini.efiBootFiles;
      uboot = gemini.uboot;
      bootloader = gemini.bootloader;
      mtkclient = gemini.mtkclient;
      recovery = historical.packages.${host}.mainlineNixosBundle;
      # Existing normal-build names remain aliases of the current system.
      mainlineNixosBundle = gemini.image.bundle;
      mainlineNixosKernel = gemini.kernel;
      mainlineNixosDtb = gemini.dtb;
      mainlineNixosInitramfs = gemini.image.initramfs;
    };
    nixosConfigurations = {
      gemini = gemini.system;
      gemini-mainline = gemini.system;
    };
    checks.${host} = {
      storage = gemini.buildPkgs.runCommand "gemini-storage-check" {
        nativeBuildInputs = with gemini.buildPkgs; [bash coreutils gnugrep gnused gawk gptfdisk];
      } ''
        mkdir work
        bash ${./nix/test-gemini-storage-provision.sh} ${gemini.buildPkgs.replaceVars ./nix/gemini-storage-provision.sh {
          SWAP_PARTUUID = gemini.system.config.gemini.storage.swapPartUuid;
          DATA_LABEL = gemini.system.config.gemini.storage.dataLabel;
        }} "$PWD/work"
        touch "$out"
      '';
      boot-install = gemini.buildPkgs.runCommand "gemini-boot-install-check" {
        nativeBuildInputs = [gemini.buildPkgs.python3 gemini.buildPkgs.dtc];
      } ''
        mkdir nix tools
        cp ${./nix/gemini-boot-install.py} nix/gemini-boot-install.py
        cp ${./nix/gemini-efi-publish.sh} nix/gemini-efi-publish.sh
        cp ${./tools/test-gemini-boot-install.py} tools/test-gemini-boot-install.py
        cp ${./tools/test-gemini-efi-publish.py} tools/test-gemini-efi-publish.py
        python3 tools/test-gemini-boot-install.py
        python3 tools/test-gemini-efi-publish.py
        touch "$out"
      '';
      desktop = gemini.userspace.desktopProtocolCheck;
      keyboard = gemini.userspace.desktopKeyboardProtocolCheck;
      gnome-cross-runtime = gemini.buildPkgs.runCommand "gemini-gnome-cross-runtime-check" {
        nativeBuildInputs = [gemini.buildPkgs.python3];
      } ''
        python3 ${./tools/check-gnome-cross-runtime.py} \
          --system ${gemini.system.config.system.build.toplevel} \
          --shell ${gemini.system.pkgs.gnome-shell} \
          --orca ${gemini.system.pkgs.orca} \
          --networkmanager ${gemini.system.config.networking.networkmanager.package} \
          --modemmanager ${gemini.system.config.networking.modemmanager.package} \
          --calls ${gemini.system.pkgs.calls} \
          --spacebar ${gemini.system.pkgs.kdePackages.spacebar} \
          --callaudiod ${gemini.system.pkgs.callaudiod} --out "$out"
      '';
      network-profiles = gemini.buildPkgs.runCommand "gemini-network-profiles-check" {
        nativeBuildInputs = [gemini.buildPkgs.python3];
      } ''
        cp ${./nix/networkmanager-import-wifi.py} networkmanager-import-wifi.py
        cp ${./nix/test-networkmanager-import-wifi.py} test-networkmanager-import-wifi.py
        python3 test-networkmanager-import-wifi.py
        touch "$out"
      '';
      networkmanager-scan = gemini.buildPkgs.runCommand "gemini-networkmanager-scan-check" {
        nativeBuildInputs = [gemini.buildPkgs.python3];
      } ''
        cp ${./tools/networkmanager-scan-evidence.py} networkmanager-scan-evidence.py
        cp ${./tools/test-networkmanager-scan-evidence.py} test-networkmanager-scan-evidence.py
        python3 test-networkmanager-scan-evidence.py
        touch "$out"
      '';
      audio-playback-routing = gemini.buildPkgs.runCommand "gemini-audio-playback-routing-check" {
        nativeBuildInputs = [gemini.buildPkgs.python3 gemini.buildPkgs.alsa-utils];
      } ''
        cp ${./tools/audio-playback-evidence.py} audio-playback-evidence.py
        cp ${./nix/test-audio-playback-routing.py} test-audio-playback-routing.py
        python3 test-audio-playback-routing.py \
          ${gemini.buildPkgs.writeText "gemini-asound.conf" gemini.system.config.environment.etc."asound.conf".text} \
          ${gemini.system.config.system.build.geminiAudioUcm}/share/alsa/ucm2/MediaTek/Gemini/HiFi.conf \
          ${gemini.buildPkgs.alsa-utils}/bin/aplay
        touch "$out"
      '';
      baseline-acceptance = gemini.buildPkgs.runCommand "gemini-baseline-acceptance-check" {
        nativeBuildInputs = with gemini.buildPkgs; [bash coreutils gnugrep gawk];
      } ''
        mkdir nix
        cp ${./nix/unattended-recovery-baseline-self-accept.sh} nix/unattended-recovery-baseline-self-accept.sh
        cp ${./nix/test-unattended-recovery-baseline-self-accept.sh} nix/test-unattended-recovery-baseline-self-accept.sh
        bash nix/test-unattended-recovery-baseline-self-accept.sh
        touch "$out"
      '';
      ssh = gemini.buildPkgs.runCommand "mainline-sshd-pam-session-check" {} ''
        pam=${gemini.buildPkgs.writeText "gemini-sshd-pam" gemini.system.config.security.pam.services.sshd.text}
        grep -Eq '^account required /nix/store/[^ ]+/lib/security/pam_unix\.so( |$)' "$pam"
        grep -Eq '^session required /nix/store/[^ ]+/lib/security/pam_unix\.so( |$)' "$pam"
        grep -Eq '^session optional /nix/store/[^ ]+/lib/security/pam_systemd\.so( |$)' "$pam"
        touch "$out"
      '';
      zram = gemini.buildPkgs.runCommand "gemini-zram-policy-check" {
        nativeBuildInputs = [gemini.buildPkgs.python3 gemini.buildPkgs.stdenv.cc];
      } ''
        mkdir tools
        cp ${./tools/qualify-zram.py} tools/qualify-zram.py
        cp ${./tools/qualify-swap-io.py} tools/qualify-swap-io.py
        cp ${./tools/test-zram-paging.py} tools/test-zram-paging.py
        python3 tools/test-zram-paging.py
        cc -std=gnu11 -O2 -Wall -Wextra -Werror ${./nix/gemini-zram-probe.c} -o probe
        ./probe --self-test
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
        gemini.kernelCompiler
      ];
      shellHook = ''
        export ARCH=arm64
        export CROSS_COMPILE=aarch64-unknown-linux-gnu-
        echo "Gemini: nix build (system bundle), nix build .#kernel, nix build .#recovery"
      '';
    };
  };
}
