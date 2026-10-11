# GNSS over CONSYS/STP

Installed source `8b9fa390` wires the retained GNSS class endpoint in
`drivers/gnss/mtk-consys.c` into the existing Linux 7.2.9 CONSYS aggregate.
The accepted image 101 includes that change. The endpoint uses the normal
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
module tree and consolidates ordered-startup blacklists. Trial 100 still lacked
the endpoint: the stale hardware-scan disable masked udev's module-loading rule.
Image 98 was restored and independently audited. That setting is now removed;
the Bluetooth startup guard remains because HCI registration queues power/setup.
Image 101 passes admission for the effective udev rule, native GNSS alias,
ordered drivers and ARM64 runtime. Its supervised trial and independent terminal
audit pass; later accepted images retain these unchanged GNSS inputs. Two 10-second open/close cycles pass
native module/driver/class registration and LNA off/on/off with zero taint,
then GNOME Bluetooth access and a fresh NetworkManager scan pass without radio
faults. Both GNSS windows receive zero bytes: this qualifies the observed power
lifetime, not reception, protocol or a position fix. Sustained concurrent radio
traffic and suspend remain unqualified. The exact scalar proof is in
[gnss-integration-20261011.json](../research/gnss-integration-20261011.json).

`tools/test-gnss-desktop.py` reuses the existing supervised boot and storage
owner. It qualifies two bounded open/close cycles, LNA cleanup and subsequent
desktop radio checks; it adds no normal-boot diagnostics. Passing that scope
does not qualify receiver protocol or position.

Establish the public receiver initialization and data-delivery contract, then
qualify received bytes, framing, a real position fix and sustained coexistence.
Protocol decoding belongs in ordinary userspace such as gpsd. A binary stream
is not evidence that gpsd already supports it or that it contains solved
positions. The public vendor NMEA-labelled port buffers userspace-written data;
its name does not prove receiver NMEA output. Public GPS EMI is optional MNL
offload and is disabled in the retained board configuration. Checked public
source establishes no additional receiver initialization command or inner
payload framing. Existing active full-STP diagnostics cannot distinguish task2
delivery from inactive endpoint discard. The next native observation needs
scalar accepted/discarded/FIFO-rejected counts at that owner; generic bootstrap
STP and KUnit counters do not measure this stream. Also count CRC-valid task-2
frames before sequence selection, so duplicate/out-of-order frames discarded
before dispatch can be distinguished from absent task-2 traffic. Preserve the
existing whole-frame ACK/retry and power-admission behavior. Keep location data out of
retained diagnostics. Use passive counters in the existing CONSYS session and
GNSS endpoint, with their existing lock and teardown ownership. Preserve counts
across parser resets and open/close; do not change admission during power-off.
Extend the existing actual-path fixtures for duplicate/out-of-order frames,
inactive discard, whole-frame FIFO rejection/retry, corrupt CRC and counter
lifetime. All-zero selected counters still cannot exclude malformed traffic
before CRC validation. Current status and
remaining work are recorded in [HARDWARE_STATUS.md](../research/HARDWARE_STATUS.md).
