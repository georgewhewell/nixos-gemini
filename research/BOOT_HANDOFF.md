# Gemini U-Boot qualification, 2026-10-04

Status: software reset and 31-second watchdog expiry are hardware-qualified
after removing an unmapped framebuffer probe. Both automatically recovered
fully healthy M69 through mtkclient. The first plain Linux handoff also passed;
repeat qualification is running. EFI smoke remains unqualified.
These profiles are based on the later U-Boot
worktree, not the September 4 WIP branch.

## Profiles

Build from this flake with `nix build .#ubootHandoffBundle`,
`.#ubootEfiSmokeBundle`, `.#ubootResetBundle`, or `.#ubootWatchdogBundle`.
Each carrier embeds the same M69 kernel, initramfs and DTB as
`mainlineNixosBundle`, with the same existing squashfs. The full artifact
manifest records payload and carrier hashes.

- Handoff: preserve LK's dynamic RAM/modem device tree and boot the checked FIT.
  Linux must expose `/chosen/gemini,uboot-handoff = "fit"`.
- EFI smoke: additionally require EFI hello entry/return and the separate
  `/chosen/gemini,uefi-hello-result = "passed"` property. This is not EFI Linux boot.
- Reset: invoke the generic reset dispatch before EFI or FIT processing.
- Watchdog: stop at WFI after arming the watchdog; there are no software kicks.
  A physical reset during this test does not prove watchdog expiry works.

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
smoke test. A completed EFI path still needs EFI Linux/ExitBootServices,
GOP, keyboard, storage and a boot manager.

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

| Profile | Current p22 SHA-256 |
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

## First Linux handoff

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
