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

## Ordinary Nix builds: defects and qualified correction

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
database seeding order and sandbox policy. Its subsequent hardware trial
passed as described below; it remains an opt-in candidate, with direct M69
installed after recovery.

| Candidate component | Identity |
|---|---|
| Bundle | `/nix/store/14x5g6smb178qvdb0skbxkdvfwhc94wb-gemini-mainline-nixos-bundle` |
| Kernel | `/nix/store/j0h3y2s1yal2sc7v1026c5hp0vn45xry-gemini-mainline-efi-nix-kernel-7.1.3` |
| System | `/nix/store/hqkwklfldn7sfw1bj7xxbdhq5c2namif-nixos-system-gemini-mainline-nixos-23.05.20240103.70bdade` |
| Padded p22 SHA-256 | `0cd222881c2dcc56d8da25f54903f70cf4d93475bc591175251403ba971be50e` |
| Store SHA-256 | `a55afc6b3ad2816a04b92659755982314195093707714ebc169e0bc8ce597d9d` |
| Store size | 426,987,520 bytes |

## Ordinary daemon build: hardware pass

`handoff/persistent-nix-01` passed the pinned `persistent-nix` profile of
`tools/qualify-uboot-recovery.py`. Its userspace store was installed under the
unique hash-named p29 filename above; the M69 store was verified before and
after publication. This is a direct LK/Linux boot of the EFI-capable kernel,
so the profile neither requires nor claims a U-Boot/EFI handoff.

Candidate boot `c6225ffd-b18e-4d85-8e25-0a1bf5d0fec0` passed full service
health, exact runtime kernel configuration, late-CPU identity binding, both
A72 online checks, the 4 GiB memory bank and LK reservations. The existing
M69 home file, fixed-output build and database records remained intact while
using the candidate's lower store and seeded database.

The ordinary build ran through `nix-build --store daemon` as `gemini` (UID
1000), launched by a transient systemd service. It declared no fixed output
hash. The builder used network namespace `net:[4026532559]`, distinct from
the host and daemon's `net:[4026531833]`, ran as non-root inside its sandbox,
and could not see `/home/gemini`. Sandbox policy and fallback policy were
checked as `true` and `false`, respectively. The resulting store directory is:

`/nix/store/y05f867msys00kbdwy1ivjpifg3h6rw6-gemini-daemon-ab69a8311a0d48e18c57e72d629aa364`

The ordinary build's output root lives in the persistent user's home. Its
proof-file SHA-256 is
`189364e47715c00352ed0b075e0a58b37e105a7929c82f3f52f877250e219cdc`.
Rescue boot `303e9296-7043-42a1-86fa-c39b219d4395` returned healthy M69 and
retained that output, root, NAR hash and derivation, together with the original
M69 persistence proof. Both boot writes/readbacks and automatic resets passed;
GPT/p30/p31 hashes are unchanged. The candidate-to-rescue preloader interval
was 329.225 seconds, including provisioning and qualification.

The terminal result sets `profile_qualified`, `ordinary_daemon_build_qualified`
and `nix_persistence_qualified` to true; `uboot_execution_proven` remains false.
The final audit reconfirmed the recovered healthy boot, free locks and no
writer. Four new host tests cover sandbox evidence and profile separation;
all 70 relevant verifier/backend regression tests pass.

This qualifies the daemon and ordinary sandboxed builds on the candidate.
The installed M69 image still has the two original limitations. The subsequent
EFI integration is described below. Normal generation management, fixed swap,
hibernation and persistent EFI settings are incomplete.

## Distro-manager integration

`geminiNixEfiBootFiles` packages this same Nix-enabled kernel and userspace as a
versioned systemd-boot entry. The bounded `efi-nix-provision` trial published
the new payload, preserved the previous entry and payload, and switched the
loader default after backing up its exact old configuration. Its candidate
passed EFI Linux health and an ordinary daemon build; all boot files, the
configuration backup and both old and new persistence proofs survived rescue.
The complete result is `handoff/efi-nix-provision-01`.

The `efi-nix-manager` trial then booted the published entry through the real
distro systemd-boot 261.2 manager. Candidate boot
`bdfccf9a-d47c-4130-8916-8596452f236c` passed full health, the exact kernel
configuration, CPU provenance and both A72 online checks. The manager's own
EFI variables selected
`gemini-9c1bfbbbb260cf5830de42c587ea599cfbad29749ee66c61c65d2caf6caff999.conf` on p29;
menu-to-execution time was 9,478,940 microseconds. An ordinary daemon build
submitted as `gemini` again ran in a distinct network namespace without access
to the user's home, with sandboxing enabled and fallback disabled.

