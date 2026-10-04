# Gemini U-Boot qualification, 2026-10-04

Status: software reset and 31-second watchdog expiry are hardware-qualified
after removing an unmapped framebuffer probe. Both automatically recovered
fully healthy M69 through mtkclient. Two plain Linux handoff/rescue cycles and
one corrected EFI-application/FIT handoff cycle also passed. The corrected
EFI Linux profile passed full service health, ExitBootServices, the full
4 GiB EFI memory map and automatic M69 rescue in trials 04 and 05. The new
EFI console profile additionally passed GOP pixel/stride checks and visible
text confirmed by the owner. Native keyboard initialization and polling
also pass through EFI. Native eMMC reads now pass the full boot-partition
and filesystem hash checks below. EFI file access and a distro systemd-boot
launch now pass separate qualifications below, including selected-entry,
boot-volume and unattended menu timing evidence. A versioned Nix-enabled entry
also passes an ordinary unprivileged daemon build and persistence through M69
recovery. Loading its own device tree through EFI DT fixup also passes the
complete hardware trial, with selected CPU provenance and LK data retained.
A separate trial also boots the newer entry from a carrier containing the
older kernel and DT, proving independence for these two qualified builds.
Physical key actuation,
complete modifier qualification and normal NixOS generation updates remain.
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
- EFI manager (`ubootEfiManagerBundle`): start the pinned distro systemd-boot
  from p29 through the native read-only filesystem after the existing console,
  keyboard and storage checks. The checked FIT remains a fallback. A fallback
  boot does not qualify the manager profile; the runner also requires the
  manager's EFI variables, selected entry, p29 device identity and menu timing.
- Nix EFI provisioning/manager (`ubootEfiNixProvisionBundle`,
  `ubootEfiNixManagerBundle`): use the ordinary-build-qualified kernel and
  userspace from `mainlineNixosNixBundle`. `geminiNixEfiBootFiles` emits a
  content-addressed entry. The provisioning profile switches the precisely
  pinned previous default only after preserving its configuration and publishing
  the new payload; the manager profile requires that exact entry's EFI evidence.
  Both require an unprivileged ordinary daemon build and its retention through
  M69 recovery. The runner names are `efi-nix-provision` and `efi-nix-manager`.

All profiles use TOPRGU for generic reset. LK handoff validation is independent
of EFI. The FIT source window now accepts up to 16 MiB at 0x45000000, within the
existing 96 MiB mapping; the independent 16 MiB p22 packaging limit still applies.
M69's payload exceeds the old 8 MiB FIT limit. Retired unreachable USB/trace
code and assembly probes were removed. The console revision also removes the remaining early framebuffer probes
and diagnostic delays, and restores normal SError delivery.

## Validation and hardware sequence

Host checks exercise the actual LK-tree validator with libfdt, malformed and
oversized trees, >8 MiB FITs, EFI failure/stale state, command ordering, reset
isolation, and bootm-return resets. Cross builds check the AArch64 image/EFI
headers, generic reset dispatch, watchdog WFI, config, and exact FIT extraction.
These checks do not prove hardware watchdog recovery or Linux handoff.

Initial software-reset and watchdog-expiry trials used supervised rescue
transactions with the owner available. Repeated plain handoffs then verified
fresh boot identity, Linux-visible markers, LK RAM/modem reservations and full
M69 health. EFI application, Linux/ExitBootServices, keyboard polling, GOP,
visible text, storage and distro-manager qualifications are recorded below.
The owner authorized subsequent unattended work using automatic recovery.

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

The identical carrier repeated successfully in `handoff/uboot-efi-linux-05`.
Candidate boot `72aa37b6-5e8f-4206-8596-c7fc04e7c583` independently passed
runtime identity, both A72 starts, full service health and EFI checks. Its
40-entry EFI map and complete LK handoff tree matched trial 04 exactly.
After the planned reboot, preloader returned at 206.019 seconds and the
automatic rescue restored healthy M69 boot
`b01b9b87-d724-4f1d-9cc3-583eae64617e`. Candidate/rescue full readbacks,
fresh exit-event phase, GPT and all boot-partition checks passed again.
Neither successful trial needed physical recovery. `repeat-comparison.json`
records the independent boot identities and matching evidence.


## EFI display and diagnostic cleanup

The cleanup carrier at `handoff/uboot-no-debug`, SHA-256
`1d463996c9506cff718f83ff3e702e68240dbcfb90aea1f6425d747bdc2f2c7e`,
removes the C framebuffer probes and diagnostic holds and restores normal
SError delivery (U-Boot `bf3ec50be3cb9bde934c173c32f51802d64c8f0f`).
Trial `handoff/uboot-efi-no-debug-01` passed full EFI Linux health as boot
`6fff14ba-8d81-457e-a86b-813accd80030`, then automatically recovered healthy
M69 boot `e9756611-8515-466c-8db2-121df0e320de`. This revision still had one
assembly framebuffer probe, which the following console revision removes.

U-Boot `e3ed105e8cac9e75d0ae3eb6125ba5be93b52199` adds the opt-in
`ubootEfiConsoleBundle` / `efi-console` profile. It validates LK's native
videolfb tag against its reserved framebuffer before enabling simplefb in
the U-Boot control tree. The Linux/LK tree is preserved. The EFI GOP now
uses the actual 4352-byte stride (1088 stored pixels, 1080 visible) for both
its published mode and all blit operations. The rotated text console uses
the inherited display; no panel reset or new display engine is introduced.

An embedded EFI application checks mode geometry, padded-stride blits,
readback and the corresponding raw framebuffer pixels, then shows
“Gemini UEFI console” for 12 seconds before booting Linux. The runner requires
`/chosen/gemini,uefi-console-result = "passed"` as well as ordinary EFI and
Linux health. Host tests exercise the actual GOP operations with padded
32/16-bit rows and validate good and malformed LK framebuffer descriptions;
the GOP regression also rejects the preceding implementation.

The exact console carrier at `handoff/uboot-efi-console` has SHA-256
`0b104d094c012a8c5c00e4284368c153a831b94a7e39fc4e55f50ce0fe762f3a`.
Trial `handoff/uboot-efi-console-01` passed as EFI Linux boot
`a05efe4d-6dfc-4069-99aa-e77b64022354`. The owner confirmed seeing the EFI
console: “yes i saw it! works”. Automatic rescue restored healthy M69 boot
`75f4fd80-c07f-4575-8949-55ec2a2a0a5d`. Both complete image readbacks,
fresh ExitBootServices phase, full RAM/LK reservations and all protected
partition checks passed. No physical recovery was needed. This proves the
inherited display/GOP/text path, not native display initialization, keyboard
input or a distro picker. M69 remains the persistent boot image.


