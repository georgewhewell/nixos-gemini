#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

grep -Fqx '  inputObserveOverlay ? false,' "$ROOT/nix/mainline.nix"
grep -Fqx '    ++ lib.optionals inputObserveOverlay [./mainline-input-observe.fragment];' "$ROOT/nix/mainline.nix"
grep -Fqx '  keyboardDtbSha256 = "8346de103fb76e4b6698ec77b5b8f70b85f657fcc867cb232e7c8091fd1528ce";' "$ROOT/nix/mainline.nix"
grep -Fqx '  inputObserveDtbSha256 = "8020621422afbc55c6605aedc0ebfb8391bf7699cbfb3acc69755b6ceae20b78";' "$ROOT/nix/mainline.nix"
grep -Fqx '          test "$(fdtget "$out/gemini-input-observe.dtb" /i2c@11011000/touchscreen@62 status)" = disabled' "$ROOT/nix/mainline.nix"
grep -Fqx '          ! fdtget -p "$out/gemini-input-observe.dtb" /i2c@11011000/touchscreen@62 \' "$ROOT/nix/mainline.nix"
grep -Fqx 'CONFIG_KEYBOARD_MATRIX=y' "$ROOT/nix/mainline-input-observe.fragment"
grep -Fqx 'CONFIG_PINCTRL_AW9523=y' "$ROOT/nix/mainline-input-observe.fragment"
grep -Fqx 'CONFIG_THERMAL_OF=y' "$ROOT/nix/mainline-input-observe.fragment"
grep -Fqx '      /bin/busybox sh /bin/input-observe stage1 &' "$ROOT/nix/mainline-nixos.nix"
grep -Fqx '  systemd.services.gemini-input-observe = {' "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '      ${pkgs.busybox}/bin/busybox sh ${../nix/input-observe.sh} stage2' "$ROOT/nixos/mainline-configuration.nix"
nix eval --raw "$ROOT#mainlineUnattendedRecoveryInputObserveDtb.drvPath" >/dev/null
