#!/bin/sh
# SPDX-License-Identifier: MIT
# Host-only composition contract. It neither builds nor contacts Gemini.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

fail() { echo "test-mainline-p22-baseline: $*" >&2; exit 1; }

# The locked input and the local platform checkout must name the reviewed DSI
# fix. The Nix derivation independently checks ordering while it builds.
grep -Fqx '      url = "git+ssh://git@github.com/georgewhewell/linux-gemini.git?ref=gemini-platform&rev=28c47150235be70cf5b19ea8d9ce7a5473ec23f2";' \
  "$ROOT/flake.nix" || fail 'linux-gemini pin drifted'
grep -Fq '"rev": "28c47150235be70cf5b19ea8d9ce7a5473ec23f2",' \
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

grep -Fqx '      displayActivation = true;' "$ROOT/flake.nix"
grep -Fqx '      kernel = mainlineP22Baseline.kernel;' "$ROOT/flake.nix"
grep -Fqx '      serviceabilityDtb = mainlineP22Baseline.serviceabilityDtb;' "$ROOT/flake.nix"
grep -Fqx '      kernelLeaseSelfAcceptToken = mainlineP22Baseline.leaseSelfAcceptToken;' "$ROOT/flake.nix"
grep -Fqx '          _module.args.geminiLeaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;' "$ROOT/flake.nix"
test "$(grep -Fxc '      leaseSelfAcceptToken = mainlineNixosLeaseSelfAcceptToken;' "$ROOT/flake.nix")" -eq 2
test "$(grep -Ec '^[[:space:]]+leaseSelfAcceptToken[[:space:]]*=' "$ROOT/flake.nix")" -eq 2

grep -Fq 'builtins.match "gemini-baseline-lease-v1-[0-9a-f]{64}" leaseSelfAcceptToken' \
  "$ROOT/nix/mainline.nix"
grep -Fq 'lib.optionalString (leaseSelfAcceptToken != null) " gemini.baseline_lease_capability=${leaseSelfAcceptToken}"' \
  "$ROOT/nix/mainline.nix"
grep -Fq 'assert kernelLeaseSelfAcceptToken == leaseSelfAcceptToken;' \
  "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'Android header baseline capability mismatch' \
  "$ROOT/nix/mainline-nixos.nix"

grep -Fqx 'CONFIG_TOUCHSCREEN_NOVATEK_NT36XXX=y' \
  "$ROOT/nix/mainline-touchscreen-activation.fragment"
grep -Fqx 'CONFIG_BATTERY_MT6351_FGADC=y' \
  "$ROOT/nix/mainline-fgadc-activation.fragment"
grep -Fqx '  p22BaselinePlatformRevision = "28c47150235be70cf5b19ea8d9ce7a5473ec23f2";' \
  "$ROOT/nix/mainline.nix"

for contract in \
  'test "$(fdtget "$out/gemini.dtb" /mmc@11240000 status)" = disabled' \
  'test "$(fdtget "$out/gemini.dtb" /gpu@13040000 status)" = disabled' \
  'test "$(fdtget "$out/gemini.dtb" /consys@18070000 status)" = disabled' \
  'test "$(fdtget "$out/gemini.dtb" /serial@1100c000 status)" = disabled' \
  'The panel may issue DSI transfers before'; do
  grep -Fq -- "$contract" "$ROOT/nix/mainline.nix" || fail "missing DT/source contract: $contract"
done

grep -Fqx '      display_gate=/sys/devices/platform/14000000.syscon/activate_drm' \
  "$ROOT/nix/mainline-nixos.nix"
grep -Fq 'display=activated gate=14000000.syscon/activate_drm dsi_irq=pre-host-registration' \
  "$ROOT/nix/mainline-nixos.nix"

echo 'test-mainline-p22-baseline: PASS'