## Native keyboard polling through EFI

The opt-in `ubootEfiKeyboardBundle` / `efi-keyboard` profile extends the
console profile with a native AW9523 matrix keyboard. U-Boot source
`25c2c55a` includes a FIFO-only MT6797 I2C driver, the narrow I2C5 clock/pin
lease, and a keyboard consumer. The driver reads chip ID 0x23 before
configuration, resets and verifies the expander, then polls all seven
columns and eight rows with two-scan debounce, ghost suppression and normal
U-Boot repeat/key translation. It leaves columns inactive after each scan,
including failed reads, and latches bus errors instead of spinning forever.
The bus operates at 100 kHz with the inherited 156 MHz AXI clock divided by
ten in hardware. Transfers have an eight-byte limit and a 10 ms timeout;
no AP DMA, PMIC, I2C6 or keyboard IRQ path is touched.

The compiled 52-entry keymap was compared byte-for-byte with the running
M69 device's matrix map. Both hash to
`c4704488ed3d4b617ea1476d42412575d83aa26efce539f14b0eacf39a88aaac`;
comparison evidence is `handoff/uboot-efi-keyboard-map.json`.

Host tests execute the production clock/pin lease, FIFO transactions,
AW9523 scan/debounce code and U-Boot input translator. They cover register
reads/writes, bounds, timeout/NACK/short-read failures, unrelated pin-bit
preservation, key release/repeat, arrows/Enter, Shift/Ctrl and ghost
suppression. These simulated presses do not establish physical actuation.
The complete cross build also passed the existing EFI, memory, reset,
watchdog, framebuffer and carrier checks.

The EFI application polls Simple Text Input before Linux. Qualification
requires at least 20 actual complete matrix scans and zero driver error,
with `/chosen/gemini,uefi-keyboard-result = "scanned"`; it deliberately does
not report a physical key-press test as passed. If keyboard discovery fails,
stdin remains nulldev and Linux can retain the error for recovery. The
physical Fn mapping, Alt/Meta semantics and real menu selection remain
unqualified. No Fn map exists in the currently running Linux DT.

The trial carrier at `handoff/uboot-efi-keyboard` has SHA-256
`2b66cccaba6e4fe52e2f172af09896c91ec7ad0fa4b34d79a195482e17e2e9d5`.
Trial `handoff/uboot-efi-keyboard-01` passed. Candidate EFI Linux boot
`845347b2-c7f7-4749-ba37-938e9b3e86d4` retained 1,402 complete native matrix
scans, zero keyboard errors and the successful GOP/text marker. Linux passed
full health, both A72 starts, the 40-entry EFI map and all LK reservations.
Automatic rescue restored healthy M69 boot
`8b6fd83e-f611-4545-a5eb-8c25c403c905`. Candidate/rescue writes and full
readbacks, fresh ExitBootServices phase and GPT/p22/p30/p31 guards all passed.
No physical recovery or key press was needed. This qualifies hardware
initialization and polling through EFI, not physical key actuation.

Subsequent read-only inspection found Gemian's installed
`/usr/share/X11/xkb/symbols/planet_vndr/gemini`: its `modifiers` section maps
`LWIN` to `ISO_Level3_Shift`, and the `common_keys` section maps third-level
arrows to PageUp/Home/PageDown/End. `keycodes/evdev` maps LWIN to X keycode
133, corresponding to Linux KEY_LEFTMETA (125), which is already in the
matrix at row 4, column 3. Thus the absent KEY_FN DT entry does not imply an
absent physical modifier; the source supplies a mapping to implement and
validate. Alt/Meta behavior and real menu selection are still unqualified.


The Fn follow-up is implemented at U-Boot `610657a0a5bb01c1213f76bd80d4f16a423c19ff`.
It uses the installed Gemian definitions captured under
`handoff/gemini-keyboard-source-20261004`: Fn+arrows produce
PageUp/PageDown/Home/End, Fn+Shift+1 through 0 produce F1–F10, and
Shift+Backspace produces Delete. Unsupported Fn combinations are suppressed
rather than typing their unmodified letters. The production input helper
now encodes the additional navigation keys for EFI. Host tests exercise
these combinations, including ghost/debounce/error handling; the full
cross build and carrier checks pass. Full Fn text-symbol/layout parity and
Alt/Meta behavior remain unfinished.

A later source audit confirms that the current Weston configuration explicitly
uses generic `keymap_layout=us`; the captured Gemian keyboard defaults also say
`us` without a variant. The installed `planet_vndr/gemini(us)` definitions
remain a reference for the compact keyboard's extra symbols, rather than proof
that the current desktop activates that variant. Its US variant inherits GB
common keys and overrides Fn+1/2, the apostrophe-position key and several
letters. The current U-Boot input helper has no Alt-prefix emission, although
EFI's console parser already understands an Escape prefix as Alt. Further
symbol/modifier work should test the matrix-to-EFI translation end to end,
including release, repeat and simultaneous keys, against these source files.

This follow-up is built but not separately flashed. Its carrier at
`handoff/uboot-efi-keyboard-fn` has SHA-256
`41171ae37f296acd38ad8f1b13f89faead71174b97ae945b41d37de244ddb419`. The qualification runner deliberately retains the
hardware-qualified `2b66ccca...e2e9d5` keyboard carrier. The default direct
Linux build remains M69. The subsequent read-only MMC profile below includes
this Fn follow-up and verifies MSDC0 operation and existing file bytes before
loading a distro manager.
No ESP migration or storage-layout change was performed here.


## Read-only native eMMC profile

`ubootEfiMmcBundle` / `efi-mmc` adds MSDC0 using the MT6797-compatible PIO
path and retains the display and Fn-enabled keyboard. U-Boot source
`4973bd4a2e1c6392a48f0fc3117a3cd208dff449` checks inherited pin muxes,
PLL power and source selections before taking ownership of only the two
MSDC0 clock gates. It derives both clock rates from live PLL registers,
retaining LK's mux, pad drive, pulls and supply settings. The Linux reference
has a 383,999,878 Hz source, 273 MHz HCLK and approximately 24 MHz actual
8-bit legacy bus; the profile requests at most 25 MHz and no high-speed modes.

MMC storage writes, erase support, boot/hardware partition configuration,
RPMB and filesystem writes are excluded from the build. A command whitelist
also rejects all data-write transfers and durable eMMC configuration commands
at the host-controller boundary. Only reads, identification and the volatile
bus-width/timing/erase-group geometry fields needed for initialization are
allowed. Production-function host tests cover those restrictions, inherited
clock/pin/power guards, gate/DMA failures and bounded complete-range hashing.

