# Packaging fixes for the pinned nixpkgs cross build.
final: prev: let
  cross = !prev.stdenv.buildPlatform.canExecute prev.stdenv.hostPlatform;
  qtHostToolsFlag = "-DQT_ADDITIONAL_HOST_PACKAGES_PREFIX_PATH=${final.pkgsBuildBuild.qt6.qtdeclarative};${final.pkgsBuildBuild.qt6.qttools};${final.pkgsBuildBuild.qt6.qtshadertools};${final.pkgsBuildBuild.qt6.qtquick3d}";
  nativeDocTools = final.pkgsBuildBuild.kdePackages.kdoctools.overrideAttrs (old: {
    cmakeFlags = (old.cmakeFlags or []) ++ ["-DINSTALL_INTERNAL_TOOLS=ON"];
  });
  nativeBreezeTools = final.pkgsBuildBuild.kdePackages.breeze-icons.overrideAttrs (old: {
    cmakeFlags = (old.cmakeFlags or []) ++ ["-DINSTALL_HOST_TOOLS=ON"];
  });
in {
  qt6 = prev.qt6.overrideScope (qtFinal: qtPrev: {
    qtModule = args: (qtPrev.qtModule args).overrideAttrs (old:
      # Modules using Qt Declarative need its native generation tools.
      prev.lib.optionalAttrs (cross && prev.lib.any
        (input: (input.pname or "") == "qtdeclarative")
        (args.propagatedBuildInputs or [])) {
        cmakeFlags = (old.cmakeFlags or []) ++ [
          qtHostToolsFlag
          # Qt Quick 3D searches this tool package directly.
          "-DQt6ShaderToolsTools_DIR=${final.pkgsBuildBuild.qt6.qtshadertools}/lib/cmake/Qt6ShaderToolsTools"
        ];
      });
    qtdeclarative = qtPrev.qtdeclarative.overrideAttrs (old:
      prev.lib.optionalAttrs cross {
        # The pinned package points at ShaderTools instead of its Tools
        # directory, silently disabling Qt Quick during cross configure.
        cmakeFlags = map (flag:
          if prev.lib.hasPrefix "-DQt6ShaderToolsTools_DIR=" flag then
            "-DQt6ShaderToolsTools_DIR=${final.pkgsBuildBuild.qt6.qtshadertools}/lib/cmake/Qt6ShaderToolsTools"
          else flag) (old.cmakeFlags or []) ++ [
          "-DQt6QuickTools_DIR=${final.pkgsBuildBuild.qt6.qtdeclarative}/lib/cmake/Qt6QuickTools"
        ];
      });
  });
  kdePackages = prev.kdePackages.overrideScope (kdeFinal: kdePrev: {
    # Gemini's Qt applications use the C++/QML libraries. The optional
    # Python bindings require native Shiboken and every Qt module, including
    # Chromium, without supplying anything used by the SMS application.
    mkKdeDerivation = args:
      let
        # Use native tools in the existing upstream install-check hook.
        nativeQmlLintHook = final.buildPackages.makeSetupHook {
          name = "qmllint-validate-hook";
          substitutions = {
            qmllint = "${final.pkgsBuildBuild.qt6.qtdeclarative}/bin/qmllint";
            jq = prev.lib.getExe final.pkgsBuildBuild.jq;
          };
          meta.license = prev.lib.licenses.mit;
        } (prev.path + "/pkgs/kde/lib/qmllint-hook.sh");
      in (kdePrev.mkKdeDerivation (args // prev.lib.optionalAttrs cross {
        hasPythonBindings = false;
        # ECM supplies architecture-independent CMake modules. CMake's
        # cross search path does not find native build dependencies.
        extraNativeBuildInputs = (args.extraNativeBuildInputs or []) ++ [
          final.buildPackages.kdePackages.extra-cmake-modules
        ];
        extraCmakeFlags = (args.extraCmakeFlags or []) ++ [
          "-DECM_DIR=${final.buildPackages.kdePackages.extra-cmake-modules}/share/ECM/cmake"
          qtHostToolsFlag
          "-DKF6_HOST_TOOLING=${final.pkgsBuildBuild.kdePackages.kconfig.dev}/lib/cmake;${nativeDocTools.dev}/lib/cmake;${nativeBreezeTools}/bin"
        ] ++ prev.lib.optionals (args.hasPythonBindings or false) [
          "-DBUILD_PYTHON_BINDINGS=OFF"
        ];
      })).overrideAttrs (old: prev.lib.optionalAttrs cross {
        nativeBuildInputs = map (input:
          if prev.lib.getName input == "qmllint-validate-hook" then nativeQmlLintHook
          # Native Qt dev outputs propagate host libraries and setup hooks.
          # Use only the outputs needed by generators and QML checks.
          else if prev.lib.getName input == "qttools" then final.pkgsBuildBuild.qt6.qttools.out
          else if prev.lib.getName input == "qtsvg" then final.pkgsBuildBuild.qt6.qtsvg.out
          else input) (old.nativeBuildInputs or []);
      });
    futuresql = kdePrev.futuresql.overrideAttrs (old:
      prev.lib.optionalAttrs cross {
        cmakeFlags = (old.cmakeFlags or []) ++ [
          "-DECM_DIR=${final.buildPackages.kdePackages.extra-cmake-modules}/share/ECM/cmake"
        ];
      });
    qcoro = kdePrev.qcoro.overrideAttrs (old:
      prev.lib.optionalAttrs cross {
        cmakeFlags = (old.cmakeFlags or []) ++ [qtHostToolsFlag];
      });
    kdoctools = kdePrev.kdoctools.overrideAttrs (old:
      prev.lib.optionalAttrs cross {
        # Bootstrap documentation and localization with host executables.
        cmakeFlags = (old.cmakeFlags or []) ++ [
          "-DMEINPROC6_EXECUTABLE=${nativeDocTools}/bin/meinproc6"
          "-DDOCBOOKL10NHELPER_EXECUTABLE=${nativeDocTools}/bin/docbookl10nhelper"
          "-DCHECKXML6_EXECUTABLE=${nativeDocTools}/bin/checkXML6"
        ];
      });
  });
  pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
    (pythonFinal: pythonPrev: {
      buildPythonApplication = pythonPrev.buildPythonApplication // {
        __functor = _: args:
          pythonPrev.buildPythonApplication (
            if prev.lib.isFunction args then args
            else args // prev.lib.optionalAttrs (
              (args.name or "") == "set-session"
              && !prev.stdenv.buildPlatform.canExecute prev.stdenv.hostPlatform
            ) {
              # NixOS's private GDM helper forces strictDeps=false. Its native
              # scanner then puts host GLib typelibs before the target libraries.
              strictDeps = true;
            });
      };
      dbus-python = pythonPrev.dbus-python.overrideAttrs (old: {
        # pygobject's test dependency propagates the introspection hook.
        # In the cross package set that hook requires a host g-ir-scanner,
        # even when dbus-python itself is being built for the build machine.
        nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.buildPackages.gobject-introspection];
      });
    })
  ];
  gupnp-av = prev.gupnp-av.overrideAttrs (old: {
    # 0.14.5 looks up gi-docgen twice. The second lookup accidentally asks
    # for a target executable; documentation generation runs on the host.
    patches = (old.patches or []) ++ [./patches/gupnp-av-native-docgen.patch];
  });
  gom = prev.gom.overrideAttrs (old: {
    # Meson runs Python to install the GI overrides. Their destination is
    # already the target sitePackages path supplied by the package.
    nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.buildPackages.python3];
  });
  gnome-session = prev.gnome-session.overrideAttrs (old: {
    # Meson needs a separate native pkg-config to find gdbus-codegen.
    # buildPackages.pkg-config still targets ARM64 in this package set.
    depsBuildBuild = (old.depsBuildBuild or []) ++ [final.pkgsBuildBuild.pkg-config];
    nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.buildPackages.glib];
  });
  gnome-shell = prev.gnome-shell.overrideAttrs (old:
    prev.lib.optionalAttrs (!prev.stdenv.buildPlatform.canExecute prev.stdenv.hostPlatform) {
      # Fixup finds Meson's native Python first. The installed extension tool
      # and test tool run on the device and only import the standard library.
      postFixup = (old.postFixup or "") + ''
        for tool in gnome-shell-extension-tool gnome-shell-test-tool; do
          substituteInPlace "$out/bin/.$tool-wrapped" \
            --replace-fail '#!${final.buildPackages.python3}/bin/python3' \
            '#!${final.python3}/bin/python3'
        done
      '';
    });
  orca = prev.orca.overrideAttrs (old:
    let nativePython = final.buildPackages.python3.withPackages (p: [p.pygobject3]);
    in
    prev.lib.optionalAttrs (!prev.stdenv.buildPlatform.canExecute prev.stdenv.hostPlatform) {
      # Native Gtk is needed by Meson's GI import. Its typelibs and loaders
      # must not precede the target libraries in the installed Python wrapper.
      strictDeps = true;
      preConfigure = ''
        geminiTargetTypelibPath="''${GI_TYPELIB_PATH:-}"
        export PATH="${nativePython}/bin:$PATH"
      '' + (old.preConfigure or "") + ''
        export GI_TYPELIB_PATH="${prev.lib.makeSearchPathOutput "lib" "lib/girepository-1.0" (with final.buildPackages; [
          gtk3 glib gdk-pixbuf at-spi2-core pango harfbuzz gobject-introspection
        ])}"
      '';
      postConfigure = (old.postConfigure or "") + ''
        export GI_TYPELIB_PATH="$geminiTargetTypelibPath"
      '';
      postFixup = (old.postFixup or "") + ''
        substituteInPlace "$out/bin/.orca-wrapped" \
          --replace-fail '#!${nativePython}/bin/python3' \
          '#!${final.python3}/bin/python3'
      '';
    });
  gnome-browser-connector = prev.gnome-browser-connector.overrideAttrs (old: {
    # Meson's configure-time gi import must use native Python extension
    # modules; pythonPath still supplies target pygobject at runtime.
    nativeBuildInputs = (old.nativeBuildInputs or []) ++ [
      (final.buildPackages.python3.withPackages (p: [p.pygobject3]))
    ];
  });
  # These Meson custom targets invoke Cargo without selecting its target.
  # Keep Cargo's output directory and Meson's installed binary in agreement.
  gst-thumbnailers = prev.gst-thumbnailers.overrideAttrs (old:
    prev.lib.optionalAttrs (prev.stdenv.buildPlatform.config != prev.stdenv.hostPlatform.config) {
      env = (old.env or {}) // { CARGO_BUILD_TARGET = prev.stdenv.hostPlatform.rust.rustcTargetSpec; };
      postPatch = (old.postPatch or "") + ''
        substituteInPlace meson.build --replace-fail \
          'cargo_target_dir / rust_target' \
          "cargo_target_dir / '${prev.stdenv.hostPlatform.rust.rustcTarget}' / rust_target"
      '';
      doCheck = prev.stdenv.buildPlatform.canExecute prev.stdenv.hostPlatform;
    });
  glycin-thumbnailer = prev.glycin-thumbnailer.overrideAttrs (old:
    prev.lib.optionalAttrs (prev.stdenv.buildPlatform.config != prev.stdenv.hostPlatform.config) {
      env = (old.env or {}) // { CARGO_BUILD_TARGET = prev.stdenv.hostPlatform.rust.rustcTargetSpec; };
      postPatch = (old.postPatch or "") + ''
        substituteInPlace glycin-thumbnailer/meson.build --replace-fail \
          'cargo_target_dir / rust_target' \
          "cargo_target_dir / '${prev.stdenv.hostPlatform.rust.rustcTarget}' / rust_target"
      '';
    });
  gnome-tour = prev.gnome-tour.overrideAttrs (old:
    prev.lib.optionalAttrs (prev.stdenv.buildPlatform.config != prev.stdenv.hostPlatform.config) {
      env = (old.env or {}) // { CARGO_BUILD_TARGET = prev.stdenv.hostPlatform.rust.rustcTargetSpec; };
      postPatch = (old.postPatch or "") + ''
        substituteInPlace src/meson.build --replace-fail \
          "'src' / rust_target" \
          "'src' / '${prev.stdenv.hostPlatform.rust.rustcTarget}' / rust_target"
      '';
    });
}
