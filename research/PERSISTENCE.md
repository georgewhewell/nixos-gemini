# Persistent home and Nix storage — October 4, 2026

The existing p32 filesystem is now initialized for the storage support already
present in M69. This is separate from fixed-size swap: the factory GPT still
has 33 partitions, p32 retains its original extent, and p34 does not exist.

## Additive initialization

Read-only admission found a clean ext4 filesystem labelled `gemini-data`, UUID
`5d978ad4-a987-4b3f-bef6-f73ad7c2d986`, containing only `lost+found`. Its
2,781,184 blocks of 4,096 bytes occupy about 10.61 GiB inside the larger
15.61 GiB partition. No format, filesystem resize or GPT write was needed.

`tools/initialize-gemini-data.py` defaults to read-only admission and a private
backup of the temporary home. `--execute` requires the same healthy M69 boot,
protected partition hashes, controller, partition geometry and filesystem
identity, then copies the current home and publishes the four directories
Stage 1 requires. Both shared flash locks exclude another transaction.
`tools/gemini-data-layout.sh` refuses foreign data, symlinks and partial
initialization; it publishes `home` last so an interrupted copy cannot open
Stage 1's layout gate. Six real-file tests cover preservation and failures.

The completed initialization is recorded in `handoff/data-initialize-01`.
The private `home-before.tar` remains in that mode-0700 evidence directory.
The helper did not reboot; the existing supervised runner owns both subsequent
accepted-image writes, readbacks and reboots.

## Reboot qualification

`tools/qualify-uboot-recovery.py --profile baseline --verify-persistence`
checks the p32 mounts and Nix database, creates a private home test file,
builds a small offline Nix object, roots it, then checks the same bytes and
database records in the fresh rescue boot. It leaves the evidence objects
rooted for later verification. `--execute` is required for the trial; without
it the runner only performs admission. Five verifier tests reject wrong
devices, bind roots, overlay paths, unexpected overmounts and changed content.

The first trial, `handoff/data-persistence-01`, returned healthy M69 on both
boots with p32 mounted and its database seeded. Its initial host verifier
rejected NixOS's normal read-only store bind over the writable overlay. That
result remains unqualified. The corrected verifier checks the mount's parent,
device, filesystem root and backing paths before accepting this specific bind.

The corrected trial, `handoff/data-persistence-02`, passed. First boot
`edb387ef-8887-4132-984d-21eea2ea16a7` created the proof; rescue boot
`a2fd95cf-c7d0-4fc5-a058-b8b1bb3a0339` retained it. Both the home file and
Nix output have SHA-256
`f6060daac54edc95a47230072c20e6752f6b09306f3ddf8959a3fc917c9effdd`.
The Nix database retained the same NAR hash and derivation, and the GC root
still resolves to the built output. Both boots passed full recovery health.
Both p22 writes/readbacks and automatic resets passed; GPT/p30/p31 hashes
remain unchanged. The terminal result has `persistence_qualified=true`, and a
fresh final audit confirmed the same healthy boot, free locks and no writer.

## Ordinary Nix builds: defects found and candidate prepared

The storage checks exposed two pre-existing M69 configuration gaps:

- The forced minimal `systemd.packages` list contains only D-Bus. NixOS's
  generated daemon overrides therefore lack the upstream `ExecStart` and socket
  `ListenStream`; both units report `LoadState=bad-setting`.
- The kernel has `CONFIG_NET_NS` disabled. An ordinary local sandboxed build
  fails at `clone()` with `EINVAL`. User, PID, IPC and UTS namespaces are enabled;
  the Nix source adds `CLONE_NEWNET` for ordinary sandboxed derivations.

The ordinary-build failure is retained in
`handoff/data-persistence-local-build-01`. A fixed-output build passed in
`data-persistence-local-build-02`, and the reboot verifier uses that same
approach. Its declared output hash checks the bytes, sandboxing stays enabled,
and the builder uses no network. Nix normally lets fixed-output builders inherit
networking, so this proves writable Nix storage and database persistence without
claiming ordinary builds or daemon service readiness.

The opt-in `mainlineNixosNixBundle` restores Nix's upstream systemd units and
adds `CONFIG_NET_NS=y` to the qualified EFI kernel. Every other final kernel
configuration value is identical to that EFI kernel. Its DT builder preserves
hardware properties and LK reservations while rebinding CPU provenance to the
new kernel. Sandbox policy stays enabled. The accepted direct M69 and previous
EFI bundles still evaluate to their original store paths.

The candidate built successfully and is rooted at
`handoff/persistent-nix-candidate`. Host checks in
`handoff/persistent-nix-candidate-host-checks` verify all manifest hashes, the
kernel configuration difference, complete daemon/socket units, enabled socket,
database seeding order and sandbox policy. It has **not been boot-tested**.

| Candidate component | Identity |
|---|---|
| Bundle | `/nix/store/14x5g6smb178qvdb0skbxkdvfwhc94wb-gemini-mainline-nixos-bundle` |
| Kernel | `/nix/store/j0h3y2s1yal2sc7v1026c5hp0vn45xry-gemini-mainline-efi-nix-kernel-7.1.3` |
| System | `/nix/store/hqkwklfldn7sfw1bj7xxbdhq5c2namif-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade` |
| Padded p22 SHA-256 | `0cd222881c2dcc56d8da25f54903f70cf4d93475bc591175251403ba971be50e` |
| Store SHA-256 | `a55afc6b3ad2816a04b92659755982314195093707714ebc169e0bc8ce597d9d` |
| Store size | 426,987,520 bytes |

Next qualification must cover a real ordinary build through the daemon, an
unprivileged client's access, both A72 starts, complete service health, and
automatic restoration of M69 with the persistent data retained. This candidate
does not implement fixed swap, hibernation, normal generation updates or
persistent EFI settings.
