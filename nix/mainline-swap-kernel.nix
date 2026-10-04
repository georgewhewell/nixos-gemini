{ kernel }:
# Opt-in extension of the watchdog-fixed power kernel. Keep earlier qualified
# artifacts unchanged while validating pressure-driven zswap writeback.
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-power-swap-kernel";
  postConfigure = (old.postConfigure or "") + ''
    scripts/kconfig/merge_config.sh -m -O . .config ${./mainline-swap.fragment}
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    for symbol in SWAP ZSWAP ZSWAP_DEFAULT_ON ZSWAP_SHRINKER_DEFAULT_ON; do
      grep -Fqx "CONFIG_$symbol=y" .config
    done
    python3 - ${./mainline-swap.fragment} <<'PY'
    import hashlib, json, sys
    from pathlib import Path
    p = Path('a72-build-provenance.json')
    record = json.loads(p.read_text())
    fragment = Path(sys.argv[1])
    record['fragments'].append({'name': 'mainline-swap.fragment',
        'sha256': hashlib.sha256(fragment.read_bytes()).hexdigest()})
    p.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    PY
    python3 ${./a72-profile-build.py} bind --config .config
  '';
})
