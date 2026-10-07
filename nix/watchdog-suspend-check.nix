args:
(import ./watchdog-hibernation-check.nix args).overrideAttrs (old: {
  pname = "gemini-watchdog-suspend-check";
  patches = old.patches ++ [ ../patches/watchdog/0002-mtk-wdt-bounded-suspend.patch ];
})
