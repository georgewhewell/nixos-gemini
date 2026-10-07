# Stage 1 mounts p32 (gemini-data) for /home and the registered Nix store
# at /persist/nixos/nix. Root remains tmpfs; p34 supplies swap behind zswap.
{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.gemini.storage;

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
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Use the p32 data filesystem and the p34 swap partition once
        gemini-storage-provision has created them. Normal boot requires
        the registered persistent Nix store on p32.
      '';
    };
    dataLabel = lib.mkOption {
      type = lib.types.strMatching "[A-Za-z0-9_-]{1,16}";
      default = "gemini-data";
      description = "ext4 label of the p32 data filesystem (Stage 1 checks it).";
    };
    swapPartUuid = lib.mkOption {
      type = lib.types.strMatching "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
      default = "5e0f3a1c-9b2d-4c8e-a7f6-2d1b0c9e8a71";
      description = "Unique GUID that provisioning gives the p34 swap partition.";
    };
  };

  config = lib.mkMerge [
    {
      # Nix is only useful with the writable store on p32.
      nix.enable = cfg.enable;
    }
    (lib.mkIf cfg.enable {
      # Absent until provisioned: nofail keeps swap.target and boot independent
      # of the optional swap partition.
      swapDevices = [
        {
          device = "/dev/disk/by-partuuid/${cfg.swapPartUuid}";
          options = ["nofail" "x-systemd.device-timeout=10s"];
        }
      ];

      # mainline-configuration.nix forces its package list; same priority, so
      # the lists merge.
      environment.systemPackages = lib.mkForce [
        provision
        config.nix.package # nix-store --serve for nix copy --to ssh://
        pkgs.gptfdisk
        pkgs.e2fsprogs
      ];

      nix.package = pkgs.nix.override {withAWS = false;};
      nix.settings = {
        experimental-features = ["nix-command" "flakes"];
        trusted-users = ["root"];
      };
    })
  ];
}
