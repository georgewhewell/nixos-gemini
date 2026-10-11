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

The [installed accepted image](accepted-baseline.json) is trial 101, kernel
source `8b9fa390ad32d61d2661b8719ae76a5fe6232abd`.
Its [integration proof](gnss-integration-20261011.json) and independent
terminal audit pass native GNSS registration and two bounded LNA power cycles,
GNOME RFKILL visibility, directed NetworkManager scanning, RAM-only paging,
retained storage and ordinary Nix builds. Onboard stereo mapping retains
unchanged-input trial 98 evidence. Normal
NetworkManager association and traffic over wlan0 retain trial 95 evidence;
Bluetooth discovery retains trial 94 evidence with unchanged radio inputs. Selecting another
SSID, Bluetooth pairing/profiles and audible orientation remain unqualified.
RTC and GPU results retain their relevant unchanged-input evidence
from [trial 88](desktop-responsiveness-20261011.json); desktop updates do not
repeat RTC alarm/calendar diagnostics.

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

Installed source `6e84a8a9a31c431f9774d828a15efb90fa4d6e41` retains validated
closed-port AT frames in a bounded native FIFO. First open drains it in order;
close, failure and removal share the same receive owner. The existing regression
fixture checks the old loss, queue limits and concurrent lifetime transitions.
GCC 15 ASan/UBSan, strict ARM64 compilation and the normal kernel build pass with
unchanged configuration. The fresh trial 101 metadata observes 56 of 56 AT
frames delivered, with zero closed-port drops versus two in trial 98. The modem
still fails at 106 seconds and ModemManager exposes no SIM object; corrected
receive ownership is not a SIM/watchdog fix. The
[modem record](desktop-radio-activation-20261011.json) preserves both results.

This combined image also installs native MMC0 pad ownership and the current-
demand check before CPU parking removes a core. Storage retention passes with
legacy timing; faster eMMC modes are not enabled. Sampled idle activity still
shows parking and udev overhead; UI responsiveness remains unqualified in the
[performance record](desktop-responsiveness-20261011.json). The native PMU
candidate remains separate until its offline-CPU probe lifetime and hardware
counters are qualified; scheduling capacity ratios must be measured.

GNSS uses the existing CONSYS/STP owner and the standard Linux GNSS class.
Normal module discovery and udev loading now work. Two power cycles receive
zero bytes, so receiver initialization, framing, position and suspend remain
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

The current experimental decoder uses vb2-vmalloc capture buffers and copies
from private cached DMA surfaces. Its buffer export and close/streamoff lifetime
checks do not qualify direct decoder-to-GPU or decoder-to-display sharing.
Moving to shared hardware surfaces requires a suitable vb2 DMA allocator,
attachment mappings for the actual consuming device, compatible formats and
modifiers, explicit CPU cache access
boundaries, reference-picture lifetime, and synchronization with other devices.
Use DMA-buf, DMA reservation fences and sync files where the participating
subsystem contracts require them. A DMA-buf fd alone does not establish hardware
completion or cache coherency. Preserve the independent pixel comparisons,
error recovery, bounds and lifetime checks when changing the allocation path.
See the [upstream DMA-buf contract](https://docs.kernel.org/driver-api/dma-buf.html).

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
  decoder's private DMA cache.
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
