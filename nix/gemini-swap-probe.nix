{ buildPkgs, crossPkgs }:
let
  hostCheck = buildPkgs.runCommand "gemini-swap-probe-host-check" {
    nativeBuildInputs = [ buildPkgs.stdenv.cc ];
  } ''
    cc -std=c11 -Wall -Wextra -Werror -Wpedantic -O2 \
      ${./gemini-swap-probe.c} -o probe
    ./probe --self-test
    touch "$out"
  '';
in crossPkgs.pkgsStatic.stdenv.mkDerivation {
  pname = "gemini-swap-probe";
  version = "1";
  dontUnpack = true;
  buildPhase = ''
    test -f ${hostCheck}
    "$CC" -std=c11 -Wall -Wextra -Werror -Wpedantic -O2 -static \
      ${./gemini-swap-probe.c} -o gemini-swap-probe
  '';
  installPhase = ''
    install -Dm755 gemini-swap-probe "$out/bin/gemini-swap-probe"
  '';
}
