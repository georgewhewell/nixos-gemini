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

  # Normal startup loads the GPU and audio routes, then opens the GNOME seat.
  # Weston and the hardware qualification services are explicitly requested.
  systemd.services.display-manager = {
    after = ["gemini-gpu.service" "gemini-audio.service"];
    requires = ["gemini-gpu.service" "gemini-audio.service"];
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
      shell_running() {
        # Nix's wrapper executes .gnome-shell-wrapped, whose kernel comm
        # field is truncated. Verify the installed executable and its UID.
        for pid in $(pgrep -u "$uid" -f /bin/gnome-shell || true); do
          if [ "$(readlink "/proc/$pid/exe" 2>/dev/null)" = "${pkgs.gnome-shell}/bin/.gnome-shell-wrapped" ]; then
            return 0
          fi
        done
        return 1
      }
      attempt=0
      while [ "$attempt" -lt 90 ]; do
        for session in $(loginctl list-sessions --no-legend | awk -v uid="$uid" '$2 == uid {print $1}'); do
          if [ "$(loginctl show-session "$session" -p Type --value)" = wayland ] &&
             [ "$(loginctl show-session "$session" -p Class --value)" = user ] &&
             [ "$(loginctl show-session "$session" -p Active --value)" = yes ] &&
             [ "$(loginctl show-session "$session" -p Remote --value)" = no ] &&
             shell_running; then
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
    [org.gnome.desktop.interface]
    scaling-factor=uint32 2
    [org.gnome.desktop.input-sources]
    sources=[('xkb', 'gemini+us')]
    [org.gnome.desktop.session]
    idle-delay=uint32 0
    [org.gnome.settings-daemon.plugins.power]
    sleep-inactive-ac-type='nothing'
    sleep-inactive-battery-type='nothing'
    [org.gnome.Calls]
    autoload-plugins=['mm']
  '';
  services.desktopManager.gnome.extraGSettingsOverridePackages = [pkgs.gnome-settings-daemon pkgs.calls];
  services.desktopManager.gnome.favoriteAppsOverride = ''
    [org.gnome.shell]
    favorite-apps=['org.gnome.Nautilus.desktop', 'org.gnome.Console.desktop', 'org.gnome.TextEditor.desktop', 'org.gnome.Settings.desktop', 'org.gnome.Calls.desktop', 'org.kde.spacebar.desktop']
  '';

  # The 1080x2160 panel needs HiDPI sizing. A compact fixed dock keeps
  # launchers available without opening the overview on the small screen.
  programs.dconf.profiles.user.databases = [{
    settings = {
      "org/gnome/shell" = {
        enabled-extensions = [pkgs.gnomeExtensions.dash-to-dock.extensionUuid];
        disable-user-extensions = false;
      };
      "org/gnome/shell/extensions/dash-to-dock" = {
        dock-position = "BOTTOM";
        dock-fixed = true;
        autohide = false;
        intellihide = false;
        dash-max-icon-size = lib.gvariant.mkInt32 32;
        show-trash = false;
        show-mounts = false;
      };
    };
  }];

  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };

  # Both applications use the existing ModemManager service. Calls also
  # installs callaudiod for the standard session audio-routing API.
  programs.calls.enable = true;
  systemd.packages = [pkgs.calls];
  systemd.user.services.calls-daemon.wantedBy = ["gnome-session.target"];

  # Install the desktop and everyday tools without the GNOME games and
  # developer suites. Additional applications use environment.systemPackages.
  services.gnome.core-apps.enable = false;
  environment.systemPackages = with pkgs; [
    nautilus
    gnome-console
    gnome-text-editor
    gnome-control-center
    gnomeExtensions.dash-to-dock
    kdePackages.spacebar
  ];
}
