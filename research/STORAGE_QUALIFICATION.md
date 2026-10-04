# Fixed swap qualification

Persistent home and the Nix store/database already work on the existing p32
filesystem. The GPT still has 33 factory partitions, no p34 and no active swap.
The requested fixed 5 GiB swap partition remains unfinished.

## Filesystem and partition geometry

Current p32 has 32,737,247 sectors from sector 89,372,672. Its ext4 filesystem
has 2,781,184 blocks of 4,096 bytes: exactly 22,249,472 sectors. It therefore
fits the proposed smaller p32 without changing filesystem geometry. That
observation must be repeated immediately before any eventual partition change.
It is not permission to reformat or shrink a different filesystem.

The proposed p34 starts at sector 111,622,144 and contains 10,485,760 sectors
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

## Required before installation

The mtkclient boot-only lane is qualified. Its backend and healthy-return
checks currently expect the factory GPT, so using it unchanged after adding
p34 would break recovery verification. Fixed swap requires a separate complete
transaction: offline persistent-data checks/backup, bounded GPT writes and
independent readback, recovery that admits both exact layouts and restores the
original GPT on failure, then boot and data-retention checks. Swap formatting,
activation and reboot persistence must be verified afterwards. Hibernation
save/restore is a further requirement, described in `POWER_QUALIFICATION.md`.
