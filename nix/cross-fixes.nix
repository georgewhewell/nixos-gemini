# Packaging fixes for the pinned nixpkgs cross build.
final: prev: {
  pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
    (pythonFinal: pythonPrev: {
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
  gnome-session = prev.gnome-session.overrideAttrs (old: {
    # Meson needs a separate native pkg-config to find gdbus-codegen.
    # buildPackages.pkg-config still targets ARM64 in this package set.
    depsBuildBuild = (old.depsBuildBuild or []) ++ [final.pkgsBuildBuild.pkg-config];
    nativeBuildInputs = (old.nativeBuildInputs or []) ++ [final.buildPackages.glib];
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
