# USB11 host-network timing gate

Status: evidence review, 2026-08-30.  This is a documentation-only finding;
it does not authorize a flash, reboot, or hardware write.

## What the image actually waits for

The serviceability init starts both network helpers as background jobs after
the watchdog, UDC, pstore, and SSH setup (`/home/grw/src/nixos-gemini/nix/mainline.nix:739-753`).
The host helper then:

```text
while [ "$attempt" -lt 60 ] && [ -z "$host_if" ]; do
  for net in /sys/class/net/*; do
    ...
    driver=$(readlink -f "$net/device/driver" 2>/dev/null || true)
    case "$driver" in
      */r8152)
        host_if=$name
        ...
```

(`/home/grw/src/nixos-gemini/nix/mainline.nix:878-902`).  If no matching
interface is found, the only timeout path is:

```text
echo "usb-host-net=missing after=60s driver=r8152" >> /run/probe-status
```

(`/home/grw/src/nixos-gemini/nix/mainline.nix:907-910`).  Once an interface is
found, the script checks `0bda:8156`, raises the link, records `waiting`, and
executes foreground `udhcpc` (`/home/grw/src/nixos-gemini/nix/mainline.nix:912-924`).  Carrier is not
tested by the 60-iteration loop.  DHCP readiness is reported separately by
the callback (`/home/grw/src/nixos-gemini/nix/mainline.nix:831-849`).

The loop is therefore an approximately 60-second *interface discovery*
window, measured from the helper's launch, not from kernel boot.  The source
does not emit a helper-start timestamp, and `/bin/usb-host-net` is launched
without an ordering barrier (`/home/grw/src/nixos-gemini/nix/mainline.nix:750-753`).

## Exact candidate-cycle evidence

The candidate's kernel log records the driver and device path succeeding:

```text
[   58.161859] r8152 1-1:1.0 enu1: renamed from eth0
[   60.314571] r8152 1-1:1.0 enu1: carrier on
```

(`/home/grw/src/nixos-gemini/artifacts/p22-recovery-20260830-065400-4074658/dmesg-pre:1524-1525`).
The same boot's pstore records the helper's timeout much later:

```text
[   49.229442] GEMINI_NIX_IXOO_STORAGE: ... userspace_block_reads=none userspace_block_writes=none mounts=none
[  109.530455] GEMINI_NIX_IXOO_PROBE: usb-host-net=missing after=60s driver=r8152
```

(`/home/grw/src/nixos-gemini/artifacts/p22-recovery-20260830-065400-4074658/pstore-pre:919,921`).
The 49.229442 line is the last visible initramfs setup marker before the
timeout; it is not a helper-start marker.  It nevertheless bounds the
observed launch context.  The approximately 60-second interval from that
setup marker to the timeout is consistent with the helper's 60 one-second
iterations, but does not itself prove the helper's exact start time.

The cycle's durable ledger states:

```text
Candidate validation failed closed because the required host-net marker
reported `usb-host-net=missing after=60s driver=r8152`;
```

(`/home/grw/src/nixos-gemini/research/HARDWARE_TEST_LEDGER.md:963-965`).  It
also records that this was not device loss: “gadget `0525:a4a2` returned at
07:46:59, link became `LOWER_UP` at 07:47:57, and independent SSH readback
then proved” the partition hashes (`/home/grw/src/nixos-gemini/research/HARDWARE_TEST_LEDGER.md:970-979`).
The observed right-NIC SSH address was `192.168.23.70`; the repository's
accepted host policy names that address and requires the ready marker
(`/home/grw/src/nixos-gemini/research/HARDWARE_TEST_LEDGER.md:550-558`).

As a read-only control, the currently reachable device exposes exactly the
sysfs shape the helper expects:

```text
net=enu1 driver=/sys/bus/usb/drivers/r8152 device=/sys/devices/platform/11200000.usb/musb-hdrc.1.auto/usb1/1-1/1-1:1.0
usb=0bda:8156 path=/sys/devices/platform/11200000.usb/musb-hdrc.1.auto/usb1/1-1
```

This was obtained over SSH from `root@192.168.23.70` using only sysfs reads;
it proves the predicate works in the current rescue environment, not that it
was visible to the candidate helper at every earlier instant.

## Judgement

**Proven.**  USB11 reaches a real RTL8156: the MT6797 overlay enables the
USB11 TPHY, U2 PHY, and MUSB node (`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda-usb11-host.dtso:118-128`),
and the platform driver configures the MT6797 controller as multipoint with
six endpoints (`/home/grw/src/linux-gemini-platform/drivers/usb/musb/mediatek.c:404-428`).
The candidate kernel registered/renamed `enu1`, later asserted carrier, and
the right-NIC SSH path eventually worked.  The helper emitted its explicit
missing marker at boot+109.530455.

**Not proven.**  The 60-second deadline did not, on this record, expire
because carrier appeared at +60.314571: carrier is not part of the loop's
condition, and the interface event preceded the helper timeout by roughly
51 seconds.  A simple deadline increase may still be useful for future
boots, but this cycle does not establish it as the fix.  The missing
`waiting` marker means we cannot tell whether the candidate helper failed to
observe the transient sysfs driver link, was not actually running the source
shown above, or encountered an unrecorded process/sysfs failure.  The log
does not prove which of those occurred.  DHCP success for the candidate is
also not proven by the later SSH observation alone.

## Smallest decisive next gate

Use one otherwise identical build/test window, with no hardware writes beyond
the already-approved test procedure, and capture three monotonic timestamps
from the same boot origin:

1. helper launch (before the loop),
2. first matching `r8152` interface plus resolved VID/PID, and
3. `waiting`, DHCP bound/renew, and `ready` callback events.

The existing kernel dmesg already supplies the USB rename and carrier events;
the missing observation is the helper's own interface-discovery result.  If
the helper sees `enu1` before its deadline but DHCP is late, adjust the
readiness/acceptance window, not the discovery predicate.  If it does not see
`enu1` despite the kernel event, inspect the exact initramfs sysfs mount and
the resolved `device/driver` path before changing the deadline.  Until that
instrumented result exists, the safe conclusion is: **USB11 hardware and
right-NIC reachability are demonstrated, candidate acceptance timing is not,
and the root cause of the false “missing” result remains unknown.**
