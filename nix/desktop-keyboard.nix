{ buildPkgs, armPkgs, hostWeston }:
let
  data = buildPkgs.runCommand "gemini-xkb-data" {} ''
    mkdir -p "$out/share/X11/xkb"
    cp -rs ${buildPkgs.xkeyboard_config}/share/X11/xkb/. "$out/share/X11/xkb/"
    test ! -L "$out/share/X11/xkb/symbols"
    chmod u+w "$out/share/X11/xkb/symbols"
    mkdir -p "$out/share/X11/xkb/symbols/planet_vndr"
    cp ${./keyboard/gemini-symbols} "$out/share/X11/xkb/symbols/planet_vndr/gemini"
    mkdir -p "$out/share/doc/gemini-xkb-data"
    cp ${./keyboard/COPYING} "$out/share/doc/gemini-xkb-data/COPYING"
  '';
  check = armPkgs.stdenv.mkDerivation {
    pname = "gemini-desktop-keyboard-check";
    version = "1";
    src = ./keyboard;
    nativeBuildInputs = [buildPkgs.pkg-config];
    buildInputs = [armPkgs.wayland armPkgs.libxkbcommon];
    dontConfigure = true;
    buildPhase = ''
      $CC -std=gnu11 -O2 -Wall -Wextra -Werror -Wno-unused-parameter \
        check.c $(pkg-config --cflags --libs wayland-client xkbcommon) \
        -o gemini-desktop-keyboard-check
    '';
    installPhase = ''
      mkdir -p "$out/bin"
      cp gemini-desktop-keyboard-check "$out/bin/"
    '';
  };
  fixture = buildPkgs.stdenv.mkDerivation {
    pname = "gemini-weston-keyboard-fixture";
    version = "1";
    src = ./keyboard/weston-keyboard-fixture.c;
    dontUnpack = true;
    dontConfigure = true;
    nativeBuildInputs = [buildPkgs.pkg-config];
    buildInputs = [hostWeston buildPkgs.pixman buildPkgs.wayland buildPkgs.libxkbcommon];
    buildPhase = ''
      $CC -shared -fPIC -O2 -Wall -Wextra -Werror -Wno-unused-parameter \
        "$src" $(pkg-config --cflags --libs weston libweston-16 pixman-1 wayland-server xkbcommon) -o keyboard-fixture.so
    '';
    installPhase = ''
      mkdir -p "$out/lib"
      cp keyboard-fixture.so "$out/lib/"
    '';
  };
in { inherit data check fixture; }