The native probe requires the expected 512-byte sectors, 122,142,720-sector
user area, eight-bit legacy bus and exact GPT extents. It hashes the primary
32 KiB GPT region and all 16 MiB of each of p22, p30 and p31 in 64 KiB chunks,
then reads and hashes `/etc/debian_version` on p29 through the ext4 reader.
The host compares p22 against the actual carrier hash; embedding that hash
in the carrier itself would be circular. It also checks all other fixed
hashes, success stage, width, clock and elapsed time. Failure is retained in
`/chosen/gemini,uefi-mmc-*` while Linux boot and automatic rescue continue.
Early clock/pin failures use retained phase `0x474d30xx`, with errno in `xx`.
The read loop has a 30-second deadline and bounded controller timeouts; the
independent watchdog covers a stuck controller or filesystem operation.

The first carrier is rooted at `handoff/uboot-efi-mmc`, SHA-256
`88c6aa8a2e466dd153c0fc19b0f2d17c5ddcdda5d1cd415bc3a166e0d681d5f4`.
Its cross build, all firmware host checks, write-API absence checks and
carrier validation passed. `handoff/uboot-efi-mmc-preflight-01` passed the
read-only live-device admission checks. Trial `handoff/uboot-efi-mmc-01` reached healthy EFI Linux boot
`cef5ad27-29fb-434f-8632-01ba7d1c90e4`. Native reads took 4,378 ms,
with eight-bit legacy mode, 25 MHz requested clock and zero error. All five
hashes matched, including the complete running carrier. Display/GOP passed,
1,402 real keyboard matrix scans completed without error, and EFI Linux
passed full health, both A72 starts, its complete RAM map and LK reservations.
The Fn implementation is included in this hardware boot; no physical key
press was required or observed. Automatic rescue restored fully healthy M69 boot
`992b64b9-c885-4b69-a071-462272ab3b4d`. Both writes, complete image readbacks and
reboot acknowledgements passed; final GPT/p22/p30/p31 guards passed. The
fresh retained phase was ExitBootServices (`0x474d10ee`), with 221.771 seconds
from candidate preloader departure to rescue entry. The EFI map contained
43 descriptors spanning all 4 GiB. No physical intervention was needed.

This proves native PIO eMMC identification and block/ext4 reads. The
subsequent EFI Block I/O and Simple File System qualification below corrects
the read-only capability reporting and verifies file access by an EFI
application. Loading the distro manager remains the next boot-path milestone. No filesystem migration or GPT change was performed. The accepted
`mainlineNixosBundle` still evaluates to
`/nix/store/92140xp096mcjqp6laid183r1cw2ky95-gemini-mainline-nixos-bundle`.


## EFI storage protocols and EOF correction

The `ubootEfiStorageBundle` / `efi-storage` profile runs an additional real
AArch64 EFI application on top of the qualified native MMC driver. It selects
the unique p29 GPT extent, verifies the partition's read-only EFI Block I/O
capability and ext4 superblock, then checks Simple File System volume/file
metadata, the exact `9.8\n` file bytes, current position, EOF, a seek-and-read
and bounded enumeration of `/etc` containing `debian_version`. It performs
no writes. Result and 64-bit EFI status are retained separately under
`/chosen/gemini,uefi-storage-{result,status}`; failure still boots Linux for
inspection and automatic rescue. The runner requires both this application
and the full native-MMC hash proof to pass.

U-Boot source `7192eea8092258cc3d4ea8a1bb984257be732e72` also reports
read-only media when the underlying block driver has no write callback,
uses that capability in filesystem information and rejects writable/create
opens before touching files. The transport command whitelist and absence of
MMC/filesystem write support remain independent protections. Host tests run
the actual EFI application with faulty protocols, malformed read results,
duplicate volumes and bounded enumeration, and exercise the production
read-only helper and file-open guard.

Trial `handoff/uboot-efi-storage-01`, carrier
`904262c53c512a528e949035ae948a14df0d60de4ed66bb5027d25bcbae6d5f1`, returned
healthy candidate Linux `edb818ff-fee7-4d44-a365-5f672efc3051` with
`EFI_DEVICE_ERROR` from the storage application. The profile correctly did
not qualify. Automatic rescue returned fully healthy M69
`22dbf523-4d6e-4d1e-94cb-fcc04e9215c5`, with all image/GPT checks passing.

Review identified a real EFI-to-filesystem boundary bug: EFI `Read()` at EOF
must succeed with zero bytes, whereas the ext4 reader rejects an effective
zero-length read. Also, `fs_read(..., length=0)` means the whole file, so an
EFI zero-length request must never be forwarded unchanged. A host regression
using the production EFI function failed at its EOF assertion before the
fix. Source `b2227743b300dc5f1ab8ace581dbbe746a4ba91a` handles zero-length
and EOF reads without issuing filesystem reads, rejects negative positions
and limits a final read to the remaining file size. EOF, empty files, zero
length, partial reads and backend failure tests now pass, as do the complete
firmware build and prior checks.

The corrected carrier is `handoff/uboot-efi-storage-eof`, SHA-256
`73095ee31d2128c6cadf920b8cc9e451f1900010dcda8c252376126d07779a0f`.
Trial `handoff/uboot-efi-storage-02` passed with candidate boot
`fb96b26d-6e87-4aab-b186-8fc3eea5fec5`: the unchanged EFI application returned
success, native MMC hashes matched in 4,378 ms, display passed and 1,402
keyboard scans completed without error. Linux passed full health, both A72
starts, its 43-descriptor EFI map covering 4 GiB and all LK reservations.
Automatic rescue restored healthy M69 `d811a8ba-9180-4f07-9316-3f37f619419d`.
Both complete writes/readbacks, reboot acknowledgements, the fresh
ExitBootServices marker and final GPT/p22/p30/p31 checks passed. Rescue entry
was 222.118 seconds after candidate preloader departure. No person was needed.

`geminiEfiBootFiles` prepares the next systemd-boot trial on the host: the
AArch64 distro manager, the existing qualified EFI kernel/initramfs in a
content-addressed directory, a Type 1 boot entry and an eight-second menu.
It retains the forced kernel command line and requires the LK-derived FDT
in the EFI configuration table. This does not implement normal NixOS
generation updates yet. No p29 filesystem or GPT migration has occurred.


Read-only boot-file publication preflight is retained at
`handoff/gemini-efi-boot-files-device-preflight.txt`. After the second storage
trial, p29 is clean and mounted `ro,norecovery`; 2,318,644 KiB is available.
`/gemian/EFI` and `/gemian/loader` are absent. `/gemian/nixos` and the accepted
squashfs remain present, with that squashfs backing the live loop-mounted
store. New boot files should therefore be published during a dedicated
Stage 1 gate before the store loop is mounted, using a journal-enabled
mount and the existing bounded recovery lease. The installer must validate
the exact bundle, refuse to overwrite different files or follow symlinks,
publish references only after their payloads, retain both existing stores,
and restore the read-only mount before normal boot. Reuse the existing
store-provisioning pattern rather than changing the live mounted store.

