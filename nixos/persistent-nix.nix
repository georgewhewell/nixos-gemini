# The minimal M69 package list drops Nix's upstream service/socket units.
# Restore them only for the opt-in persistent-Nix candidate. The existing
# storage module seeds the database before this daemon can start.
{ config, lib, pkgs, ... }: {
  systemd.packages = lib.mkOverride 40 [ pkgs.dbus config.nix.package ];
}
