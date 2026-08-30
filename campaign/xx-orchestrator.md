# Orchestration and test discipline

The campaign has one rule: source archaeology can run in parallel; silicon
transactions are serial, bounded, and reversible. A status is promoted only by
the evidence named in the front-page matrix.

## Required gate record

Every device experiment records:

- exact kernel commit, DTB/overlay, config and boot slot;
- resources resolved from the live DT (address, IRQ, clock, reset, rail,
  reserved memory);
- expected timeout and failure state;
- complete relevant dmesg/sysfs/trace artifact;
- rollback image and confirmation that p31/recovery remains untouched.

`SOURCE EXISTS`, `IN_TREE`, a successful compile, and QEMU/KUnit are not
hardware proof. In particular, the current STP KUnit tests are hardware-free;
they do not demonstrate CONSYS, BTIF, GNSS or Bluetooth progress.

## Connectivity gate order

1. Passive resource inventory: no MMIO, clocks, reset, IRQ, DMA, firmware or
   reserved-memory access.
2. CONSYS identity: use VCN18 -> 240 us -> VCN28 -> sleep mask -> reset ->
   `PWRON_CONFG_EN` -> SCP_SYS_CONN/CCF -> 30 us -> ID `0x0279`, keeping reset
   and AFE/radio/firmware untouched. The vendor off path leaves mask/config
   writes unresolved; restoration is UNKNOWN.
3. PIO-only BTIF bytes using the dormant resource description. Add APDMA only
   after MT6797 address width and channel routing are proven; generic VFF
   offsets are not enough.
4. STP mandatory/full codec with bounded lengths, preserved unconsumed input,
   `(header[1] & 0x70) >> 4` channel extraction, ACK/window state and resync.
5. Exact WMT type/opcode/LE16-length transactions; then GNSS task 2 or BT HCI.

Do not load a firmware blob, enable Wi-Fi/FM/modem, or run an invented “ping”
until the preceding gate has a captured pass. Do not treat a custom 8 KiB ring
as the architecture when upstream 8250/APDMA support is available.