The cross build completed successfully with systemd 261.2. The publication
bundle is `handoff/gemini-efi-boot-files-publish`: a canonical five-file archive
of 20,449,280 bytes, SHA-256
`3acf483171660dc96b373966ed80e1c2e36286149bec3c3715f1ca14550b36d7`.
The manager itself is 176,128 bytes, SHA-256
`ed24e7e8b385f25f9df8812c899ecf581a6aa87368827b6a4a41fe4cb6f513cd`.
Kernel and initramfs retain the qualified EFI payload's exact bytes.

The opt-in `ubootEfiProvisionBundle` adds a Stage 1 hook after the existing
store hash check and before any store loop attachment. The accepted M69 and
base EFI initramfs remain unchanged. The host checks fresh boot identity,
candidate p22/GPT hashes, EFI storage proof and the read-only mount, then
uploads only the pinned archive into RAM. Stage 1 verifies it before mounting
p29 with journaling enabled. It requires a live watchdog, at least 120 seconds
remaining on the recovery lease, no attached store loops, sufficient space
and matching hashes for both existing squashfs stores.

Publication checks all five source and destination paths before writing,
rejects symlinks and conflicting files, copies through exclusive temporary
files, verifies each copy and publishes by a hard link that cannot overwrite
an existing destination. Payloads precede their entry and loader configuration.
An interrupted run can reuse already verified files. Both stores are checked
again, p29 is restored to read-only and all five files are read back before
normal boot resumes. The host independently verifies the files from healthy
candidate Linux before the existing supervisor restores M69.

Twenty-one focused host tests pass for publication, the Stage 1 mount/lease
sequence and host upload/readback, including partial copies, conflicting
files, symlink parents, corrupt archives, a short lease, mount failures,
disabled journaling and failed read-only restoration. Eight existing EFI
qualification tests also pass. The provisioning carrier is
`handoff/uboot-efi-provision`, SHA-256
`eabf8e42eeca5d08a7f7564dee82b44b44bb485235b74e1d6a81b08ba6dc97eb`;
its firmware remains source `b2227743b300dc5f1ab8ace581dbbe746a4ba91a`.
Read-only admission passed in `handoff/uboot-efi-provision-preflight-01`.
The accepted M69 bundle still evaluates to the same store path recorded above.

Hardware trial `handoff/uboot-efi-provision-01` passed. Candidate boot
`f2ec2e7b-ac40-4050-ab46-5595589b4771` installed the archive, rechecked both
stores, restored p29 read-only and reached full Linux health. Independent
Stage 2 readback matched all five file hashes (`boot-files.json`). Native
MMC, EFI storage, display, keyboard polling, both A72 starts and the complete
EFI memory/LK reservation checks also passed. Automatic rescue returned
healthy direct M69 `49655993-d7c5-42a1-adc7-9f12935076bc`. Both full p22
writes/readbacks and reboot acknowledgements passed; GPT/p30/p31 remained
exact. The fresh retained phase was ExitBootServices, and candidate departure
to rescue entry took 311.354 seconds. No physical intervention was required.
These files are installed; systemd-boot itself has not yet been booted.

## Distro manager launch

U-Boot source `aeafd9be180019ffa7909cfe31603e860375f205` adds the opt-in
`GEMINI_EFI_MANAGER` launcher. It requires the native MMC and EFI storage
checks, reads exactly 176,128 bytes from `/EFI/systemd/systemd-bootaa64.efi`
on `mmc 0:1d` (hexadecimal p29), checks the pinned SHA-256 above and binds the
Loaded Image device path to that volume. The launcher runs after EFI memory
preparation and exit-event registration, before the FIT kernel is decompressed.
It supplies the checked LK FDT and no initrd: systemd-boot loads the selected
kernel and registers its own LoadFile2 initrd from the installed Type 1 entry.

The firmware records `gemini,uefi-manager-{result,stage,sha256}` before starting
the manager and changes the result to `returned` with an EFI status on any
return. Read/admission failures record their stage. Linux can therefore remain
reachable through the FIT fallback while the profile correctly fails. The
independent hardware watchdog and mtkclient rescue ownership are unchanged;
all U-Boot storage write APIs remain disabled.

The host requires a non-returning launch and independently reads systemd-boot's
volatile EFI variables from Linux: version, exact selected entry and image
path, a boot-volume UUID resolving to p29, and menu-to-execution timing matching
the unattended eight-second menu. It rechecks all five installed file hashes.
This uses the real distro manager with no synthetic keypress. Physical key
actuation and visual inspection of this menu are not claimed.

The complete cross build and firmware host checks passed, including injected
file-size/read/hash/path failures, allocation failure, manager returns and
metadata exhaustion. Four host evidence tests and eight integrated EFI proof
tests passed. The carrier is `handoff/uboot-efi-manager`, SHA-256
`a99963352d9d3fbf017bfcb613fd05f020556d684bda0729a26ac4fcc94187f3`.
Its fallback FIT, kernel, initramfs and DTB remain the exact qualified EFI
payload. Read-only admission and all five live file hashes passed in
`handoff/uboot-efi-manager-preflight-01`.

The first manager trial, `handoff/uboot-efi-manager-01`, did not reach Linux.
The retained phase was `0x474d10e6` (FIT validated), before the explicit
manager launch marker, so this does not show that systemd-boot ran. Rescue
entry followed initial candidate departure by 26.327 seconds. Automatic
recovery passed both full writes/readbacks and restored healthy M69
`dd83a3fe-d624-44ab-a751-7a9d934fe571`, with GPT/p22/p30/p31 guards passing.
Source `e24b294a22507fca9f63c0b7ed80937647a1efd8` adds retained phase markers
around EFI preparation and the manager read/hash/device-path stages to
identify that failure without requiring a screen observer.

The diagnostic carrier (`handoff/uboot-efi-manager-stages`, SHA-256
`ca803a3cd9ab517fce7b796f1e214f96ae539d796f3a339290ada3b1159535e5`)
was tried in `handoff/uboot-efi-manager-02`. It reached phase `0x474d4025`,
the EFI boot-device-path setup, after successfully reading and verifying the
manager file. It did not reach the manager launch. Automatic rescue again
passed, restoring healthy M69 `9772e3f1-1c80-4f5b-b947-1fb879318f2c` with
all protected hashes unchanged; candidate-to-rescue entry took 26.352 seconds.
Source `75b676ba8a46bc4da0fc9957028cae91a74766ba` adds finer retained markers
inside that EFI device-path setup. Its cross build and existing tests passed.

