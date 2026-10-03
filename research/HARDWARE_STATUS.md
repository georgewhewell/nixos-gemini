# Gemini completion status, 2026-10-04

The objective remains complete hardware enablement and consolidation. Camera
and vibrator are excluded by the owner; hardware video is still unresolved,
not an additional exclusion. Historical milestone names are not completion
proof. Current direct-Linux baseline is M69 (`master` 3f8e9d5, kernel c0dbf01b2bdaa).

## Fresh device observations

Read-only checks are retained at workspace
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
| Recovery / mtkclient | Repeatable read, boot-only write/readback and return to accepted Linux; failure recovery and host ownership |
| U-Boot / UEFI | See BOOT_HANDOFF.md; host builds alone do not qualify hardware |
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
M69 flashing transaction still uses SP Flash Tool. The owner now prioritises
making mtkclient work.

The patched mtkclient package and supervised read/reboot runner are described
in [MTKCLIENT.md](MTKCLIENT.md). The October 4 hardware trial read the primary
GPT and full M69 boot partition with matching hashes. The DA acknowledged
reboot, but Linux did not return within three minutes; USB remained at the
preloader and the owner reported a black screen. The read/reboot trial failed,
and boot-only writes remain unqualified. No eMMC writes were issued.
After the owner's force restart, the vendor Linux USB gadget returned
(`0fce:7169`), consistent with Gemian. The OS was not authenticated over SSH;
this is not a new healthy M69 observation.
