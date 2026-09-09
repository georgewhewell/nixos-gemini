{ buildPkgs, armPkgs, mesa }:
let
  weston = (armPkgs.weston.override {
    demoSupport = false;
    jpegSupport = false;
    lcmsSupport = false;
    luaSupport = false;
    pipewireSupport = false;
    rdpSupport = false;
    remotingSupport = false;
    vncSupport = false;
    vulkanSupport = false;
    webpSupport = false;
    xwaylandSupport = false;
  }).overrideAttrs (old: {
    mesonFlags = old.mesonFlags ++ [
      "-Dbackend-x11=false"
      "-Dbackend-wayland=false"
      "-Dshell-ivi=false"
      "-Dshell-kiosk=false"
      "-Dtools=terminal,info,debug"
      "-Dtests=false"
    ];
  });
  presentationCheck = armPkgs.stdenv.mkDerivation {
    pname = "gemini-desktop-presentation-check";
    version = "1";
    src = ./desktop-presentation-check.c;
    dontUnpack = true;
    nativeBuildInputs = [buildPkgs.pkg-config buildPkgs.wayland-scanner];
    buildInputs = [armPkgs.wayland];
    buildPhase = ''
      wayland-scanner client-header ${armPkgs.wayland-protocols}/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml xdg-shell-client-protocol.h
      wayland-scanner private-code ${armPkgs.wayland-protocols}/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml xdg-shell-protocol.c
      wayland-scanner client-header ${armPkgs.wayland-protocols}/share/wayland-protocols/stable/presentation-time/presentation-time.xml presentation-time-client-protocol.h
      wayland-scanner private-code ${armPkgs.wayland-protocols}/share/wayland-protocols/stable/presentation-time/presentation-time.xml presentation-time-protocol.c
      $CC -std=gnu11 -O2 -Wall -Wextra -Werror -Wno-unused-parameter -I. \
        "$src" xdg-shell-protocol.c presentation-time-protocol.c \
        $(pkg-config --cflags --libs wayland-client) -o gemini-desktop-presentation-check
    '';
    installPhase = ''
      mkdir -p "$out/bin"
      cp gemini-desktop-presentation-check "$out/bin/"
    '';
  };
in {
  inherit weston mesa presentationCheck;
  inherit (armPkgs) seatd dejavu_fonts vanilla-dmz;
}
