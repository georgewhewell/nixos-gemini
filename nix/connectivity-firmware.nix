{ buildPkgs }:
buildPkgs.runCommand "gemini-connectivity-firmware" {} ''
  mkdir -p "$out/lib/firmware"
  cp ${../blobs/WMT_SOC.cfg} "$out/lib/firmware/WMT_SOC.cfg"
  cp ${../blobs/ROMv3_patch_1_1_hdr.bin} "$out/lib/firmware/ROMv3_patch_1_1_hdr.bin"
  cp ${../blobs/ROMv3_patch_1_0_hdr.bin} "$out/lib/firmware/ROMv3_patch_1_0_hdr.bin"
  cp ${../blobs/WIFI_RAM_CODE_6797} "$out/lib/firmware/WIFI_RAM_CODE_6797"
  cd "$out/lib/firmware"
  sha256sum -c <<'HASHES'
  f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880  WMT_SOC.cfg
  5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e  ROMv3_patch_1_1_hdr.bin
  450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630  ROMv3_patch_1_0_hdr.bin
  a69383d74d829430487c39eef6b5e281b25f901595c903a632a10aa8631426dd  WIFI_RAM_CODE_6797
  HASHES
  test "$(stat -c %s WMT_SOC.cfg)" -eq 80
  test "$(stat -c %s ROMv3_patch_1_1_hdr.bin)" -eq 46472
  test "$(stat -c %s ROMv3_patch_1_0_hdr.bin)" -eq 210904
  test "$(stat -c %s WIFI_RAM_CODE_6797)" -eq 411632
''
