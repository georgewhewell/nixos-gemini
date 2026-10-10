# The normal desktop uses the same cross package set as the rest of NixOS.
{ config, lib, pkgs, geminiDesktop, geminiDesktopKeyboard, ... }: {
  disabledModules = ["i18n/input-method/default.nix"];
  imports = [./cross-input-method.nix];

  hardware.graphics = {
    enable = true;
    package = geminiDesktop.mesa;
  };
  services.desktopManager.gnome.enable = true;
  services.displayManager = {
    gdm = {
      enable = true;
      autoSuspend = false;
    };
    defaultSession = "gnome";
    autoLogin = {
      enable = true;
      user = "gemini";
    };
  };

  # Weston owns KMS during the existing graphics/keyboard qualification.
  # GDM starts only after those checks finish, and releases that test session
  # before opening its own seat. Each compositor has a separate runtime dir.
  systemd.services.display-manager = {
    after = ["gemini-desktop-qualify.service"];
    requires = ["gemini-desktop-qualify.service"];
    preStart = lib.mkBefore ''
      ${config.systemd.package}/bin/systemctl stop gemini-desktop.service gemini-seatd.service
    '';
  };

  systemd.services.gemini-gnome-qualify = {
    description = "Verify the local Gemini GNOME Wayland session";
    wantedBy = ["graphical.target"];
    requires = ["display-manager.service"];
    after = ["display-manager.service"];
    before = ["gemini-baseline-self-accept.service"];
    path = [config.systemd.package pkgs.coreutils pkgs.gawk pkgs.procps];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "100s";
    };
    script = ''
      uid=$(id -u gemini)
      attempt=0
      while [ "$attempt" -lt 90 ]; do
        for session in $(loginctl list-sessions --no-legend | awk -v uid="$uid" '$2 == uid {print $1}'); do
          if [ "$(loginctl show-session "$session" -p Type --value)" = wayland ] &&
             [ "$(loginctl show-session "$session" -p Class --value)" = user ] &&
             [ "$(loginctl show-session "$session" -p Active --value)" = yes ] &&
             [ "$(loginctl show-session "$session" -p Remote --value)" = no ] &&
             pgrep -u "$uid" -x gnome-shell >/dev/null; then
            printf 'desktop=gnome\nsession=%s\nuid=%s\ntype=wayland\n' "$session" "$uid" > /run/gemini-gnome-session
            exit 0
          fi
        done
        attempt=$((attempt + 1))
        sleep 1
      done
      echo 'No active local GNOME Wayland session' >&2
      exit 1
    '';
  };
  systemd.services.gemini-baseline-self-accept = {
    after = ["gemini-gnome-qualify.service"];
    requires = ["gemini-gnome-qualify.service"];
  };

  users.users.gemini.shell = pkgs.bashInteractive;
  services.xserver.xkb = {
    layout = "gemini";
    variant = "us";
    dir = "${geminiDesktopKeyboard.data}/share/X11/xkb";
  };
  environment.sessionVariables.XKB_CONFIG_ROOT = "${geminiDesktopKeyboard.data}/share/X11/xkb";

  # The board's inhibitor owns suspend and lid policy. GNOME must not add
  # independent idle sleep or a competing CPU power-policy daemon.
  services.power-profiles-daemon.enable = false;
  services.desktopManager.gnome.extraGSettingsOverrides = ''
    [org.gnome.desktop.input-sources]
    sources=[('xkb', 'gemini+us')]
    [org.gnome.desktop.session]
    idle-delay=uint32 0
    [org.gnome.settings-daemon.plugins.power]
    sleep-inactive-ac-type='nothing'
    sleep-inactive-battery-type='nothing'
  '';
  services.desktopManager.gnome.extraGSettingsOverridePackages = [pkgs.gnome-settings-daemon];

  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };

  # Install the desktop and everyday tools without the GNOME games and
  # developer suites. Additional applications use environment.systemPackages.
  services.gnome.core-apps.enable = false;
  environment.systemPackages = with pkgs; [
    nautilus
    gnome-console
    gnome-text-editor
    gnome-control-center
  ];
}
