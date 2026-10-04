# Fixed swap qualification

Persistent home and the Nix store/database work on p32. The fixed 5 GiB p34
swap partition is now installed and active, including after an ordinary reboot
in `handoff/fixed-swap-02`. Restoration to the original GPT/header passed in
`handoff/fixed-swap-01`. Paging under pressure now passes with zswap's shrinker
temporarily enabled; the default-policy correction and hibernation remain
unqualified. The latest active-swap boot is recorded in `handoff/swap-io-03`.

## Filesystem and partition geometry

Factory p32 had 32,737,247 sectors from sector 89,372,672. Its ext4 filesystem
has 2,781,184 blocks of 4,096 bytes: exactly 22,249,472 sectors. It therefore
fits the proposed smaller p32 without changing filesystem geometry. That
observation must be repeated immediately before any eventual partition change.
It is not permission to reformat or shrink a different filesystem.

The installed p34 starts at sector 111,622,144 and contains 10,485,760 sectors
(5 GiB). p33 `flashinfo` stays at sector 122,109,919 with 32,768 sectors. All
other partition entries, p32's start/identity/attributes, and both GPT headers'
unchanged fields are preserved.

`tools/plan-gemini-swap.py` prepares exact before/after GPT images on the host.
It does not access devices, flash, format, mount or reboot. It requires:

- The exact captured factory primary hash and complete primary/backup bytes.
- Valid header/table CRCs, matching copies, and the expected partition geometry.
- The identified ext4 filesystem's observed extent fitting the new p32.

Its primary write extent is 34 sectors; the backup is 33 sectors, beginning
immediately after p33. Rounding the backup write to 32 KiB would include
`flashinfo` data, so the plan never does that. The manifest records exact write
and rollback offsets, lengths and SHA-256 hashes. Only entries 32 and 34 change.

## Host evidence

```sh
python3 tools/test-plan-gemini-swap.py
python3 tools/plan-gemini-swap.py --primary PRIMARY_CAPTURE \
  --backup BACKUP_CAPTURE --extent EXTENT_JSON --out NEW_DIRECTORY
```

Five host tests cover exact byte preservation and write extents, filesystem
size boundaries, mismatched/corrupted GPT copies, changed protected geometry,
foreign p34 entries and invalid filesystem identity. Native `sgdisk -v` also
passed on sparse factory, planned and restored disk images. The oracle used
the current DA primary and a historical backup whose header/table matched it;
that is an independent layout check, not a substitute for fresh device capture. The fresh read-only capture and completed plan are in
`handoff/fixed-swap-plan-01`, taken from healthy M69 boot
`6ccf152f-2d43-4a71-8695-beabcf62ff3e` after the power-kernel trial. Both GPT
copies match the native oracle's inputs, the filesystem fits exactly, and all
four planned/rollback files match their manifest hashes. The capture held both
flash locks and verified unchanged device state before and after. No device
writes occurred.

The older `codex/storage-consolidation` branch also has a tested extent guard
for `gemini-storage-provision`; it is not deployed. Installed M69's old manual
provisioning script is not the qualified path for this change.

## Factory GPT writer

The separate `mtkclientGpt` package adds a deliberately restricted
`gemini-gpt-rewrite DIRECTORY` command. It accepts only the captured factory
GPT bytes and the identified MT6797 eMMC geometry. In one connected download
agent session it checks both GPT copies and all three boot partitions, captures
`flashinfo`, writes the backup first, verifies its readback, then writes and
verifies the primary. Complete GPT and protected-partition reads follow both
writes. A failed admitted operation attempts to restore both original copies;
reboot requires verified original GPT and protected data.

`tools/qualify-gpt-rewrite.py` stages private inputs and evidence, pins the
package and executed sources, and holds both flash locks through the bounded
DA session and Linux/data-retention checks. Its default is a read-only
preflight. The execution path runs in a durable host service and requires
the complete admission/write/readback/reboot sequence, independent binary
readbacks, a fresh healthy M69 boot, preserved EFI files and all ten previous
ordinary Nix build outputs.

