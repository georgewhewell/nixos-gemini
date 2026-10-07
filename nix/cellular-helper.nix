{
  buildPkgs,
  crossPkgs,
  linux-gemini,
}:
crossPkgs.pkgsStatic.stdenv.mkDerivation {
  pname = "gemini-cellular-fs-register";
  version = "ci1";
  src = linux-gemini;
  dontConfigure = true;
  nativeBuildInputs = [buildPkgs.python3 buildPkgs.coreutils buildPkgs.bash];
  buildPhase = ''
    mkdir stage2-tests
    cp ${./test-cellular-stage2.py} stage2-tests/test-cellular-stage2.py
    cp ${./cellular-stage2.sh} stage2-tests/cellular-stage2.sh
    python3 stage2-tests/test-cellular-stage2.py
    python3 tools/gemini/test-fs-restore-register.py
    python3 ${./test-a72-resource-preflight.py} tools/gemini/mt6797-a72-resource-preflight.sh
    $CC -O2 -Wall -Wextra -Werror -o mt6797-fs-register tools/gemini/mt6797-fs-register.c
  '';
  installPhase = ''
    mkdir -p "$out/bin"
    cp mt6797-fs-register "$out/bin/"
    mkdir -p "$out/share/gemini"
    cp tools/gemini/mt6797-a72-resource-preflight.sh "$out/share/gemini/"
    cp tools/gemini/{mt6797_fs_restore_register,nvram_restore_archive,nvram_backup_format}.py "$out/share/gemini/"
  '';
}
