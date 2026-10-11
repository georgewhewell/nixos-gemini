# GNSS over CONSYS/STP

The maintained Linux 7.2.9 driver uses the standard `/dev/gnssN` raw interface,
the existing CONSYS/STP transport owner and an ordinary `lna-supply`. One radio
power and transport stack owns task 2. Protocol decoding belongs in ordinary
userspace; receiver output and gpsd support remain unestablished.

[Accepted image 112](../research/accepted-baseline.json) uses kernel source
`8e0e9aa9358e48a4d6b2dbe2b45ae922afd0f1a0`. Native registration and two bounded
10-second open/close cycles pass LNA off/on/off, zero taint and subsequent
GNOME Bluetooth/NetworkManager checks. Both windows receive zero bytes.
The [scalar proof](../research/gnss-integration-20261011.json) preserves trial
101 and the new receive attribution separately, with their exact builds and
independent terminal/storage audits.

The native CONSYS aggregate exposes read-only `gnss_rx_frames`: CRC-valid,
nonempty task-2 frames before sequence selection, including duplicate and
out-of-order frames. The GNSS platform child exposes read-only `rx_delivery`:
`admitted=<u64> inactive=<u64> rejected=<u64>`. These are independent owner-local
lifetime counts, preserved across parser resets and open/close. They are not an
atomic accounting identity. Existing locks and teardown own their lifetime;
no payloads or location data are retained. The observer verifies both native
owners and snapshots counts before open, after the read window and after close.

All counters remain zero in both trial-112 cycles. No validated task-2 frame
reaches the selected boundary; malformed traffic before CRC validation is still
possible. No inactive discard or whole-frame FIFO rejection is observed.
Changing endpoint admission, resetting shared STP sequence state or adding a
FIFO workaround is unsupported by this result.

Public GPL source establishes WMT function 2 and the board LNA sequence.
`GPS_open` powers GPS, checks shared STP readiness and registers its callback;
registration is host-local and flushes the queue. MT6797 skips GPS_SYNC.
The NMEA-labelled vendor node accepts userspace-written output, so its name
does not prove receiver NMEA output. Optional GPS EMI offload is disabled in
the retained board configuration. Checked public source supplies no additional
receiver initialization command or inner payload framing. Proprietary-library
claims are not a clean-room protocol contract.

Remaining owner work: establish public receiver output/initialization and inner
framing, then qualify a stream and position through ordinary userspace,
sustained radio coexistence and suspend. Keep whole-frame FIFO rejection/retry
and power admission intact. The existing actual-path fixtures cover CRC errors,
sequence selection, callback outcomes, retry and counter lifetime.
`tools/test-gnss-desktop.py` reuses the supervised boot/storage owner and adds no
normal-boot diagnostic service. Power lifetime success does not qualify a fix.
Current conclusions are recorded in [HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md).