```sh
nix build .#mtkclientGpt --out-link ../handoff/mtkclient-gpt
python3 tools/test-qualify-gpt-rewrite.py
python3 tools/qualify-gpt-rewrite.py --out NEW_DIRECTORY
```

Add `--execute` only for the factory rewrite trial. This command cannot install
the proposed swap layout. Thirteen package tests cover protocol addresses and
payloads, partial writes, failed acknowledgements, readback/restoration errors,
device identity, input files and CLI dispatch. Five host verifier tests reject
incomplete or reordered evidence, altered readbacks and protected data changes.
The build and test evidence is in `handoff/gpt-rewrite-host-checks`; fresh
read-only preflight passed in `handoff/gpt-rewrite-preflight-02`.

The hardware trial `handoff/gpt-rewrite-01` passed using
`/nix/store/rj1a8wj8l9w7z7rfy6sw0ka2imlhrawy-mtkclient-gemini-gpt-2.1.4.1`.
The backup write was exactly 16,896 bytes at byte offset 62,537,055,744;
the primary was exactly 17,408 bytes at offset zero. Both were acknowledged
and independently read back before proceeding. The complete 20-event journal,
four GPT readback files and protected-partition hashes passed verification.
The DA acknowledged reboot, and Linux returned automatically as healthy M69
boot `2c468de5-5249-43a0-ab38-6be1cf570603`. All ten ordinary Nix outputs,
their database/GC-root identities, the original home/fixed-output proof and
published EFI files survived. That trial left 33 partitions, no p34,
no swap. This proves successful factory-copy writes; failure restoration is
covered by host tests. The later changed-layout trial is recorded below.

## Installation prerequisites

The mtkclient boot-only lane and factory-GPT rewrites are qualified. The boot
backend and healthy-return checks still expect the factory GPT, so using them
unchanged after adding p34 would break recovery verification. Fixed swap
requires a separate complete transaction: offline persistent-data checks/backup,
bounded GPT writes and
independent readback, recovery that admits both exact layouts and restores the
original GPT on failure, then boot and data-retention checks. Swap formatting,
activation and reboot persistence must be verified afterwards. Hibernation
save/restore is a further requirement, described in `POWER_QUALIFICATION.md`.

## Offline persistent-data backup

`mtkclientBackup` adds `gemini-data-backup DIRECTORY`, a read-only DA command.
It admits the exact factory GPT and protected boot images, identifies p32 by
its ext4 UUID and exact 11,391,729,664-byte filesystem extent, and captures the
whole extent in 679 consecutive 16 MiB reads. It also preserves the original
4 KiB at the proposed swap start. Each chunk has a recorded digest, and the
host independently checks every chunk, the complete digest, filesystem
identity and GPT/protected data before accepting the backup.

The first hardware attempt, `handoff/data-backup-01`, refused the filesystem
because the ext4 journal-recovery flag remained set after shutdown. It
captured no filesystem data, performed no flash writes, and returned
automatically to healthy M69 boot `9452a763-5179-4336-929c-1e6d55fbde96`.
Published EFI files, all ten ordinary Nix outputs and the original persistence
proof passed subsequent checks; the backup attempt remains unqualified.

The corrected capture preserves the untouched offline journal instead of
requiring it to be already replayed. `tools/check-gemini-backup-image.py`
copies the captured bytes to a new private host file, verifies the copy's
input digest, and runs `e2fsck -p -E journal_only` on that copy. A subsequent
forced read-only check must pass. The original image's hash must remain
unchanged, and recovered UUID, extent and clean state must match expectations.
Known home and Nix proof files are read from the recovered image using
`debugfs`, without mounting it. This is host-copy journal recovery, not
permission to repair or format the live data partition.

```sh
nix build .#mtkclientBackup --out-link ../handoff/mtkclient-backup
python3 tools/test-qualify-data-backup.py
python3 tools/test-check-gemini-backup-image.py
python3 tools/qualify-data-backup.py --out NEW_DIRECTORY
```

