# Storage: eMMC and MicroSD

Status: MMC0/eMMC was DEVICE-TESTED in the earlier bounded baseline; its state
after the latest p22 transaction, high-speed modes and MicroSD are **UNKNOWN**.

The independent recheck recorded `boot`, `boot2`, and `boot3` resolved to p22,
p30 and p31 with exact sizes/hashes; p29 and the store were read-only
(`research/HARDWARE_TEST_LEDGER.md:41-49`). Stage A later retained p30/p31 and
verified p22 after boot (`:291-308`). This is conservative eMMC access evidence
only; it does not prove HS200/HS400, tuning, write safety or MMC1 detection.

The later p22 candidate/rollback transaction stopped before SSH and a
post-rollback readback (`research/HARDWARE_TEST_LEDGER.md:655-674`). Therefore
there is no current partition-state claim. The next gate is a read-only full
hash/size/label check of p22/p30/p31 after the network/recovery path returns.
MicroSD remains disabled until pins, card detect and rail levels have an
independent evidence packet.
