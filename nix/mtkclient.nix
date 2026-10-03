{ buildPkgs }:
buildPkgs.mtkclient.overrideAttrs (old: {
  pname = "mtkclient-gemini";
  patches = (old.patches or []) ++ [
    ../patches/mtkclient/0001-explicit-reboot-and-acknowledged-reset.patch
  ];
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    ${buildPkgs.python3.interpreter} ${./test-mtkclient-reset.py}
    ${buildPkgs.python3.interpreter} ${../tools}/test-qualify-mtkclient.py
    runHook postCheck
  '';
})
