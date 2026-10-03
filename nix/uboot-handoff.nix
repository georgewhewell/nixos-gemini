{ buildPkgs, crossPkgs, source, efiSmoke ? false, recoveryTest ? 0 }:
assert builtins.elem recoveryTest [0 1 2];
assert recoveryTest == 0 || !efiSmoke;
crossPkgs.buildUBoot {
  pname = "uboot-mt6797-gemini-${if efiSmoke then "efi-smoke" else "handoff"}-${toString recoveryTest}";
  version = "2026.10-m69";
  src = source;
  defconfig = if efiSmoke then "mt6797_gemini_efi_smoke_defconfig" else "mt6797_gemini_handoff_defconfig";
  preConfigure = ''
    echo 'CONFIG_GEMINI_RECOVERY_TEST=${toString recoveryTest}' >> configs/${if efiSmoke then "mt6797_gemini_efi_smoke_defconfig" else "mt6797_gemini_handoff_defconfig"}
  '';
  SOURCE_DATE_EPOCH = 1788493603;
  filesToInstall = [
    "u-boot" "u-boot.bin" "u-boot.dtb" "u-boot.map" ".config"
  ] ++ buildPkgs.lib.optional efiSmoke "lib/efi_loader/helloworld.efi";
  postBuild = ''
    HOST_CC=${buildPkgs.stdenv.cc}/bin/cc ${buildPkgs.python3}/bin/python3 tools/gemini/test-efi-smoke-host.py
    HOST_CC=${buildPkgs.stdenv.cc}/bin/cc ${buildPkgs.python3}/bin/python3 tools/gemini/test-reset-host.py
    HOST_CC=${buildPkgs.stdenv.cc}/bin/cc ${buildPkgs.python3}/bin/python3 tools/gemini/test-boot-flow-host.py
    ${crossPkgs.stdenv.cc.targetPrefix}objdump -dr arch/arm/mach-mediatek/mt6797/init.o \
      | sed -n '/<reset_cpu>:/,/^$/p' > reset-cpu-disassembly.txt
    grep -Fq gemini_reset reset-cpu-disassembly.txt
    ${crossPkgs.stdenv.cc.targetPrefix}objdump -dr board/planet/gemini/gemini.o \
      | sed -n '/<board_late_init>:/,/^$/p' > boot-disassembly.txt
    ${buildPkgs.lib.optionalString (recoveryTest == 1) "grep -Fq reset_cpu boot-disassembly.txt"}
    ${buildPkgs.lib.optionalString (recoveryTest == 2) "grep -wq wfi boot-disassembly.txt"}
    if grep -Fq psci_system_reset reset-cpu-disassembly.txt; then
      echo "Gemini reset still calls PSCI" >&2
      exit 1
    fi
    HOST_CC=${buildPkgs.stdenv.cc}/bin/cc GEMINI_HOST_DTC=${buildPkgs.dtc} ${buildPkgs.python3}/bin/python3 tools/gemini/test-lk-fdt-host.py
    grep -Fqx 'CONFIG_PRE_CON_BUF_SZ=65536' .config
    grep -Fqx '# CONFIG_ARCH_FIXUP_FDT_MEMORY is not set' .config
    ${crossPkgs.stdenv.cc.targetPrefix}strings u-boot > binary-strings.txt
    ${buildPkgs.lib.optionalString (recoveryTest == 0) "grep -Fqx 'bootm 0x45000000#gemini 0x45000000#gemini 0x44000000' binary-strings.txt"}
    test "$(stat -c %s u-boot.bin)" -lt $((2 * 1024 * 1024))
    test "$(${crossPkgs.stdenv.cc.targetPrefix}readelf -h u-boot | awk '/Entry point address:/ {print $4}')" = 0x40200000
    test "$(od -An -tx1 -j0x38 -N4 u-boot.bin | tr -d ' \n')" = 41524d64
    grep -Fqx 'CONFIG_GEMINI_LK_HANDOFF=y' .config
    grep -Fqx 'CONFIG_GEMINI_RECOVERY_TEST=${toString recoveryTest}' .config
    ${buildPkgs.lib.optionalString efiSmoke ''
    for symbol in GEMINI_EFI_SMOKE BLK EFI_LOADER EFI_BINARY_EXEC CMD_BOOTEFI CMD_BOOTEFI_BINARY CMD_BOOTEFI_HELLO EFI_VARIABLE_NO_STORE; do
      grep -Fqx "CONFIG_$symbol=y" .config
    done
    ''}
    ${buildPkgs.lib.optionalString (!efiSmoke) ''
    if grep -Eq '^CONFIG_(GEMINI_EFI_SMOKE|EFI_LOADER)=y$' .config; then
      echo 'plain handoff unexpectedly enables EFI' >&2
      exit 1
    fi
    ''}
    for symbol in EFI_VARIABLE_FILE_STORE EFI_VARIABLE_SF_STORE EFI_MM_COMM_TEE EFI_BOOTMGR EFI_NET FAT_WRITE FAT_RENAME FASTBOOT_FLASH MMC MTD NVME SCSI USB_STORAGE; do
      if grep -Eq "^CONFIG_$symbol=y$" .config; then
        echo "unexpected persistent or boot-manager option: $symbol" >&2
        exit 1
      fi
    done
    test "$(fdtget u-boot.dtb /framebuffer@7dfb0000 status)" = disabled
    ${buildPkgs.lib.optionalString efiSmoke ''
    ${buildPkgs.python3}/bin/python3 - <<'PY_EFI'
    import struct
    from pathlib import Path
    data = Path('lib/efi_loader/helloworld.efi').read_bytes()
    assert data[:2] == b'MZ'
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe+4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe+4)[0] == 0xaa64
    assert struct.unpack_from('<H', data, pe+24)[0] == 0x20b
    assert struct.unpack_from('<H', data, pe+24+68)[0] == 10
    print('EFI hello: AArch64 PE32+ EFI application verified')
    PY_EFI
    ''}
  '';
}
