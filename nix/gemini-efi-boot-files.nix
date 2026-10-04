{ buildPkgs, bootloader, linuxBundle, kernel }:
# Files for a real systemd-boot trial on the existing EFI-readable volume.
# Publication is a separate operation: this output never changes the device.
buildPkgs.runCommand "gemini-efi-boot-files" {
  nativeBuildInputs = [ buildPkgs.python3 ];
} ''
  mkdir -p "$out"
  python3 - "$out" ${bootloader} ${linuxBundle} ${kernel} <<'PY'
  import gzip, hashlib, json, shutil, struct, sys
  from pathlib import Path
  out, bootloader, linux, kernel = map(Path, sys.argv[1:])
  image = gzip.decompress((linux/'kernel/Image.gz').read_bytes())
  initrd = (linux/'initramfs.cpio.gz').read_bytes()
  manager = (bootloader/'lib/systemd/boot/efi/systemd-bootaa64.efi').read_bytes()
  for name, data in [('Linux', image), ('systemd-boot', manager)]:
      assert data[:2] == b'MZ', name
      pe = struct.unpack_from('<I', data, 0x3c)[0]
      assert data[pe:pe+4] == b'PE\0\0', name
      assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64, name
      assert struct.unpack_from('<H', data, pe+24)[0] == 0x20b, name
      assert struct.unpack_from('<H', data, pe+24+68)[0] == 10, name
  # This first manager trial retains the hardware-qualified kernel command
  # line and CPU provenance. General NixOS generation updates remain separate.
  config = (kernel/'kernel.config').read_text()
  assert 'CONFIG_CMDLINE_FORCE=y\n' in config
  payload = hashlib.sha256(image + initrd).hexdigest()
  directory = 'EFI/Gemini/' + payload
  files = {
      'EFI/systemd/systemd-bootaa64.efi': manager,
      directory + '/linux.efi': image,
      directory + '/initrd.cpio.gz': initrd,
      'loader/loader.conf': ("default gemini-efi-trial.conf\ntimeout 8\nconsole-mode keep\n"
                             "editor no\nauto-entries no\nauto-firmware no\nrandom-seed-mode off\n").encode(),
      'loader/entries/gemini-efi-trial.conf': ("title NixOS Gemini (EFI trial)\n"
          "sort-key gemini\nversion 7.1.3\nlinux /" + directory + "/linux.efi\n"
          "initrd /" + directory + "/initrd.cpio.gz\n").encode(),
  }
  tree = out/'tree'
  for name, data in files.items():
      path = tree/name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(data)
  manifest = {'status': 'host-prepared-not-published-or-booted',
              'bootloader': str(bootloader), 'linux_payload': str(linux),
              'kernel': str(kernel), 'payload_identity': payload,
              'entry': 'gemini-efi-trial.conf', 'menu_timeout_seconds': 8,
              'requires': ['LK-derived FDT in EFI configuration table',
                           'native EFI Block I/O and Simple File System',
                           'image device handle bound to the containing filesystem'],
              'files': {name: {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
                        for name, data in files.items()}}
  (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
  print('PASS: AArch64 systemd-boot and Linux PE images; content-addressed payload and bounded menu entry prepared')
  PY
''
