# Gemini PDA firmware blobs
{
  config,
  pkgs,
  lib,
  ...
}: {
  hardware.firmware = [
    (pkgs.runCommandLocal "gemini-firmware" {
      # Linux 3.18 cannot load NixOS's modern .xz firmware form, and the
      # MediaTek WMT helper also requires the original, unhashed filenames.
      compressFirmware = false;
    } ''
      mkdir -p $out/lib/firmware
      cp ${../blobs/ROMv3_patch_1_0_hdr.bin} $out/lib/firmware/ROMv3_patch_1_0_hdr.bin
      cp ${../blobs/ROMv3_patch_1_1_hdr.bin} $out/lib/firmware/ROMv3_patch_1_1_hdr.bin
      cp ${../blobs/WIFI_RAM_CODE_6797} $out/lib/firmware/WIFI_RAM_CODE_6797
      cp ${../blobs/WMT_SOC.cfg} $out/lib/firmware/WMT_SOC.cfg
      cp ${../blobs/mt6631_fm_v1_coeff.bin} $out/lib/firmware/mt6631_fm_v1_coeff.bin
      cp ${../blobs/mt6631_fm_v1_patch.bin} $out/lib/firmware/mt6631_fm_v1_patch.bin
      cp ${../blobs/novatek_ts_fw.bin} $out/lib/firmware/novatek_ts_fw.bin
      cp ${../blobs/pcm_deepidle.bin} $out/lib/firmware/pcm_deepidle.bin
      cp ${../blobs/pcm_sodi.bin} $out/lib/firmware/pcm_sodi.bin
      cp ${../blobs/pcm_suspend.bin} $out/lib/firmware/pcm_suspend.bin

      # These three bare filenames are the production WMT bootstrap ABI.
      # Fail the build if the retained local evidence changes silently.
      test "$(stat -c %s $out/lib/firmware/WMT_SOC.cfg)" = 80
      test "$(sha256sum $out/lib/firmware/WMT_SOC.cfg | cut -d' ' -f1)" = \
        f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880
      test "$(stat -c %s $out/lib/firmware/ROMv3_patch_1_1_hdr.bin)" = 46472
      test "$(sha256sum $out/lib/firmware/ROMv3_patch_1_1_hdr.bin | cut -d' ' -f1)" = \
        5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e
      test "$(stat -c %s $out/lib/firmware/ROMv3_patch_1_0_hdr.bin)" = 210904
      test "$(sha256sum $out/lib/firmware/ROMv3_patch_1_0_hdr.bin | cut -d' ' -f1)" = \
        450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630
    '')
  ];
}
