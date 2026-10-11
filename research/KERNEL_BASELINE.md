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

The [installed accepted image](accepted-baseline.json) is trial 95, kernel
source `9d8ecc3776f0c0705173149446c66ea417d700e7`.
Its [desktop proof](desktop-radio-activation-20261011.json) and independent
terminal audit pass GNOME RFKILL visibility, bounded Bluetooth discovery as
the desktop user, directed NetworkManager scanning, effective onboard stereo
mapping, RAM-only paging, retained storage and ordinary Nix builds. Normal
NetworkManager association and traffic over wlan0 also pass. Selecting another
SSID, Bluetooth pairing/profiles and audible orientation remain unqualified. RTC and GPU results retain their relevant unchanged-input evidence
from [trial 88](desktop-responsiveness-20261011.json); desktop updates do not
repeat RTC alarm/calendar diagnostics.

This revision admits
current supplicant userspace capability flags and station joins to cached
passive-channel APs. Its real-callback tests use the kernel's native flag enums
and are required by the normal kernel build. Native modem bring-up remains
incomplete: a fresh boot reaches HS2, then receives a modem watchdog interrupt
at 107 seconds before any SIM diagnostic. SIM/eSIM and cellular data are not
qualified.
The installed platform retains built-in IPv6, FUSE, LZ4 zram, decoder resources,
GPU DVFS and native thermal cooling. Zswap, zram writeback and hibernation are
disabled. The [no-swap 7.1.3 fallback](baselines/boot-test-76.json) remains preserved;
historical packages and their exact proofs are separate from current development.

The kernel exports its generated configuration and `Module.symvers` for strict
external-module builds. Experimental media modules must be rebuilt against the
exact installed kernel and toolchain. [Decoder trials 89–90](mt6797-vdec-v4l2/irq-trial-90.json)
used the recorded trial-88 build: both timed out with zero delivered decoder
interrupts, then passed quiescence, unload, recovery and terminal audits.
No successful frame was exported. Media hardware completion, shared surfaces,
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
