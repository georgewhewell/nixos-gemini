# Keep the pinned upstream input-method module, correcting only the paths
# passed to its cross emulator. QEMU does not search PATH for its program.
args@{ lib, pkgs, modulesPath, ... }:
let
  cross = !pkgs.stdenv.buildPlatform.canExecute pkgs.stdenv.hostPlatform;
  queryTools = {
    "gtk2-immodule.cache" = { package = pkgs.gtk2; program = "gtk-query-immodules-2.0"; };
    "gtk3-immodule.cache" = { package = pkgs.gtk3; program = "gtk-query-immodules-3.0"; };
  };
  cacheRunCommand = name: attrs: command:
    let
      tool = queryTools.${name};
      executable = "${lib.getDev tool.package}/bin/${tool.program}";
      needle = " ${tool.program} >";
    in
    pkgs.runCommand name attrs (
      if cross && builtins.hasAttr name queryTools then
        assert lib.hasInfix needle command;
        # The generated comment names argv[0]. Drop it so the runtime cache
        # retains upstream's prohibition on references to GTK's dev output.
        "set -o pipefail\n" + builtins.replaceStrings [needle]
          [" ${executable} | sed '/^# Created by /d' >"] command
      else command
    );
  upstream = import "${modulesPath}/i18n/input-method/default.nix" (args // {
    pkgs = pkgs // { runCommand = cacheRunCommand; };
  });
in {
  options = upstream.options;
  config = upstream.config;
  meta = upstream.meta;
}
