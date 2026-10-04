{ buildPkgs, kernel }:
kernel.overrideAttrs (old: {
  pname = "gemini-mainline-efi-kernel";
  postConfigure = (old.postConfigure or "") + ''
    scripts/kconfig/merge_config.sh -m -O . .config ${./mainline-efi.fragment}
    # Archive the actual EFI descriptors through Linux's early boot log.
    bash scripts/config --set-str CMDLINE "$(bash scripts/config -s CMDLINE) efi=debug"
    make ARCH=arm64 CROSS_COMPILE=aarch64-unknown-linux-gnu- olddefconfig
    for symbol in EFI EFI_STUB EFI_GENERIC_STUB; do
      grep -Fqx "CONFIG_$symbol=y" .config
    done
    grep -Fqx '# CONFIG_EFI_ZBOOT is not set' .config
    python3 - ${./mainline-efi.fragment} <<'PY'
    import hashlib, json, sys
    from pathlib import Path
    p = Path('a72-build-provenance.json')
    record = json.loads(p.read_text())
    fragment = Path(sys.argv[1])
    record['fragments'].append({'name': 'mainline-efi.fragment',
        'sha256': hashlib.sha256(fragment.read_bytes()).hexdigest()})
    p.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
    PY
    python3 ${./a72-profile-build.py} bind --config .config
  '';
  postBuild = (old.postBuild or "") + ''
    python3 - <<'PY'
    import struct
    from pathlib import Path
    image = Path('arch/arm64/boot/Image').read_bytes()
    assert image[:2] == b'MZ'
    assert image[0x38:0x3c] == b'ARM\x64'
    pe = struct.unpack_from('<I', image, 0x3c)[0]
    assert image[pe:pe+4] == b'PE\0\0'
    assert struct.unpack_from('<H', image, pe+4)[0] == 0xaa64
    assert struct.unpack_from('<H', image, pe+24)[0] == 0x20b
    assert struct.unpack_from('<H', image, pe+24+68)[0] == 10
    print('PASS: EFI Linux AArch64 PE32+ header and native Image header')
    PY
  '';
})
