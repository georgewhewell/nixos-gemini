args:
(import ./rtc-alarm-check.nix args).overrideAttrs (old: {
  pname = "gemini-rtc-calendar-check";
  patches = old.patches ++ [ ../patches/rtc/0002-mt6351-calendar-epoch.patch ];
  buildPhase = old.buildPhase + ''
    python3 tools/testing/selftests/rtc/mt6351-calendar-host.py | tee calendar-test.log
  '';
  installPhase = old.installPhase + ''
    cp include/linux/mfd/mt6397/rtc.h calendar-test.log "$out/"
  '';
})
