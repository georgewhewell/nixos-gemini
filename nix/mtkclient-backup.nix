{ buildPkgs }:
(import ./mtkclient-gpt.nix { inherit buildPkgs; }).overrideAttrs (old: {
  pname = "mtkclient-gemini-backup";
  patches = old.patches ++ [
    ../patches/mtkclient/0005-gemini-offline-data-backup-command.patch
  ];
  postPatch = old.postPatch + ''
    cp ${./mtk-data-backup.py} mtkclient/Library/gemini_data_backup.py
  '';
  checkPhase = old.checkPhase + ''
    ${buildPkgs.python3.interpreter} ${./test-mtk-data-backup.py}
  '';
})
