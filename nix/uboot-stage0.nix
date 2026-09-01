{
  buildPkgs,
  crossPkgs,
  u-boot-src,
}: let
  sourceDateEpoch = 1788272077;

  uboot = crossPkgs.buildUBoot {
    pname = "uboot-mt6797-gemini-stage0";
    version = "2026.10-stage0";
    src = u-boot-src;
    defconfig = "mt6797_gemini_stage0_defconfig";
    extraPatches = [
      ../patches/u-boot/0001-arm-mediatek-add-Gemini-MT6797-stage-0-target.patch
    ];
    filesToInstall = [
      "u-boot"
      "u-boot.bin"
      "u-boot-nodtb.bin"
      "u-boot.dtb"
      "u-boot.map"
      ".config"
    ];
    SOURCE_DATE_EPOCH = sourceDateEpoch;
    postBuild = ''
      test "$(stat -c %s u-boot.bin)" -lt $((28 * 1024 * 1024))
      test "$(${crossPkgs.stdenv.cc.targetPrefix}readelf -h u-boot \
        | awk '/Entry point address:/ { print $4 }')" = 0x40080000
      ${crossPkgs.stdenv.cc.targetPrefix}nm -n u-boot \
        | grep -Eq '^0000000040080000 T (_start|__image_copy_start)$'
      ${crossPkgs.stdenv.cc.targetPrefix}nm u-boot \
        | grep -Eq ' T save_boot_params$'
      ! ${crossPkgs.stdenv.cc.targetPrefix}nm u-boot \
        | grep -Eq 'mtk_wdt_probe|watchdog_reset'
      grep -Fqx '# CONFIG_ARMV8_SET_SMPEN is not set' .config
      grep -Fqx '# CONFIG_WATCHDOG is not set' .config
      grep -Fqx '# CONFIG_WDT is not set' .config
      grep -Fqx 'CONFIG_NULLDEV_SERIAL=y' .config
    '';
  };

  inertInitramfs = buildPkgs.runCommand "gemini-uboot-stage0-inert-initramfs.cpio.gz" {
    nativeBuildInputs = [buildPkgs.cpio buildPkgs.gzip];
  } ''
    mkdir empty
    (
      cd empty
      find . -print0 | sort -z \
        | cpio --null --create --format=newc --owner=0:0 \
            --reproducible --quiet
    ) | gzip -n -9 > "$out"
  '';

  bundle = buildPkgs.runCommand "gemini-uboot-stage0-p22-bundle" {
    nativeBuildInputs = [buildPkgs.coreutils buildPkgs.python3];
  } ''
    mkdir -p "$out"
    python3 ${../tools/build-android-uboot-v0.py} \
      --uboot ${uboot}/u-boot.bin \
      --ramdisk ${inertInitramfs} \
      --dtb ${uboot}/u-boot.dtb \
      --output "$out/boot-raw.img" \
      | tee "$out/build-metadata"
    cp --no-preserve=mode "$out/boot-raw.img" "$out/boot-padded-p22.img"
    truncate -s 16777216 "$out/boot-padded-p22.img"
    test "$(stat -c %s "$out/boot-padded-p22.img")" -eq 16777216
    sha256sum \
      ${uboot}/u-boot.bin \
      ${uboot}/u-boot.dtb \
      "$out/boot-raw.img" \
      "$out/boot-padded-p22.img" \
      > "$out/SHA256SUMS"
    {
      echo 'u-boot-upstream=cc8c034e78eba6b2a3845783889b80753bb1af1e'
      echo 'stage0-source-commit=94a4e9d7'
      echo 'source-date-epoch=${toString sourceDateEpoch}'
      echo 'trace-page=0x43fff000+0x1000'
      echo 'trace-format=GEMUB001/version-1/length-0xa8'
      echo 'hardware-write=none'
      sha256sum ${../patches/u-boot/0001-arm-mediatek-add-Gemini-MT6797-stage-0-target.patch}
    } > "$out/MANIFEST"
    ln -s ${uboot} "$out/u-boot"
    ln -s ${inertInitramfs} "$out/inert-initramfs.cpio.gz"
  '';
in {
  inherit bundle inertInitramfs uboot;
}
