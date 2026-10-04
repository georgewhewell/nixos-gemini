# Gemini U-Boot qualification, 2026-10-04

Status: software reset and 31-second watchdog expiry are hardware-qualified
after removing an unmapped framebuffer probe. Both automatically recovered
fully healthy M69 through mtkclient. Two plain Linux handoff/rescue cycles and
one corrected EFI-application/FIT handoff cycle also passed. The corrected
EFI Linux profile passed full service health, ExitBootServices, the full
4 GiB EFI memory map and automatic M69 rescue in trial 04. GOP, keyboard,
storage and a boot manager remain unfinished.
These profiles are based on the later U-Boot
worktree, not the September 4 WIP branch.

## Profiles

Build from this flake with `nix build .#ubootHandoffBundle`,
`.#ubootEfiSmokeBundle`, `.#ubootResetBundle`, or `.#ubootWatchdogBundle`.
Those four carriers embed the same M69 kernel, initramfs and DTB as
`mainlineNixosBundle`, with the same existing squashfs. The full artifact
manifest records payload and carrier hashes.

- Handoff: preserve LK's dynamic RAM/modem device tree and boot the checked FIT.
  Linux must expose `/chosen/gemini,uboot-handoff = "fit"`.
- EFI smoke: additionally require EFI hello entry/return and the separate
  `/chosen/gemini,uefi-hello-result = "passed"` property. This is not EFI Linux boot.
- Reset: invoke the generic reset dispatch before EFI or FIT processing.
- Watchdog: stop at WFI after arming the watchdog; there are no software kicks.
  A physical reset during this test does not prove watchdog expiry works.
- EFI Linux (`ubootEfiLinuxBundle`): a separate EFI-enabled kernel, matching
  modules/userspace, and the accepted LK carrier DT with CPU provenance
  rebound to the EFI kernel. It uses `os = "efi"`
  in the checked FIT and U-Boot's existing EFI LoadImage/LoadFile2 path.
  It requires a new, content-addressed squashfs; it cannot reuse M69's
  non-EFI kernel modules. `/chosen/gemini,uboot-handoff = "efi"` alone is
  insufficient: the runner checks Linux's EFI system table and full memory
  map as well as ordinary service health and LK reservations.

All profiles use TOPRGU for generic reset. LK handoff validation is independent
of EFI. The FIT source window now accepts up to 16 MiB at 0x45000000, within the
existing 96 MiB mapping; the independent 16 MiB p22 packaging limit still applies.
M69's payload exceeds the old 8 MiB FIT limit. Retired unreachable USB/trace
code and assembly probes were removed. Live early framebuffer probes and the
historical SError-mask diagnostic remain and need review before consolidation
into a production bootloader.

## Validation and hardware sequence

Host checks exercise the actual LK-tree validator with libfdt, malformed and
oversized trees, >8 MiB FITs, EFI failure/stale state, command ordering, reset
isolation, and bootm-return resets. Cross builds check the AArch64 image/EFI
headers, generic reset dispatch, watchdog WFI, config, and exact FIT extraction.
These checks do not prove hardware watchdog recovery or Linux handoff.

First qualify software reset and watchdog expiry with a supervised rescue
transaction and a person at the device. Then boot M69 through the plain
handoff, verify both new boot identity and the Linux-visible marker, LK RAM and
modem reservations, and full M69 health. Repeat boots before adding the EFI
smoke test. EFI Linux/ExitBootServices now has a separate qualification below;
GOP, keyboard, storage and a boot manager remain.

The mtkclient candidate/rescue supervisor now has a hardware-qualified M69
baseline (`handoff/mtkclient-supervisor-baseline-02`); both writes, readbacks,
USB reboot sequences and final full service health passed. Run
`python3 tools/qualify-uboot-recovery.py --profile reset --out NEW_DIRECTORY`
for read-only preflight; `--execute` starts the pinned reset carrier with the
durable M69 rescue supervisor already waiting. `--profile watchdog` selects
the independent expiry carrier. The runner's recovery result deliberately
does not equate a preloader return with proof of U-Boot execution.

