# Stage 1 mounts p32 (gemini-data) for /home and the registered Nix store
# at /persist/nixos/nix. Paging uses compressed RAM only, never flash.
{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.gemini.storage;
  zramProbe = import ../nix/zram-probe.nix { inherit pkgs; };

  provision = pkgs.writeShellApplication {
    name = "gemini-storage-provision";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.gnugrep
      pkgs.gnused
      pkgs.gptfdisk
      pkgs.e2fsprogs
      pkgs.util-linux
      config.systemd.package # udevadm
    ];
    text =
      builtins.replaceStrings ["@SWAP_PARTUUID@" "@DATA_LABEL@"]
      [(lib.toUpper cfg.swapPartUuid) cfg.dataLabel]
      (builtins.readFile ../nix/gemini-storage-provision.sh);
  };
in {
  options.gemini.storage = {
    dataLabel = lib.mkOption {
      type = lib.types.strMatching "[A-Za-z0-9_-]{1,16}";
      default = "gemini-data";
      description = "ext4 label of the p32 data filesystem (Stage 1 checks it).";
    };
    swapPartUuid = lib.mkOption {
      type = lib.types.strMatching "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
      default = "5e0f3a1c-9b2d-4c8e-a7f6-2d1b0c9e8a71";
      description = "GUID of the reserved p34 partition; the normal system never activates it as swap.";
    };
  };

  config = {
    system.build.geminiZramProbe = zramProbe;
    # Persistent home and the registered store are the normal boot path.
    nix.enable = true;
    swapDevices = [];
    zramSwap = {
      enable = true;
      algorithm = "lz4";
      memoryPercent = 50;
      writebackDevice = null;
    };
    assertions = [
      {
        assertion = config.swapDevices == [];
        message = "Gemini paging must use RAM-only zram, without eMMC or SD swap.";
      }
      {
        assertion = config.zramSwap.writebackDevice == null;
        message = "Gemini zram must not use a flash writeback device.";
      }
      {
        assertion = config.systemd.sleep.settings.Sleep.AllowHibernation == false &&
          config.systemd.sleep.settings.Sleep.AllowSuspendThenHibernate == false;
        message = "The normal system uses RAM-only swap and disables hibernation.";
      }
    ];

    environment.systemPackages = [
      provision
      zramProbe
      config.nix.package # nix-store --serve for nix copy --to ssh://
      pkgs.gptfdisk
      pkgs.e2fsprogs
    ];

    nix.settings = {
      experimental-features = ["nix-command" "flakes"];
      trusted-users = ["root"];
    };
  };
}
