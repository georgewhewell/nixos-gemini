# MT6797 SPM PCM scenario programs from the stock Gemian/Android system
# image (/vendor/firmware, dated 2019-05-08).  They are vendor binaries with no
# redistribution grant, so they are not in this repository: each file is a
# fixed-output store path that must be added once on the build host, e.g.
#
#   nix-store --add-fixed sha256 \
#     /mnt/Home/src/nixos-gemini/private-vendor-firmware-20260928/firmware/pcm_*.bin
#
# The names and the directory layout follow the kernel's MODULE_FIRMWARE
# entries (mediatek/mt6797/pcm_*.bin).
{ buildPkgs }:
let
  images = [
    { name = "pcm_suspend.bin"; size = 7378; sha256 = "d6e8a0b8851e78e95891c995605ffbf210eade56583b14cf6b4a67e7d770f4e0"; }
    { name = "pcm_suspend_by_mp1.bin"; size = 7382; sha256 = "f8b9e333423d5d051302072cb853d50ab4e13a8528b407b9efdc92fe28648807"; }
    { name = "pcm_vcorefs_lpm.bin"; size = 8261; sha256 = "b756fb01239ea5d857d01e0516a86a12b41ddf4fa04006297fef93e6b1a4c3c3"; }
    { name = "pcm_vcorefs_hpm.bin"; size = 8085; sha256 = "c0f676003ffa69341402f29a58a1d1d753fd1035d3a52f5cc7306f305412e584"; }
    { name = "pcm_vcorefs_ultra.bin"; size = 8087; sha256 = "a52ea060d30110a52c18d31ab70b3b9600c90d67287a1acb83ebbd41c1966730"; }
    { name = "pcm_sodi.bin"; size = 6423; sha256 = "dda8cca1e110d57137afb8ef4957da758c19d38db45ea2bb30bc7133cc122ae4"; }
    { name = "pcm_sodi_by_mp1.bin"; size = 6427; sha256 = "8649d6db309753fd017bcd778568e093af623bc0f4acc2a20efa8c8d4c775ffd"; }
    { name = "pcm_deepidle.bin"; size = 6723; sha256 = "e9066110b607379cd73560804bf195f2cd9ea1e799f130f5638c09c446eedcd8"; }
    { name = "pcm_deepidle_by_mp1.bin"; size = 6727; sha256 = "36267de8a55699de516d61b1d9e64591a2b7d4f187d3460cfa93c81b3e1e4cf6"; }
  ];
  fetch = image: buildPkgs.requireFile {
    inherit (image) name sha256;
    hashMode = "flat";
    message = ''
      ${image.name} is a private MT6797 SPM firmware image from the stock
      Gemini system partition (/vendor/firmware).  Add it to the store with:
        nix-store --add-fixed sha256 /path/to/${image.name}
    '';
  };
in
buildPkgs.runCommand "gemini-mt6797-spm-firmware" {} ''
  dir="$out/lib/firmware/mediatek/mt6797"
  mkdir -p "$dir"
  ${buildPkgs.lib.concatMapStrings (image: ''
    cp ${fetch image} "$dir/${image.name}"
    test "$(stat -c %s "$dir/${image.name}")" -eq ${toString image.size}
    echo "${image.sha256}  $dir/${image.name}" | sha256sum -c --quiet
  '') images}
''