The September 9 carrier flashed but no Linux or later reset was observed;
its failure boundary is unknown. The later panic/reset fix was never deployed.
Do not reuse that trial's M37 payload or stale device guard.

## Original carriers and first hardware trials

| Flake output | p22 SHA-256 |
|---|---|
| `ubootHandoffBundle` | `64d899b7cf22d1d63a0ee8ef86cabfda5b60dbd7ae3cd17ce12ea9ad68c14fca` |
| `ubootEfiSmokeBundle` | `83243cfd35910819e01fff9df8a748af38d05ba61f58462e953e8d5ce89888b4` |
| `ubootResetBundle` | `a63157a63b6c77c0db610900340e36792e6f47ae36c6a9b85daa6b1be0ff0ed9` |
| `ubootWatchdogBundle` | `25d0c8449562bad3291ef17315d3f788991a85303f74051e837ee58c6f4bdf3f` |

Artifacts and logs are rooted in the workspace `handoff/uboot-m69*` and
`handoff/boot-consolidation-build.log`. The accepted direct-Linux M69 p22 hash is
`913eb41721a1a5862fb47a1387fce535f715bca5c1c951554395100a6c762ee3`.

The original source revision is `77c8387ae485f3c76e508bce83e82ec892ee9ec0`.
The reset trial (`handoff/uboot-reset-mtkclient-01`) returned to preloader
13.792 seconds after the first post-flash preloader departed. The watchdog
trial (`handoff/uboot-watchdog-mtkclient-01`) returned in 9.050 seconds,
shorter than its programmed 31-second wait. Both candidate and rescue images
had acknowledged writes and complete verified readbacks. Final M69 health
and GPT/p22/p30/p31 checks passed without physical recovery. These are rescue
path passes, not proof that either intended U-Boot test branch was reached.

Investigation found the watchdog setup readback compared the low write-key
bits against the written value. M69's recorded LK handoff has WDT_LENGTH
`0x5000`, with no `0x8` write key. U-Boot would reject an otherwise correct
timer readback without that key and reset at `GEMINI_PHASE_WDT_FAILURE`,
before either test branch. This is a plausible cause, not yet a measured
phase: `/dev/mem` is absent in M69, so the retained phase register could not
be read after rescue. The source fix `0fd3dad965c4ed586e43dcec95facae42b740a00`
compares only the timer field. Its production-function regression reproduces
the old failure, accepts key-present/key-absent readbacks, and rejects incorrect
timer, enable, auto-restart, IRQ and dual-mode values.

All four corrected carriers cross-built successfully with that regression
included in each build. They are rooted at `handoff/uboot-m69-wdt-readback*`;
log: `handoff/uboot-wdt-readback-build.log`. The earlier qualification runner pinned
these corrected reset/watchdog hashes:

| Profile | Corrected p22 SHA-256 |
|---|---|
| Handoff | `d1a71f14cd36730d690b608ccfa9c68d548541db8f019e71ae1a8f238e276589` |
| EFI smoke | `a282352804bad1df2128ab66ab24848c138dd57bd4f6ce63336354058d21a75a` |
| Reset | `9da4d1d570fd864b6a6f65012516e532644088cfdae488e720d03532cc08dc65` |
| Watchdog | `1dd22447fc113180a30cefc368d5091f7df64046960537880d73775959e38016` |

The corrected watchdog trial (`handoff/uboot-watchdog-mtkclient-02`) also
recovered healthy M69, boot ID `3c53798b-adfa-42ec-a540-5b68f97e6e3f`, but its
return was 9.044 seconds. The key-readback correction therefore does not
resolve the observed early return. Do not promote this result to watchdog
qualification or proceed on the assumption that `board_late_init` was reached.

## Confirmed failure interval

