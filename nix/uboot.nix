{buildPkgs, crossPkgs, source}:
crossPkgs.buildUBoot {
  pname = "uboot-gemini";
  version = "2026.10";
  src = source;
  defconfig = "mt6797_gemini_defconfig";
  SOURCE_DATE_EPOCH = 1788493603;
  filesToInstall = ["u-boot" "u-boot.bin" "u-boot.dtb" "u-boot.map" ".config" "BUILD-MANIFEST"];

  postBuild = ''
    export HOST_CC=${buildPkgs.stdenv.cc}/bin/cc GEMINI_HOST_DTC=${buildPkgs.dtc}
    for test in tools/gemini/test-*-host.py; do
      ${buildPkgs.python3}/bin/python3 "$test"
    done

    ${crossPkgs.stdenv.cc.targetPrefix}nm u-boot > linked-symbols.txt
    if grep -Eq ' (mmc_bwrite|mmc_berase|mmc_hwpart_config|gemini_mmc_qualify|__efi_gemini_console_begin|__efi_gemini_storage_begin)$' linked-symbols.txt; then
      echo 'obsolete startup diagnostics or storage write APIs remain linked' >&2
      exit 1
    fi
    for symbol in GEMINI_LK_HANDOFF GEMINI_EFI_LINUX GEMINI_EFI_DT_FIXUP \
      GEMINI_EFI_CONSOLE GEMINI_EFI_KEYBOARD GEMINI_EFI_KEY_EVENTS GEMINI_EFI_MMC \
      GEMINI_EFI_MANAGER EFI_LOADER EFI_BINARY_EXEC BOOTM_EFI EFI_VARIABLE_NO_STORE \
      OF_BOARD_SETUP DM_I2C SYS_I2C_MT6797_FIFO DM_KEYBOARD GEMINI_AW9523_KEYBOARD \
      MMC DM_MMC MMC_MTK EFI_PARTITION FS_EXT4; do
      grep -Fqx "CONFIG_$symbol=y" .config
    done
    for symbol in GEMINI_EFI_STORAGE EFI_VARIABLE_FILE_STORE EFI_VARIABLE_SF_STORE \
      EFI_MM_COMM_TEE EFI_BOOTMGR EFI_NET FAT_WRITE FAT_RENAME FASTBOOT_FLASH \
      MMC_WRITE MMC_HW_PARTITIONING SUPPORT_EMMC_BOOT SUPPORT_EMMC_RPMB \
      MMC_IO_VOLTAGE MMC_UHS_SUPPORT MMC_HS200_SUPPORT MMC_HS400_SUPPORT CMD_MMC \
      EXT4_WRITE ENV_IS_IN_MMC MTD NVME SCSI USB_STORAGE; do
      if grep -Fqx "CONFIG_$symbol=y" .config; then
        echo "unexpected boot configuration: $symbol" >&2
        exit 1
      fi
    done
    grep -Fqx 'CONFIG_GEMINI_RECOVERY_TEST=0' .config
    grep -Fqx 'CONFIG_SYS_FDT_PAD=0x10000' .config
    grep -Fqx 'CONFIG_EFI_IMAGE_MIN_ALIGNMENT=0x200000' .config
    grep -Fqx 'CONFIG_STACK_SIZE=0x400000' .config
    grep -Fqx '# CONFIG_ARCH_FIXUP_FDT_MEMORY is not set' .config
    test "$(fdtget u-boot.dtb /mmc@11230000 compatible)" = mediatek,mt6797-mmc
    test "$(fdtget u-boot.dtb /mmc@11230000 max-frequency)" = 25000000
    test "$(fdtget u-boot.dtb /i2c@1101c000/keyboard@5b compatible)" = planet,gemini-aw9523-keyboard
    test "$(fdtget u-boot.dtb /framebuffer@7dfb0000 status)" = okay
    test "$(stat -c %s u-boot.bin)" -lt $((2 * 1024 * 1024))
    test "$(${crossPkgs.stdenv.cc.targetPrefix}readelf -h u-boot | awk '/Entry point address:/ {print $4}')" = 0x40200000
    test "$(od -An -tx1 -j0x38 -N4 u-boot.bin | tr -d ' \n')" = 41524d64
    {
      echo 'source-revision=${source.rev or source.narHash}'
      sha256sum u-boot.bin u-boot.dtb .config
    } > BUILD-MANIFEST
  '';
}
