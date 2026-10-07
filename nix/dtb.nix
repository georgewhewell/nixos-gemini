{
  buildPkgs,
  kernel,
}:
# Use Linux's board DT directly, including for a native Kbuild build.
buildPkgs.runCommand "gemini-dtb" {} ''
  mkdir -p "$out"
  cp ${kernel}/base.dtb "$out/gemini.dtb"
  cat ${kernel}/Image.gz "$out/gemini.dtb" > "$out/Image.gz-dtb"
''