The read-only phase operation qualified in `handoff/mtkclient-phase-read-01`.
The next identical corrected-watchdog trial,
`handoff/uboot-watchdog-mtkclient-03`, captured `0x00000000` before writing the
candidate and `0x474d10e3` at rescue, before restoring M69. The fresh marker
proves U-Boot executed `board_init`; the failure occurs before
`board_late_init`, whose first action writes a different marker. Retention
through the direct preloader/DA rescue path is now observed on hardware.
It returned in 9.069 seconds and recovered fully healthy M69, boot ID
`833c472e-c6bd-42cd-9e40-7b2f192ad8da`, with unchanged GPT and all three boot
partitions. No physical recovery was needed.

The original runner result only reports recovery and was started before phase
decoding was added. `phase-analysis.json` records the additional execution
proof without overwriting that original result. Future runs decode only a
known marker that differs from the pre-candidate value; missing, stale and
unknown values cannot prove execution. Reaching `board_init` does not qualify
the later reset/watchdog test branches.

## Framebuffer fault fixed; reset and watchdog qualified

Source review found `gemini_r_band()` writing the framebuffer at `0x7dfb0000`
around `console_init_r`, after `initr_caches()` had enabled the MMU. That
address lies outside both the 96 MiB DDR mapping and the MMIO mapping.
U-Boot revision `285fb4088dbf7aaa0a2abb75202b97a4d55b666b` removes the helper
and its two calls. All four carriers cross-built and passed the existing
production-function, LK FDT, FIT extraction and AArch64 layout checks.
Artifacts: `handoff/uboot-m69-fbfix*`; log: `handoff/uboot-fbfix-build.log`.

| Profile | Framebuffer-fix p22 SHA-256 |
|---|---|
| Handoff | `365ac36a96e095a93e0b7071241c4569f5e052164bd8de8bf793dbbd4bd9ff8c` |
| EFI smoke | `3c7c408e72e745912246fa8993f062430b8ca01cb7c8008645beb024a93bfd95` |
| Reset | `e9e0f6f2f44c28d98424420444c9f3466fa593adfe7f5d38c66652c349e8e950` |
| Watchdog | `5f02a4db11c14fdd604626b48fdd71886db9d90ff699c936d397800a4278c66d` |

The watchdog trial (`handoff/uboot-watchdog-fbfix-01`) captured fresh phase
`0x474d10ed`, proving entry into the no-kick WFI branch. Preloader returned
after 40.110 seconds, consistent with the 31-second watchdog plus startup
overhead. Automatic rescue produced healthy M69 boot
`886f161d-ab6b-4395-8626-2ce854be4fea`.

The software-reset trial (`handoff/uboot-reset-fbfix-01`) captured fresh phase
`0x474d10ec` and returned after 9.064 seconds, before the armed watchdog could
expire. Rescue produced healthy M69 boot `56273f52-f246-4058-8f52-fc0d26eaf56f`.
Both trials verified complete candidate/rescue writes and readbacks, unchanged
GPT/p22/p30/p31 after recovery, and full M69 service health. Neither required
physical intervention. `profile_qualified=true` requires the intended fresh
marker and the appropriate timing window; a recovery pass alone is insufficient.

The runner also supports `--profile handoff` and `--profile efi-smoke`. It
requires the exact pinned carrier in p22, the accepted M69 system and full
health, a new boot identity, the expected Linux-visible markers, the full
4 GiB RAM bank, the complete modem table, and unchanged LK reservations.
LK's low-bank dummy-read allocation window may move after the larger FIT
ramdisk, but must remain within low RAM. After observation it reboots the
identified candidate into the already waiting M69 rescue. These profiles do
not permanently accept a carrier. The M69 kernel's forced command line
retains its existing baseline health capability.

## Repeated Linux handoff

`handoff/uboot-handoff-fbfix-01` booted the exact handoff carrier into healthy
M69, boot ID `2534bdc5-fdeb-41fa-aeb5-7cd234312097`. Linux exposed
`/chosen/gemini,uboot-handoff=fit`; the 4 GiB RAM bank, complete 48-byte modem
table and LK reservations matched the direct-Linux baseline. Usable memory
was 3,784,496 KiB versus 3,784,500 KiB on direct M69. The expected dummy-read
allocation range began at `0x458fc000` after the larger FIT ramdisk instead of
`0x45259000` after the direct-Linux initramfs; its upper bound was unchanged.

