# Gemini kernel development baseline

The maintained base is Linux 7.2.9 (`v7.2.9`,
`5fce161649b4d779d1b76d9fcd52dc77779774b8`), the latest stable release checked
against [kernel.org](https://www.kernel.org/releases.json) on 2026-10-10.
Mainline was 7.3-rc6. New drivers use current subsystem contracts, checked
against the pinned stable source; builds use reproducible commits.

Linux development uses one branch, `gemini-7.2.9`, with upstream ancestry and
the replayed board port. Packaging uses `master`. The default build and
its development shell use the locked Nixpkgs ARM64 compiler: GCC 15.3.0 with
binutils 2.46. There is no separate compiler version pin or media kernel variant.
Driver fixes belong in Linux; packaging builds its native defconfig and DTB.

The [installed accepted image](accepted-baseline.json) is trial 115, kernel
source `89c13acdc6c0891191be7847450ed8e199a76f10`.
Its focused deployment and independent terminal audit pass GNOME RFKILL
visibility, directed NetworkManager scanning, native eMMC high-speed admission,
RAM-only paging, retained storage and an ordinary Nix build.
Onboard audio mapping retains its unchanged inputs. The native FUSB301 fix removes
repeated unchanged Type-C/USB-role notifications: zero of each in six seconds,
versus 12 of each on image 102. The [performance record](desktop-responsiveness-20261011.json)
retains both observations, the exact build and independent audit.
Native GNSS registration and two bounded LNA cycles pass with the new owner
counters in [image 112 proof](gnss-integration-20261011.json). Onboard stereo mapping retains
unchanged-input trial 98 evidence. Normal
NetworkManager association and traffic over wlan0 retain trial 95 evidence;
Bluetooth discovery retains trial 94 evidence with unchanged radio inputs. Selecting another
SSID, Bluetooth pairing/profiles and audible orientation remain unqualified.
RTC and GPU results retain their relevant unchanged-input evidence
from [trial 88](desktop-responsiveness-20261011.json); desktop updates do not
repeat RTC alarm/calendar diagnostics.

The installed revision verifies the native SYSIRQ polarity field before
forwarding type setup to the GIC. Its normal ARM64 build, required actual-callback
regression and platform admission pass. Decoder trial 103 accepts SPI 240 setup
and polarity write readback on this revision, but delivers no completion IRQ.
The [media IRQ owner note](mt6797-vdec-v4l2/irq-contract.json) preserves that
distinction and the remaining source-enable/handshake contract.

This revision admits current supplicant userspace capability flags and station
joins to cached passive-channel APs. Its real-callback tests use the kernel's native flag enums
and are required by the normal kernel build. Native modem bring-up remains
incomplete: a fresh boot reaches HS2 and exchanges AT traffic, then receives a
modem watchdog interrupt at 106 seconds. SIM/eSIM and cellular data are not
qualified.

The installed revision acknowledges AP-side CLDMA RX IP_BUSY at the native IRQ
owner and detaches old Wi-Fi connection admission before cfg80211 notifications.
Actual-path regressions fail before each fix and pass afterwards with GCC 15
ASan/UBSan; strict ARM64 builds, the normal build and supervised image/audit pass.
Bounded exception decoding reads the independent PL prefix of the nine-core
report while keeping its overview unqualified. It identifies an undefined-
instruction offender and a cross-core exception, without establishing their
cause. The watchdog remains unresolved. GNOME Calls, Spacebar and callaudiod are cross-built and installed;
native SIM, speech control and call-audio lifetime work remains open.

Modem receive change `6e84a8a9a31c431f9774d828a15efb90fa4d6e41` retains validated
closed-port AT frames in a bounded native FIFO. First open drains it in order;
close, failure and removal share the same receive owner. The existing regression
fixture checks the old loss, queue limits and concurrent lifetime transitions.
GCC 15 ASan/UBSan, strict ARM64 compilation and the normal kernel build pass with
unchanged configuration. The fresh trial 101 metadata observes 56 of 56 AT
frames delivered, with zero closed-port drops versus two in trial 98. The modem
still fails at 106 seconds and ModemManager exposes no SIM object; corrected
receive ownership is not a SIM/watchdog fix. The
[modem record](desktop-radio-activation-20261011.json) preserves both results.

Image 115 qualifies native fatal AT withdrawal through standard WWAN HUP/ERR
and port removal, without sending AT commands or reading payload. It installs
the bounded public disabled-PBM DBM initializer before the HS1 runtime reply;
the modem still reaches READY and receives its watchdog interrupt. Native SIM
electrical maps expose all six inherited pad settings, matching the public board
configuration: mode 1, IES/Schmitt enabled, CLK/RST pulls disabled and SIO pull-up
with R1/R0 encoding 1/0. Linux has not claimed those pads. The
[cellular owner](sms-voice-integration-20261011.json) records the exact build,
independent terminal audit, finite observations and remaining cold-state,
modem-stability and eUICC access work. No SIM presence or provisioning is claimed.

The combined image retains native MMC0 pad ownership and the current-demand
check before CPU parking removes a core. Image 112's locked readbacks confirm all
12 pad settings and configured supplies. Accepted image 114 retains verified
clock acceptance/restoration, balanced clock leases and standard eMMC high speed:
52 MHz requested and 47,999,984 Hz actual on the unchanged 8-bit bus. All 15 native
error counters remain zero around retained-storage checks and one ordinary Nix
build. It installs bounded reset/FIFO/STOP polling and checked MSDC/CQHCI DMA
ownership through recovery and teardown. Actual-source GCC15 ASan/UBSan checks,
compiled old-source controls, strict ARM64 objects, the normal build and supervised
trial/independent audit pass. No hardware recovery fault or sustained storage
benchmark is claimed. Physical controller isolation and generic CQE error-return
propagation remain owner work.

Image 114 also preserves complete procfs text and seeking while avoiding unused
IRQ-tail construction for CPU-only readers. A post-audit isolated trace records
40 complete CPU records and zero IRQ-counter lookups, versus 245 per report in
image 113. Its passive 30-second daemon observation uses 1.05% of one core,
including 0.73% kernel time, versus 3.93%/3.74% on 113. Both windows keep cores
0–1 with no transitions; activity is uncontrolled, so this qualifies the removed
native work and bounded owner cost, not UI latency. Policy and cadence are
unchanged. Earlier allocation/topology fixes and the native FUSB301 removal of
udev overhead retain their evidence in the
[performance record](desktop-responsiveness-20261011.json). Native PMU counters,
measured scheduling capacities, deep idle and user-visible responsiveness remain
open. The obsolete per-boot M39 RTC presence service is removed while retaining
its unchanged logind policy; accepted RTC alarm/calendar evidence is reused.

GNSS uses the existing CONSYS/STP owner and the standard Linux GNSS class.
Normal module discovery and udev loading now work. Two power cycles receive
zero bytes and all CRC-valid/admitted/inactive/rejected counters stay zero.
No validated task-2 frame reaches the selected boundary; malformed traffic
before CRC validation remains possible. Receiver output/initialization, framing, position and suspend remain
open in the [GNSS owner record](../campaign/13-gps-gnss.md).

The installed platform retains built-in IPv6, FUSE, LZ4 zram, decoder resources,
GPU DVFS and native thermal cooling. Zswap, zram writeback and hibernation are
disabled. The [no-swap 7.1.3 fallback](baselines/boot-test-76.json) remains preserved;
historical packages and their exact proofs are separate from current development.

The kernel exports its generated configuration and `Module.symvers` for strict
external-module builds. Experimental media modules must be rebuilt against the
exact installed kernel and toolchain. [Decoder trial 97](mt6797-vdec-v4l2/irq-trial-97.json)
uses the recorded image-96 build. CCF-owned ACTIVE initialization changes the
clock word to `0x101`, but it still times out with zero delivered interrupts.
Quiescence, guards, unload, supervised return to image 96 and terminal audit
pass; no successful frame is exported. Media hardware completion, shared surfaces,
encoding and suspend remain unfinished.

## Media interfaces

The firmware-free H.264 decoder uses the upstream stateless V4L2 Request API,
V4L2 memory-to-memory scheduling and videobuf2 queues. VA-API is a userspace
interface; the kernel driver remains V4L2. New decoder and encoder work must use
the current subsystem interfaces for controls, buffer lifetime, DMA mapping,
completion, runtime power and supplier ownership. Similar silicon supplies
public register leads, which still require MT6797-specific validation.

The experimental decoder now replaces private-picture capture copying with
native compound DMA-buf surfaces, independent DPB/job references, reservation
fences and explicit CPU/MMAP cache transitions for every attachment. The
maintained kernel includes change `01222a4b2074555955a85715587bebf0933fb0eb`,
which marks direct DMA SG bounce mappings and clears direct/IOMMU markers on
teardown. This belongs
in the DMA owner: Gemini's GPU uses direct DMA with its own MMU, rather than a
system-IOMMU domain. The driver admits proved unbounced mapping routes and
rejects unsupported routes without a copy fallback. See the
[decoder owner](mt6797-vdec-v4l2/README.md) for current restrictions and the
hardware qualification still required. Image 111 installs the shared DMA and
Mesa owner changes in the normal desktop. Experimental decoder results retain
their exact module and kernel inputs; hardware completion remains unfinished.
Trial 105 on the `01222a4b` kernel now qualifies native allocation, export,
Panfrost PRIME mapping, cache transitions and release lifetime with no codec
or GPU submissions. [Its scoped proof](mt6797-vdec-v4l2/buffers-trial-105.json)
includes supervised restoration and independent audit of image 102. Rendering
and decoder completion remain unfinished.
Trial 106 additionally qualifies advertised and mixed CREATE_BUFS lengths,
including chroma's offset in the minimum format size and retaining a separate
codec extent. [Its proof](mt6797-vdec-v4l2/buffers-trial-106.json) records the
module build, failure regressions, hardware result and restored-system audit.
These experimental-module fixes and retired probes leave the normal kernel and
deploy derivations unchanged.

## Verified DMA-buf changes

Inspection of the fetched upstream `v7.1.3..v7.2.9` history shows:

- Linux 7.2 makes the system and CMA heaps loadable modules. Both currently
  prohibit unloading. This helps package standard userspace buffer allocators;
  it does not automatically change our decoder's allocation path.
  [System heap change](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=fd55edff8a0abe1b198af9a4280bfb208b9d2ab7),
  [CMA heap change](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=10bb37fc624cfcc1d10e0ebfc1b829401abba91e).
- Udmabuf fixes malformed scatterlists, DMA direction and CPU cache synchronization,
  including the first CPU access. These matter if userspace-created buffers are
  used in a future shared-frame pipeline. They are not exercised by the current
  decoder's native DMA-buf cache ownership.
  [First CPU access fix](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=1d0e25c1ddf206).
- Stable 7.2 includes `dma_buf_fd_install()` and changes DMA-heap allocation to
  publish a reserved fd only after the userspace result copy succeeds. This
  prevents allocation failure from leaking a published fd or closing a reused
  fd in another thread. The V4L2 driver should continue to use vb2's export
  helper rather than duplicating this allocation ioctl.
  [Stable fix](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id=0d4a5d218055db29b50cc07d3d73d27007c2a391).
- Stable 7.2.8 fixes a fence driver/timeline name lifetime regression introduced
  in 7.2. The 7.2.9 target includes the fix.
  [Linux CVE team explanation](https://lists.openwall.net/linux-cve-announce/2026/10/06/71).
- `dma_buf_phys_vec_to_sgt()` already exists in 7.1.3. Its 7.2 stable overflow
  and page-aligned splitting fixes primarily address large MMIO/PCI peer-to-peer
  mappings. They are not a new MT6797 video surface API.
  [Original helper](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=3aa31a8bb11e47c0ff2b306988d1756b810c1c3c).

## Other Gemini ports

Reviewed [cjdell/gemini-nixos](https://github.com/cjdell/gemini-nixos) at
`6a27937b525fe3a6db765ffb50cf5c8564c176f7` on 2026-10-10. Its maintained
[kernel package](https://github.com/cjdell/gemini-nixos/blob/6a27937b525fe3a6db765ffb50cf5c8564c176f7/devices/planet-geminipda/kernel/default.nix)
is based on upstream 6.6. Its [configuration](https://github.com/cjdell/gemini-nixos/blob/6a27937b525fe3a6db765ffb50cf5c8564c176f7/devices/planet-geminipda/kernel/config)
disables `CONFIG_MEDIA_SUPPORT` and the MediaTek video codec drivers; its tracked
kernel delta contains no `drivers/media` files. It does not supply the native
video implementation needed here.

Its [Mesa 26.2.2 polygon-list patch](https://github.com/cjdell/gemini-nixos/blob/6a27937b525fe3a6db765ffb50cf5c8564c176f7/patches/mesa-panfrost-polygon-list-26.2.2.patch)
is a useful public lead for Mali-T880 geometry corruption: it maps the tiler
polygon list for CPU access and clears the entire list before reuse. Our current
Mesa package does not carry that patch. This observation has not been reproduced
or qualified on our board, and no code has been imported from that project. Its GNOME keyboard registry
work also highlighted the need to register our existing layout in the XKB XML
registry. Our independent implementation resolves `gemini+us` through
libxkbregistry and matches all 416 captured key combinations in the host check.

The completed platform trial and strict recovery audit are recorded in
[`kernel-7.2.9.json`](kernel-7.2.9.json), including exact source, configuration,
image, module and candidate-system identities. The supervisor and subsequent
board audit both exited successfully before this result was recorded. This
trial uses the direct Linux boot path; it does not requalify the U-Boot/EFI menu
path or the media modules.
