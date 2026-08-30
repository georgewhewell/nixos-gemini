#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

grep -Fqx '      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-platform&rev=28c47150235be70cf5b19ea8d9ce7a5473ec23f2";' "$ROOT/flake.nix"
grep -Fqx '        "rev": "28c47150235be70cf5b19ea8d9ce7a5473ec23f2",' "$ROOT/flake.lock"
grep -Fqx '      thermalHallObserveOverlay = true;' "$ROOT/flake.nix"
grep -Fqx '      provisionWaitSeconds = 600;' "$ROOT/flake.nix"
grep -Fqx '      watchdogLeaseSeconds = 720;' "$ROOT/flake.nix"
grep -Fqx '  inputObserveOverlay ? false,' "$ROOT/nix/mainline.nix"
grep -Fqx '  thermalHallObserveOverlay ? false,' "$ROOT/nix/mainline.nix"
grep -Fqx '    ++ lib.optionals inputObserveOverlay [./mainline-input-observe.fragment]' "$ROOT/nix/mainline.nix"
grep -Fqx '    ++ lib.optionals thermalHallObserveOverlay [./mainline-thermal-hall-observe.fragment]' "$ROOT/nix/mainline.nix"
grep -Fqx '          test "$(fdtget "$out/gemini-input-observe.dtb" /i2c@11011000/touchscreen@62 status)" = disabled' "$ROOT/nix/mainline.nix"
grep -Fqx '          ! fdtget -p "$out/gemini-input-observe.dtb" /i2c@11011000/touchscreen@62 \' "$ROOT/nix/mainline.nix"
grep -Fqx 'CONFIG_KEYBOARD_MATRIX=y' "$ROOT/nix/mainline-input-observe.fragment"
grep -Fqx 'CONFIG_PINCTRL_AW9523=y' "$ROOT/nix/mainline-input-observe.fragment"
grep -Fqx 'CONFIG_MTK_SCPSYS=y' "$ROOT/nix/mainline-platform-smoke.fragment"
grep -Fqx 'CONFIG_COMMON_CLK_MT6797_MMSYS=y' "$ROOT/nix/mainline-platform-smoke.fragment"
grep -Fqx '        grep -Fqx '\''CONFIG_MTK_SCPSYS=y'\'' .config' "$ROOT/nix/mainline.nix"
grep -Fqx '        grep -Fqx '\''CONFIG_COMMON_CLK_MT6797_MMSYS=y'\'' .config' "$ROOT/nix/mainline.nix"
grep -Fqx 'CONFIG_MTK_SCPSYS=y' "$ROOT/nix/mainline-consys-identity.fragment"
grep -Fqx 'CONFIG_THERMAL_OF=y' "$ROOT/nix/mainline-input-observe.fragment"
grep -Fqx 'CONFIG_MTK_SOC_THERMAL=y' "$ROOT/nix/mainline-thermal-hall-observe.fragment"
grep -Fqx 'CONFIG_IIO=y' "$ROOT/nix/mainline-thermal-hall-observe.fragment"
grep -Fqx 'CONFIG_MEDIATEK_MT6577_AUXADC=y' "$ROOT/nix/mainline-thermal-hall-observe.fragment"
grep -Fqx 'CONFIG_KEYBOARD_GPIO=y' "$ROOT/nix/mainline-thermal-hall-observe.fragment"
grep -Fqx '          test "$(fdtget "$out/gemini-thermal-hall-observe.dtb" /thermal@1100b000 status)" = okay' "$ROOT/nix/mainline.nix"
grep -Fqx '          test "$(fdtget -t u "$out/gemini-thermal-hall-observe.dtb" /thermal-zones/soc-thermal polling-delay)" = 1000' "$ROOT/nix/mainline.nix"
grep -Fqx '          test -z "$(fdtget -l "$out/gemini-thermal-hall-observe.dtb" /thermal-zones/soc-thermal)"' "$ROOT/nix/mainline.nix"
grep -Fqx "          ! fdtget -p \"\$out/gemini-thermal-hall-observe.dtb\" /gpio-keys \\" "$ROOT/nix/mainline.nix"
grep -Fqx "            | grep -Fqx 'wakeup-source'" "$ROOT/nix/mainline.nix"
grep -Fqx '      /bin/busybox sh /bin/input-observe stage1 &' "$ROOT/nix/mainline-nixos.nix"
grep -Fqx '  systemd.services.gemini-input-observe = {' "$ROOT/nixos/mainline-configuration.nix"
grep -Fqx '      ${pkgs.busybox}/bin/busybox sh ${../nix/input-observe.sh} stage2' "$ROOT/nixos/mainline-configuration.nix"
nix eval --raw "$ROOT#mainlineUnattendedRecoveryInputObserveDtb.drvPath" >/dev/null
nix eval --raw "$ROOT#mainlinePlatformSmokeKernel.drvPath" >/dev/null
nix eval --raw "$ROOT#mainlineConsysIdentityKernel.drvPath" >/dev/null
