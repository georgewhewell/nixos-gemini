#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

grep -Fqx '      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-platform&rev=a280c8bef7e9cfbc588ce64e6cb803ae7c79939c";' "$ROOT/flake.nix"
grep -Fqx '        "rev": "a280c8bef7e9cfbc588ce64e6cb803ae7c79939c",' "$ROOT/flake.lock"
grep -Fqx '      thermalHallObserveOverlay = true;' "$ROOT/flake.nix"
grep -Fqx '      provisionWaitSeconds = 600;' "$ROOT/flake.nix"
grep -Fqx '      watchdogLeaseSeconds = 720;' "$ROOT/flake.nix"
grep -Fqx '  inputObserveOverlay ? false,' "$ROOT/nix/mainline.nix"
grep -Fqx '  thermalHallObserveOverlay ? false,' "$ROOT/nix/mainline.nix"
grep -Fqx '    ++ lib.optionals inputObserveOverlay [./mainline-input-observe.fragment]' "$ROOT/nix/mainline.nix"
grep -Fqx '    ++ lib.optionals thermalHallObserveOverlay [./mainline-thermal-hall-observe.fragment];' "$ROOT/nix/mainline.nix"
grep -Fqx '  keyboardDtbSha256 = "8346de103fb76e4b6698ec77b5b8f70b85f657fcc867cb232e7c8091fd1528ce";' "$ROOT/nix/mainline.nix"
grep -Fqx '  inputObserveDtbSha256 = "8020621422afbc55c6605aedc0ebfb8391bf7699cbfb3acc69755b6ceae20b78";' "$ROOT/nix/mainline.nix"
grep -Fqx '  thermalHallDtbSha256 = "a87ef1feb384520ada3ad17e84787a8f5dcd51619d83bbca091d3977712ee81f";' "$ROOT/nix/mainline.nix"
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
