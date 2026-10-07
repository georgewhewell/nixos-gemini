# Normal U-Boot firmware with systemd-boot and an embedded Linux fallback.
# Historical experiments use the independently pinned packaging snapshot.
{ buildPkgs, uboot, linuxBundle }:
buildPkgs.runCommand "gemini-bootloader" {
  nativeBuildInputs = [ buildPkgs.python3 buildPkgs.dtc buildPkgs.ubootTools ];
  SOURCE_DATE_EPOCH = 1788493603;
} ''
  mkdir "$out"
  GEMINI_CARRIER_BUILDER=${../tools/build-android-uboot-carrier-v0.py} python3 ${../tools/test-android-uboot-carrier.py}
  kernel=${linuxBundle}/kernel/Image.gz
  initramfs=${linuxBundle}/initramfs.cpio.gz
  dtb=${linuxBundle}/gemini-usb11-host.dtb
  test "$(fdtget "$dtb" / compatible)" = 'planet,gemini-pda mediatek,mt6797'
  test "$(od -An -tx1 -N2 "$kernel" | tr -d ' \n')" = 1f8b
  cat > gemini.its <<EOF
  /dts-v1/;
  / {
    description = "Gemini U-Boot with current Linux payload";
    #address-cells = <1>;
    images {
      kernel {
        data = /incbin/("$kernel");
        type = "kernel"; arch = "arm64"; os = "efi";
        compression = "gzip";
        load = <0x40200000>; entry = <0x40200000>;
        hash-1 { algo = "sha256"; };
      };
      fdt {
        data = /incbin/("$dtb");
        type = "flat_dt"; arch = "arm64"; compression = "none";
        hash-1 { algo = "sha256"; };
      };
      ramdisk {
        data = /incbin/("$initramfs");
        type = "ramdisk"; arch = "arm64"; os = "linux";
        compression = "none";
        hash-1 { algo = "sha256"; };
      };
    };
    configurations {
      default = "gemini";
      gemini { kernel = "kernel"; fdt = "fdt"; ramdisk = "ramdisk"; };
    };
  };
  EOF
  mkimage -f gemini.its "$out/gemini.itb"
  test "$(stat -c %s "$out/gemini.itb")" -le $((16 * 1024 * 1024))
  test "$(fdtget -t x "$out/gemini.itb" /images/kernel load)" = 40200000
  test "$(fdtget -t x "$out/gemini.itb" /images/kernel entry)" = 40200000
  test "$(fdtget "$out/gemini.itb" /configurations default)" = gemini
  dumpimage -l "$out/gemini.itb" > "$out/fit-list.txt"
  dumpimage -T flat_dt -p 0 -o kernel-extracted "$out/gemini.itb"
  dumpimage -T flat_dt -p 1 -o dtb-extracted "$out/gemini.itb"
  dumpimage -T flat_dt -p 2 -o initramfs-extracted "$out/gemini.itb"
  cmp kernel-extracted "$kernel"
  cmp dtb-extracted "$dtb"
  cmp initramfs-extracted "$initramfs"
  system=$(readlink ${linuxBundle}/system)
  test -x "$system/init"
  ln -s "$system" "$out/fallback-system"
  cmdline="bootopt=64S3,32N2,64N2 init=$system/init $(cat "$system/kernel-params")"
  python3 ${../tools/build-android-uboot-carrier-v0.py} --cmdline "$cmdline" \
    --uboot ${uboot}/u-boot.bin --ramdisk "$out/gemini.itb" \
    --dtb "$dtb" --output "$out/boot-raw.img" > "$out/build-metadata.txt"
  cp "$out/boot-raw.img" "$out/boot-padded-p22.img"
  truncate -s 16777216 "$out/boot-padded-p22.img"
  python3 - "$out" ${uboot} ${linuxBundle} <<'PY'
  import gzip, hashlib, json, struct, sys, zlib
  from pathlib import Path
  out, uboot, linux = map(Path, sys.argv[1:])
  image = (out/'boot-raw.img').read_bytes()
  assert image[:8] == b'ANDROID!'
  size, load, rsize, rload, _, _, tags, page = struct.unpack_from('<8I', image, 8)
  assert load == 0x40200000 and rload == 0x45000000 and tags == 0x44000000
  assert page == 2048 and size >= 512*1024 and size % page == 0
  kernel = image[page:page+size]
  decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
  assert decoder.decompress(kernel) == (uboot/'u-boot.bin').read_bytes()
  assert decoder.eof
  dtb = (linux/'gemini-usb11-host.dtb').read_bytes()
  assert kernel.endswith(dtb)
  assert not decoder.unused_data[:-len(dtb)].strip(b'\0')
  fit = (out/'gemini.itb').read_bytes()
  assert rsize == len(fit) and image[page+size:page+size+rsize] == fit
  assert not image[page+size+rsize:].strip(b'\0')
  padded = (out/'boot-padded-p22.img').read_bytes()
  assert len(padded) == 16*1024*1024 and padded[:len(image)] == image
  assert not padded[len(image):].strip(b'\0')
  raw_kernel = gzip.decompress((linux/'kernel/Image.gz').read_bytes())
  assert raw_kernel[0x38:0x3c] == b'ARM\x64'
  assert 0x40200000 + len(raw_kernel) < 0x43000000
  assert raw_kernel[:2] == b'MZ'
  manifest = {'status':'host-validated-not-booted', 'uboot':str(uboot),
              'linux_payload':str(linux), 'fallback_system':str((linux/'system').resolve()),
              'profile':'efi-manager', 'recovery_test':0,
              'expected_outcome':'accepted-linux',
              'uboot_evidence_required':'/chosen/gemini,uboot-handoff=efi',
              'efi_evidence_required':'Linux EFI system table and full EFI memory map',
              'linux_image_bytes':len(raw_kernel),
              'payload_files':{}, 'files':{}}
  for name in ('kernel/Image.gz', 'initramfs.cpio.gz', 'gemini-usb11-host.dtb'):
      data = (linux/name).read_bytes()
      manifest['payload_files'][name] = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
  for name in ('boot-raw.img', 'boot-padded-p22.img', 'gemini.itb'):
      data = (out/name).read_bytes()
      manifest['files'][name] = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
  (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
  print('PASS: carrier header, LK window layout, real gzip payload, FIT extraction, padding and Linux load extent')
  PY
''