Its output is
`/nix/store/10ihy8gva9za862c1vhq3ak2yhyw60id-gemini-daemon-2cec893b5e3b4c21b5ffc8f514e78fec`,
rooted in `/home/gemini/.gemini-daemon-build-2cec893b5e3b4c21b5ffc8f514e78fec/result`.
The proof-file SHA-256 is
`af75e7fe0bf0b0c0748b87e8aca7863d022c792debf116796a0be7f6f832ae5b`.
Artifact pins and the boot-publication contract are recorded in
[BOOT_HANDOFF.md](BOOT_HANDOFF.md#nix-enabled-versioned-entry-and-default-activation).

The complete `handoff/efi-nix-manager-01` result qualifies EFI handoff, the
ordinary build and Nix persistence. Automatic rescue restored healthy M69
`715150bb-63d5-48fb-ad86-9132df5e6274` and retained the output, root, NAR hash
and derivation, the original persistence proof and both sets of boot files.
GPT/p30/p31 remained unchanged. M69 stays the installed image; its daemon and
namespace limitations are unchanged. The Nix-enabled manager is a qualified
candidate, and arbitrary generation selection still requires per-entry CPU
provenance handling.

The later `efi-nix-provision-02` trial qualified deterministic initramfs
packaging and reused the verified publication. Its final healthy M69 boot
`6ab5f118-ecb3-49ff-9018-543c166b94fa` retained all four ordinary-build outputs
from the direct trial and three EFI trials, including every proof hash,
home GC root and registered NAR/derivation identity. The locked final audit is
`handoff/efi-nix-provision-02/final-idle-check.json`; per-output evidence is in
its `all-nix-outputs/` directory. Factory GPT is unchanged and fixed swap remains
unprovisioned.


The subsequent six-file DT publication and manager trials,
`handoff/efi-entry-dt-provision-01` and `handoff/efi-entry-dt-manager-01`, also
passed ordinary unprivileged builds and retention through automatic M69
rescue. The selected DT carries its own CPU identity; LK's memory and modem
reservations remain intact. The second trial's locked audit independently
retained all six ordinary outputs, home GC roots and database identities.
The current default selects the DT-bearing entry
`gemini-49d449df65df5f412d738d56cde096e212d61d437bb7faca7afccf86f6729da3.conf`;
both earlier entries/payloads and their configuration backups are preserved.
Normal NixOS generation installation and fixed swap remain incomplete.


`handoff/efi-entry-dt-cross-manager-01` subsequently booted this selected entry
from a carrier containing the older EFI kernel and DT. Candidate
`e0e358ec-c55f-48c5-88eb-034e11b115db` retained the selected CPU provenance,
passed full EFI/Linux health and built another ordinary sandboxed output:
`/nix/store/xs9rihi5nvjqd44l7smxw7a6r37mq19j-gemini-daemon-0903d3c227654da4a9be340dfb186a49`.
Its proof SHA-256 is
`4643d37c28a2a82beeb6869bf1e2831c5f0196911f40188768cb4e0ee2949b95`.
Automatic recovery returned healthy M69
`055f7573-d77d-43f9-80e4-ca06ae55e3b7` and verified the output, home root,
registered NAR and derivation, original persistence proof and all boot files.
The complete profile, cross-kernel selection and Nix persistence flags pass.


The final locked audit in `handoff/efi-entry-dt-cross-manager-01` independently
retained all seven ordinary build outputs, home GC roots, proof hashes and
registered NAR/derivation identities. It reconfirmed healthy M69, both flash
locks free and no writer; every trial handle is terminal. Evidence is in
`all-nix-outputs/` and `final-idle-check.json`.


The native EFI input retry `handoff/efi-key-events-manager-02` passed the same
complete manager, selected-entry DT and sandboxed daemon-build checks.
Candidate `7318eee6-a9a0-4fb1-ad67-4b993b37f026` created
`/nix/store/c7679k2rcaqw74hax6pcxdjcsr5bmkv6-gemini-daemon-99d09aee533443478a6242c44eb0f09f`,
with proof SHA-256
`c4cb51011bc22acbd6685f69bc5c22ef0c768cb1acb8583a1d3f44bc2f1822ed`.
Automatic rescue returned healthy M69
`58169ffb-952a-478a-ad72-59595d939729` and verified the new output, home GC root,
registered NAR/derivation, original proof and boot files. Its preceding attempt
was rejected by a host keyboard-poll counter check before the build phase and
created no ordinary output; it is not counted as a successful Nix trial.


The final locked audit independently verified all eight successful ordinary
build outputs, their proof bytes, home GC roots and registered NAR/derivation
identities. It reconfirmed healthy M69, free flash locks and no writer. Evidence
is in `handoff/efi-key-events-manager-02/all-nix-outputs/` and
`final-idle-check.json`; both native-key trial handles are terminal.
