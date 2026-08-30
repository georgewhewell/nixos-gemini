#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

grep -Fqx '  security.pam.services.sshd.startSession = lib.mkForce false;' \
  "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '    mainlineSshdPam = mainlineNixosSystemCross.config.environment.etc."pam.d/sshd".source;' \
  "$ROOT/flake.nix"
nix build --no-link "$ROOT#mainlineSshPamSessionCheck"
