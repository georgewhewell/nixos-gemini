{pkgs}:
(pkgs.mesa.override {
  galliumDrivers = ["panfrost"];
  vulkanDrivers = [];
  vulkanLayers = [];
  withValgrind = false;
}).overrideAttrs (old: {
  # Keep the normal EGL/GLX frontends for GNOME and Xwayland, with the
  # MT6797's Panfrost renderer and KMS bridge. Codec work uses native V4L2.
  patches = (old.patches or []) ++ [./panfrost-image-extents.patch];
  postPatch = old.postPatch + ''
    ${pkgs.buildPackages.python3.withPackages (p: [p.pyyaml])}/bin/python3 \
      ${./test-panfrost-image-extents.py} . \
      --cc ${pkgs.buildPackages.stdenv.cc}/bin/cc
  '';
  mesonFlags = old.mesonFlags ++ [
    "-Dauto_features=auto"
    "-Dgallium-va=disabled"
    "-Dteflon=false"
  ];
  postInstall = old.postInstall + ''
    mkdir -p "$spirv2dxil"
  '';
})
