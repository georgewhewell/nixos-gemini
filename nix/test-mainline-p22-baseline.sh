#!/bin/sh
# SPDX-License-Identifier: MIT
# Host-only composition contract. It neither builds nor contacts Gemini.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

fail() { echo "test-mainline-p22-baseline: $*" >&2; exit 1; }

# The locked input and the local platform checkout must name the reviewed DSI
# fix. The Nix derivation independently checks ordering while it builds.
grep -Fqx '      url = "git+file:///home/grw/src/linux-gemini-display-default-proven-20260902?ref=codex/display-default-proven-20260902&rev=d6b7b657e94a91734c380496566e2d2996ee5fce";' \
  "$ROOT/flake.nix" || fail 'linux-gemini pin drifted'
grep -Fq '"rev": "d6b7b657e94a91734c380496566e2d2996ee5fce",' \
  "$ROOT/flake.lock" || fail 'linux-gemini lock drifted'

candidate=$(sed -n '/mainlineP22Baseline = import/,/    };/p' "$ROOT/flake.nix")
printf '%s\n' "$candidate" | grep -Fqx '      storageOverlay = true;'
printf '%s\n' "$candidate" | grep -Fqx '      sshAccess = true;'
printf '%s\n' "$candidate" | grep -Fqx '      usbHostOverlay = true;'
printf '%s\n' "$candidate" | grep -Fqx '      displayOverlay = true;'
printf '%s\n' "$candidate" | grep -Fqx '      powerObserveOverlay = true;'
printf '%s\n' "$candidate" | grep -Fqx '      powerObservePreflight = true;'
printf '%s\n' "$candidate" | grep -Fqx '      unattendedRecovery = true;'
printf '%s\n' "$candidate" | grep -Fqx '      touchscreenActivationOverlay = true;'
printf '%s\n' "$candidate" | grep -Fqx '      fgadcActivationOverlay = true;'
printf '%s\n' "$candidate" | grep -Fqx '      leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;'
if printf '%s\n' "$candidate" | grep -Eq 'deviceActivationOverlay|audioHeadphoneTest|consysIdentityOverlay'; then
  fail 'candidate enabled a retired all-or-nothing or unproven component'
fi

if grep -Fqx '      displayActivation = true;' "$ROOT/flake.nix"; then
  fail 'default/full Stage2 still enables the userspace display gate'
fi
grep -Fqx '      kernel = mainlineP22Baseline.kernel;' "$ROOT/flake.nix"
grep -Fqx '      serviceabilityDtb = mainlineP22Baseline.serviceabilityDtb;' "$ROOT/flake.nix"
grep -Fqx '      kernelLeaseSelfAcceptToken = mainlineP22Baseline.leaseSelfAcceptToken;' "$ROOT/flake.nix"
grep -Fqx '      stage2BaselineAcceptScript = mainlineNixosSystemCross.config.systemd.services.gemini-baseline-self-accept.script;' "$ROOT/flake.nix"
grep -Fqx '          _module.args.geminiLeaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;' "$ROOT/flake.nix"
test "$(grep -Fxc '      leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;' "$ROOT/flake.nix")" -eq 2
test "$(grep -Ec '^[[:space:]]+leaseSelfAcceptToken[[:space:]]*=' "$ROOT/flake.nix")" -eq 2

grep -Fq 'builtins.match "gemini-baseline-lease-v1-[0-9a-f]{64}" leaseSelfAcceptToken' \
  "$ROOT/nix/mainline.nix"
grep -Fq 'lib.optionalString (leaseSelfAcceptToken != null) " gemini.baseline_lease_capability=${leaseSelfAcceptToken}"' \
  "$ROOT/nix/mainline.nix"
grep -Fq 'assert kernelLeaseSelfAcceptToken == leaseSelfAcceptToken;' \
  "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'export GEMINI_BASELINE_ACCEPT_TOKEN=' \
  "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'Android header baseline capability mismatch' \
  "$ROOT/nix/mainline-nixos.nix"

grep -Fqx 'CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX=y' \
  "$ROOT/nix/mainline-touchscreen-activation.fragment"
grep -Fqx 'CONFIG_BATTERY_MT6351_FGADC=y' \
  "$ROOT/nix/mainline-fgadc-activation.fragment"
grep -Fqx '  p22BaselinePlatformRevision = "d6b7b657e94a91734c380496566e2d2996ee5fce";' \
  "$ROOT/nix/mainline.nix"

for contract in \
  'test "$(fdtget "$out/gemini.dtb" /mmc@11240000 status)" = disabled' \
  'test "$(fdtget "$out/gemini.dtb" /gpu@13040000 status)" = disabled' \
  'test "$(fdtget "$out/gemini.dtb" /consys@18070000 status)" = disabled' \
  'test "$(fdtget "$out/gemini.dtb" /serial@1100c000 status)" = disabled' \
  'The panel may issue DSI transfers before'; do
  grep -Fq -- "$contract" "$ROOT/nix/mainline.nix" || fail "missing DT/source contract: $contract"
done

grep -Fq 'display-activation=kernel-default-probe-no-userspace-gate' \
  "$ROOT/nix/mainline.nix"
grep -Fq 'mt6797-gemini-pda-display-gated.dtbo' "$ROOT/nix/mainline.nix"
grep -Fq 'mediatek,drm-on-demand >/dev/null 2>&1' "$ROOT/nix/mainline.nix"
grep -Fq 'kernel-default-probe; no userspace gate' \
  "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'console=tty0 console=ttyS0,921600n8' "$ROOT/nix/mainline.nix"
grep -Fq 'fbcon=rotate:3 consoleblank=0 fbcon=font:TER16x32' "$ROOT/nix/mainline.nix"
grep -Fqx '  services.getty.autologinUser = "root";' \
  "$ROOT/nixos/mainline-configuration.nix"
grep -Fq 'unit_active getty@tty1.service || fail tty1-getty-inactive' \
  "$ROOT/nix/unattended-recovery-baseline-self-accept.sh"

echo 'test-mainline-p22-baseline: PASS'
