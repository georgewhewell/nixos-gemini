{ kernel }:
# Preserve the qualified alarm-only candidate while checking firmware encoding.
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-power-rtc-calendar-kernel";
  patches = (old.patches or []) ++ [
    ../patches/rtc/0002-mt6351-calendar-epoch.patch
  ];
  postBuild = (old.postBuild or "") + ''
    python3 tools/testing/selftests/rtc/mt6351-calendar-host.py
  '';
})
