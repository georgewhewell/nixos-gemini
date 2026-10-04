{ buildPkgs }:
(import ./mtkclient-backup.nix { inherit buildPkgs; }).overrideAttrs (old: {
  pname = "mtkclient-gemini-swap";
  patches = old.patches ++ [ ../patches/mtkclient/0006-gemini-fixed-swap-command.patch ];
  postPatch = old.postPatch + ''
    cp ${./mtk-fixed-swap.py} mtkclient/Library/gemini_fixed_swap.py
  '';
  checkPhase = old.checkPhase + ''
    ${buildPkgs.python3.interpreter} ${./test-mtk-fixed-swap.py}
  '';
})
