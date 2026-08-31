#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
KERNEL_SOURCE=${LINUX_GEMINI_NEXT_SOURCE:-/home/grw/src/linux-gemini-platform}
EXPECTED_REV=da6e93b0bce1b62e0e38425938efe3ceba7cfc09

test "$(git -C "$KERNEL_SOURCE" rev-parse HEAD)" = "$EXPECTED_REV"
grep -Fqx '  consysG2dPostpatchOverlay ? false,' "$ROOT/nix/mainline.nix"
grep -Fqx '    ++ lib.optionals consysG2dPostpatchOverlay [./mainline-consys-g2d-postpatch.fragment]' "$ROOT/nix/mainline.nix"
grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2D_POSTPATCH_OWNER=y' "$ROOT/nix/mainline-consys-g2d-postpatch.fragment"
grep -Fqx 'CONFIG_MTK_MT6797_CONSYS_G2C_PATCH_OWNER=y' "$ROOT/nix/mainline-consys-g2d-postpatch.fragment"
grep -Fqx '      consysG2dPostpatchOverlay = true;' "$ROOT/flake.nix"
grep -Fq 'mt6797_consys_g2d_postpatch_owner.enable_experimental_g2d_postpatch_owner=1' "$ROOT/nix/mainline.nix"
! grep -F 'consysG2dPostpatchOverlay' "$ROOT/nix/mainline.nix" | grep -Fq 'enable_experimental_g2c_patch_owner=1'
grep -Fq 'fdtput -t s "$out/gemini-consys.dtb" /consys-g2c-patch-owner status disabled' "$ROOT/nix/mainline.nix"
grep -Fq 'fdtput -t s "$out/gemini-consys.dtb" /consys-g2d-postpatch-owner status okay' "$ROOT/nix/mainline.nix"

# This is an evaluation-only local-input proof. It never builds a closure.
nix eval --override-input linux-gemini-next "path:$KERNEL_SOURCE" --raw \
  "$ROOT#mainlineConsysG2dPostpatchKernel.drvPath" >/dev/null
