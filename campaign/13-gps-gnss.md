# GNSS over CONSYS/STP

Development source `8b9fa390` wires the retained GNSS class endpoint in
`drivers/gnss/mtk-consys.c` into the existing Linux 7.2.9 CONSYS aggregate.
The accepted image 98 still precedes that change. The endpoint uses the normal
`/dev/gnssN` raw interface;
a second kernel decoder or private userspace interface is unnecessary.

The recovered August 31 hardware evidence proves GPIO69 LNA control and WMT
GPS function on/off acknowledgements. It does not prove a position fix or a
NMEA stream. The later assertion that a proprietary navigation library is
required is not clean-room evidence. Receiver output semantics remain unknown.

Public GPL source establishes STP task 2, WMT function 2, and the board LNA
sequence. The current shared CONSYS owner already provides full-STP transport
and lifetime management. Integration work uses that owner and a standard
`lna-supply`, retaining one radio power and transport stack.

The native receive path refuses a whole frame if its FIFO cannot fit it;
STP retry cannot duplicate a published prefix. First open powers GPS and its
LNA; last close or terminal teardown balances both through the shared owner.
An unused endpoint-local reset export is retired: clearing a sticky fault
without rebuilding the transport does not recover the radio. Actual-path host
regressions, strict ARM64 compilation, selected DT schemas and the normal
kernel build pass. Trial 99 rejected the candidate because the custom system
omitted the standard NixOS kernel module tree, so automatic device loading
could not find the GNSS module. Accepted image 98 was restored; the independent
terminal and storage audit passes. The boot integration now supplies the standard
module tree and consolidates ordered-startup blacklists. Image 100 passes native
GNSS alias resolution, ARM64 module/runtime and existing service admission checks;
hardware lifetime checks are pending.

`tools/test-gnss-desktop.py` reuses the existing supervised boot and storage
owner. It qualifies two bounded open/close cycles, LNA cleanup and subsequent
desktop radio checks; it adds no normal-boot diagnostics. Passing that scope
does not qualify receiver protocol or position.

Qualify repeated open/close and shared-radio coexistence,
then establish publicly documented receiver framing and a real position fix.
Protocol decoding belongs in ordinary userspace such as gpsd. A binary stream
is not evidence that gpsd already supports it or that it contains solved
positions. The public vendor NMEA-labelled port buffers userspace-written data;
its name does not prove receiver NMEA output. Public GPS EMI is optional MNL
offload and is disabled in the retained board configuration. Checked public
source establishes no additional receiver initialization command or inner
payload framing. Keep location data out of retained diagnostics. Current status and
remaining work are recorded in [HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md).
