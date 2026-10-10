# Normal generation installation; the initramfs keeps this volume read-only
# with its journal loaded, allowing the installer to remount it safely.
{config, lib, pkgs, geminiBootKernel, geminiBootDtb, geminiBootInitrd, geminiBootManager, ...}: let
  tools = pkgs.writeShellApplication {
    name = "gemini-boot-install";
    runtimeInputs = [pkgs.bash pkgs.coreutils pkgs.util-linux pkgs.e2fsprogs pkgs.dtc config.nix.package];
    text = ''
      export GEMINI_EFI_PUBLISH=${../nix/gemini-efi-publish.sh}
      export GEMINI_BOOT_MANAGER=${geminiBootManager}
      exec ${pkgs.python3}/bin/python3 ${../nix/gemini-boot-install.py} "$@"
    '';
  };
in {
  environment.systemPackages = [tools];
  system.build.geminiBootTools = tools;
  system.build.installBootLoader = "${tools}/bin/gemini-boot-install --system";
  system.boot.loader.id = "gemini";
  system.systemBuilderCommands = ''
    ln -s ${geminiBootKernel}/Image "$out/kernel"
    ln -s ${geminiBootInitrd} "$out/initrd"
    ln -s ${geminiBootDtb}/gemini.dtb "$out/gemini.dtb"
    printf '%s\n' ${lib.escapeShellArg (lib.concatStringsSep " " config.boot.kernelParams)} > "$out/kernel-params"
  '';
}
