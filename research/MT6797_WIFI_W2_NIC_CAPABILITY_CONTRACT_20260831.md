# MT6797 Wi-Fi W2 NIC-capability/IRQ contract

W2 is a bounded successor to the hardware-passed W1 firmware/READY path. It
does not claim a WLAN transport, cfg80211 device, or netdev. It uses one
ordinary read-only vendor command to prove that the real Wi-Fi interrupt
delivers a fresh port-1 firmware event.

## Exact vendor evidence

- `nic/nic_pwr_mgt.c:379-389` reads and clears `WHISR`, reads TX released
  counts when required, resets host TX resources, and only then enables
  interrupts. W2 reuses W1's completed status/release clearing before it arms
  the platform IRQ. This bounded client allocates no vendor adapter/TX
  resource, so it has no host TX resource to reset.
- `common/wlan_lib.c:3726-3779` builds the normal
  `CMD_ID_GET_NIC_CAPABILITY` query. It allocates
  `CMD_HDR_SIZE + sizeof(EVENT_NIC_CAPABILITY_T)`, marks it as a query needing
  a response, and calls `nicRxWaitResponse(..., 1, ..., 124, ...)`.
- `common/wlan_lib.c:3782-3816` requires
  `EVENT_ID_NIC_CAPABILITY` and copies only the capability fields from the
  response.
- `include/nic_cmd_event.h:41-42,163,199,294-315,495-516` fixes the packet
  constants and layouts: PQ `0x8000`, command type `0xa0`, CID `0x80`, event
  type `0xe000`, EID `0x01`, 8-byte headers, and 116-byte capability payload.
  The event is therefore exactly 124 bytes.
- `nic/nic.c:1025-1040` starts `ucCmdSeqNum` at zero, so the first normal W2
  command/event pair uses sequence 1. This is distinct from W1's init-command
  sequencing.
- `nic/nic_rx.c:3615-3714` maps response port 1 to the upper 16 bits of
  `WRPLR` and `WRDR1`; it waits at most 1000 ms. With
  `CFG_ENABLE_READ_EXTRA_4_BYTES=1` in `include/config.h:740`, lines
  3680-3692 transfer an additional four portal bytes while retaining the
  exact 124-byte event.
- `include/nic/mt6630_reg.h:289-305` defines `WHISR_RX1_DONE_INT` bit 2 and
  enables it in `WHIER_DEFAULT`; `nic/nic.c:348-380` sets `WHLPCR_INT_EN_SET`
  to enable global delivery.

## W2 acceptance rule

After W1 READY and status/release clearing, the upper `WRPLR` half must be
zero. W2 then requests the DT Wi-Fi IRQ (`<GIC_SPI 283 IRQ_TYPE_LEVEL_LOW>`),
arms its completion state, enables device global IRQ delivery, and writes one
124-byte port-1 command. The only success is one threaded real IRQ whose
`WHISR` contains RX1-done, whose upper `WRPLR` half is exactly 124, and whose
`WRDR1` event has packet length/type `124/0xe000`, EID `0x01`, and sequence 1.

Any queued pre-command port-1 response, non-RX1 interrupt, wrong length,
packet type, EID, sequence, portal error, or 1000 ms timeout fails closed.
The device global IRQ is cleared and the Linux IRQ is freed before W1 portal
and power cleanup. This prevents stale TX_DONE from being reported as an IRQ
proof while preserving the passed W1 driver-own, firmware, EMI/MPU, start, and
READY route.
