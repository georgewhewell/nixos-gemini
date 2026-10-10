{ buildPkgs, armPkgs, hostWeston }:
let
  data = buildPkgs.runCommand "gemini-xkb-data" {
    nativeBuildInputs = [buildPkgs.python3];
  } ''
    mkdir -p "$out/share/X11/xkb"
    cp -rs ${buildPkgs.xkeyboard_config}/share/X11/xkb/. "$out/share/X11/xkb/"
    test ! -L "$out/share/X11/xkb/symbols"
    chmod u+w "$out/share/X11/xkb/symbols"
    mkdir -p "$out/share/X11/xkb/symbols/planet_vndr"
    cp ${./keyboard/gemini-symbols} "$out/share/X11/xkb/symbols/planet_vndr/gemini"
    ln -s planet_vndr/gemini "$out/share/X11/xkb/symbols/gemini"
    # GNOME's XkbInfo validates source IDs against the XML registry before
    # asking xkbcommon to compile them. A symbols file alone is insufficient.
    chmod u+w "$out/share/X11/xkb/rules"
    python3 - "$out/share/X11/xkb/rules" <<'PY'
    from pathlib import Path
    import sys
    import xml.etree.ElementTree as ET
    for name in ('base.xml', 'evdev.xml'):
        path = Path(sys.argv[1]) / name
        tree = ET.parse(path)
        layouts = tree.getroot().find('layoutList')
        assert layouts is not None
        assert not any(x.findtext('configItem/name') == 'gemini' for x in layouts)
        layout = ET.SubElement(layouts, 'layout')
        item = ET.SubElement(layout, 'configItem')
        for key, value in [('name', 'gemini'), ('shortDescription', 'en'),
                           ('description', 'Planet Computers Gemini (US)')]:
            ET.SubElement(item, key).text = value
        languages = ET.SubElement(item, 'languageList')
        ET.SubElement(languages, 'iso639Id').text = 'eng'
        variants = ET.SubElement(layout, 'variantList')
        variant = ET.SubElement(variants, 'variant')
        config = ET.SubElement(variant, 'configItem')
        ET.SubElement(config, 'name').text = 'us'
        ET.SubElement(config, 'description').text = 'Planet Computers Gemini (US)'
        path.unlink()
        tree.write(path, encoding='utf-8', xml_declaration=True)
    PY
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
