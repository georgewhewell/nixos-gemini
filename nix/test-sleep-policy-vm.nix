# Host test of nixos/power-policy.nix against the same systemd (253) logind
# as the device.  A uinput SW_LID switch stands in for the Hall sensor,
# dummy_hcd + g_zero for the MTU3 gadget, and systemd-suspend.service only
# records that logind asked for a sleep.
{pkgs}: let
  lidHelper = pkgs.writers.writePython3 "fake-lid" {
    libraries = [pkgs.python3Packages.evdev];
  } ''
    import os
    from evdev import UInput, ecodes

    fifo = "/run/fake-lid.ctl"
    if not os.path.exists(fifo):
        os.mkfifo(fifo)
    ui = UInput({ecodes.EV_SW: [ecodes.SW_LID]}, name="Fake Hall lid")
    with open("/run/fake-lid.ready", "w") as ready:
        ready.write(ui.device.path + "\n")
    while True:
        with open(fifo) as ctl:
            for line in ctl:
                ui.write(ecodes.EV_SW, ecodes.SW_LID, int(line.strip()))
                ui.syn()
  '';
in
  pkgs.nixosTest {
    name = "gemini-sleep-policy";
    nodes.machine = {lib, ...}: {
      imports = [../nixos/power-policy.nix];
      gemini.powerPolicy.lidSuspendDelaySec = 8;
      gemini.powerPolicy.usbDeviceController = "dummy_udc.0";
      services.logind.extraConfig = lib.mkAfter ''
        HoldoffTimeoutSec=3s
      '';
      boot.kernelModules = ["dummy_hcd"];
      systemd.services.fake-lid = {
        wantedBy = ["multi-user.target"];
        before = ["gemini-sleep-inhibit.service"];
        requiredBy = ["gemini-sleep-inhibit.service"];
        serviceConfig.ExecStart = lidHelper;
        serviceConfig.ExecStartPost = "${pkgs.bash}/bin/bash -c 'until test -e /run/fake-lid.ready; do sleep 0.1; done; udevadm settle'";
      };
      systemd.services.systemd-suspend.serviceConfig.ExecStart = [
        ""
        "${pkgs.bash}/bin/bash -c 'date +%%s.%%N >> /run/suspend-requests'"
      ];
    };

    testScript = ''
      import time

      def inhibitors():
          return machine.succeed("systemd-inhibit --list --no-pager --no-legend")

      def suspends():
          return int(machine.succeed("if test -e /run/suspend-requests; then wc -l < /run/suspend-requests; else echo 0; fi").strip())

      def lid(state):
          machine.succeed(f"echo {state} > /run/fake-lid.ctl")

      machine.wait_for_unit("gemini-sleep-inhibit.service")
      machine.wait_until_succeeds("systemd-inhibit --list --no-legend | grep -q 'lid open'")

      with subtest("recovery lease blocks sleep until accepted"):
          assert "unattended-recovery lease not yet accepted" in inhibitors()
          machine.succeed("echo unattended_recovery=healthy > /run/ura.tmp && mv /run/ura.tmp /run/unattended-recovery.accepted")
          machine.wait_until_fails("systemd-inhibit --list --no-legend | grep -q 'lease not yet accepted'")

      # Let logind's boot holdoff expire.
      machine.wait_until_succeeds("awk '$1 > 5 { ok=1 } END { exit !ok }' /proc/uptime")

      with subtest("closed lid suspends only after the grace period"):
          lid(1)
          t0 = time.monotonic()
          machine.sleep(4)
          assert suspends() == 0, "suspended during the lid grace period"
          assert "handle-lid-switch" in inhibitors()
          machine.wait_until_succeeds("test -s /run/suspend-requests", timeout=30)
          elapsed = time.monotonic() - t0
          assert elapsed >= 7, f"suspend after {elapsed:.1f}s, before the 8s grace"
          assert "handle-lid-switch" not in inhibitors()

      with subtest("opening the lid restores the inhibitor and stops suspending"):
          lid(0)
          machine.wait_until_succeeds("systemd-inhibit --list --no-legend | grep -q handle-lid-switch")
          n = suspends()
          machine.sleep(10)
          assert suspends() == n, "suspended with the lid open"

      with subtest("an attached USB host blocks the lid action"):
          print(machine.succeed("cat /sys/class/udc/dummy_udc.0/state"))
          machine.succeed("modprobe g_zero")
          machine.wait_until_succeeds("systemd-inhibit --list --no-legend | grep -q 'USB host attached'")
          print(machine.succeed("cat /sys/class/udc/dummy_udc.0/state"))
          n = suspends()
          lid(1)
          machine.sleep(15)
          assert suspends() == n, "suspended while a USB host was attached"
          # dummy_udc never reports "not attached" again after a disconnect
          # (MTU3 does, in mtu3_gadget_disconnect()), so detach by recreating
          # the UDC and restarting the daemon, which then sees no host.
          machine.succeed("rmmod g_zero dummy_hcd && modprobe dummy_hcd")
          machine.succeed("test \"$(cat /sys/class/udc/dummy_udc.0/state)\" = 'not attached'")
          machine.succeed("systemctl restart gemini-sleep-inhibit")
          machine.wait_until_fails("systemd-inhibit --list --no-legend | grep -q 'USB host attached'")
          machine.wait_until_succeeds(f"test $(wc -l < /run/suspend-requests) -gt {n}", timeout=30)
          lid(0)

      with subtest("daemon started with the lid closed grants the full grace"):
          lid(1)
          machine.succeed("systemctl restart gemini-sleep-inhibit")
          machine.wait_until_succeeds("systemd-inhibit --list --no-legend | grep -q handle-lid-switch")
          n = suspends()
          machine.sleep(4)
          assert suspends() == n
          machine.wait_until_succeeds(f"test $(wc -l < /run/suspend-requests) -gt {n}", timeout=30)
          lid(0)

      with subtest("logind configuration"):
          conf = machine.succeed("cat /etc/systemd/logind.conf")
          for line in ["HandleLidSwitch=suspend", "HandleLidSwitchExternalPower=suspend",
                       "HandleLidSwitchDocked=ignore", "LidSwitchIgnoreInhibited=no"]:
              assert line in conf, line
          sleep = machine.succeed("cat /etc/systemd/sleep.conf")
          for line in ["SuspendState=freeze", "HibernateMode=shutdown",
                       "HibernateDelaySec=24h", "AllowSuspendThenHibernate=false"]:
              assert line in sleep, line
      print(machine.succeed("journalctl -u gemini-sleep-inhibit --no-pager"))
    '';
  }
