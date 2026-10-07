{ kernel }:
# Keep qualified power/swap artifacts pinned while validating RTC cancellation.
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-power-rtc-kernel";
  patches = (old.patches or []) ++ [
    ../patches/rtc/0001-mt6397-alarm-irq-enable.patch
  ];
  postBuild = (old.postBuild or "") + ''
    python3 tools/testing/selftests/rtc/mt6397-alarm-host.py
    grep -Eq ' [tT] mtk_rtc_alarm_irq_enable$' System.map
  '';
})
