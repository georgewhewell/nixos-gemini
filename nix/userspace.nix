{
  buildPkgs,
  crossPkgs,
  ubootSource,
}: let
  # Firmware changes outside the keymap do not rebuild the desktop or system.
  keyboardMatrix = builtins.path {
    path = "${ubootSource}/arch/arm/dts/mt6797-gemini-pda-keyboard.dts";
    name = "gemini-keyboard.dts";
  };
  inputHeader = builtins.path {
    path = "${ubootSource}/include/linux/input.h";
    name = "input.h";
  };
  gpuUserspace = import ./gpu-oneboot-userspace.nix {
    inherit buildPkgs;
    armPkgs = crossPkgs;
  };

  desktopUserspace = import ./desktop-userspace.nix {
    inherit buildPkgs;
    armPkgs = crossPkgs;
    mesa = gpuUserspace.mesa;
  };

  desktopHostUserspace = import ./desktop-userspace.nix {
    inherit buildPkgs;
    armPkgs = buildPkgs;
    mesa = null;
  };

  desktopKeyboard = import ./desktop-keyboard.nix {
    inherit buildPkgs;
    armPkgs = crossPkgs;
    hostWeston = desktopHostUserspace.weston;
  };
  desktopHostKeyboard = import ./desktop-keyboard.nix {
    inherit buildPkgs;
    armPkgs = buildPkgs;
    hostWeston = desktopHostUserspace.weston;
  };
  desktopKeyboardProtocolCheck =
    buildPkgs.runCommand "gemini-desktop-keyboard-protocol-check" {
      nativeBuildInputs = [buildPkgs.python3];
    } ''
      python3 ${./keyboard}/generate-reference.py \
        --library ${buildPkgs.libxkbcommon}/lib/libxkbcommon.so \
        --include ${buildPkgs.xkeyboard_config}/share/X11/xkb \
        --matrix ${keyboardMatrix} \
        --input-header ${inputHeader} \
        --output reference.h
      cmp reference.h ${./keyboard/reference.h}
      python3 ${./keyboard/test-weston.py} \
        ${desktopHostUserspace.weston}/bin/weston \
        ${desktopHostKeyboard.check}/bin/gemini-desktop-keyboard-check \
        ${desktopHostKeyboard.fixture}/lib/keyboard-fixture.so \
        ${desktopKeyboard.data}/share/X11/xkb > "$out"
    '';

  desktopProtocolCheck =
    buildPkgs.runCommand "gemini-desktop-protocol-check" {
      nativeBuildInputs = [buildPkgs.python3 buildPkgs.binutils];
    } ''
      python3 ${./test-desktop-presentation.py} \
        ${desktopHostUserspace.weston}/bin/weston \
        ${desktopHostUserspace.presentationCheck}/bin/gemini-desktop-presentation-check > "$out"
      nm --defined-only ${gpuUserspace.mesa}/lib/libgallium-${gpuUserspace.mesa.version}.so > symbols
      grep -Eq ' [tT] kmsro_drm_screen_create$' symbols
      grep -Eq ' [tT] panfrost_drm_screen_create_renderonly$' symbols
      if grep -Eq ' [tT] (llvmpipe|softpipe)_create_screen$' symbols; then
        echo 'unexpected software renderer in desktop Mesa' >&2
        exit 1
      fi
      echo 'Panfrost renderonly and KMS bridge: present; software renderers: absent' >> "$out"
    '';
in {
  inherit
    gpuUserspace
    desktopUserspace
    desktopHostUserspace
    desktopKeyboard
    desktopHostKeyboard
    desktopKeyboardProtocolCheck
    desktopProtocolCheck
    ;
}
