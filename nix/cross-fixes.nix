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
}