Trial `handoff/uboot-efi-manager-03` used `handoff/uboot-efi-manager-path`,
SHA-256 `99105f1ec00c1a41755513da6b2cf5ebf73b666ba9afe03c6b8f06fc5d27954b`.
It reached phase `0x474d4039`, immediately before constructing the EFI file
path from the successfully constructed partition path. The manager still did
not start. Rescue entry took 26.303 seconds; both writes/readbacks and final
guards passed, restoring healthy M69 `f10de83d-e233-408d-87aa-f41f45e482e3`.

Investigation found unaligned UTF-16 stores in the packed file-path converter.
An MMC node is five bytes, so a following pathname may begin at an odd address.
A regression using the actual converter and charset helpers reproduces an
alignment-sanitizer failure before the fix. Source
`cc1e892d742942bf15ef369c072efaa96453c41d` encodes characters in aligned local
storage and copies their bytes, including the terminator, into the packed
path. Tests pass at all eight byte offsets for ASCII, Unicode, malformed UTF-8
and the empty string, with destination guards. This confirms the software
defect and its correction; device verification is still required to establish
whether it explains the retained failure.

It did not resolve the device failure. Trial `handoff/uboot-efi-manager-04`
used `handoff/uboot-efi-manager-aligned-path`, SHA-256
`7c748701ca8cc3d1d4afc89a713dd30a0734ad2d7fec86d2abc5f30c14adadf1`, and
again retained `0x474d4039`. The manager did not start. Automatic recovery
passed in 26.337 seconds to rescue entry and restored fully healthy M69
`8edbec93-5d47-44db-a48a-1d11eafa505c`; both writes/readbacks and all final
GPT/boot-partition checks passed. The alignment fix is supported by its host
regression but is not the established cause of this hardware failure.

The next diagnostic source, `0f373c8a81937a1c2179527b700910d150755131`, separates
file-path sizing, allocation, copy and encoding in retained phases
`0x474d4040` through `0x474d4045`. Its cross build and all existing firmware
checks passed. Carrier `handoff/uboot-efi-manager-file-stages` has SHA-256
`128bf5992f4f4c9d8af5612ef8c0829c9fd79c810323995c5b14d4de771cf4d0` and
passed read-only admission in `handoff/uboot-efi-manager-preflight-05` and
`handoff/uboot-efi-manager-preflight-05b`, including fresh M69 health and all
five installed-file hashes. Trial `handoff/uboot-efi-manager-05` retained
`0x474d4041`: device-path and UTF-8 sizing completed, but `efi_alloc()` did
not return. Automatic rescue restored healthy M69
`61c994e0-b227-436a-85c7-b2383a6d90ab`; rescue entry took 26.341 seconds.

Source `b1dddd4b3e82e362e43e5169ef679ddbebe51e1c` adds an opt-in exception
record to the existing retained TOPRGU word. For a PC within the carrier's
2 MiB U-Boot link window, it retains the unrelocated instruction address,
ESR exception class and low six syndrome bits before normal exception/reset
handling. It does not write RAM or storage. The decoder rejects stale records
as execution proof and never accepts an exception as a successful boot.
Firmware encoding tests and nine host EFI proof tests passed.

Trial `handoff/uboot-efi-manager-06` used `handoff/uboot-efi-manager-fault`,
SHA-256 `0b742593b485456fddc96d2dde8d3fec5cb627d39ac399b74aa5d155eb4495f7`.
It retained `0xca20f4c6`: PC `0x4023d318`, exception class `0x25`, syndrome
low six bits `0x04`. The exact unstripped firmware resolves that instruction
to `efi_update_memory_map()`, `lib/efi_loader/efi_memory.c:361`, loading
`evt->group` while traversing the EFI event list. Rescue entry took 26.355
seconds and healthy M69 `fab3d42c-7ec8-4d96-a815-f4025dfd9540` returned.
Both trials passed full candidate/rescue writes and readbacks, reboot
acknowledgements and final protected-partition guards.

This exposed a lifetime error in `efi_binary_run()`: a returning RAM-backed
EFI application freed its temporary memory device path but left the same
pointer in `bootefi_device_path`. A subsequent EFI event could reuse that
pool page; `efi_set_bootdev()` then freed it through the stale pointer, and
allocating a new partition path overwrote the still-linked event. The new
host regression executes the production runner and cleanup with deterministic
pool-page reuse. It fails on the old code when cleanup frees the replacement
event. Source `0a4c160d21c906d83202615222d9050c2fbd8c4e` keeps the temporary
path local and passes successful/error RAM-app returns, installation failure,
replacement allocation survival and persistent disk-path ownership checks.

The fixed cross build and all firmware checks passed. Carrier
`handoff/uboot-efi-manager-owned-path` has SHA-256
`d05f46b7e9b97381abfd03f59755742386ef1d9a5daab4a4c5411811b5b83750`.
Read-only admission passed in `handoff/uboot-efi-manager-preflight-07`.
Trial `handoff/uboot-efi-manager-07` reached fully healthy candidate Linux
`03df6c05-a89b-4879-8dfe-9163a6b28d9e`, retaining the manager's `starting`
marker and no return status. Console, 1,402 keyboard scans with zero error,
native MMC, EFI storage, the full 48-descriptor EFI memory map, both A72s,
initrd handoff and all LK reservations passed. This device result confirms
the path-lifetime fix removes the crash.

The overall manager profile still failed while reading the loader's EFI
variables from Linux. The original collector discarded the failed command's
partial output, so trial 07 does not establish which read failed. The host
collector now preserves partial data and stderr before rescue, with a failure
regression. Automatic recovery restored healthy M69
`70abf7c4-9444-4777-938c-3ea39f5cb9e2`, both full writes/readbacks and final
guards passed, and the retained phase was ExitBootServices. Rescue entry took
231.25 seconds after candidate departure. The accepted M69 bundle still
evaluates to `/nix/store/92140xp096mcjqp6laid183r1cw2ky95-gemini-mainline-nixos-bundle`.

Trial `handoff/uboot-efi-manager-08` repeated the same firmware and reached
healthy Linux `1b3554e9-65e3-4d84-9e05-1f51d9e8ab32`. Live diagnosis showed
that default `modprobe` is BusyBox and fails because `/lib/modules` is absent.
The matching kmod executable was invoked with `-d` pointing at the pinned EFI
kernel in the Nix store, then efivarfs was mounted read-only. That operation
is recorded in `efivar-mount.txt`; the host collector now performs it itself.
No firmware/kernel/store replacement was needed to expose runtime variables.

