# Gemini kernel development baseline

Development follows the latest stable upstream Linux APIs. As checked against
[kernel.org](https://www.kernel.org/releases.json) on 2026-10-10, that is Linux
7.2.9 (`v7.2.9`, `5fce161649b4d779d1b76d9fcd52dc77779774b8`).
Mainline is 7.3-rc6. Use mainline documentation and subsystem implementations
when designing drivers, and verify the APIs against the pinned stable source.
Update the stable base regularly; keep the pin reproducible rather than fetching
a moving branch during a build.

The 7.2.9 port is in branch `gemini-7.2.9`, with the full upstream ancestry,
854 replayed board commits and the original 11 merges. The normal kernel,
DTB and modules build successfully, and every required kernel host check passes.
The native media modules also build with strict MODPOST against the generated
7.2.9 `Module.symvers` and matching kernel configuration. The supervised normal-operation
profile passes on the device: boot identity, native RTC startup, UTC and awake
alarms, actual swap I/O and an ordinary unprivileged Nix build. The supervisor
restores the accepted 7.1.3 system, with all stored outputs retained, matching
executed sources, no remaining writer and a clean board audit. The installed
baseline remains 7.1.3. Media, suspend and hibernation proofs have not been rerun
on 7.2.9.
Previous hardware results describe their exact source, configuration and kernel;
they do not qualify a rebased kernel. Historical reproduction packages retain
their original version pins. Uncommitted allocator diagnostics in the original
kernel checkout are preserved separately and are not part of this build.

The hardware-qualified port source is `5fb8876d52f20cf79d8618c675d478633b052fc5`.
Current development pins `6a338355fefbc5ec31baee53f7ad22ca9098111c`, which
enables built-in LZ4 zram and disables both zswap and zram writeback. The new
configuration has built successfully, but has not been boot-qualified. The
older paging evidence exercised eMMC-backed swap and does not qualify zram.
The experimental `gemini-video-7.2.9` branch also uses this RAM-only policy at
`c22f516a93aee65f2a6a6741d5e7e9873d56c852`. Its kernel and all three original
media modules build with strict MODPOST, matching configuration and release
string. This is a host build result; none of these new modules has been loaded
on the device. Their identities are recorded in
[`desktop-consolidation-20261010.json`](desktop-consolidation-20261010.json).
The subsequent [decoder IRQ candidate](mt6797-vdec-v4l2/irq-build-20261010.json)
also passes ARM64 compilation with `W=1` and strict MODPOST against that media
kernel. It requires a delivered done event before accepting a picture, and
synchronizes the handler before reset or power release. This candidate has
not been loaded; previous polling results do not qualify IRQ delivery.
For recovery migration only, a [temporary no-swap rescue derivative](ram-only-recovery-20261010.json)
preserves the recorded working 7.1.3 kernel, DTB and userspace. It removes early
disk resume, disables zswap and masks swap at every boot. This image is now
the [accepted recovery](ram-only-recovery-hardware-20261010.json): two distinct
supervised boots, byte-exact writes/readbacks, boot masks, zero p34 writes,
RTC/Nix/storage checks and an independent terminal audit pass. Its paging
policy is accurately recorded as `none`. The normal development base remains
the current 7.2.9 zram system; its changed paging policy needs its first device
qualification. The accepted recovery does not need another baseline trial.
The rebase keeps upstream's new DSI pre-enable ordering, optional Panfrost ACE
clock ownership and native CPU hotplug code. Board followups adapt the renamed
CNP capability, add the codec's required `#sound-dai-cells`, and expand the
GPULDO host fixture to cover both optional clocks and every acquisition failure.
The maintained package exports its generated `Module.symvers` for external
module builds and verifies the upstream version against its declared version.

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