The runner then rebooted into its waiting rescue writer. Full accepted M69
health returned as boot `caaedcf2-65c5-4872-9131-fed97f1ad29d`, with unchanged
GPT/p22/p30/p31. The rescue phase was `0x474d10e9`, written by
`armv8_switch_to_el2_prep` immediately before Linux entry. The initial result's
decoder did not yet name that value; the recorded Linux marker and full
candidate health independently prove the handoff.

The repeat (`handoff/uboot-handoff-fbfix-02`) independently reached healthy
candidate boot `ae0f8752-733f-403c-8b92-2705f8f39ab3` with identical handoff
and LK-tree checks, then restored healthy direct M69 boot
`fdea5023-c884-46e8-af74-06d3574819cb`. GPT and all boot partitions matched.
It also captured the raw Linux FDT and kernel log. Linux's watchdog probe
recorded inherited length `0x0000f800` and a running 31-second watchdog, and
the modem probe validated the LK descriptor and reserved regions.

M69 currently has `CONFIG_EFI` disabled. The EFI smoke profile exercises an
EFI application before the qualified FIT handoff; EFI Linux and
ExitBootServices still require a separate kernel/profile qualification.

## Initial EFI smoke failure and initialization order

`handoff/uboot-efi-smoke-fbfix-01` returned after 9.125 seconds with fresh
phase `0x474d1e01`: `bootefi hello` returned command status 1. This proves
the attempted command failed, not that the EFI application was entered.
Automatic rescue restored healthy M69 boot
`46485bd2-b360-4398-9300-06da9d5fe97c`, with unchanged GPT and boot partitions.
The original decoder did not name this phase; `phase-analysis-v2.json`
adds its interpretation without modifying the original result.

Source review identified an ordering fault: `board_late_init` runs before
`EVT_LAST_STAGE_INIT`, where `install_smbios_table` sets `gd->arch.smbios_start`.
The EFI profile enables SMBIOS, so its earlier `efi_init_obj_list` calls
`efi_smbios_register` with no installed table and returns `EFI_NOT_FOUND`.
The retained command status could not distinguish this error from another
EFI failure; the subsequent corrected trial below establishes the outcome.

Revision `71c1f7044f20a60379c48dafcf8f5281c4bd8f0f` defers the EFI payload
dispatcher to `EVT_MAIN_LOOP`, after all last-stage handlers and before
autoboot or USB. Plain handoff and recovery profiles retain their earlier
dispatch. The host regression executes the production wrapper and actual
event binding, rejecting EFI execution before the last stage while retaining
the existing reset/failure-path checks.

All four updated carriers passed their cross-build checks at
`handoff/uboot-m69-efi-order*` (log: `handoff/uboot-efi-order-build.log`).
The plain handoff, reset and watchdog carriers are byte-for-byte identical
to their qualified framebuffer-fix images. Only EFI smoke changed, to p22
SHA-256 `3ab7a708611fa221e2f875b1d5a7a7f7041c2874e2ef6f4cca8e8714ac1d7e74`.
The linked EFI map contains both the last-stage SMBIOS handler and the
main-loop payload handler. The runner pins these updated artifact roots.

## Corrected EFI smoke passed

`handoff/uboot-efi-smoke-order-01` reached healthy candidate M69 boot
`4decc2d8-bdf9-4834-8e7c-0a27fcb91daf` with both Linux-visible properties:
`gemini,uefi-hello-result=passed` and `gemini,uboot-handoff=fit`. This proves
successful EFI application entry/return followed by the FIT Linux handoff.
The full M69 system and service checks passed, GPT/p30/p31 matched, and the
4 GiB RAM bank, complete modem table and LK reservations were preserved.
Usable RAM matched direct M69 at 3,784,500 KiB. The raw Linux FDT and kernel
log are archived with the trial.

