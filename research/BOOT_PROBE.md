# Gemini boot probe

The Gemini's Little Kernel (LK) bootloader selects an Android-format boot
partition; Gemian does not kexec from Android or from another Linux kernel.
On the inspected device:

| Partition | Label | Observed contents | Selection |
|-----------|-------|-------------------|-----------|
| p22 | `boot` | Known-good Gemian recovery image | Normal power-on |
| p30 | `boot2` | Failed Nix-built ixoo candidate `d25799ce...` | Designated experiment slot |
| p31 | `boot3` | Known-good Gemian recovery image | Alternate/reserve |

The table reflects a live read on 2026-08-29. p22 and p31 both hash to
`1fa78de9f8744a6818bcef2f6773737939f84364de982413910d4958d6d21513`;
p30 hashes to
`d25799ce1a7f6810f205aa69e9e14bca5dad5055a24a5a6d1524e5866b81d211`.
Gemian currently boots with p29 as `/`. Do not describe p22 as NixOS until a
future installation is read back and then boots successfully.

The known-good Gemian kernel plus appended DTB was extracted from `boot2` and
saved as `blobs/Gemian-Image.gz-dtb`. Its SHA-256 is:

```
b53d191dc41d3f7364b0fa62b4bc920b1d013a1942b2e6b06727263fc56fcf4d
```

The probe boot image keeps that kernel byte-for-byte and replaces only the
ramdisk. Its `/init` waits for p29, mounts it read-write, writes
`/nixos-probe.log`, syncs the filesystem, and opens a console shell. It does
not start Wi-Fi or SSH.

## Build and inspect

```sh
nix build .#probeBootImg --out-link artifacts/nixos-probe-boot.img

unpack_bootimg \
  --boot_img artifacts/nixos-probe-boot.img \
  --out artifacts/probe-unpacked \
  --format info
```

The image must be smaller than the 16 MiB `boot2` partition. The Nix build
checks this automatically.

## Mainline ixoo probe

The mainline probe is a separate p30-only workflow. It never replaces
`bootImg`, p22, or p31:

```sh
nix build .#mainlineBundle --out-link artifacts/mainline-bundle
cat artifacts/mainline-bundle/MANIFEST
```

The next diagnostic candidate is
`artifacts/mainline-bundle/probe-padded-boot2.img`, exactly 16 MiB with
SHA-256
`122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159`.
It contains the Nix-built Linux `7.1.3-gemini-da921x-lkro`, ixoo's exact
hardware-passed serviceability DTB, and a new storage-free BusyBox initramfs.
The Nix kernel binary is not byte-identical to ixoo's Buildbox kernel, so the
candidate itself is not yet hardware-proven.

This candidate is deliberately diagnostic. A final config overlay restores
`console=tty0`, disables ixoo's raw ARM64 entry ledger, enables ordinary
ramoops plus the attributable post-registration marker, and leaves the serial
console in place. The initramfs mounts pstore read-only and reports watchdog,
USB-device-controller, cmdline, dmesg, and retained-record state through the
USB shell and a 60-second tty1 fallback. It never opens `/dev/watchdog0` and
never accesses storage.

`artifacts/mainline-config-control-bundle` is the config-control build. Its
kernel is byte-identical to the kernel in the failed p30 image, proving that
removing all Nix hardening-wrapper policy did not change the payload. Its
padded image hash is
`f2ca10a57279f6667e692693fb19c6df0db0464249599a78d41a966ab347b93b`.
It is retained for binary-search evidence, not preferred over the diagnostic
candidate.

Before a write, boot known-good Gemian from p22 or p31 and resolve the target
from the live GPT. Do not substitute a remembered partition number:

```sh
target=$(readlink -f /dev/disk/by-partlabel/boot2)
root_source=$(findmnt -n -o SOURCE /)
printf 'boot2=%s root=%s\n' "$target" "$root_source"
case "$target" in
  /dev/mmcblk0p*) ;;
  *) echo 'refusing unexpected boot2 target' >&2; exit 1 ;;
esac
test "$target" != "$root_source"
test -z "$(findmnt -rn -S "$target" -o TARGET)"
test "$(blockdev --getsize64 "$target")" -eq 16777216
```

Run those commands on the Gemini as root, or through `sudo`. Save and hash a
full p30 backup on the host before replacing it:

```sh
ssh gemini@gemini \
  'sudo dd if=/dev/disk/by-partlabel/boot2 bs=4M status=progress' \
  > artifacts/boot2-before-mainline.img
test "$(stat -c %s artifacts/boot2-before-mainline.img)" -eq 16777216
sha256sum artifacts/boot2-before-mainline.img
```

Copy the padded candidate, verify the remote file, then repeat the live target,
unmounted-state, and size checks. The following `dd` is the destructive step
and is permitted for resolved `boot2` only:

