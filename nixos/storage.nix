# Stage 1 mounts p32 (gemini-data) for /home and the registered Nix store
# at /persist/nixos/nix. Root remains tmpfs; p34 supplies swap behind zswap.
# Image-based recovery uses the older overlay layout and database seeding.
{
  config,
  lib,
  pkgs,
  geminiPersistentStore ? false,
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
        gemini-storage-provision has created them.  Before that the image
        behaves as if this were off.
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
    _module.args.geminiPersistentStore = lib.mkDefault false;
    # Nix is only useful with the writable store on p32.
    nix.enable = cfg.enable;
  }
  (lib.mkIf cfg.enable {
    # Absent until provisioned: nofail keeps swap.target, and so boot and
    # the recovery acceptance, independent of it.
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

    # Nix on the device: `nix copy --to ssh://root@...` needs nix-store
    # --serve --write here.  The store is only writable with p32 in place.
    nix.package = pkgs.nix.override {withAWS = false;};
    nix.settings = {
      experimental-features = ["nix-command" "flakes"];
      trusted-users = ["root"];
    };

    # The persistent database must know this image's paths (they live in
    # the read-only lower layer).  Register them once per image, drop
    # entries whose paths disappeared with an older image, and root the
    # booted system so a garbage collection cannot whiteout it.
    systemd.services.gemini-nix-db-seed = {
      description = "Register this image's store paths in the persistent Nix database";
      wantedBy = ["multi-user.target"];
      before = ["nix-daemon.service"];
      unitConfig.ConditionPathIsMountPoint = "/persist";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [config.nix.package pkgs.coreutils];
      script = ''
        mkdir -p /nix/var/nix/gcroots
        ln -sfn /run/booted-system /nix/var/nix/gcroots/gemini-booted-system
        ${lib.optionalString (!geminiPersistentStore) ''
        system=$(cat /nix/store/.gemini-system)
        stamp=/nix/var/nix/gemini-seeded-system
        if [ "$(cat "$stamp" 2>/dev/null || true)" = "$system" ]; then
          exit 0
        fi
        if ! nix-store --load-db < /nix/store/.gemini-registration; then
          echo "nix-store --load-db failed; the Nix database may be incomplete" >&2
          exit 0
        fi
        # Never fail the boot over database hygiene; log instead.
        nix-store --verify || echo "nix-store --verify reported problems" >&2
        echo "$system" > "$stamp"
        ''}
      '';
    };
  })
  ];
}