Add `--execute` for the bounded offline capture and automatic Linux return.
Nine package tests exercise exact capture, short reads, device/filesystem
identity, pending journal preservation, failure recovery and real CLI
dispatch. Six host verifier tests reject missing/reordered chunks, altered
images and inconsistent evidence. Four tests using native ext4 tools prove
that journal replay preserves the raw snapshot and file bytes, and that it
does not hide unrelated bitmap corruption. Evidence is under
`handoff/data-backup-host-checks`.

The corrected hardware trial `handoff/data-backup-02` passed. It captured all
11,391,729,664 bytes, returned automatically to healthy M69 boot
`31c4b11e-73e6-4e3a-a22d-214d03c0ef81`, and retained the original home proof,
all ten ordinary Nix outputs and published EFI files. The raw image is
`data.ext4`, SHA-256
`30dfab1e1016f033c1a427f23d76be750b36eb82f5592bcd5e15186877bec434`.
Its recovered host copy is `data-recovered.ext4`, SHA-256
`faf8cff46f5b8cdc28bc3f91f39aaba7d7c0d066c2ab33ab584eda9c5bc8573d`.
Journal-only replay and the forced read-only check both returned zero. The
recovered image contains all twelve expected file proofs: the original home
and fixed-output files plus each of the ten ordinary build proofs. Both images
are private and read-only. No filesystem, GPT or boot-partition writes were
issued through the DA. The final locked audit found no writer and matched all
thirteen executed-source hashes before the package-pin update described below.

The trial used package
`/nix/store/yrsqgzlcrjfbk60i7lgy1w0d045gfrai-mtkclient-gemini-backup-2.1.4.1`,
retained through `data-backup-02/mtkclient`. A packaging correction now copies
only the two required host test files into the Nix build instead of importing
the entire tools directory. This removes the package-hash cycle caused by host
runners pinning that same package. The reproducible package is
`/nix/store/y65zyaa56fv5m08ra7hnjdj35g35a3kf-mtkclient-gemini-backup-2.1.4.1`.
All 1,276 files match the trial package after substituting only each package's
own store prefix; the runtime, dependencies and download-agent bytes are the
same. `data-backup-host-checks/package-equivalence.json` records that comparison.
The runner now pins this package; its executed trial archive retains the
original pin. The capture is a snapshot of that shutdown, not a live backup
of changes made by subsequent Linux boots.

## Prepared swap header

`tools/prepare-gemini-swap-header.py` uses pinned native `mkswap` on a new
sparse host file and retains only the inspected first 4 KiB. It checks every
byte against Linux's `union swap_header` and requires independent `blkid`
agreement. The prepared artifact is `handoff/fixed-swap-header-01`:

- Partition extent: 5,368,709,120 bytes; usable swap: 5,368,705,024 bytes.
- Page size: 4,096 bytes; filesystem UUID:
  `85ae0e4c-91cb-4b97-a960-fc6780f42361`; label: `gemini-swap`.
- Header SHA-256:
  `807f5f949455432666930598531247d0b6dc2bb23ba2ab3b18bc60f1f7382e7d`.
- Future write: 4,096 bytes at byte offset 57,150,537,728.

The native oracle test also rejects altered version, bounds, UUID, label,
reserved bytes and swap signature. At this preparation stage, the header had
not been written to the device. The transition must verify
the current filesystem extent and save the old header bytes, write/read back
the new header before publishing p34, and restore those bytes as well as GPT
on rollback. A standard swap header must be present before Linux's early
resume probe can see the new partition.

## Controlled layout transition

`mtkclientSwap` adds `gemini-fixed-swap DIRECTORY [--restore]`. It accepts
only six pinned factory/proposed GPT and header artifacts, the identified
MT6797 eMMC, unchanged protected images and the exact existing ext4 extent.
Installation writes and independently reads back the swap header, backup GPT
and primary GPT, in that order. It then verifies both complete GPT copies,
the header, unchanged ext4 superblock and protected images before reboot.
There is no filesystem resize or write inside the persistent filesystem.

