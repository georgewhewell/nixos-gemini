{pkgs}:
(pkgs.mesa.override {
  galliumDrivers = ["panfrost"];
  vulkanDrivers = [];
  vulkanLayers = [];
  withValgrind = false;
}).overrideAttrs (old: {
  # Keep the normal EGL/GLX frontends for GNOME and Xwayland, with the
  # MT6797's Panfrost renderer and KMS bridge. Codec work uses native V4L2.
  mesonFlags = old.mesonFlags ++ [
    "-Dauto_features=auto"
    "-Dgallium-va=disabled"
    "-Dteflon=false"
  ];
  postInstall = old.postInstall + ''
    mkdir -p "$spirv2dxil"
  '';
})
