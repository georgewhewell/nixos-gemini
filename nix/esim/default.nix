{ pkgs, buildPkgs }:
let
  inherit (pkgs) lib;
  runtimePython = pkgs.python3.withPackages (ps: [ps.pygobject3]);
  lpac = pkgs.stdenv.mkDerivation {
    pname = "lpac";
    version = "2.3.0-82ada9e";
    src = buildPkgs.fetchzip {
      url = "https://github.com/estkme-group/lpac/archive/82ada9e53251c7f0cb08bfd9060b17019a30242c.tar.gz";
      sha256 = "1489hgvpd5x1vkjjyyj4si8ixs5zhgkzscx052yrhm0d8av21di0";
    };
    patches = [./at-unix-transport.patch];
    nativeBuildInputs = [buildPkgs.cmake buildPkgs.pkg-config];
    buildInputs = [pkgs.cjson pkgs.curl pkgs.pcsclite pkgs.libmbim pkgs.libqmi];
    cmakeFlags = [
      "-DUSE_SYSTEM_DEPS=ON"
      "-DBUILD_TESTING=OFF"
      "-DLPAC_VERSION=2.3.0-82ada9e"
      "-DLPAC_WITH_APDU_AT=ON"
      "-DLPAC_WITH_APDU_MBIM=ON"
      "-DLPAC_WITH_APDU_QMI=ON"
    ];
    # These actual-source checks run on the build host in cross builds too.
    postPatch = ''
      HOSTCC=${buildPkgs.stdenv.cc}/bin/cc HOSTCFLAGS=-U_FORTIFY_SOURCE \
        ${buildPkgs.python3}/bin/python3 ${./test-lpac-at.py} .
    '';
    strictDeps = true;
    postInstall = ''
      mkdir -p "$out/share/doc/lpac"
      cp -r ../docs/. "$out/share/doc/lpac/"
    '';
    meta = {
      description = "eUICC LPA with the generic AT transport";
      homepage = "https://github.com/estkme-group/lpac";
      mainProgram = "lpac";
      license = [lib.licenses.agpl3Only lib.licenses.lgpl21Plus];
      platforms = lib.platforms.linux;
    };
  };
  lpaGtk = pkgs.stdenv.mkDerivation {
    pname = "lpa-gtk";
    version = "0.4-35e272a";
    src = buildPkgs.fetchzip {
      url = "https://codeberg.org/lucaweiss/lpa-gtk/archive/35e272af38405ef1e138d89bce7acb5ac8e305fb.tar.gz";
      sha256 = "1l71wx95sxib03xhjf68vdbc914k1hlqj1bxyiv69fakrb0rxj6n";
    };
    patches = [./lpa-at.patch];
    nativeBuildInputs = [
      buildPkgs.meson buildPkgs.ninja buildPkgs.pkg-config
      buildPkgs.python3 buildPkgs.blueprint-compiler
      buildPkgs.desktop-file-utils buildPkgs.glib
      pkgs.gobject-introspection
      pkgs.wrapGAppsHook4
    ];
    buildInputs = [pkgs.gtk4 pkgs.libadwaita runtimePython];
    strictDeps = true;
    # Meson uses native Python to configure/build resources; installed modules
    # and the launcher belong to the target interpreter, including its GI ABI.
    postPatch = ''
      substituteInPlace src/meson.build \
        --replace-fail "pythondir = python3.get_install_dir()" \
          "pythondir = get_option('prefix') / '${pkgs.python3.sitePackages}'" \
        --replace-fail "conf.set('PYTHON', python3.full_path())" \
          "conf.set('PYTHON', '${runtimePython}/bin/python3')"
    '';
    # A host-only test must also run in a cross build.
    postBuild = ''
      ${buildPkgs.python3}/bin/python3 ../tests/test_at_backend.py
    '';
    # Blueprint and resource tools need native GI during the build. Only
    # target typelibs may be baked into the installed GApps wrapper.
    postInstall = ''
      install -Dm644 ${./70-lpa-at-uaccess.rules} "$out/lib/udev/rules.d/70-lpa-at-uaccess.rules"
      ${buildPkgs.systemd}/bin/udevadm verify "$out/lib/udev/rules.d/70-lpa-at-uaccess.rules"
      export GI_TYPELIB_PATH="${lib.makeSearchPathOutput "lib" "lib/girepository-1.0" [
        pkgs.glib pkgs.gobject-introspection pkgs.gdk-pixbuf pkgs.librsvg
        pkgs.graphene pkgs.harfbuzz pkgs.pango pkgs.gtk4 pkgs.libadwaita
      ]}"
    '';
    preFixup = ''
      gappsWrapperArgs+=(--prefix PATH : ${lib.makeBinPath [lpac]})
    '';
    postFixup = ''
      ${buildPkgs.python3}/bin/python3 - "$out" "${runtimePython}/bin/python3" <<'PY'
      import os, struct, sys
      from pathlib import Path
      package, python = map(Path, sys.argv[1:])
      wrapper = package / 'bin/lpa-gtk'
      launcher = package / 'bin/.lpa-gtk-wrapped'
      assert launcher.read_text().splitlines()[0] == '#!' + str(python)
      for path in (wrapper, python):
          header = path.read_bytes()[:20]
          assert header[:7] == b'\x7fELF\x02\x01\x01'
          assert struct.unpack_from('<HH', header, 16)[0] in (2, 3)
          assert struct.unpack_from('<H', header, 18)[0] == 183
          assert os.access(path, os.X_OK)
      assert (package / 'share/lpa-gtk/lpa-gtk.gresource').stat().st_size > 0
      assert (package / '${pkgs.python3.sitePackages}/lpa_gtk/modemmanager.py').is_file()
      for native in ('${buildPkgs.glib}', '${buildPkgs.gobject-introspection}', '${buildPkgs.python3}'):
          assert native.encode() not in wrapper.read_bytes()
      print('LPA_LAUNCHER_ARM64_PASS')
      PY
    '';
    meta = {
      description = "eUICC GTK interface with read-only generic AT discovery";
      homepage = "https://codeberg.org/lucaweiss/lpa-gtk";
      mainProgram = "lpa-gtk";
      license = lib.licenses.gpl3Only;
      platforms = ["aarch64-linux"];
    };
  };
in { inherit lpac lpaGtk runtimePython; }