The runner then restored the exact accepted direct-Linux p22 image through
its waiting mtkclient supervisor. Final healthy M69 boot was
`7f567308-9b27-4719-af29-edf5c6f8496e`; GPT/p22/p30/p31 matched and no physical
recovery was needed. The retained `os_jump` phase was `0x474d10e9`.
The trial reports `profile_qualified=true`. This is one EFI-application
smoke pass, not EFI Linux/ExitBootServices, GOP, input, storage or boot-manager
qualification.

## EFI Linux profile and first trial

U-Boot source `a7dc70fbae4b854d9a6135f24260894e8d5ae5cc` adds a separate
EFI Linux profile after `EVT_LAST_STAGE_INIT`. The board validates every
static LK reservation before changing the EFI map. It preserves the existing
low-bank EFI allocations and runtime descriptors, and reports RAM outside
`0x40001000..0x43fff000` as boot-services data. EFI cannot allocate that
unmapped upper RAM; Linux reclaims it after exit and applies the DT reserves.
No-map regions remain EFI reserved memory. Malformed, overflowing and
firmware-overlapping ranges fail closed. Dynamic size-only reservations
remain Linux's responsibility.

A configurable minimum PE allocation alignment supplies the kernel's 2 MiB
alignment, avoiding a second kernel relocation in the small firmware bank.
The EFI profile reserves a 4 MiB stack. The exit event only kicks TOPRGU and
records phase `0x474d10ee`; it neither allocates nor changes the memory map.
That phase proves the callback ran, not that the entire exit or Linux boot
completed.

The new kernel fragment enables EFI/EFI_STUB separately from M69 and binds
the changed config to its module provenance. `efi=debug` records the actual
EFI map. The default `mainlineNixosBundle` still evaluates to
`/nix/store/92140xp096mcjqp6laid183r1cw2ky95-gemini-mainline-nixos-bundle`.
Stage 1 can convert the existing persistent OpenSSH host key into a private
RAM-only Dropbear key. Conversion was checked on M69; the provisioning SSH
retains strict host-key checking. The unique-file upload requires the exact
candidate boot/GPT, EFI handoff, journal-enabled p29 mount, SHA-256 and size;
it preserves and verifies the accepted M69 squashfs.

Host validation includes the production EFI map code against libfdt and the
captured LK reservations, injected map/event failures, low firmware bank
preservation, every reg tuple, and the exit callback. The archived Linux DT
contains one later bootm initrd memreserve; the test identifies that exact
addition and removes it before testing the pre-boot LK contract. All five
profiles cross-built. Plain handoff, reset and watchdog carriers remain
byte-identical to their qualified artifacts. The rebuilt EFI-smoke carrier
has a different hash and is not newly qualified; its runner still pins the
previous qualified artifact.

Trial `handoff/uboot-efi-linux-01` used carrier SHA-256
`9a2c6bc2142831dfb348a6b20d7c6ebd354a557547215318bed69260288681ff`.
It reached fresh phase `0x474d10ee`, exposed a Linux USB gadget, and returned
to preloader after 63.408 seconds without reachable Stage 1. No userspace
file was uploaded. Automatic candidate/rescue writes and full readbacks
passed, restoring healthy M69 boot
`1b8ceb4c-91a9-4981-9154-ef2d4d33c9e2` with unchanged GPT/p22/p30/p31.
The EFI Linux profile did not qualify. No physical recovery was needed.

M69's subsequent pstore was empty and reported invalid retained buffers.
The EFI pstore backend registers after ramoops, so registration order does
not explain the loss. A separate read-only DA trial,
`handoff/mtkclient-ramoops-read-01`, captured the fixed 896 KiB region before
flash access and recovered a valid console ring including M69's shutdown.
It returned healthy M69 in 195.1 seconds, boot ID
`de63a924-392f-45ab-8a25-51e2a35fc4e0`, without eMMC writes. The runner now
captures that region before flash reads/writes; `tools/parse-gemini-ramoops.py`
decodes its checked record/console rings. Recovery after flashing cannot be
relied on to retain that diagnostic RAM.

