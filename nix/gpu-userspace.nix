{ buildPkgs, armPkgs }:
let
  # The smoke test, Weston qualification and GNOME share one Mesa build.
  mesa = import ./mesa.nix {pkgs = armPkgs;};
  smoke = armPkgs.stdenv.mkDerivation {
    pname = "gemini-gpu-render-smoke";
    version = "1";
    src = ./gpu-render-smoke.c;
    dontUnpack = true;
    nativeBuildInputs = [buildPkgs.pkg-config armPkgs.makeWrapper buildPkgs.python3];
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
    # This reads target artifacts on the build host. Cross stdenv skips the
    # installCheck phase, so keep the mandatory admission after fixups.
    postFixup = ''
      python3 - "$out" "${armPkgs.runtimeShell}" <<'PY'
      import os
      from pathlib import Path
      import struct
      import sys

      package, shell = Path(sys.argv[1]), sys.argv[2]
      wrapper = package / "bin/gpu-render-smoke"
      line = wrapper.read_text().splitlines()[0]
      if not line.startswith("#!") or line[2:].split() != [shell, "-e"]:
          raise SystemExit("GPU launcher does not use the expected target shell")
      for path in (Path(shell), package / "bin/.gpu-render-smoke-wrapped"):
          with path.open("rb") as executable:
              header = executable.read(20)
          if (len(header) != 20 or header[:7] != b"\x7fELF\x02\x01\x01"
                  or struct.unpack_from("<H", header, 16)[0] not in (2, 3)
                  or struct.unpack_from("<H", header, 18)[0] != 183
                  or not os.access(path, os.X_OK)):
              raise SystemExit("GPU launcher executable is not ELF64 ARM64: " + str(path))
      print("GPU_LAUNCHER_ARM64_PASS interpreter=" + shell)
      PY
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
