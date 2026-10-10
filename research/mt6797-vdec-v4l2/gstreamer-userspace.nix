# SPDX-License-Identifier: GPL-2.0-only
{ buildPkgs, targetPkgs }:

# Original build recipe; dependencies retain their upstream licenses.
let
  pkgs = buildPkgs;
  arm = targetPkgs;
  gst = arm.gst_all_1.gstreamer.override {
    withRust = false;
    withIntrospection = false;
    enableDocumentation = false;
  };
  base = (arm.gst_all_1.gst-plugins-base.override {
    gstreamer = gst;
    withIntrospection = false;
    enableDocumentation = false;
    enableX11 = false;
    enableWayland = false;
    enableAlsa = false;
    enableGl = false;
    enableCdparanoia = false;
  }).overrideAttrs (old: {
    buildInputs = [ arm.orc ];
    mesonFlags = [
      "-Dauto_features=disabled" "-Dorc=enabled" "-Dapp=enabled"
      "-Dvideoconvertscale=enabled" "-Drawparse=enabled"
      "-Dglib_debug=disabled" "-Dexamples=disabled" "-Dtests=disabled"
      "-Dintrospection=disabled" "-Ddoc=disabled"
    ];
  });
  bad = (arm.gst_all_1.gst-plugins-bad.override {
    gstreamer = gst;
    gst-plugins-base = base;
    enableDocumentation = false;
  }).overrideAttrs (old: {
    patches = (old.patches or []) ++ [ ./gstreamer-v4l2-buffer-errors.patch ];
    nativeBuildInputs = [ pkgs.meson pkgs.ninja pkgs.pkg-config pkgs.python3 pkgs.gettext pkgs.orc pkgs.glib ];
    buildInputs = [ base arm.orc arm.libgudev arm.libdrm ];
    mesonFlags = [
      "-Dauto_features=disabled" "-Dv4l2codecs=enabled" "-Dvideoparsers=enabled"
      "-Dorc=enabled" "-Dglib_debug=disabled" "-Dexamples=disabled"
      "-Dtests=disabled" "-Dintrospection=disabled" "-Ddoc=disabled"
    ];
  });
in pkgs.runCommand "gemini-video-gstreamer-userspace" {} ''
  mkdir -p "$out"
  ln -s ${gst.bin}/bin "$out/bin"
  ln -s ${gst.out}/libexec/gstreamer-1.0 "$out/helpers"
  printf '%s\n' '${gst.out}/lib/gstreamer-1.0:${base}/lib/gstreamer-1.0:${bad}/lib/gstreamer-1.0' > "$out/plugin-path"
  printf '%s\n' '${gst}' '${base}' '${bad}' > "$out/packages"
  test -e ${bad}/lib/gstreamer-1.0/libgstv4l2codecs.so
  test -e ${bad}/lib/gstreamer-1.0/libgstvideoparsersbad.so
''
