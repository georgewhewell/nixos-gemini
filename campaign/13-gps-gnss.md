# GNSS over CONSYS/STP

Current Linux 7.2.9 retains the GNSS class endpoint in
`drivers/gnss/mtk-consys.c`, but the installed CONSYS aggregate does not yet
register it. The existing endpoint uses the normal `/dev/gnssN` raw interface;
a second kernel decoder or private userspace interface is unnecessary.

The recovered August 31 hardware evidence proves GPIO69 LNA control and WMT
GPS function on/off acknowledgements. It does not prove a position fix or a
NMEA stream. The later assertion that a proprietary navigation library is
required is not clean-room evidence. Receiver output semantics remain unknown.

Public GPL source establishes STP task 2, WMT function 2, and the board LNA
sequence. The current shared CONSYS owner already provides full-STP transport
and lifetime management. Integration work uses that owner and a standard
`lna-supply`, retaining one radio power and transport stack.

The native receive path now refuses a whole frame if its FIFO cannot fit it;
STP retry cannot duplicate a published prefix. Actual-path host regressions
and strict ARM64 compilation pass in development; hardware qualification is
pending.

Finish the provider integration, qualify repeated open/close and coexistence,
then establish publicly documented receiver framing and a real position fix.
Protocol decoding belongs in ordinary userspace such as gpsd. A binary stream
is not evidence that gpsd already supports it or that it contains solved
positions. Keep location data out of retained diagnostics. Current status and
remaining work are recorded in [HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md).
