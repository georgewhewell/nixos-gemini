{
  description = "NixOS for Planet Computers Gemini PDA";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # Compatibility snapshot for the Linux 3.18 userspace and GCC 8 kernel
    # toolchain. Keep this pinned deliberately; current systemd targets much
    # newer kernels.
    nixpkgs-old.url = "github:NixOS/nixpkgs/nixos-23.05";
    vendor-kernel = {
      # This is the Gemian 3.18.41 tree used immediately before the known-good
      # kernel's 2019-03-29 build, not the unrelated UBports k97v1 tree.
      url = "github:gemian/gemini-linux-kernel-3.18/51e705e4e7b1e52a31a79985f7fbbc9e98b59c8c";
      flake = false;
    };
    ixoo-kernel = {
      # Exact source/config commit behind ixoo's hardware-passed, read-only
      # DA921x serviceability baseline.  Later ixoo work is intentionally not
      # allowed to move this first reproduction target.
      url = "github:ixoo/gemini-pda-mainline/7199e8229c6a805a941e33a6862956949dfebd3a";
      flake = false;
    };
    linux-gemini = {
      # Integrated Linux 7.1.3 platform tree: ixoo's proven Gemini baseline
      # plus the reviewed, opt-in bring-up slices. Pin the exact fork commit;
      # experiments never consume a moving branch tip.
      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-platform&rev=28c47150235be70cf5b19ea8d9ce7a5473ec23f2";
      flake = false;
    };
    linux-gemini-next = {
      # Critical-path experiments consume a second immutable pin so the
      # accepted p22 baseline remains rebuildable byte-for-byte while newer
      # CONSYS/GPU/cellular work advances on the same maintained fork.
      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-platform&rev=da6e93b0bce1b62e0e38425938efe3ceba7cfc09";
      flake = false;
    };
    linux-gemini-w1-candidate = {
      # Deliberately consume the reviewed local W1 commit rather than moving
      # linux-gemini-next.  The flake lock records its content hash for the
      # staged candidate while every accepted profile retains its old pin.
      url = "path:/mnt/Home/src/linux-gemini-w1-firmware-source";
      flake = false;
    };
    linux-gemini-w1-forensic-candidate = {
      # Keep causal instrumentation separate from the earlier W1 READY image.
      # The source is a committed, independent Trex clone; this profile is
      # build/stage-only and never changes an accepted candidate's pin.
      url = "path:/mnt/Home/src/linux-gemini-w2-trex";
      flake = false;
    };
    ixoo-candidate = {
      # Commit which froze and independently validated the boot2 candidate
      # derived from the kernel commit above.
      url = "github:ixoo/gemini-pda-mainline/a24b2d264844ee2bb50e77dc7aceaa6b902c7b6a";
      flake = false;
    };
  };

  outputs = {
    self,
    nixpkgs,
    nixpkgs-old,
    vendor-kernel,
    ixoo-kernel,
    linux-gemini,
    linux-gemini-next,
    linux-gemini-w1-candidate,
    linux-gemini-w1-forensic-candidate,
    ixoo-candidate,
  }: let
    # Build system (your machine)
    buildSystem = "x86_64-linux";

    # Target system (Gemini PDA)
    targetSystem = "aarch64-linux";

    # Explicit capability for the one reviewed full-NixOS baseline. It is
    # intentionally neither derived from nor a hash of the NixOS toplevel:
    # feeding a toplevel hash into the config that creates that toplevel would
    # be circular. Stage 1 carries the exact resulting system path separately.
    # Experimental p22 outputs do not receive this argument or cmdline token.
    mainlineNixosLeaseSelfAcceptToken = "gemini-baseline-lease-v1-4e8e71c5b0c2aa1543c6fb079cc22964d0a7e25b942cb350f7a1e3d69b8c4052";

    # Native pkgs for build tools
    buildPkgs = import nixpkgs {
      system = buildSystem;
      config.permittedInsecurePackages = ["python-2.7.18.12"];
      config.allowUnfree = true;
    };

    # Old nixpkgs for gcc8 and cross-compilation
    oldPkgs = import nixpkgs-old {
      system = buildSystem;
      config.permittedInsecurePackages = ["python-2.7.18.6"];
    };

    # Cross pkgs for aarch64
    crossPkgs = buildPkgs.pkgsCross.aarch64-multiplatform;

    # Historical cross-compilers for controlled vendor-kernel comparisons.
    # The known-good binary identifies Debian GCC 6.3.0; nixpkgs 23.05 gives
    # us GCC 6.5 and GCC 8.5 as reproducible first-pass comparison points.
    gcc6Cross = oldPkgs.pkgsCross.aarch64-multiplatform.buildPackages.gcc6;
    gcc8Cross = oldPkgs.pkgsCross.aarch64-multiplatform.buildPackages.gcc8;

    #############################################
    # MTK Flash Tool
    #############################################
    mtkFlashTool = buildPkgs.callPackage ./pkgs/mtk-flash-tool.nix {};

    # Udev rules for MTK devices
    mtkUdevRules = buildPkgs.writeTextFile {
      name = "mtk-udev-rules";
      destination = "/etc/udev/rules.d/99-mtk.rules";
      text = ''
        # MediaTek devices - prevent ModemManager from grabbing them
        ATTRS{idVendor}=="0e8d", ENV{ID_MM_DEVICE_IGNORE}="1"
        ATTRS{idVendor}=="6000", ENV{ID_MM_DEVICE_IGNORE}="1"
        # Allow user access
        SUBSYSTEM=="usb", ATTRS{idVendor}=="0e8d", MODE="0666"
        SUBSYSTEM=="usb", ATTRS{idVendor}=="6000", MODE="0666"
      '';
    };

    # Shared NixOS modules
    sharedModules = [
      ./nixos/configuration.nix
      ./nixos/firmware.nix
    ];

    #############################################
    # Vendor Kernel
    #############################################
    vendorKernelRevision = "51e705e4e7b1e52a31a79985f7fbbc9e98b59c8c";

    # Match nixpkgs' normal kernel policy.  The generic stdenv wrapper enables
    # userspace hardening by default; most of it is either overridden by
    # Kbuild or irrelevant to a static kernel, but disabling it is a cheap and
    # explicit reproducibility control.  Current stdenv has no `pie` hardening
    # flag (and does not enable PIE here), so this is the applicable subset of
    # nixpkgs 23.05's six-item kernel list.
    kernelHardeningDisable = [
      "bindnow"
      "format"
      "fortify"
      "stackprotector"
      "pic"
    ];

    mkVendorKernel = {
      pname,
      crossCompiler,
      compilerLabel,
      variant,
      configCommands ? "",
      hardeningDisable ? kernelHardeningDisable,
    }:
      buildPkgs.stdenv.mkDerivation {
        inherit pname hardeningDisable;
        version = "3.18.41";

        # Freeze the embedded release metadata to the working kernel.  Besides
        # making repeated builds comparable, this removes several irrelevant
        # string differences from compiler/output-size comparisons.
        KBUILD_BUILD_TIMESTAMP = "Fri Mar 29 10:39:03 GMT 2019";
        KBUILD_BUILD_VERSION = "7";
        KBUILD_BUILD_USER = "dguidi";
        KBUILD_BUILD_HOST = "nowhere";
        LOCALVERSION = "+";
        SOURCE_DATE_EPOCH = "1553855943";

        src = vendor-kernel;

        patches = [
          ./patches/gcc10-extern_YYLOC.patch
          ./patches/fix-drvgen-makefile.patch
          ./patches/fix-wlan-include-order.patch
          ./patches/fix-mediatek-include-paths.patch
        ];

        postPatch = ''
          find . \( -name "Makefile*" -o -name "*.mk" \) -exec sed -i 's/-Werror=[^) ,]*//g' {} \;
          find . \( -name "Makefile*" -o -name "*.mk" \) -exec sed -i 's/ -Werror / /g' {} \;
          find . \( -name "Makefile*" -o -name "*.mk" \) -exec sed -i 's/-Werror$//g' {} \;
        '';

        nativeBuildInputs =
          (with buildPkgs; [bc bison flex openssl perl ncurses elfutils dtc hostname])
          ++ [oldPkgs.python2 crossCompiler];

        depsBuildBuild = [buildPkgs.stdenv.cc];

        makeFlags = [
          "ARCH=arm64"
          "CROSS_COMPILE=aarch64-unknown-linux-gnu-"
          "python=python2"
          "KCFLAGS=-Wno-error"
        ];

        configurePhase = ''
          runHook preConfigure
          # Generic stdenv adds `$out/lib` as an RPATH.  ARM64 Kbuild embeds its
          # dynamically linked vDSO inside Image, so leaving NIX_LDFLAGS intact
          # leaks the changing derivation path into the kernel payload.
          unset NIX_LDFLAGS
          # Start every diagnostic row from the exact configuration recovered
          # from the working 2019 Gemian kernel.  Variant-specific changes are
          # then visible here and in the installed config hash.
          cp ${./research/vendor-kernel.config} .config
          make $makeFlags olddefconfig
          ${configCommands}
          make $makeFlags olddefconfig
          runHook postConfigure
        '';

        buildPhase = ''
          runHook preBuild
          make $makeFlags -j$NIX_BUILD_CORES Image.gz
          runHook postBuild
        '';

        installPhase = ''
          runHook preInstall
          mkdir -p $out
          cp arch/arm64/boot/Image.gz $out/

          # Preserve the exact 130745-byte DTB from the running Gemian kernel.
          # Only the compressed kernel payload changes; this avoids introducing
          # a second, untested hardware description at the same time.
          tail -c +8299081 ${./blobs/Gemian-Image.gz-dtb} > $out/gemini.dtb
          cat $out/Image.gz $out/gemini.dtb > $out/Image.gz-dtb
          cp .config $out/kernel.config
          diff -u \
            --label live-kernel.config \
            --label generated-kernel.config \
            ${./research/vendor-kernel.config} $out/kernel.config \
            > $out/kernel.config.diff || true
          # Retain the exact symbols used by the flashed image so watchdog/AEE
          # program counters can be resolved without reconstructing the build.
          cp vmlinux System.map $out/

          {
            echo "variant=${variant}"
            echo "source-revision=${vendorKernelRevision}"
            echo "compiler-label=${compilerLabel}"
            printf 'compiler='
            aarch64-unknown-linux-gnu-gcc --version | head -n 1
            printf 'linker='
            aarch64-unknown-linux-gnu-ld --version | head -n 1
            echo "hardening-disable=${builtins.concatStringsSep "," hardeningDisable}"
            echo "nix-ldflags=unset (prevents output RPATH in embedded vDSO)"
            echo "known-good-kernel-sha256=b53d191dc41d3f7364b0fa62b4bc920b1d013a1942b2e6b06727263fc56fcf4d"
            echo "live-config-sha256=231d8a2ffe7afac3a4cc62c27d0eb6fe8bd9165ebd096e3e3346dd6df35c18f4"
            (
              cd $out
              sha256sum \
                kernel.config \
                kernel.config.diff \
                Image.gz \
                gemini.dtb \
                Image.gz-dtb \
                vmlinux \
                System.map
              stat -c '%n size=%s' \
                Image.gz \
                gemini.dtb \
                Image.gz-dtb \
                vmlinux
            )
          } > $out/BUILD-MANIFEST
          runHook postInstall
        '';

        dontStrip = true;
        dontPatchELF = true;
      };

    # Test rows A-C deliberately alter one input at a time.  Do not add USB
    # options until one of these exact-live-config baselines has booted.
    vendorKernelBaselineGcc8 = mkVendorKernel {
      pname = "linux-gemini-vendor-baseline-gcc8";
      crossCompiler = gcc8Cross;
      compilerLabel = "nixpkgs-23.05-gcc-8.5";
      variant = "A: live config, GCC 8.5, kernel hardening disabled";
    };

    vendorKernelBaselineGcc8Hardened = mkVendorKernel {
      pname = "linux-gemini-vendor-baseline-gcc8-wrapper-hardening";
      crossCompiler = gcc8Cross;
      compilerLabel = "nixpkgs-23.05-gcc-8.5";
      variant = "B: live config, GCC 8.5, wrapper hardening retained";
      hardeningDisable = [];
    };

    vendorKernelBaselineGcc6 = mkVendorKernel {
      pname = "linux-gemini-vendor-baseline-gcc6";
      crossCompiler = gcc6Cross;
      compilerLabel = "nixpkgs-23.05-gcc-6.5";
      variant = "C: live config, GCC 6.5, kernel hardening disabled";
    };

    vendorKernel = mkVendorKernel {
      pname = "linux-gemini-vendor-usb-ncm-gcc8";
      crossCompiler = gcc8Cross;
      compilerLabel = "nixpkgs-23.05-gcc-8.5";
      variant = "D: live config plus USB_NCM and no Anbox, GCC 8.5";
      configCommands = ''
        # The attached RTL8156 exposes a standards-compliant CDC-NCM
        # configuration.  Test this row only after a baseline kernel boots.
        bash scripts/config \
          --enable USB_USBNET \
          --enable USB_NET_CDC_NCM \
          --disable USB_NET_AX8817X \
          --disable USB_NET_AX88179_178A \
          --disable USB_NET_CDCETHER \
          --disable USB_NET_NET1080 \
          --disable USB_NET_CDC_SUBSET \
          --disable USB_BELKIN \
          --disable USB_ARMLINUX \
          --disable USB_NET_ZAURUS \
          --disable ANBOX \
          --disable ANBOX_BINDER_IPC
      '';
    };

    #############################################
    # Upstream-derived ixoo kernel
    #############################################
    mainline = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
    };

    # A binary-search control for the failed p30 attempt.  It retains ixoo's
    # exact selected config (including its raw entry ledger and serial-only
    # cmdline) while applying only the corrected no-wrapper-hardening build
    # environment.  The normal `mainline` output adds the diagnostic overlay.
    mainlineConfigControl = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = false;
    };

    # First useful mainline stage after the storage-inert boot proof.  Keep the
    # same proven gadget/debug path, add ixoo's hardware-passed 25 MHz eMMC
    # enumeration fragment, and replace the unauthenticated nc shell with a
    # key-only Dropbear daemon listening on every IPv4 interface.
    mainlineStorageSsh = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
    };

    # Second storage stage: retain the exact key-only SSH and eMMC-enumeration
    # image, then mount p29 with ext4's journal replay disabled and inspect only
    # the /nixos directory metadata.  It never remounts or writes p29.
    mainlineRootfsProbe = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      rootfsProbe = true;
    };

    # Full mainline platform image: the proven storage/SSH baseline plus the
    # physical right-port USB11 MUSB host and built-in RTL815x support.
    mainlineNixosPlatform = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
    };

    # One-shot Stage-B image: preserve the booted storage/SSH/USB platform,
    # then activate only the reset-held, bounded CONSYS identity overlay.
    mainlineConsysIdentity = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysIdentityOverlay = true;
    };

    # Critical-path radio-subsystem experiment. This keeps the accepted
    # storage, SSH, dual-USB and watchdog substrate, then performs the complete
    # no-firmware G2b chronology in one boot: persistent EMI, reset-held 0x0279
    # identity, MBIST/AFE/reset release, and raw/mandatory/full WMT queries.
    # It never requests a patch or enables a radio function.
    mainlineConsysG2bNoFirmware = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-next;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysG2bOverlay = true;
      unattendedRecovery = true;
    };

    # Firmware-preflight companion to G2b. It packages only the three
    # byte-identified Gemini WMT inputs under the bare names requested by the
    # controller. The existing G2b command line deliberately leaves patch
    # download and every radio function disabled.
    mainlineConsysFirmwarePreflight = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-next;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysG2bOverlay = true;
      consysFirmware = true;
      unattendedRecovery = true;
    };

    # G2c is prepared, not implied: it is for a later p22-only cycle after a
    # corrected G2b run has proved raw HCR/HVR/FVR and the full-STP query. It
    # alone enables the hash-pinned patch gate, then fences before any radio
    # function can be created.
    mainlineConsysG2cPatchOnly = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-next;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysG2cPatchOverlay = true;
      unattendedRecovery = true;
    };

    # G2d completes the vendor post-patch firmware initialisation inside the
    # G2c retained full-STP lifecycle. It is a p22-only, watchdog-protected
    # owner swap: G2c's DT node and boot gate stay disabled, and no radio
    # function/client is exposed.
    mainlineConsysG2dPostpatch = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-next;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysG2dPostpatchOverlay = true;
      unattendedRecovery = true;
    };

    # W1 follows the hardware-passed W0 CMD53 portal read. It sends only the
    # SHA-pinned image, proves WCIR.READY, then fences IRQ delivery and every
    # WLAN client because the vendor tree has no isolated post-enable IRQ
    # event. This output is build/stage-only; it does not authorize a flash.
    mainlineWifiW1Ready = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-w1-candidate;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysG2dPostpatchOverlay = true;
      wifiW0Observe = true;
      wifiW1FirmwareReadyProof = true;
      unattendedRecovery = true;
    };

    # W1 forensic successor to the safely failed READY candidate. It carries
    # the same deliberately fenced device policy, but its committed kernel
    # records every causal portal and PALDO cleanup result before any next
    # hardware review. This output is not authorization to flash.
    mainlineWifiW1Forensic = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-w1-forensic-candidate;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      consysG2dPostpatchOverlay = true;
      wifiW0Observe = true;
      wifiW1FirmwareReadyProof = true;
      wifiW1Forensic = true;
      unattendedRecovery = true;
    };

    # Critical-path GPU identity experiment. It keeps the accepted recovery
    # substrate, then exclusively votes RT5735 and all four MFG domains,
    # enables BG3D, reads immutable Mali-T880 identity/features, and unwinds.
    # The real GPU node remains disabled, so Panfrost cannot bind or submit.
    mainlineGpuStaged = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-next;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      gpuStagedOverlay = true;
      unattendedRecovery = true;
    };

    # First real Panfrost binding experiment.  Keep the boot-proven recovery,
    # eMMC, SSH and dual-USB substrate, but expose exactly one GPU OPP: the
    # already-programmed 500.5 MHz clock at the vendor type-12 975 mV voltage.
    # There is deliberately no DVFS table and no staged diagnostic transaction.
    mainlineGpuFixedOpp = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        ixoo-candidate
        ;
      linux-gemini = linux-gemini-next;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      gpuFixedOppOverlay = true;
      unattendedRecovery = true;
    };

    # Queued Stage-C recovery image: test the reviewed native display and
    # MT6351 audio-card enumeration together.  Touch support is built in but
    # its contradictory rail/EINT candidate remains disabled in the base DT.
    mainlinePlatformSmoke = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
    };

    # Queued Stage-D recovery image: retain the combined platform smoke test
    # and add only the independently routed BQ2589x no-write/no-IRQ observer.
    mainlinePlatformRecovery = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
      powerObserveOverlay = true;
    };

    # Unattended p22 recovery control: retain the boot-proven storage/SSH
    # baseline and add only the built-in MTK watchdog plus initramfs petter.
    # This isolates recovery validation from display/audio/power/keyboard.
    mainlineUnattendedRecoveryWatchdog = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      unattendedRecovery = true;
    };

    # Combined platform queue: the same unattended recovery substrate, with
    # the already reviewed right-port platform enablement layered on top.
    mainlineUnattendedRecoveryPlatform = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      unattendedRecovery = true;
    };

    # One-shot Stage-D acceptance image.  The BQ2589x DT observer remains
    # opt-in, and this extra collector only records bounded read-only evidence
    # for a remote reviewer; it never takes the watchdog lease itself.
    mainlineUnattendedRecoveryPowerPreflight = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
      powerObserveOverlay = true;
      powerObservePreflight = true;
      unattendedRecovery = true;
    };

    # Input-observability increment over the exact unattended full-platform
    # candidate above.  It composes the reviewed AW9523 polling keyboard
    # overlay and an I2C4-only touchscreen observer; the touchscreen client,
    # VTOUCH rail, and reset line remain disabled/untouched.
    mainlineUnattendedRecoveryInputObserve = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
      powerObserveOverlay = true;
      powerObservePreflight = true;
      unattendedRecovery = true;
      inputObserveOverlay = true;
      thermalHallObserveOverlay = true;
    };

    # First combined unattended hardware image. It retains the full
    # display/audio/power/input observation chain, then enables only the
    # touchscreen, FGADC, and conservative 3.0V MicroSD contracts that were
    # proven on the live rescue kernel. Native DRM remains behind the kernel's
    # one-way userspace activation gate; this image never writes it itself.
    mainlineUnattendedRecoveryDeviceActivation = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
      powerObserveOverlay = true;
      powerObservePreflight = true;
      unattendedRecovery = true;
      inputObserveOverlay = true;
      thermalHallObserveOverlay = true;
      deviceActivationOverlay = true;
    };

    # Cycle 18 full-NixOS baseline candidate. Keep the accepted Stage-2/eMMC
    # lineage, both USB paths, BQ observer and watchdog self-accept intact.
    # The DSI gate is released by the corresponding Stage-1 constructor only
    # after watchdog ownership is established. Touchscreen and FGADC are
    # explicit independent components; MicroSD is deliberately absent.
    mainlineP22Baseline = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
      powerObserveOverlay = true;
      powerObservePreflight = true;
      unattendedRecovery = true;
      inputObserveOverlay = true;
      thermalHallObserveOverlay = true;
      touchscreenActivationOverlay = true;
      fgadcActivationOverlay = true;
    };

    # Manual-only staged ALSA boundary diagnostic over the existing fully
    # observable recovery profile. It adds a static helper to the initramfs
    # but never invokes it: default execution only observes the named card;
    # an operator must explicitly select and activate each later stage.
    mainlineUnattendedRecoveryDeviceActivationAudioHeadphone = import ./nix/mainline.nix {
      inherit
        buildPkgs
        oldPkgs
        crossPkgs
        ixoo-kernel
        linux-gemini
        ixoo-candidate
        ;
      debugOverlay = true;
      storageOverlay = true;
      sshAccess = true;
      usbHostOverlay = true;
      platformEnablement = true;
      displayOverlay = true;
      audioOverlay = true;
      audioHeadphoneTest = true;
      powerObserveOverlay = true;
      powerObservePreflight = true;
      unattendedRecovery = true;
      inputObserveOverlay = true;
      thermalHallObserveOverlay = true;
      deviceActivationOverlay = true;
    };

    #############################################
    # NixOS System - Cross-compiled from x86_64
    #############################################
    nixosSystemCross = nixpkgs-old.lib.nixosSystem {
      system = buildSystem;
      modules =
        sharedModules
        ++ [
          {
            nixpkgs.hostPlatform = targetSystem;
            nixpkgs.buildPlatform = buildSystem;
          }
        ];
    };

    mainlineNixosSystemCross = nixpkgs-old.lib.nixosSystem {
      system = buildSystem;
      modules = [
        ./nixos/mainline-configuration.nix
        {
          _module.args.geminiLeaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
        }
        {
          nixpkgs.hostPlatform = targetSystem;
          nixpkgs.buildPlatform = buildSystem;
        }
      ];
    };

    #############################################
    # Squashfs builder
    #############################################
    mkSquashfs = pkgs: nixosToplevel:
      pkgs.runCommand "nixos.squashfs" {
        nativeBuildInputs = [pkgs.squashfsTools];
      } ''
        mkdir -p store-contents
        for path in $(cat ${pkgs.closureInfo {rootPaths = [nixosToplevel];}}/store-paths); do
          cp -a $path store-contents/
        done
        # Keep the selected toplevel inside the atomically replaced image.
        # Stage 1 can now remain unchanged across userspace-only rebuilds.
        basename ${nixosToplevel} > store-contents/.gemini-system
        # The known-good Gemian kernel has SquashFS XZ support but no Zstd
        # support. The store is immutable at runtime, so it does not need an
        # OverlayFS upper layer.
        mksquashfs store-contents $out \
          -comp xz -b 131072 -noappend -all-root -no-progress
      '';

    nixosSquashfs =
      mkSquashfs buildPkgs nixosSystemCross.config.system.build.toplevel;

    # Linux SquashFS names the zlib codec "gzip".  Keep this distinct from
    # the vendor-kernel XZ payload and install it under a new p29 filename.
    mainlineNixosSquashfs = buildPkgs.runCommand "mainline-nixos-zlib.squashfs" {
      nativeBuildInputs = [buildPkgs.squashfsTools];
    } ''
      mkdir -p store-contents
      for path in $(cat ${buildPkgs.closureInfo {
        rootPaths = [mainlineNixosSystemCross.config.system.build.toplevel];
      }}/store-paths); do
        cp -a "$path" store-contents/
      done
      basename ${mainlineNixosSystemCross.config.system.build.toplevel} \
        > store-contents/.gemini-system
      mksquashfs store-contents "$out" \
        -comp gzip -b 131072 -noappend -all-root -no-progress
      unsquashfs -s "$out" | grep -Fqx 'Compression gzip'
    '';

    mainlineSshdPam = mainlineNixosSystemCross.config.environment.etc."pam.d/sshd".source;
    mainlineSshPamSessionCheck = buildPkgs.runCommand "mainline-sshd-pam-session-check" {} ''
      grep -Fqx 'session required pam_unix.so' ${mainlineSshdPam}
      ! grep -Fq 'pam_systemd.so' ${mainlineSshdPam}
      touch "$out"
    '';

    mainlineNixos = import ./nix/mainline-nixos.nix {
      inherit buildPkgs crossPkgs ixoo-kernel;
      # Cycle 18's full Stage-2/eMMC substrate with explicit active display,
      # NT36772 and FGADC components. The profile cannot pull MicroSD from the
      # retired all-or-nothing device-activation overlay.
      kernel = mainlineP22Baseline.kernel;
      serviceabilityDtb = mainlineP22Baseline.serviceabilityDtb;
      squashfs = mainlineNixosSquashfs;
      nixosToplevel = mainlineNixosSystemCross.config.system.build.toplevel;
      authorizedKeys = ./nixos/authorized_keys;
      bq2589xPreflight = ./nix/bq2589x-preflight.sh;
      unattendedRecovery = true;
      inputDiagnostics = true;
      displayActivation = true;
      provisionStore = true;
      # Cycle 7 proved the RTL8156 Stage1 path but the one-time 100,421,632-byte
      # p29 install still exceeded 230 seconds.  Give the complete write,
      # digest and journal sync ten minutes, with two minutes left for the
      # watchdog to recover a stalled installer without human intervention.
      provisionWaitSeconds = 600;
      watchdogLeaseSeconds = 720;
      leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;
    };

    #############################################
    # Initramfs
    #############################################
    initramfs =
      buildPkgs.runCommand "initramfs.cpio.gz" {
        nativeBuildInputs = [buildPkgs.cpio buildPkgs.gzip];
        busybox = crossPkgs.pkgsStatic.busybox;
      } ''
        mkdir -p initrd/{bin,dev,lib/firmware,mnt/gemian,mnt/nixos,proc,sys}

        cp $busybox/bin/busybox initrd/bin/

        # These built-in drivers can ask for firmware before stage 2 exists.
        # Keeping the board-specific set in the initramfs makes the kernel's
        # direct firmware loader work without Android's ueventd fallback.
        cp ${./blobs/ROMv3_patch_1_0_hdr.bin} initrd/lib/firmware/ROMv3_patch_1_0_hdr.bin
        cp ${./blobs/ROMv3_patch_1_1_hdr.bin} initrd/lib/firmware/ROMv3_patch_1_1_hdr.bin
        cp ${./blobs/WIFI_RAM_CODE_6797} initrd/lib/firmware/WIFI_RAM_CODE_6797
        cp ${./blobs/WMT_SOC.cfg} initrd/lib/firmware/WMT_SOC.cfg
        cp ${./blobs/mt6631_fm_v1_coeff.bin} initrd/lib/firmware/mt6631_fm_v1_coeff.bin
        cp ${./blobs/mt6631_fm_v1_patch.bin} initrd/lib/firmware/mt6631_fm_v1_patch.bin
        cp ${./blobs/novatek_ts_fw.bin} initrd/lib/firmware/novatek_ts_fw.bin
        cp ${./blobs/pcm_deepidle.bin} initrd/lib/firmware/pcm_deepidle.bin
        cp ${./blobs/pcm_sodi.bin} initrd/lib/firmware/pcm_sodi.bin
        cp ${./blobs/pcm_suspend.bin} initrd/lib/firmware/pcm_suspend.bin

        cat > initrd/init << 'INIT'
        #!/bin/busybox sh
        /bin/busybox --install -s /bin
        mount -t proc none /proc
        mount -t sysfs none /sys
        mount -t devtmpfs none /dev

        PATH=/bin
        export PATH

        exec </dev/console >/dev/console 2>&1

        LOG=/dev/kmsg
        log() {
          echo "gemini-initrd: $*"
          echo "gemini-initrd: $*" >> "$LOG" 2>/dev/null || true
        }

        log "========================================"
        log "NixOS Gemini initramfs"
        log "  $(date 2>/dev/null || echo 'no date')"
        log "========================================"

        log "waiting for /dev/mmcblk0p29"
        attempt=0
        while [ ! -b /dev/mmcblk0p29 ] && [ "$attempt" -lt 30 ]; do
          attempt=$((attempt + 1))
          sleep 1
        done

        if [ ! -b /dev/mmcblk0p29 ]; then
          log "ERROR: Linux partition did not appear"
          cat /proc/partitions
          exec /bin/sh
        fi

        if ! mount -t ext4 -o rw /dev/mmcblk0p29 /mnt/gemian; then
          log "ERROR: could not mount the Linux partition"
          exec /bin/sh
        fi

        LOG=/mnt/gemian/nixos-boot.log
        : > "$LOG"
        log "mounted the persistent Linux partition"

        SQUASHFS=/mnt/gemian/nixos/nixos.squashfs
        if [ ! -f "$SQUASHFS" ]; then
          log "ERROR: missing $SQUASHFS"
          sync
          exec /bin/sh
        fi

        log "found NixOS store image"
        if ! mount -t tmpfs -o mode=0755,size=768M tmpfs /mnt/nixos; then
          log "ERROR: could not mount the tmpfs root"
          exec /bin/sh
        fi

        # Keep stage 1 strictly POSIX-sh-compatible.  BusyBox ash supports
        # these paths directly; relying on optional brace expansion here only
        # creates a needless failure mode in the recovery-critical initramfs.
        mkdir -p \
          /mnt/nixos/dev \
          /mnt/nixos/etc \
          /mnt/nixos/gemian \
          /mnt/nixos/proc \
          /mnt/nixos/run \
          /mnt/nixos/sys \
          /mnt/nixos/tmp \
          /mnt/nixos/var \
          /mnt/nixos/nix/store \
          /mnt/nixos/nix/var/nix/gcroots \
          /mnt/nixos/nix/var/nix/profiles \
          /mnt/nixos/nix/var/nix/temproots

        loopdev=$(losetup -f 2>/dev/null || true)
        if [ -z "$loopdev" ]; then
          log "ERROR: no loop device is available"
          exec /bin/sh
        fi
        if ! losetup "$loopdev" "$SQUASHFS"; then
          log "ERROR: could not attach the NixOS store image"
          exec /bin/sh
        fi
        if ! mount -t squashfs -o ro "$loopdev" /mnt/nixos/nix/store; then
          log "ERROR: could not mount the NixOS store image"
          sync
          exec /bin/sh
        fi

        SYSTEM_POINTER=/mnt/nixos/nix/store/.gemini-system
        if [ ! -s "$SYSTEM_POINTER" ]; then
          log "ERROR: the store image has no NixOS system pointer"
          exec /bin/sh
        fi
        NIXOS_SYSTEM="/nix/store/$(cat "$SYSTEM_POINTER")"
        NIXOS_INIT="$NIXOS_SYSTEM/init"
        if [ ! -x "/mnt/nixos$NIXOS_INIT" ]; then
          log "ERROR: $NIXOS_INIT is absent from the store image"
          exec /bin/sh
        fi

        log "store mounted; preparing stage 2"
        mount --move /mnt/gemian /mnt/nixos/gemian
        LOG=/mnt/nixos/gemian/nixos-boot.log
        mount --move /proc /mnt/nixos/proc
        mount --move /sys /mnt/nixos/sys
        mount --move /dev /mnt/nixos/dev
        mount -t tmpfs -o mode=0755 tmpfs /mnt/nixos/run
        mount -t tmpfs -o mode=1777 tmpfs /mnt/nixos/tmp
        ln -s "$NIXOS_SYSTEM" /mnt/nixos/run/current-system

        log "switching root to $NIXOS_INIT"
        sync
        exec switch_root /mnt/nixos $NIXOS_INIT
        INIT
        chmod +x initrd/init

        (cd initrd && find . -print0 | cpio --null -o -H newc | gzip -n -9 > $out)
      '';

    #############################################
    # First-boot probe
    #############################################
    # Keep the kernel and appended DTB from the known-working Gemian boot
    # partition.  The probe changes only the ramdisk, which lets us test the
    # LK -> kernel -> initramfs path independently of the custom kernel and
    # NixOS userspace.
    probeInitramfs =
      buildPkgs.runCommand "gemini-probe-initramfs.cpio.gz" {
        nativeBuildInputs = [buildPkgs.cpio buildPkgs.gzip];
        busybox = crossPkgs.pkgsStatic.busybox;
      } ''
        mkdir -p root/{bin,dev,mnt/linux,proc,sys}
        cp $busybox/bin/busybox root/bin/

        cat > root/init <<'INIT'
        #!/bin/busybox sh

        export PATH=/bin
        /bin/busybox --install -s /bin

        mount -t proc proc /proc 2>/dev/null || true
        mount -t sysfs sysfs /sys 2>/dev/null || true
        mount -t devtmpfs devtmpfs /dev 2>/dev/null || true

        exec </dev/console >/dev/console 2>&1

        say() {
          echo "gemini-probe: $*"
          echo "<6>gemini-probe: $*" > /dev/kmsg 2>/dev/null || true
        }

        say "known-good Gemian kernel reached the probe initramfs"
        say "waiting for the Linux partition"

        attempt=0
        while [ ! -b /dev/mmcblk0p29 ] && [ "$attempt" -lt 30 ]; do
          attempt=$((attempt + 1))
          sleep 1
        done

        if [ ! -b /dev/mmcblk0p29 ]; then
          say "ERROR: /dev/mmcblk0p29 did not appear"
          cat /proc/partitions 2>/dev/null || true
          exec /bin/sh
        fi

        if ! mount -t ext4 -o rw /dev/mmcblk0p29 /mnt/linux; then
          say "ERROR: could not mount /dev/mmcblk0p29"
          dmesg | tail -100
          exec /bin/sh
        fi

        LOG=/mnt/linux/nixos-probe.log
        {
          echo "Gemini NixOS boot probe: SUCCESS"
          echo "probe-version: 1"
          echo "date: $(date -u 2>/dev/null || true)"
          echo "uname: $(uname -a 2>/dev/null || true)"
          echo "cmdline: $(cat /proc/cmdline 2>/dev/null || true)"
          echo
          echo "Block devices:"
          cat /proc/partitions 2>/dev/null || true
          echo
          echo "Recent kernel log:"
          dmesg | tail -200 2>/dev/null || true
        } > "$LOG"

        sync
        say "SUCCESS: wrote /nixos-probe.log on the Linux partition"
        say "probe complete; dropping to a console shell"
        exec /bin/sh
        INIT
        chmod +x root/init

        (cd root && find . -print0 | cpio --null -o -H newc | gzip -n -9 > $out)
      '';

    mkProbeBootImage = name: kernel:
      buildPkgs.runCommand name {
        nativeBuildInputs = [buildPkgs.android-tools];
      } ''
        mkbootimg \
          --kernel ${kernel} \
          --ramdisk ${probeInitramfs} \
          --base 0x40000000 \
          --kernel_offset 0x00080000 \
          --ramdisk_offset 0x05000000 \
          --second_offset 0x00f00000 \
          --tags_offset 0x04000000 \
          --pagesize 2048 \
          --cmdline "bootopt=64S3,32N2,64N2 log_buf_len=4M" \
          -o $out

        # boot2/boot3 are 16 MiB partitions.
        test "$(stat -c %s $out)" -le 16777216
      '';

    probeBootImg =
      mkProbeBootImage "gemini-known-good-probe-boot.img"
      ./blobs/Gemian-Image.gz-dtb;

    baselineProbeBootImgGcc8 =
      mkProbeBootImage "gemini-baseline-gcc8-probe-boot.img"
      "${vendorKernelBaselineGcc8}/Image.gz-dtb";

    baselineProbeBootImgGcc8Hardened =
      mkProbeBootImage "gemini-baseline-gcc8-hardened-probe-boot.img"
      "${vendorKernelBaselineGcc8Hardened}/Image.gz-dtb";

    baselineProbeBootImgGcc6 =
      mkProbeBootImage "gemini-baseline-gcc6-probe-boot.img"
      "${vendorKernelBaselineGcc6}/Image.gz-dtb";

    usbNcmProbeBootImg =
      mkProbeBootImage "gemini-usb-ncm-gcc8-probe-boot.img"
      "${vendorKernel}/Image.gz-dtb";

    #############################################
    # Boot image
    #############################################
    mkBootImage = name: kernel:
      buildPkgs.runCommand name {
        nativeBuildInputs = [buildPkgs.android-tools];
      } ''
        mkbootimg \
          --kernel ${kernel} \
          --ramdisk ${initramfs} \
          --base 0x40000000 \
          --kernel_offset 0x00080000 \
          --ramdisk_offset 0x05000000 \
          --second_offset 0x00f00000 \
          --tags_offset 0x04000000 \
          --pagesize 2048 \
          --cmdline "bootopt=64S3,32N2,64N2 log_buf_len=4M systemd.unified_cgroup_hierarchy=0" \
          -o $out

        test "$(stat -c %s $out)" -le 16777216
      '';

    # The locally rebuilt payload currently reaches the kernel entry point but
    # is reset by the MediaTek watchdog before initramfs.  Keep it available
    # for diagnosis, but deploy the exact byte-for-byte working Gemian kernel
    # while we validate the NixOS userspace and hardware integration.
    rebuiltBootImg =
      mkBootImage "gemini-rebuilt-kernel-boot.img" "${vendorKernel}/Image.gz-dtb";
    knownGoodBootImg =
      mkBootImage "gemini-known-good-kernel-boot.img" ./blobs/Gemian-Image.gz-dtb;
    mkBootImg = knownGoodBootImg;

    deployBundle = buildPkgs.runCommand "gemini-nixos-deploy" {} ''
      mkdir -p $out
      ln -s ${mkBootImg} $out/boot.img
      ln -s ${nixosSquashfs} $out/nixos.squashfs
      {
        echo "system=${nixosSystemCross.config.system.build.toplevel}"
        sha256sum $out/boot.img $out/nixos.squashfs
      } > $out/MANIFEST
    '';

    diagnosticKernelBundle = buildPkgs.runCommand "gemini-vendor-kernel-diagnostic-matrix" {} ''
      mkdir -p $out
      ln -s ${vendorKernelBaselineGcc8} $out/A-kernel-gcc8
      ln -s ${baselineProbeBootImgGcc8} $out/A-probe-gcc8.img
      ln -s ${vendorKernelBaselineGcc8Hardened} $out/B-kernel-gcc8-hardened
      ln -s ${baselineProbeBootImgGcc8Hardened} $out/B-probe-gcc8-hardened.img
      ln -s ${vendorKernelBaselineGcc6} $out/C-kernel-gcc6
      ln -s ${baselineProbeBootImgGcc6} $out/C-probe-gcc6.img
      ln -s ${vendorKernel} $out/D-kernel-usb-ncm-gcc8
      ln -s ${usbNcmProbeBootImg} $out/D-probe-usb-ncm-gcc8.img
    '';
  in {
    # Packages built on x86_64
    packages.${buildSystem} = {
      kernel = vendorKernel;
      kernelBaselineGcc8 = vendorKernelBaselineGcc8;
      kernelBaselineGcc8Hardened = vendorKernelBaselineGcc8Hardened;
      kernelBaselineGcc6 = vendorKernelBaselineGcc6;
      bootImg = mkBootImg;
      rebuiltBootImg = rebuiltBootImg;
      deploy = deployBundle;
      diagnosticKernelBundle = diagnosticKernelBundle;
      initramfs = initramfs;
      probeBootImg = probeBootImg;
      baselineProbeBootImgGcc8 = baselineProbeBootImgGcc8;
      baselineProbeBootImgGcc8Hardened = baselineProbeBootImgGcc8Hardened;
      baselineProbeBootImgGcc6 = baselineProbeBootImgGcc6;
      usbNcmProbeBootImg = usbNcmProbeBootImg;
      probeInitramfs = probeInitramfs;
      mainlineKernel = mainline.kernel;
      mainlineServiceabilityDtb = mainline.serviceabilityDtb;
      mainlineProbeInitramfs = mainline.probeInitramfs;
      mainlineProbeBootImg = mainline.probeBootImg;
      mainlineProbeBoot2Img = mainline.probeBoot2Img;
      mainlineBundle = mainline.bundle;
      mainlineConfigControlKernel = mainlineConfigControl.kernel;
      mainlineConfigControlBundle = mainlineConfigControl.bundle;
      mainlineStorageSshKernel = mainlineStorageSsh.kernel;
      mainlineStorageSshProbeInitramfs = mainlineStorageSsh.probeInitramfs;
      mainlineStorageSshBundle = mainlineStorageSsh.bundle;
      mainlineRootfsProbeInitramfs = mainlineRootfsProbe.probeInitramfs;
      mainlineRootfsProbeBundle = mainlineRootfsProbe.bundle;
      mainlineNixosKernel = mainlineP22Baseline.kernel;
      mainlineNixosDtb = mainlineP22Baseline.serviceabilityDtb;
      mainlineNixosSquashfs = mainlineNixosSquashfs;
      mainlineSshPamSessionCheck = mainlineSshPamSessionCheck;
      mainlineNixosInitramfs = mainlineNixos.initramfs;
      mainlineNixosBundle = mainlineNixos.bundle;
      mainlineP22BaselineKernel = mainlineP22Baseline.kernel;
      mainlineP22BaselineDtb = mainlineP22Baseline.serviceabilityDtb;
      mainlineConsysIdentityKernel = mainlineConsysIdentity.kernel;
      mainlineConsysIdentityDtb = mainlineConsysIdentity.serviceabilityDtb;
      mainlineConsysIdentityBundle = mainlineConsysIdentity.bundle;
      mainlineConsysG2bNoFirmwareKernel = mainlineConsysG2bNoFirmware.kernel;
      mainlineConsysG2bNoFirmwareDtb = mainlineConsysG2bNoFirmware.serviceabilityDtb;
      mainlineConsysG2bNoFirmwareInitramfs = mainlineConsysG2bNoFirmware.probeInitramfs;
      mainlineConsysG2bNoFirmwareBundle = mainlineConsysG2bNoFirmware.bundle;
      mainlineConsysFirmwarePreflightKernel = mainlineConsysFirmwarePreflight.kernel;
      mainlineConsysFirmwarePreflightDtb = mainlineConsysFirmwarePreflight.serviceabilityDtb;
      mainlineConsysFirmwarePreflightInitramfs = mainlineConsysFirmwarePreflight.probeInitramfs;
      mainlineConsysFirmwarePreflightBundle = mainlineConsysFirmwarePreflight.bundle;
      mainlineConsysG2cPatchOnlyKernel = mainlineConsysG2cPatchOnly.kernel;
      mainlineConsysG2cPatchOnlyDtb = mainlineConsysG2cPatchOnly.serviceabilityDtb;
      mainlineConsysG2cPatchOnlyInitramfs = mainlineConsysG2cPatchOnly.probeInitramfs;
      mainlineConsysG2cPatchOnlyBundle = mainlineConsysG2cPatchOnly.bundle;
      mainlineConsysG2dPostpatchKernel = mainlineConsysG2dPostpatch.kernel;
      mainlineConsysG2dPostpatchDtb = mainlineConsysG2dPostpatch.serviceabilityDtb;
      mainlineConsysG2dPostpatchInitramfs = mainlineConsysG2dPostpatch.probeInitramfs;
      mainlineConsysG2dPostpatchBundle = mainlineConsysG2dPostpatch.bundle;
      mainlineWifiW1ReadyKernel = mainlineWifiW1Ready.kernel;
      mainlineWifiW1ReadyDtb = mainlineWifiW1Ready.serviceabilityDtb;
      mainlineWifiW1ReadyInitramfs = mainlineWifiW1Ready.probeInitramfs;
      mainlineWifiW1ReadyBundle = mainlineWifiW1Ready.bundle;
      mainlineWifiW1ForensicKernel = mainlineWifiW1Forensic.kernel;
      mainlineWifiW1ForensicDtb = mainlineWifiW1Forensic.serviceabilityDtb;
      mainlineWifiW1ForensicInitramfs = mainlineWifiW1Forensic.probeInitramfs;
      mainlineWifiW1ForensicBundle = mainlineWifiW1Forensic.bundle;
      mainlineGpuStagedKernel = mainlineGpuStaged.kernel;
      mainlineGpuStagedDtb = mainlineGpuStaged.serviceabilityDtb;
      mainlineGpuStagedInitramfs = mainlineGpuStaged.probeInitramfs;
      mainlineGpuStagedBundle = mainlineGpuStaged.bundle;
      mainlineGpuFixedOppKernel = mainlineGpuFixedOpp.kernel;
      mainlineGpuFixedOppDtb = mainlineGpuFixedOpp.serviceabilityDtb;
      mainlineGpuFixedOppInitramfs = mainlineGpuFixedOpp.probeInitramfs;
      mainlineGpuFixedOppBundle = mainlineGpuFixedOpp.bundle;
      mainlinePlatformSmokeKernel = mainlinePlatformSmoke.kernel;
      mainlinePlatformSmokeDtb = mainlinePlatformSmoke.serviceabilityDtb;
      mainlinePlatformSmokeBundle = mainlinePlatformSmoke.bundle;
      mainlinePlatformRecoveryKernel = mainlinePlatformRecovery.kernel;
      mainlinePlatformRecoveryDtb = mainlinePlatformRecovery.serviceabilityDtb;
      mainlinePlatformRecoveryBundle = mainlinePlatformRecovery.bundle;
      mainlineUnattendedRecoveryWatchdogKernel = mainlineUnattendedRecoveryWatchdog.kernel;
      mainlineUnattendedRecoveryWatchdogDtb = mainlineUnattendedRecoveryWatchdog.serviceabilityDtb;
      mainlineUnattendedRecoveryWatchdogBundle = mainlineUnattendedRecoveryWatchdog.bundle;
      mainlineUnattendedRecoveryKernel = mainlineUnattendedRecoveryPlatform.kernel;
      mainlineUnattendedRecoveryDtb = mainlineUnattendedRecoveryPlatform.serviceabilityDtb;
      mainlineUnattendedRecoveryBundle = mainlineUnattendedRecoveryPlatform.bundle;
      mainlineUnattendedRecoveryPowerPreflightKernel = mainlineUnattendedRecoveryPowerPreflight.kernel;
      mainlineUnattendedRecoveryPowerPreflightDtb = mainlineUnattendedRecoveryPowerPreflight.serviceabilityDtb;
      mainlineUnattendedRecoveryPowerPreflightInitramfs = mainlineUnattendedRecoveryPowerPreflight.probeInitramfs;
      mainlineUnattendedRecoveryPowerPreflightBundle = mainlineUnattendedRecoveryPowerPreflight.bundle;
      mainlineUnattendedRecoveryInputObserveKernel = mainlineUnattendedRecoveryInputObserve.kernel;
      mainlineUnattendedRecoveryInputObserveDtb = mainlineUnattendedRecoveryInputObserve.serviceabilityDtb;
      mainlineUnattendedRecoveryInputObserveInitramfs = mainlineUnattendedRecoveryInputObserve.probeInitramfs;
      mainlineUnattendedRecoveryInputObserveBundle = mainlineUnattendedRecoveryInputObserve.bundle;
      mainlineUnattendedRecoveryDeviceActivationKernel = mainlineUnattendedRecoveryDeviceActivation.kernel;
      mainlineUnattendedRecoveryDeviceActivationDtb = mainlineUnattendedRecoveryDeviceActivation.serviceabilityDtb;
      mainlineUnattendedRecoveryDeviceActivationInitramfs = mainlineUnattendedRecoveryDeviceActivation.probeInitramfs;
      mainlineUnattendedRecoveryDeviceActivationBundle = mainlineUnattendedRecoveryDeviceActivation.bundle;
      mainlineUnattendedRecoveryDeviceActivationAudioHeadphoneHelper = mainlineUnattendedRecoveryDeviceActivationAudioHeadphone.audioHeadphoneExercise;
      mainlineUnattendedRecoveryDeviceActivationAudioHeadphoneInitramfs = mainlineUnattendedRecoveryDeviceActivationAudioHeadphone.probeInitramfs;
      mainlineUnattendedRecoveryDeviceActivationAudioHeadphoneBundle = mainlineUnattendedRecoveryDeviceActivationAudioHeadphone.bundle;
      # Cross-compiled squashfs
      squashfs = nixosSquashfs;
      toplevel = nixosSystemCross.config.system.build.toplevel;
      # Flash tool
      flash-tool = mtkFlashTool;
      udev-rules = mtkUdevRules;
    };

    # NixOS configurations
    nixosConfigurations = {
      # Cross-compiled from x86_64 to aarch64.
      gemini = nixosSystemCross;
    };

    # Development shell
    devShells.${buildSystem}.default = buildPkgs.mkShell {
      packages = with buildPkgs; [
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
        echo "Gemini PDA development shell"
        echo ""
        echo "Build targets:"
        echo "  nix build .#kernel              - Vendor kernel (cross-compiled)"
        echo "  nix build .#bootImg             - Boot image"
        echo "  nix build .#squashfs            - NixOS squashfs (cross-compiled)"
      '';
    };
  };
}