The manager's own variables now confirmed `systemd-boot 261.2` and selected
entry `gemini-efi-trial.conf`. Its image identifier is
`/\EFI\systemd\systemd-bootaa64.efi`; U-Boot's DevicePathToText prefixes nodes
with `/`, so the verifier accepts that exact equivalent rendering as well as
the ordinary EFI pathname. The remaining failure was a missing
`LoaderDevicePartUUID`. Automatic recovery restored healthy M69
`b7efb665-5b80-43fb-bb6c-b3675d3e176f`; full writes/readbacks and protected
hashes passed, phase was ExitBootServices and rescue entry took 231.213 seconds.

The captured factory GPT has a zero disk GUID and zero MBR signature, while
p29 has the valid partition GUID `b72ccbe9-2055-46f4-a167-4a069c201738`.
U-Boot chose the hard-drive device-path signature type from the disk signature,
so it omitted the partition GUID. systemd-boot discovers its volume UUID from
that device-path node and therefore could not report it. Source
`3da3110deebdb351eff0cd48d76271596dfa407d` uses the partition GUID for GPT
paths independently of the disk signature. A regression with the captured p29
identity fails before the fix and passes afterward, including unchanged DOS
signature behavior and failed partition lookup. No on-disk GPT change is made.

The complete cross build passed with both new regressions included in the
Nix build checks. Carrier `handoff/uboot-efi-manager-partuuid` has SHA-256
`fd6e29e1727209d1445c85380417ed06470bfd61da429ff7e1cd0f7a1fe43a20`.
Trial `handoff/uboot-efi-manager-09` reached healthy candidate Linux
`39e5b43c-043a-43f9-9e47-374879408e92` with the corrected collector loading
the module and mounting efivarfs itself. All six loader variables were read.
The UUID was now present and matched p29, but the verifier incorrectly
required lowercase while systemd-boot emitted uppercase hexadecimal.

The verifier now normalizes UUID case before validation and device lookup;
malformed identifiers still fail. Its five host tests pass, including the
actual U-Boot path rendering and uppercase UUID. Offline revalidation of the
original trial 09 variables confirms systemd-boot 261.2, the intended entry
and manager path, p29 UUID and a menu-to-execution interval of 9,477,423 us.
That separate evidence is `manager-variables-revalidated.json`; the original
trial result remains unchanged, since it stopped before the final device-link
and installed-file checks. A complete repeat is still required.
Trial 09's automatic rescue restored healthy M69
`23fa25d1-b82c-48d9-bb72-fc499508b84e`, with both full writes/readbacks,
unchanged protected hashes and ExitBootServices phase; rescue entry took
231.395 seconds.

Trial `handoff/uboot-efi-manager-10` repeated the same partition-identity
firmware with the corrected host verifier. Candidate Linux
`e2dd69ab-00cf-4653-900d-1d8536c8312b` passed every candidate check. The
manager's own EFI variables independently identify systemd-boot 261.2,
`gemini-efi-trial.conf`, the pinned manager path, and p29's UUID, which resolves
to `/dev/mmcblk0p29` in that same boot. Menu-to-execution time was 9,480,210 us
with the configured eight-second menu. The host loaded the matching efivarfs
module and mounted it read-only without manual assistance.

All five installed boot-file sizes/hashes matched and p29 remained read-only.
Console/GOP, native keyboard scans, raw MMC hashes, EFI file reads, the full
EFI memory map, initrd handoff, late-CPU identity and LK reservations passed
alongside full desktop/GPU/JPEG/Wi-Fi/audio health. No keypress was synthesized
or observed, and there was no person watching this menu. This qualifies the
unattended distro-manager boot path; physical menu input, persistent EFI
settings and normal NixOS generation management remain separate work.

The complete trial 10 finished with `profile_qualified=true` and
`linux_handoff_proven=true`. Automatic rescue restored fully healthy M69
`99e02757-9dfe-4e5b-8bb6-7b94d030ce17`. Both full p22 writes/readbacks and
reboot acknowledgements passed, GPT/p30/p31 stayed exact, and the retained
phase was ExitBootServices. Candidate departure to rescue entry took 233.556
seconds. The trial handle is terminal and the flash lane is idle. The accepted
installation remains direct M69; the qualified U-Boot manager is an opt-in
candidate. No physical intervention was required.

## Nix-enabled versioned entry and default activation

The Nix daemon correction qualified in [PERSISTENCE.md](PERSISTENCE.md) now has
separate EFI boot files and carriers. The U-Boot source remains
`3da3110deebdb351eff0cd48d76271596dfa407d`; the manager binary remains the
qualified systemd-boot 261.2 image. The kernel, initramfs, userspace and CPU
provenance match the directly qualified Nix candidate.

| Component | SHA-256 |
|---|---|
| Boot-file archive, 20,449,280 bytes | `4d98df6ccc325f7f1354ca85a66bb6d8f02dad94b586c64301bce4e7a0f1bc0f` |
| Original provisioning p22 carrier (trial 01) | `5958a922dfb113f64a8042d84d2e5ae0708ecc4fb86110b607bc9dd93c098088` |
| Manager p22 carrier | `004def7151492f54d3e34bc84ddef33de4bfd378def703a5e7858a09e8f37093` |

The artifacts are rooted at `handoff/nix-efi-candidates`, `-1` and `-2`,
respectively. The new entry is
`gemini-9c1bfbbbb260cf5830de42c587ea599cfbad29749ee66c61c65d2caf6caff999.conf`.
Its payload directory uses the same full identity under `EFI/Gemini/`.

The publisher's `activate` mode requires the old loader configuration hash
`9547db8cf45f9d032c9792411c7f06bbde375e7b9f620deea6c09740b4d34266`.
It checks all sources and existing destinations before publishing, retains
the previous entry and payload, and backs up the old configuration as
`loader/loader.conf.gemini-backup-<old-sha256>`. After syncing the payloads,
entry and backup, it atomically renames the new configuration into place.
Foreign configurations, backups, temporary files and symlinks are refused;
retries accept only the same verified bytes. The bounded Stage 1 hook restores
p29 to read-only before reporting success and preserves both protected stores.

Trial `handoff/efi-nix-provision-01` passed the complete provisioning profile.
Candidate `14de0b34-29eb-4806-8cbc-2684a572ffd1` passed EFI handoff, full Linux
health, both A72s, the full memory map, LK reservations, all five new file
hashes and retention of the old payload and configuration backup. An ordinary
daemon build submitted as UID 1000 ran in a separate network namespace and
could not access the user's home. Its output and database registration survived
automatic recovery to healthy M69 `e0cd8653-6a33-473a-94b3-a4f8faf48f1f`,
alongside the original persistence proof and both sets of boot files.
Candidate departure to rescue entry took 376.090 seconds, including publication
and qualification. Full candidate/rescue writes and readbacks, reset
acknowledgements and unchanged GPT/p30/p31 passed; the terminal result qualifies
the profile, ordinary daemon build and Nix persistence. The final audit found
both locks free and no writer.

