# M37 accelerated desktop

Accepted September 9, 2026 after a supervised repeat boot. The session runs
Weston 16 with the existing Mesa 26.2.1 Panfrost driver on Mali-T880 MC4 and
mediatek-drm. A locked normal user `gemini` owns the compositor and terminal;
seatd grants VT, DRM and input access.

## Allocation and session changes

M36's initial seatd command used an unsupported `-s` option. Correcting that
command diagnostically initialized the GL renderer, but the first scanout
failed with `EGL_BAD_ALLOC`; no frames were presented. Console and GPU shutdown
restored correctly.

M37 uses seatd's default `/run/seatd.sock` and `-g video`. It increases the
kernel CMA reservation from 32 to 64 MiB. The retained fbcon allocation is
9,334,784 bytes; three 64-byte-pitch-aligned 1088×2160×32 scanout allocations need
another 28,200,960 bytes. Those allocations alone exceed32 MiB.

`nix/desktop-buffer-check.c` opens the verified mediatek KMS and Panfrost render
nodes, allocates three buffers concurrently, exports each DMA-BUF and imports
it into Panfrost, then releases every imported and original handle. It performs
no modeset or GPU submission and has a 15-second deadline. Each compositor
start must pass this check first. The hardware returned pitch 4352 and size
9,400,320 per buffer on both starts. The64 MiB reservation resolved the observed
presentation failure in this candidate; the separate allocation/import evidence
also distinguishes those stages from rendering.

The service preserves its runtime directory after failure and removes its
three known log files before a new start. Startup failures therefore retain
useful evidence without allowing a prior attempt's result to stand in for a
new one. The session lets Mesa detect mediatek-drm and use its KMS bridge to
Panfrost; it does not force the Panfrost loader onto the KMS descriptor.

## Qualification

`nix/desktop-qualify.sh` performs two complete session starts. Each must show:

- Native DSI-1 mode 1080×2160, scale 2, transform 3, keyboard/touch capabilities.
- Three progressing presentation timestamps and VSync sequence numbers.
- Mali-T880 Panfrost renderer identity, GPU job interrupt progress, and a live
  normal-user terminal in the desktop service cgroup.
- Three concurrent scanout allocations and successful PRIME imports.

Between starts it stops Weston/seatd, requires tty1, checks the fbcon scanout,
and verifies all six MFG power domains are off. The second desktop stays active
on tty7. Device baseline acceptance depends on this qualification, together with
the existing CPU, watchdog, cellular, connectivity and audio checks.

The first M37 boot passed these tests, but its inherited host validator still
required tty1 to be active. That transaction was recovered to rescue after a
health-guarded normal reboot; its host acceptance marker was never overridden.
Both host validators were corrected to require tty7 plus boot-bound desktop
evidence and a live normal-user terminal, retaining tty1 root-shell readiness.
All corrected checks passed read-only before a fresh transaction reused the
same candidate.

The accepted repeat boot completed presentations at 158.47 s and 161.09 s with
flags 0x7 and 17,514,055 ns refresh. GPU job interrupt progress was 20 then 19. The
supervisor accepted at 10:36:28 Europe/Zurich; the host transaction exited 0 at
10:36:33. Full post-acceptance health passed at 306.13 s, including all seven guarded
partition hashes. No recovery scanner remained and both flash locks were free.

## Provenance

| Item | Accepted value |
|---|---|
| Nix source | `50ea6f0fc8861be4961b4a6b6af19152fa4cddba` |
| Kernel source | `fd7a602f2b93019df96b0df8624cc0fd4102d3d2` |
| Boot ID | `110776b5-12a2-4812-bfb8-2a5b95b27f1a` |
| p22 SHA256 | `af6e46734329cb0164ca1b4ab30b97d24ecf93591fe018ced1b3b2bef2d52451` |
| Store SHA256 | `f983181e0c26995079d59b8575804d0ee96385af90ec3970eebcecb7d6e24c35` |
| Store size | `392548352` bytes |
| Host transaction | `p22-recovery-20260909-103153-2255200` |

The accepted Nix worktree is `repo-integration-m37` and kernel worktree is
`linux-gemini-integration-m36` in the bring-up workspace. Documentation changes
may follow this source revision without changing the accepted build pin.
Hardware logs are under `handoff/m37-oneboot-r2/`; build/configuration evidence
is under `handoff/m37-desktop/`. The resolved M37 kernel configuration differs
from M36 only in its milestone token and CMA size. Kernel source also contains
the previously reviewed read-only Wi-Fi TX instrumentation relative to M35.

Host checks built the buffer helper for native and AArch64 targets with
`-Wall -Wextra -Werror`; invalid arguments, missing devices and non-DRM
identities were rejected. Native Weston/protocol fixtures and the Mesa
KMS/Panfrost capability checks passed. Device tests supply the actual DRM,
PRIME, Panfrost, presentation and shutdown evidence.

## Limits

Presentation feedback is not a physical visual inspection. The touchscreen
calibration reverses the kernel's swap/invert normalization before Weston
applies its output transform; actual alignment remains unobserved. Keyboard
capability and terminal process checks do not prove physical key presses.
Audio stream/routing qualification does not prove audibility. User home and
font caches remain volatile. Wi-Fi measurements must report the running desktop
as an additional workload relative to M35. Suspend, complete power policy,
eSIM service and UEFI remain separate unfinished work.

## Wi-Fi measurement after acceptance

All six workload intervals and 12 diagnostic boundary snapshots completed.
Three uploads delivered 17.177–17.491 Mbit/s with 78.678–79.687 ms mean loaded
RTT to the workstation. Mean driver queue residence was 26.889–27.268 ms;
mean send duration was 0.634–0.645 ms. Credit waits are included in send
duration, so those intervals must not be added together. No send failures,
purges or credit timeouts occurred. Download delivered 18.979 Mbit/s with
9.076 ms mean loaded RTT.

These measurements localize substantial waiting to the driver's queue but do
not account for firmware occupancy, airtime or every part of end-to-end RTT.
Median upload loaded RTT remained close to M35; RF, AP/server load and the new
desktop workload prevent attributing small changes to one implementation
change. Final exact device health passed at 511.99 s; no iperf/ping clients
remained at 553.32 s. The device was released back to root. Raw evidence and
the complete report are in `handoff/m37-wifi-tx-measurement/`.
