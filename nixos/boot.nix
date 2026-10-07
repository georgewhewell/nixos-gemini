# Normal generation installation; the initramfs keeps this volume read-only
# with its journal loaded, allowing the installer to remount it safely.
{lib, pkgs, ...}: let
  tools = pkgs.writeShellApplication {
    name = "gemini-boot-install";
    runtimeInputs = [pkgs.bash pkgs.coreutils pkgs.util-linux pkgs.e2fsprogs];
    text = ''
      export GEMINI_EFI_PUBLISH=${../nix/gemini-efi-publish.sh}
      exec ${pkgs.python3}/bin/python3 ${../nix/gemini-boot-install.py} "$@"
    '';
  };
in {
  environment.systemPackages = lib.mkForce [tools];
  system.build.geminiBootTools = tools;
}