Trial `handoff/efi-nix-manager-01` then passed the complete distro-manager
profile. Candidate `bdfccf9a-d47c-4130-8916-8596452f236c` reported the new full
entry name through systemd-boot's own `LoaderEntrySelected`, together with the
expected manager path and p29 UUID. The menu-to-execution interval was
9,478,940 microseconds. All five file hashes, the old configuration backup,
48 EFI memory descriptors covering 4 GiB, LK reservations, both A72s and full
service health passed. The keyboard completed 1,402 native scans with zero
errors; no physical keypress was observed.

An ordinary unprivileged daemon build passed its independent namespace and
sandbox checks. Automatic rescue returned to healthy M69
`715150bb-63d5-48fb-ad86-9132df5e6274`; its new output, home GC root, NAR hash
and derivation survived, together with the original persistence proof and
both boot-file sets. Both p22 writes/readbacks and automatic resets passed,
GPT/p30/p31 remained exact, and rescue entry took 242.017 seconds. The terminal
result sets `profile_qualified`, `linux_handoff_proven`,
`ordinary_daemon_build_qualified` and `nix_persistence_qualified` to true.
The final audit confirmed the same healthy rescue boot, free locks and no writer.

Versioned filenames and default activation do not yet implement arbitrary
NixOS generation selection. The carrier supplies a DT whose late-A72 provenance
is bound to its kernel. Booting another kernel needs matching per-entry
provenance while preserving LK's dynamic RAM/modem reservations. Retaining the
previous entry therefore provides rollback material for its matching carrier;
cross-kernel selection under the new carrier remains unqualified.

Local source inspection identifies the existing route for that next step:
systemd-boot 261.2 accepts a BLS `devicetree` file and calls
`EFI_DT_FIXUP_PROTOCOL` before installing it. This U-Boot enables the protocol,
whose handler invokes `image_setup_libfdt()`, but has no Gemini board fixup
to transfer LK's dynamic data into a replacement entry DT. That transfer must
retain the entry's CPU provenance and preserve the firmware's full memory map
and reservations. The generic protocol being enabled is insufficient evidence.

## Reproducible provisioning initramfs

Correcting the provisioning manifest's activation-policy record exposed a
pre-existing packaging defect: extracting and repacking its cpio assigned the
current build timestamp and host inode numbers to every member. A metadata-only
recipe change therefore changed the image even though all member contents were
identical. `nix/gemini-efi-provision.nix` now sets a fixed source epoch,
normalizes timestamps and uses cpio's reproducible inode/device metadata.
It also lists the activation-policy file and its previous-configuration hash
in `provision-manifest.json`.

Checks in `handoff/nix-efi-reproducibility-checks` compare every member's name,
content, mode, ownership and regular-file link topology with trial 01's
initramfs. Only archive metadata changed. Separate Nix `--check` rebuilds of
the provisioning bundle and complete carrier both pass. The corrected carrier
is rooted at `handoff/nix-efi-provision-reproducible`, SHA-256
`238072a0243de05435dcee15f60aa8304c36c07fe8431c49dfd5f6e03b9aa121`.
The manager carrier and published boot-file archive are unchanged.

Trial `handoff/efi-nix-provision-02` qualified that exact reproducible carrier.
Candidate `0ed2010c-f53b-46ae-9c55-6adeba2066e1` reused the complete publication
without requesting another archive upload, passed full EFI/Linux health and
an ordinary unprivileged daemon build, then recovered automatically to healthy
M69 `6ab5f118-ecb3-49ff-9018-543c166b94fa`. The new output and original
persistence proof survived; both boot-file sets and configuration backup
remained exact. Both full p22 writes/readbacks and resets passed, with unchanged
GPT/p30/p31. Rescue entry took 234.675 seconds, and all qualification flags
passed. The runner now pins this reproducible carrier for `efi-nix-provision`.

The final locked audit independently verified all four ordinary build outputs
from the direct Nix trial and these three EFI trials, including their home GC
roots, proof hashes, registered NAR hashes and derivations. It reconfirmed the
healthy M69 boot, both locks free and no writer. Evidence is in the last trial's
`all-nix-outputs/` and `final-idle-check.json`. All 94 relevant host regression
tests pass. Each EFI trial archives its seven exact executed host sources and
their hashes in `executed-sources/` and `plan.json`; subsequent pin changes do
not rewrite historical evidence. Accepted M69 and the original direct EFI and
Nix bundle paths remain unchanged.

## Per-entry device tree handoff

The opt-in DT-fixup profile lets systemd-boot load the entry's own DT through the BLS
`devicetree` directive. Its firmware compares the hash-checked original DT in
its embedded FIT with LK's live tree, then applies LK's changes to the selected
entry. Unchanged kernel nodes, CPU provenance, phandle numbering and command
line remain owned by that entry. Firmware RAM geometry and reservations are
retained; stale initrd-address properties are removed so EFI LoadFile2 remains
the initrd authority. Conflicting deletions, changed firmware phandles,
malformed trees and insufficient buffers fail the fixup.

U-Boot `fded2918d273c78d646db5224e54444c7419ec5f` introduced the helper and
board hook. Review of the actual EFI copy path found that it adds 64 KiB to
LK's already expanded 512 KiB DT. `c50f76ab4995037008b4b5ab37a828bd23e3373c`
corrects the entry-buffer bound; the corresponding regression fails on the
first revision and passes after the fix. Neither earlier manager image was
flashed. `GEMINI_EFI_DT_FIXUP` enables the hook and `SYS_FDT_PAD=0x10000` allows
space for LK's 22 KiB memory table and other dynamic properties.

The production helper and board hook pass host tests for independent entry
properties and phandles, LK additions/deletions, exact CPU identity retention,
idempotence, malformed inputs, hash failures, unaligned embedded DTs,
allocation failures and reservation conflicts. Tests also merge captured LK
data from the Nix-enabled boot into the older EFI kernel's DT without replacing
its CPU provenance. AddressSanitizer and UndefinedBehaviorSanitizer pass.
The corrected complete firmware/carrier cross build passes all existing boot,
reset, display, keyboard, storage and EFI regressions. Padding failure/success
logs are in `handoff/entry-dt-host-checks`.

