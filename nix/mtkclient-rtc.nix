{ buildPkgs }:
(import ./mtkclient.nix { inherit buildPkgs; }).overrideAttrs (old: {
  pname = "mtkclient-gemini-rtc";
  patches = old.patches ++ [ ../patches/mtkclient/0007-explicit-rtc-preservation.patch ];
  checkPhase = old.checkPhase + ''
    ${buildPkgs.python3.interpreter} ${./test-mtkclient-rtc.py} ${./test-mtkclient-reset.py}
  '';
})
