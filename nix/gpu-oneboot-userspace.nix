{ buildPkgs, armPkgs }:
let
  # Keep the same Mesa revision and Panfrost renderer, but do not transfer
  # unrelated GPU/Vulkan/software drivers into the bounded RAM test boot.
  mesa = (armPkgs.mesa.override {
    galliumDrivers = [ "panfrost" ];
    vulkanDrivers = [];
    vulkanLayers = [];
    eglPlatforms = [];
    withValgrind = false;
  }).overrideAttrs (old: {
    # nixpkgs enables optional Meson features globally; these two require
    # X11 and must be explicitly disabled for the headless EGL test.
    mesonFlags = old.mesonFlags ++ [
      "-Dauto_features=auto" "-Dxlib-lease=disabled" "-Dglx=disabled"
      "-Dgallium-va=disabled" "-Dteflon=false"
    ];
    # Mesa's multi-output package still declares this output when no D3D12
    # frontend is selected. Publish an empty output, not a missing path.
    postInstall = old.postInstall + ''
      mkdir -p "$spirv2dxil"
    '';
  });
  smoke = armPkgs.stdenv.mkDerivation {
    pname = "gemini-gpu-render-smoke";
    version = "1";
    src = ./gpu-render-smoke.c;
    dontUnpack = true;
    nativeBuildInputs = [armPkgs.pkg-config armPkgs.makeWrapper];
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
in { inherit smoke closure archive; }
