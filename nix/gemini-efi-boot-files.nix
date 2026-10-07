{ buildPkgs, bootloader, linuxBundle, kernel, versionedEntry ? false, entryDtb ? false }:
assert !entryDtb || versionedEntry;
# The host artifact is separate from its one-shot early-boot publication.
buildPkgs.runCommand "gemini-efi-boot-files" {
  nativeBuildInputs = [ buildPkgs.python3 ] ++ buildPkgs.lib.optional entryDtb buildPkgs.dtc;
} ''
  mkdir -p "$out"
  GEMINI_BOOT_INSTALL=${./gemini-boot-install.py} python3 ${../tools/build-gemini-efi-boot-files.py} \
    "$out" ${bootloader} ${linuxBundle} ${kernel} ${buildPkgs.lib.optionalString versionedEntry "--versioned-entry"}${buildPkgs.lib.optionalString entryDtb " --entry-dtb"}
''
