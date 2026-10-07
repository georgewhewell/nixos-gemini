{ kernel }:
# Separate diagnostic image: keep the watchdog counter running during short
# suspend trials. Normal RTC/calendar artifacts retain their existing policy.
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-power-suspend-guard-kernel";
  patches = (old.patches or []) ++ [
    ../patches/watchdog/0002-mtk-wdt-bounded-suspend.patch
  ];
  postConfigure = (old.postConfigure or "") + ''
    python3 - <<'PY'
    import json, subprocess
    from pathlib import Path
    lines = [s for s in Path('.config').read_text().splitlines() if s.startswith('CONFIG_CMDLINE=')]
    assert len(lines) == 1
    command = json.loads(lines[0].split('=', 1)[1])
    assert 'mtk_wdt.suspend_keep_running' not in command
    subprocess.run(['bash', 'scripts/config', '--set-str', 'CMDLINE',
                    command + ' mtk_wdt.suspend_keep_running=1'], check=True)
    PY
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    grep -q '^CONFIG_CMDLINE=.*mtk_wdt.suspend_keep_running=1' .config
    python3 ${./a72-profile-build.py} bind --config .config
  '';
})
