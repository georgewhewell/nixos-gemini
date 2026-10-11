{ buildPkgs, armPkgs }:
let
  # The smoke test, Weston qualification and GNOME share one Mesa build.
  mesa = import ./mesa.nix {pkgs = armPkgs;};
  smoke = armPkgs.stdenv.mkDerivation {
    pname = "gemini-gpu-render-smoke";
    version = "1";
    src = ./gpu-render-smoke.c;
    dontUnpack = true;
    nativeBuildInputs = [buildPkgs.pkg-config buildPkgs.makeWrapper];
    buildInputs = [armPkgs.libglvnd armPkgs.libgbm armPkgs.libdrm];
    buildPhase = ''
      $CC -std=gnu11 -O2 -Wall -Wextra -Werror "$src" \
        $(pkg-config --cflags --libs egl glesv2 gbm libdrm) -o gpu-render-smoke
    '';
    installPhase = ''
      test -s ${pixelCheck}
      mkdir -p "$out/bin"
      cp gpu-render-smoke "$out/bin/"
      wrapProgram "$out/bin/gpu-render-smoke" \
        --set __EGL_VENDOR_LIBRARY_FILENAMES ${mesa}/share/glvnd/egl_vendor.d/50_mesa.json \
        --set LIBGL_DRIVERS_PATH ${mesa}/lib/dri \
        --set GBM_BACKENDS_PATH ${mesa}/lib/gbm \
        --set MESA_LOADER_DRIVER_OVERRIDE panfrost \
        --set MESA_SHADER_CACHE_DISABLE true
    '';
  };
  pixelCheck = buildPkgs.runCommand "gemini-gpu-pixel-check" {
    nativeBuildInputs = [buildPkgs.python3 buildPkgs.stdenv.cc];
  } ''
    cp ${./gpu-render-smoke.c} gpu-render-smoke.c
    cp ${./test-gpu-pixel-check.py} test-gpu-pixel-check.py
    HOSTCC="$CC" python3 test-gpu-pixel-check.py > "$out"
  '';
in { inherit smoke mesa; }
