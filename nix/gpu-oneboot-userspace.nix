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
  closure = buildPkgs.closureInfo { rootPaths = [smoke]; };
  pixelCheck = buildPkgs.runCommand "gemini-gpu-pixel-check" {
    nativeBuildInputs = [buildPkgs.python3 buildPkgs.stdenv.cc];
  } ''
    cp ${./gpu-render-smoke.c} gpu-render-smoke.c
    cp ${./test-gpu-pixel-check.py} test-gpu-pixel-check.py
    HOSTCC="$CC" python3 test-gpu-pixel-check.py > "$out"
  '';
  archive = buildPkgs.runCommand "gemini-gpu-oneboot-userspace.tar.gz" {
    nativeBuildInputs = [buildPkgs.gnutar buildPkgs.gzip buildPkgs.binutils];
  } ''
    test -s ${pixelCheck}
    # Mesa 26.2 links drivers into libgallium; it no longer installs the
    # per-driver DRI aliases. Check the actual linked screen constructors.
    test -s ${mesa}/lib/libgallium-${mesa.version}.so
    nm --defined-only ${mesa}/lib/libgallium-${mesa.version}.so > driver-symbols
    grep -Eq ' [tT] panfrost_create_screen$' driver-symbols
    if grep -Eq ' [tT] (llvmpipe|softpipe)_create_screen$' driver-symbols; then
      echo 'unexpected software renderer in Panfrost-only archive' >&2
      exit 1
    fi
    test -s ${mesa}/share/glvnd/egl_vendor.d/50_mesa.json
    tar -c -f - --files-from ${closure}/store-paths | gzip -1 > "$out"
  '';
in { inherit smoke closure archive mesa; }
