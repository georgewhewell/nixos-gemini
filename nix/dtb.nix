{
  buildPkgs,
  kernel,
}:
# All hardware configuration comes from Linux's board DTS. Only the identity
# consumed by the existing A72 driver is attached after the kernel is linked.
buildPkgs.runCommand "gemini-dtb" {
  nativeBuildInputs = [buildPkgs.python3 buildPkgs.dtc buildPkgs.binutils];
} ''
  mkdir -p "$out"
  cp ${kernel}/base.dtb "$out/gemini.dtb"
  chmod u+w "$out/gemini.dtb"
  python3 ${./a72-profile-package.py} ${kernel} "$out/gemini.dtb" \
    ${./generate-late-cpu-provenance.py}
  cat ${kernel}/Image.gz "$out/gemini.dtb" > "$out/Image.gz-dtb"
''
