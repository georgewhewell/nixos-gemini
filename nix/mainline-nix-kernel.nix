{ kernel }:
# Opt-in extension of the qualified EFI kernel. Keep both accepted bundles
# reproducible while preparing the ordinary Nix build trial.
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-efi-nix-kernel";
  postConfigure = (old.postConfigure or "") + ''
    scripts/kconfig/merge_config.sh -m -O . .config ${./mainline-nix.fragment}
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    for symbol in NAMESPACES USER_NS PID_NS IPC_NS UTS_NS NET_NS; do
      grep -Fqx "CONFIG_$symbol=y" .config
    done
    python3 - ${./mainline-nix.fragment} <<'PY'
    import hashlib, json, sys
    from pathlib import Path
    p = Path('a72-build-provenance.json')
    record = json.loads(p.read_text())
    fragment = Path(sys.argv[1])
    record['fragments'].append({'name': 'mainline-nix.fragment',
        'sha256': hashlib.sha256(fragment.read_bytes()).hexdigest()})
    p.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    PY
    python3 ${./a72-profile-build.py} bind --config .config
  '';
})
