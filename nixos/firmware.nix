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
    '')
  ];
}