The six-file package adds `gemini.dtb` to the content-addressed kernel/initrd
payload. Its identity covers all three original components; the published DT
carries that identity in `/chosen/gemini,efi-entry-id`. The Linux verifier
requires the selected entry's full provenance record and the firmware's
`gemini,uefi-dt-fixup=lk-delta-v1` marker, in addition to the manager's own entry
variables, exact boot-file readback, full EFI map and ordinary service health.
A successful FIT fallback cannot satisfy those manager and entry-DT checks.

| Component | SHA-256 |
|---|---|
| Six-file archive, 20,510,720 bytes | `3dfa2790fabf3a7875adc0b75c27e54f8607931a923a5db15958b26f2232a76b` |
| Entry DT, 63,997 bytes | `e99e32b198cc0263288cbb81220b947abec5726314f5e393427f7f274347bcb3` |
| Provisioning p22 carrier | `ac6f70b9655f0a8c181901966ab0c03a37d485df6ccbf59cdb62905aae7b1adc` |
| Corrected manager p22 carrier | `ef5c215b95da370e993710785d23c84c57dda47e40dab600b2ee302ef1d4ec19` |

The entry is
`gemini-49d449df65df5f412d738d56cde096e212d61d437bb7faca7afccf86f6729da3.conf`.
Archive and provisioning roots are `handoff/nix-efi-entry-dt-candidates` and
`-1`; the corrected manager root is `handoff/nix-efi-entry-dt-manager-pad`.
The initial `-2`/`nix-efi-entry-dt-manager` firmware lacks the padding fix and
must not be used. The new flake outputs are `geminiNixEfiDtBootFiles`,
`ubootEfiNixDtProvisionBundle` and `ubootEfiNixDtManagerBundle`; the runner
profiles are `efi-nix-dt-provision` and `efi-nix-dt-manager`. The Nix-enabled
kernel/system and the previously qualified manager retain their original
artifact paths. The `efi-nix-dt-manager` candidate uses the same Nix kernel
on both sides.
The separate cross-kernel profile described below tests independence from
the kernel and DT embedded in the carrier.


Provisioning trial `handoff/efi-entry-dt-provision-01` published the six-file
archive and activated the new default. Candidate
`ab5c37a1-0338-43ea-953a-3a8d9f1f2d43` passed EFI/Linux health and an ordinary
sandboxed daemon build. Automatic rescue restored healthy M69
`2c9526c2-8a41-44e9-9cc4-8d2d6b51d011`, retaining the original legacy entry,
the preceding Nix entry, both configuration backups and the new publication.
Both full p22 writes/readbacks and resets passed; GPT/p30/p31 were unchanged.
The rescue interval was 324.635 seconds. Its locked final audit retained all
five ordinary build outputs and found no active writer.

The cross-kernel profile, `efi-nix-dt-cross-manager`, keeps the older EFI
kernel and DT embedded in the carrier but selects the published Nix-enabled
entry. It uses the same corrected U-Boot binary. The host verifier extracts all
three FIT components directly from the pinned Android image, requires exact
older payload bytes and the same older DT in LK's appended copy, and requires
the selected DT to have different kernel configuration and GNU build identities.
Linux must then verify the selected entry's complete provenance and pass the
ordinary daemon build. The new output is `ubootEfiCrossDtManagerBundle`, rooted
at `handoff/efi-cross-entry-dt-manager`; p22 SHA-256 is
`d399b431e2683039848550bd64e2c43be343522b0d14cf1551a06511d02615d4`.
Host tests also apply older captured LK data to the newer kernel DT successfully.
The completed hardware result is recorded below.


Trial `handoff/efi-entry-dt-manager-01` qualified the corrected manager.
Candidate `8072e910-1639-4cd2-bbc9-b9ecca0e8e97` booted the selected DT through
systemd-boot 261.2, with a 9.785083-second menu interval and exact entry/volume
EFI variables. Runtime DT retained every selected CPU-provenance property and
both entry/fixup markers. Linux verified its CPU identity, the full 4 GiB EFI
map (49 descriptors), LK reservations, all service health and an ordinary
unprivileged daemon build. Native keyboard polling recorded 1,402 scans and
zero errors; physical key input remains untested.

Automatic rescue returned healthy M69 `03a22836-6f5e-4805-8ee2-c5cc2558593b`.
The complete result sets `entry_dt_handoff_qualified`,
`ordinary_daemon_build_qualified` and `nix_persistence_qualified` true, while
`cross_kernel_generation_selection_qualified` correctly remains false for
this same-kernel trial. The rescue interval was 240.975 seconds. Both full
writes/readbacks and resets passed, with GPT/p30/p31 and all three boot-file
sets retained. This qualifies the DT fixup on the device; the separate
cross-kernel profile below establishes independence from the carrier.


The cross-kernel candidate boot `e0e358ec-c55f-48c5-88eb-034e11b115db` passed
all checks in `handoff/efi-entry-dt-cross-manager-01`. Its exact older FIT
kernel/initramfs/DT and LK DT copy differ from the selected entry. Seven CPU
provenance properties differ, including both kernel configuration and GNU
build identities; the runtime DT matches the newer selected entry in full.
The Linux CPU verifier accepted that binding and both A72 cores came online.
Systemd-boot's menu interval was 9.784276 seconds, the EFI map contained
49 descriptors covering 4 GiB, and all LK reservations and service health
passed. An ordinary unprivileged sandboxed daemon build also passed.
Automatic recovery restored healthy M69
`055f7573-d77d-43f9-80e4-ca06ae55e3b7`. The complete result sets
`cross_kernel_generation_selection_qualified`, `entry_dt_handoff_qualified`,
`ordinary_daemon_build_qualified` and `nix_persistence_qualified` true.
Both full p22 writes/readbacks and resets passed; GPT/p30/p31 and every
published boot-file set remained unchanged. The rescue interval was
247.945 seconds.

All 105 relevant host regression tests pass, alongside the firmware's native
C checks, sanitizer runs and complete AArch64 build. Rebuilt legacy five-file
archives match their qualified bytes exactly; accepted M69, original EFI,
Nix Linux and the earlier manager retain their artifact paths. Host evidence
is in `handoff/entry-dt-host-checks`. Each current trial archives eight exact
executed qualification sources and their hashes.

These trials qualify per-entry DT selection between the two known kernel
builds. Normal NixOS generation installation, boot-file retention policy,
persistent EFI settings and physical keyboard selection are still separate
work. Direct M69 remains installed, and the newer DT-bearing entry remains
the published default for the qualified DT-fixup firmware.


The final locked audit in `handoff/efi-entry-dt-cross-manager-01` independently
retained all seven ordinary build outputs, home GC roots, proof hashes and
registered NAR/derivation identities. It reconfirmed healthy M69, both flash
locks free and no writer; every trial handle is terminal. Evidence is in
`all-nix-outputs/` and `final-idle-check.json`.
