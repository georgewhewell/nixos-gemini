{ pkgs }: pkgs.pkgsStatic.stdenv.mkDerivation {
  pname = "gemini-zram-probe";
  version = "1";
  src = ./gemini-zram-probe.c;
  dontUnpack = true;
  dontConfigure = true;
  buildPhase = ''
    $CC -std=gnu11 -O2 -Wall -Wextra -Werror "$src" -o gemini-zram-probe
  '';
  installPhase = ''
    mkdir -p "$out/bin" "$out/share/gemini-zram-probe"
    cp gemini-zram-probe "$out/bin/"
    echo ${builtins.hashFile "sha256" ./gemini-zram-probe.c} > "$out/share/gemini-zram-probe/source.sha256"
  '';
}