The identical candidate repeated in `handoff/uboot-efi-linux-02` with the
qualified RAM capture ahead of flash access. Its console proves Linux ran
through device initialization and panicked at 48.280 seconds with
`VFS: Unable to mount root fs on unknown-block(0,0)`. It rebooted after its
five-second panic timeout; preloader elapsed time was 63.452 seconds.
Automatic rescue returned healthy M69 boot
`983b67c5-066d-486b-bb9a-4947d3ce9bd4`; all partition guards passed.

Source inspection identified inherited LK `/chosen/linux,initrd-start/end`
as an initrd-authority bug. LK points these at the Android ramdisk, which is
now the outer FIT. The native Linux bootm prep replaces them, whereas EFI
calls `image_setup_libfdt` with empty image metadata and retains them. This
Linux EFI stub supplies its initrd through a configuration table, which the
kernel only consumes if DT has not already supplied a nonzero initrd size.
U-Boot fix `7f1d75237b1ac4e8fff042f6462447c0f09aee93` removes those two
carrier properties only in the EFI profile. The production libfdt regression
covers both stale properties and their absence.

Trial `handoff/uboot-efi-linux-03`, carrier SHA-256
`21f241cad055439b7a3715d654a9ffa9bc3accf78177d588906c122f3f93c6fb`,
confirmed the initrd correction: trusted Stage 1 SSH returned, the unique
426,971,136-byte EFI squashfs was installed and verified, and Stage 2 booted.
The accepted M69 squashfs was verified before and after the upload. Linux
reported the EFI INITRD configuration table without the stale DT properties,
the complete 4 GiB EFI map, preserved LK reservations, and 3,783,752 KiB
usable RAM. `stage1-evidence/` contains that proof.

This trial failed service-health qualification because its composed DT still
carried M69's old kernel identity. Linux rejected the config/build-ID/command
line binding and CPU8 admission returned EAGAIN before a power transaction.
The A72 health gate was retained. The runner restored healthy M69 boot
`29374ab3-2f9d-4e7c-b385-932a9084f179`; GPT/p22/p30/p31 all matched.

`nix/mainline-efi-dtb.nix` regenerates only the provenance leaf using the
existing package-owned generator and the actual EFI kernel. Build assertions
require all three runtime identities to change and every other DT property,
node and header reservation to remain identical. The kernel, initramfs and
userspace are unchanged. The corrected carrier at
`handoff/uboot-efi-provenance-fix` has SHA-256
`c00f0a9dcc0f776184e4c34678e9de54a1619bbe5ede12db71a6ff9c1891c0bc`.
The EFI runner additionally requires the kernel's runtime-binding and
late-CPU readiness messages, alongside normal service health.

## Healthy EFI Linux and automatic rescue

Trial `handoff/uboot-efi-linux-04` booted the corrected carrier into healthy
EFI Linux, boot ID `10e17099-fe8d-4f60-9409-c280f6c956b6`. The kernel verified
its runtime identity and readiness before A72 admission. CPU8 and CPU9 both
started under the existing power checks, and all ten CPUs were online. The
normal desktop, GPU, JPEG, Wi-Fi and audio health checks passed with no failed
units. No additional userspace upload was necessary.

Linux initialized U-Boot EFI v2.11 and its INITRD table, and published all
40 EFI descriptors covering exactly 4,294,967,296 bytes. It retained the
complete LK modem table and reservations, reported 3,783,752 KiB usable RAM,
and lacked both stale LK initrd properties. The runtime-binding and EFI
evidence, complete dmesg and raw FDT are retained in the trial directory.

The runner then requested rescue. Preloader returned 202.105 seconds after
the candidate's initial boot departure, and the DA captured fresh exit-event
phase `0x474d10ee`. Automatic rescue restored healthy direct M69 boot
`57d9effa-69ba-4f0f-bbc6-1c085f031b2b`. Both full image readbacks and all
GPT/p22/p30/p31 guards passed. The result is `profile_qualified=true`;
M69 remains the persistent boot image.
