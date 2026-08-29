{
  lib,
  stdenv,
  fetchurl,
  autoPatchelfHook,
  makeWrapper,
  # Runtime dependencies
  zlib,
  libx11,
  libxext,
  libxrender,
  libsm,
  libice,
  libjpeg,
  libpng,
  gst_all_1,
  glib,
  sqlite,
  fontconfig,
  freetype,
  libGL,
  dbus,
  libpulseaudio,
}:
stdenv.mkDerivation rec {
  pname = "mtk-flash-tool";
  version = "2018-04-07";

  src = fetchurl {
    url = "http://support.planetcom.co.uk/download/FlashToolLinux.tgz";
    sha256 = "0fy0i6qw4lhnixl1nna8v45cgwnmjq1ip6cwh0ch8zmig13c3zba";
  };

  nativeBuildInputs = [
    autoPatchelfHook
    makeWrapper
  ];

  buildInputs = [
    stdenv.cc.cc.lib # libstdc++
    zlib
    libx11
    libxext
    libxrender
    libsm
    libice
    libjpeg
    libpng
    gst_all_1.gstreamer
    gst_all_1.gst-plugins-base
    glib
    sqlite
    fontconfig
    freetype
    libGL
    dbus
    libpulseaudio
  ];

  # Ignore Qt4 internal deps and old soversions we can't satisfy
  autoPatchelfIgnoreMissingDeps = [
    "libQtXml.so.4"
    "libQtSvg.so.4"
    "libQtCLucene.so.4"
    "libaudio.so.2" # NAS audio - not needed for flashing
    "libmng.so.1" # MNG image format plugin - optional
    "libtiff.so.5" # TIFF image format plugin - optional
  ];

  sourceRoot = "FlashToolLinux";

  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/opt/mtk-flash-tool
    mkdir -p $out/bin
    mkdir -p $out/lib

    # Copy all files
    cp -r . $out/opt/mtk-flash-tool/

    # Create stub libaudio.so.2 - the flash tool doesn't actually need audio
    echo 'void AuOpenServer() {} void AuCloseServer() {} void AuNextEvent() {}' > stub.c
    $CC -shared -o $out/lib/libaudio.so.2 stub.c

    # Create wrapper script
    makeWrapper $out/opt/mtk-flash-tool/flash_tool $out/bin/mtk-flash-tool \
      --prefix LD_LIBRARY_PATH : $out/opt/mtk-flash-tool:$out/lib \
      --set QT_X11_NO_MITSHM 1 \
      --set QT_PLUGIN_PATH $out/opt/mtk-flash-tool/plugins

    runHook postInstall
  '';

  meta = with lib; {
    description = "MediaTek SP Flash Tool for flashing Android/Linux devices";
    homepage = "https://support.planetcom.co.uk/index.php/Linux_Flashing_Guide";
    license = licenses.unfree;
    platforms = ["x86_64-linux"];
    maintainers = [];
  };
}
