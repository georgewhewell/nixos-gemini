{ buildPkgs }:
buildPkgs.mtkclient.overrideAttrs (old: {
  pname = "mtkclient-gemini";
  patches = (old.patches or []) ++ [
    ../patches/mtkclient/0001-explicit-reboot-and-acknowledged-reset.patch
    ../patches/mtkclient/0002-report-partition-write-failures.patch
    ../patches/mtkclient/0003-mt6797-shutdown-packet-size.patch
  ];
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    ${buildPkgs.python3.interpreter} ${./test-mtkclient-reset.py}
    ${buildPkgs.python3.interpreter} ${./test-mtkclient-write.py}
    # Keep host orchestrator pins out of the package hash. Importing the whole
    # tools directory creates a hash cycle when a runner pins this package.
    mkdir qualification-tests
    cp ${../tools/qualify-mtkclient.py} qualification-tests/qualify-mtkclient.py
    cp ${../tools/test-qualify-mtkclient.py} qualification-tests/test-qualify-mtkclient.py
    ${buildPkgs.python3.interpreter} qualification-tests/test-qualify-mtkclient.py
    runHook postCheck
  '';
})