```sh
scp artifacts/mainline-bundle/probe-padded-boot2.img \
  gemini@gemini:mainline-padded-boot2.img
ssh gemini@gemini '
  set -eu
  expected=122c0f461e94d3439016e80339c7ee96f865e3591a3e2fbd163a7769dc0ac159
  target=$(readlink -f /dev/disk/by-partlabel/boot2)
  test "$(sha256sum "$HOME/mainline-padded-boot2.img" | cut -d" " -f1)" = "$expected"
  case "$target" in /dev/mmcblk0p*) ;; *) exit 1 ;; esac
  test -z "$(findmnt -rn -S "$target" -o TARGET)"
  test "$(sudo blockdev --getsize64 "$target")" -eq 16777216
  sudo dd if="$HOME/mainline-padded-boot2.img" of="$target" \
    bs=4M conv=fsync,notrunc status=progress
  sudo blockdev --flushbufs "$target"
  test "$(sudo sha256sum "$target" | cut -d" " -f1)" = "$expected"
  sudo poweroff
'
```

Arm host observation before physically selecting side-button `boot2`. On the
headless USB host, watch the kernel log and USB interfaces. The gadget requests
host MAC `42:00:15:19:82:00`; configure that interface as
`10.15.19.1/24`, then connect:

```sh
sudo dmesg -w
ip -brief link
sudo ip address replace 10.15.19.1/24 dev USB_INTERFACE
sudo ip link set USB_INTERFACE up
nc 10.15.19.82 2323
```

A successful shell starts with `GEMINI_NIX_IXOO_PROBE`. Collect at least:

```sh
uname -a
cat /proc/cmdline
cat /sys/devices/system/cpu/online
cat /sys/devices/system/cpu/offline
dmesg
```

Expected CPU state is online `0-7`, offline `8-9`. The kernel command line has
`console=tty0`, `earlycon`, `ignore_loglevel`, `initcall_debug`, a 1 MiB log
buffer, and `panic=0`; the DT retains framebuffer/tty1, keyboard, watchdog,
ordinary ramoops, and USB-gadget diagnostics. The kernel output retains
`vmlinux`, `System.map`, and its exact `.config`, allowing addresses from a
captured panic or ramoops record to be resolved after recovery.

If USB never enumerates, check the framebuffer/keyboard shell and power-cycle
back to Gemian p22 or p31. Do not repeatedly boot a faulting candidate. After
recovery, mount and capture `/sys/fs/pstore` before another experimental boot,
then verify p30's hash.
Restore only from `artifacts/boot2-before-mainline.img` after checking its size
and recorded hash. Never use p22 or p31 as a restore source.

## Test procedure

Do not overwrite stable `boot`/p22 during a kernel probe. Use `boot2`/p30 as
the experiment slot and leave `boot3`/p31 untouched as Gemian recovery.

First save another explicit backup of `boot2`:

```sh
mkdir -p artifacts
ssh gemini@gemini \
  'sudo dd if=/dev/disk/by-partlabel/boot2 bs=4M status=progress' \
  > artifacts/boot2-before-probe.img
sha256sum artifacts/boot2-before-probe.img
```

Copy the probe to Gemian and verify its size before writing anything:

```sh
scp artifacts/nixos-probe-boot.img gemini@gemini:/home/gemini/
ssh gemini@gemini \
  'stat -c "%n: %s bytes" /home/gemini/nixos-probe-boot.img; \
   sudo blockdev --getsize64 /dev/disk/by-partlabel/boot2'
```

The following command is the destructive step. Run it only after checking that
the first size is no greater than the second:

```sh
ssh gemini@gemini \
  'sudo dd if=/home/gemini/nixos-probe-boot.img \
     of=/dev/disk/by-partlabel/boot2 bs=4M conv=fsync status=progress; sync'
```

Power off, then use the same side-button boot normally used for Gemian. After
the probe has run, power-cycle back into Android or the untouched alternate
Gemian slot. From Gemian, inspect:

```sh
sudo cat /nixos-probe.log
```

If `boot2` must be restored, use its explicit, hash-recorded backup. Verify the
partition labels before any restore operation rather than assuming the layout;
leave `boot3` untouched.

The full image now uses an XZ SquashFS mounted directly at `/nix/store` and a
tmpfs root; it does not require OverlayFS. Its independent recovery paths are
the stable default p22 image, untouched Gemian p31, and the left-port RNDIS
gadget.

Do not extend the `dd` procedure above to `boot`/p22. LK applies power-on eMMC
write protection to the 8 MiB groups covering p10 through p26. The vendor
kernel detects `R1_WP_VIOLATION` but clears the request error before returning
it, so `dd` reports success even though p22 remains unchanged. Default-slot
installation must happen in the pre-boot MediaTek download environment, using
the device's exact scatter file, **Download Only**, and only the `boot` entry.
Never use **Format All + Download**.
