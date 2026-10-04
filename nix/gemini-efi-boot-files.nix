{ buildPkgs, bootloader, linuxBundle, kernel }:
# The host artifact is separate from its one-shot early-boot publication.
buildPkgs.runCommand "gemini-efi-boot-files" {
  nativeBuildInputs = [ buildPkgs.python3 ];
} ''
  mkdir -p "$out"
  python3 ${../tools/build-gemini-efi-boot-files.py} \
    "$out" ${bootloader} ${linuxBundle} ${kernel}
''