An admitted failure attempts factory restoration. Restoration also accepts
torn writes confined to byte positions that differ between the two reviewed
layouts; changes outside that set are rejected. It restores backup GPT,
primary GPT and the original header, and requires complete final readbacks
before reboot. Twelve package tests cover bounds, partial writes, failed
readbacks/restoration, device/filesystem identity, stale inputs and CLI dispatch.

`tools/qualify-fixed-swap.py` holds both flash locks and starts an independent
rescue service before reboot. Worker failure without a verified commit causes
the rescue to acquire both locks and restore the factory layout. A successful
commit requires fresh healthy Linux, exact active swap, retained home/Nix/EFI
data and an additional ordinary reboot with the same checks. Ten host tests
cover the complete DA evidence, altered artifacts, both layout guards,
BusyBox swap identification and independent recovery after worker failure.

```sh
nix build .#mtkclientSwap --out-link ../handoff/mtkclient-swap
python3 tools/test-qualify-fixed-swap.py
python3 tools/qualify-fixed-swap.py --out NEW_DIRECTORY
```

The default command is a read-only factory-layout preflight; `--execute`
performs the transition. The pinned package is
`/nix/store/n4p7mz68zms2m6pawpwfbrs1sbdjq4vs-mtkclient-gemini-swap-2.1.4.1`.
Build and test evidence is in `handoff/fixed-swap-host-checks`.

The first trial, `handoff/fixed-swap-01`, installed the exact layout and
Linux activated 5,242,876 KiB of swap. Its host health check incorrectly
expected BusyBox `blkid` to return a bare partition UUID; it instead returned
a full filesystem record. The trial therefore failed. The independent rescue
then restored the original GPT and header, verified its complete DA sequence,
and returned to healthy factory-layout M69 boot
`0904beeb-2517-4d99-8ab9-0b80b302d3d1`, retaining all ten ordinary Nix outputs,
the original persistence proof and published EFI files. The rejected install
profile remains rejected; the complete hardware restoration evidence is valid.

The corrected verifier resolves the partition-UUID symlink and parses the full
`blkid` filesystem record. It independently revalidates the first trial's
restoration artifacts and execution archive before reusing that evidence.
Older boot and power qualification profiles still require the factory layout;
they must be explicitly adapted and checked before use with fixed swap.

The corrected trial `handoff/fixed-swap-02` passed the full install and
ordinary-reboot sequence. Installation returned healthy M69 boot
`5c846ac4-82a4-420d-b735-2fc0eb573f25`; the ordinary reboot returned
`2cdddb4d-755f-43d7-acb6-e830d4a2984d`. Both activated exactly 5,242,876 KiB
of p34 swap and retained the original persistence proof, all ten ordinary Nix
outputs and published EFI files. GPT/header readbacks and protected-image
hashes matched. The independent rescue accepted the verified commit and
stopped. Hibernation remains disabled. The final locked audit repeats the
live identity, active-swap and retention checks and verifies all thirteen
executed-source hashes, inactive trial services and absence of a writer.

## Prepared paging probe

`geminiSwapProbe` builds a static AArch64 probe for real swap I/O. It fills
128 MiB of anonymous memory with a deterministic incompressible pattern,
requests page-out, requires at least 64 MiB in its own `VmSwap`, and checks
every word after reading it back. It also requires at least 64 MiB of both
reads and writes in p34's block counters, so compressed RAM alone cannot
satisfy the check. The probe does not write directly to the block device.

The host self-test, strict compiler checks and static ELF inspection pass.
The artifact is `handoff/fixed-swap-io-probe`, binary SHA-256
`e2d910dc9ccacf3521f091089890cac47e12ee06a1f6df2b98d8ffe859862867`.
Active swap and reboot persistence do not establish paging under pressure or
hibernation save/restore. Device pressure trials are recorded below.

## Pressure trials and zswap writeback

