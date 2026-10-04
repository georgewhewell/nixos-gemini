# Gemini completion status, 2026-10-04

The objective remains complete hardware enablement and consolidation. Camera
and vibrator are excluded by the owner; hardware video is still unresolved,
not an additional exclusion. Historical milestone names are not completion
proof. Current direct-Linux baseline is M69 (baseline configuration 3f8e9d5,
kernel c0dbf01b2bdaa).

## Fresh device observations

Initial read-only checks before the mtkclient trials are retained at workspace
`handoff/boot-consolidation-20261004/live-state.txt`:

- Boot ID fcce1f76-8617-480c-9dcb-5617e109cc7d; p22 matches M69; accepted healthy.
- Desktop, GPU, JPEG, Wi-Fi and audio services active; no failed units; CPUs 0-9 present.
- Charger reports Full; fuel gauge returns current. This is not a new codec,
  audio loopback, wireless traffic or battery-discharge qualification.
- Factory GPT verifies clean: p32 is 15.6 GiB and p34 does not exist.
- No swap is active. Stage 1 skips resume (no p34) and persistent storage
  (`layout missing=home`). The `/nix/store` is still the read-only squashfs.
- No cpuidle driver is published at `/sys/devices/system/cpu/cpuidle/current_driver`.

## Remaining work

| Area | Required evidence |
|---|---|
| Recovery / mtkclient | Read/reboot, boot-only candidate/rollback ownership, software-reset rescue and watchdog rescue now pass; general harness migration and GPT-write qualification remain |
| U-Boot / UEFI | Software reset, watchdog expiry and two full M69 FIT handoff/rescue cycles pass; EFI/UEFI work remains. See BOOT_HANDOFF.md |
| Persistence and fixed-size swap | Working layout compatible with the recovery tool, writable home/Nix across reboot, active swap; owner requested fixed swap rather than a swap file |
| Power | Qualify lid suspend/wake, deep idle, hibernation save/restore and 24-hour suspend-then-hibernate policy |
| Cellular / eSIM | Resolve weak reception and registration; compare stock scan at same location; qualify applicable SIM/eSIM use |
| Peripherals | microSD, wired headset and RTC alarm power-on need hands-on qualification; check retained evidence for other interfaces |
| Display IOMMU | Resolve intermittent translated scanout stalls; current M69 display bypasses translation |
| Media | JPEG was hardware-tested historically; video encode/decode remains unimplemented and requires further vendor investigation |
| Consolidation | Merge qualified work, reconcile stale docs and stranded branches, and preserve reproducible source/artifacts |

## Storage and recovery correction

The September 29 note claiming p34 was provisioned is historical. Claude later
restored the factory GPT after SP Flash Tool refused the modified layout with
error 8502. The fixed-size LVM alternative was proposed, but is not implemented
on the live system. Do not repartition from the earlier note.

The mtkclient logs (`handoff/mtkclient-test/printgpt.log`, `multi.log`) show two
successful GPT reads, including the then-existing swap partition. Subsequent
return to Linux was not demonstrated. Claims that the whole DA/read sequence
failed at USB speed switching are not supported by these logs. The successful
M69 flashing transaction at the start of this work used SP Flash Tool. The
owner then prioritised making mtkclient work; the qualified boot-only trials
below now use it without a vendor-tool fallback.

The patched mtkclient package and supervised read/reboot runner are described
in [MTKCLIENT.md](MTKCLIENT.md). The initial October 4 trial read the primary
GPT and full M69 boot partition with matching hashes. The DA acknowledged
reboot, but Linux did not return within three minutes; USB remained at the
preloader and the owner reported a black screen. The read/reboot trial failed,
and boot-only writes had not yet been tested. No eMMC writes were issued in
that initial trial.
After the owner's force restart, the vendor Linux USB gadget returned
(`0fce:7169`). SSH via `gemini@gemini` confirmed Gemian / Debian 9, kernel
`3.18.41+`, fresh boot ID `1508c791-df3f-4384-b4fd-5704338ef3ca`, and unchanged
p22/GPT hashes and partition geometry. Manual recovery succeeded; this is
not a new healthy M69 observation.

After correcting the MT6797 DA shutdown payload from 32 to 28 bytes, two
sessions returned automatically to healthy M69 with unchanged GPT/p22 hashes.
The full repeat runner passed in 194.4 seconds using its corrected six-minute
health deadline, returning boot ID
`6b1b01f6-cd4b-462f-8b5a-3de4b73c909a`.
Detailed evidence and the packet-size diagnosis are in MTKCLIENT.md.

The following boot-only write trial also passed: the DA acknowledged writing
the exact accepted M69 image, full readback matched, and it rebooted
automatically to healthy M69. That trial returned boot ID
`74d10f78-c5e0-48fd-915d-9eea69e6b87b`; GPT/p22 hashes and geometry remain
unchanged. Evidence: `handoff/mtkclient-boot-write-20261004-01`.

The durable candidate/rescue baseline subsequently passed, followed by
hardware-qualified U-Boot software-reset and 31-second watchdog-expiry tests.
Removing an unmapped post-MMU framebuffer probe resolved the early U-Boot
failure. Two plain U-Boot FIT handoffs then reached fully healthy M69
with its Linux-visible marker, full RAM bank and unchanged modem reservations.
The supervised trial restored direct M69 afterward. Details and exact
artifacts are in [BOOT_HANDOFF.md](BOOT_HANDOFF.md); these boot tests do not
qualify EFI Linux, writable persistence, fixed swap or hibernation.
