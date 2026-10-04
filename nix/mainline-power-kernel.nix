{ kernel }:
# Apply the maintained 48ec0f99486e2 watchdog change before the A72 input
# manifest is captured. Its source digest therefore includes the actual patch.
# This opt-in extension retains the qualified EFI/Nix configuration.
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-power-kernel";
  patches = (old.patches or []) ++ [
    ../patches/watchdog/0001-mtk-wdt-pause-for-hibernation-io.patch
  ];
  postBuild = (old.postBuild or "") + ''
    python3 tools/testing/selftests/watchdog/mtk-wdt-pm-host.py
    grep -Eq ' [tT] mtk_wdt_pm_notify$' System.map
  '';
})
