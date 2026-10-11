# Gemini kernel development baseline

Linux development uses one branch, `gemini-7.2.9`, based on upstream `v7.2.9`
(`5fce161649b4d779d1b76d9fcd52dc77779774b8`). Linux 7.2.9 was the latest stable
release checked against [kernel.org](https://www.kernel.org/releases.json) on
2026-10-10; mainline was 7.3-rc6. Packaging uses `master`. The default build and
development shell use locked Nixpkgs GCC 15.3.0 and binutils 2.46, with no separate
compiler pin or media kernel variant. New work uses the pinned Linux subsystem
contracts; driver fixes belong in their native owners.

The [installed accepted image](accepted-baseline.json) is trial 116, kernel
source `477538930f3d819c19a93bd27ad72f76b721979d`. Its normal ARM64 build,
1,431-ELF/124-script GNOME cross-runtime check, supervised focused deployment
and independent terminal audit pass. The audit verifies all 47 source hashes,
retained storage, an ordinary Nix build, RAM-only paging and terminal writers.
Feature acceptance and unfinished work live in [hardware status](HARDWARE_STATUS.md)
and the linked owner records; unchanged behavior retains its existing evidence.

The [cellular owner](sms-voice-integration-20261011.json) records native bounded
AT receive lifetime, fatal WWAN HUP/ERR and port removal, and zero open-count
retention after removal. The protected modem cold transaction now selects the
named SIM state: all six Linux pin claims pass with electrical encoding preserved.
The bounded public disabled-PBM DBM initializer is installed before the validated
HS1 runtime reply. The modem still reaches READY and receives its watchdog IRQ;
SIM presence, eUICC APDUs, cellular data, SMS delivery and calls remain unqualified.
CCCI framing and DMA remain kernel responsibilities. The generic AT eSIM GUI
candidate uses standard WWAN, ModemManager and lpac interfaces; packaging and
provisioning qualification remain open.

[Native MMC and performance evidence](desktop-responsiveness-20261011.json)
records MMC0 pad/supply ownership, verified 47,999,984 Hz eMMC high-speed clock,
error attribution and checked MSDC/CQHCI DMA ownership. Reset/FIFO/STOP polls
are bounded; physical controller isolation and generic CQE error propagation
remain open. Native FUSB301 event suppression and procfs CPU-prefix reading remove
measured overhead. GPU clock/voltage readbacks pass seven OPPs from 238 to 900 MHz
with normal thermal cooling and simple_ondemand policy. Native PMU counters,
measured scheduling capacities, deep idle and UI latency still need qualification.

[GNSS](../campaign/13-gps-gnss.md) uses the existing CONSYS/STP owner, standard
Linux GNSS class and standard LNA supply. Registration and two power cycles pass,
but no validated task-2 frame reaches the receiver endpoint. Public receiver
initialization, output, NMEA framing, positioning and suspend remain open.
Wi-Fi association/traffic, Bluetooth discovery and onboard audio mapping retain
their recorded scope; SSID switching, pairing/profiles and acoustic orientation
remain unqualified. Calls, Spacebar and callaudiod are cross-built and installed;
modem speech control and duplex audio lifetime remain unfinished.

Built-in IPv6, FUSE, LZ4 zram and native RTC acceptance are retained. Zswap,
zram writeback and hibernation are disabled. The [no-swap 7.1.3 fallback](baselines/boot-test-76.json)
and exact historical proofs remain preserved. Documentation cleanup needs no
hardware trial; test changed behavior and unresolved acceptance checks.

## Media interfaces

Decoder and encoder work use current V4L2, videobuf2, DMA mapping, runtime power
and supplier contracts. The firmware-free H.264 decoder uses stateless V4L2
Requests and memory-to-memory scheduling; VA-API belongs in userspace. Similar
silicon supplies public register leads requiring MT6797 validation.

The [decoder owner](mt6797-vdec-v4l2/README.md) records compound DMA-buf surfaces,
independent DPB/job references, reservation fences and per-attachment CPU/MMAP
cache transitions. Native direct-DMA SG bounce markers belong in the DMA owner;
Gemini's GPU has its own MMU. Unsupported mapping routes are rejected. Trial 106
qualifies allocation/export, mixed CREATE_BUFS lengths, Panfrost PRIME mapping
and release lifetime without codec/GPU submissions. Synthetic MM21 rendering
passes [trial 109](mt6797-vdec-v4l2/gpu-trial-109.json); image 111 installs the
shared DMA/Mesa changes in the normal desktop.

Native SYSIRQ polarity admission passes, but decoder SPI 240 still delivers no
completion interrupt in [trial 103](mt6797-vdec-v4l2/irq-trial-103.json). AVC
hardware finishes with ACTIVE clear and zero syntax error; exact source enablement
and handshake remain open. Decoded-surface rendering, encoding and suspend are
unfinished. The normal image does not load experimental codec modules. Rebuild
such modules against the exact installed kernel, exported configuration and
`Module.symvers`; retain each experimental proof's recorded inputs.

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
