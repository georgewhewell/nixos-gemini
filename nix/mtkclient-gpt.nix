{ buildPkgs }:
(import ./mtkclient.nix { inherit buildPkgs; }).overrideAttrs (old: {
  pname = "mtkclient-gemini-gpt";
  patches = old.patches ++ [
    ../patches/mtkclient/0004-gemini-factory-gpt-rewrite-command.patch
  ];
  postPatch = (old.postPatch or "") + ''
    cp ${./mtk-gpt-rewrite.py} mtkclient/Library/gemini_gpt_rewrite.py
  '';
  checkPhase = old.checkPhase + ''
    ${buildPkgs.python3.interpreter} ${./test-mtk-gpt-rewrite.py}
  '';
})