`tools/qualify-swap-io.py` runs the 128 MiB probe in a target service limited
to 64 MiB of memory, 256 MiB of swap and 90 seconds. It verifies the actual
service limits and process exit, the complete probe result, unchanged M69
identity, watchdog ownership, active swap and retained home/Nix/EFI proofs.
An independent host service waits for authoritative worker termination. On
failure it stops and clears only the named probe service, then preserves the
swap layout if full health and retention pass. Otherwise it uses the qualified
factory GPT/header restoration. Ten host tests cover evidence rejection,
runtime-policy cleanup and both recovery branches.

```sh
python3 tools/test-qualify-swap-io.py
python3 tools/qualify-swap-io.py --out NEW_DIRECTORY
```

Default is read-only preflight; `--execute` starts the bounded device trial.
Executed sources, probe bytes, target service properties and diagnostics are
retained privately in the requested directory.

The first trial, `handoff/swap-io-01`, failed with a memory-cgroup OOM before
producing a valid probe result. Its independent rescue restored the exact
factory layout and healthy M69 boot `216413ef-1fc6-42f0-a37c-d8161fe8939d`,
retaining all ten ordinary Nix outputs and original persistence/EFI proofs.
The final audit found no writer and matched all fifteen executed sources.

M69 has zswap enabled with LZ4, but `shrinker_enabled=N`. Its Linux 7.1
`zswap_compress()` stores incompressible pages uncompressed in the pool;
`zswap_shrinker_count()` and `zswap_shrinker_scan()` refuse pressure-driven
writeback while that switch is off. The live policy otherwise allowed swap:
`vm.swappiness=60`, parent `memory.swap.max=max`, and
`memory.zswap.writeback=1`. The later controlled runtime correction passes
the same allocation and memory limit, supporting this diagnosis.

The corrected trial temporarily enables the shrinker using `ExecStartPre`
and restores its original disabled value using `ExecStopPost`. Its result
distinguishes that runtime correction from the unmodified default policy.
The first setup attempt, `handoff/swap-io-02`, failed before producing paging
evidence: the system manager's PATH contains only systemd tools, so the setup
script could not find `cat`. Automatic factory restoration returned healthy
M69 `7f5b8d96-fcec-423f-9881-b24e464d2fab`, retaining all prior proofs. The
restricted-PATH failure was reproduced on the host; an explicit target PATH
then passed actual device setup/process/cleanup against a harmless temporary
file. Evidence: `handoff/swap-io-host-checks/setup-reproduction.json` and
`target-setup/`. The retry uses that tested service environment.

The opt-in `mainlineNixosPowerSwapBundle` enables
`CONFIG_ZSWAP_SHRINKER_DEFAULT_ON=y` from boot, retaining the previously
qualified watchdog correction. Its complete build passes, but it is not yet
hardware-qualified or installed. Artifact pins are in
[POWER_QUALIFICATION.md](POWER_QUALIFICATION.md).

The corrected hardware trial `handoff/swap-io-03` passed on M69 boot
`f48ecf05-1772-49e7-898a-ce9bd3740c5e`, following the successful reinstall and
ordinary reboot in `handoff/fixed-swap-04`. The probe verified all 134,217,728
bytes under the enforced 67,108,864-byte memory limit. Its own `VmSwap`
reached 131,080 KiB, including 8 KiB beyond the mapped test buffer. p34 counters
advanced by 262,184 written sectors and 238,384 read sectors (512 bytes each).
The service exited successfully with no remaining process. The captured
kernel diagnostics contained no OOM, I/O-error or kernel-fault matches.

The independent policy observation was `Y` during the test; stopping the
service ran `ExecStopPost` and restored `N`. Full Linux/watchdog health, active
swap, all ten retained ordinary Nix outputs and original home/EFI proofs
passed. The independent rescue accepted the complete commit. The final locked
audit repeats live health and retention, verifies all fifteen executed-source
hashes and the probe digest, and confirms inactive services and no writer.
This qualifies real paging under memory-cgroup pressure with the runtime
correction. Installed M69 still has its original disabled-shrinker policy;
booting and promoting the built correction remains necessary.
