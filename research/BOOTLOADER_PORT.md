# A chainloaded U-Boot for the Gemini PDA

Status: source-backed feasibility study plus reproducible stage-0 build,
2026-09-02. No U-Boot device write or reboot has been performed.

## Verdict

A 64-bit U-Boot port, carried as the kernel payload of the ordinary p22 Android
boot image and entered through the unchanged vendor LK and ATF, is feasible enough
to build. It is the shortest route to the desired end state:

```text
power button
  -> preloader
  -> stock p20/p21 LK
  -> fixed p22 Android-v0 wrapper containing U-Boot
  -> extlinux.conf + kernel + initrd + DTB on p29
  -> NixOS generation
```

This is not a proposal to flash a replacement p20/p21. Those partitions remain
untouched. The first U-Boot proof is just another bounded p22 payload and must obey
the existing p22-only Flash Tool transaction rules.

Two qualifications matter:

1. Source evidence makes the chainload contract strong, but no U-Boot binary has
   yet crossed it on this board.
2. Ordinary remote `nixos-rebuild` updates become possible only after a deliberate
   migration of p29 to a boot filesystem/layout that U-Boot can read and NixOS may
   update. The current campaign rule says, verbatim, “Never write p29/p30/p31”
   (`CATCHUP.md:225-233`). That rule is correct for current experiments and must be
   changed explicitly for the later migration; feasibility is not authorization.

## 1. The vendor boot contract

The public source examined here is
`/home/grw/src/gemini-lk-android8` at
`f4988d74bb70a0a15d7f362f412afba7e7fcda46`. It is near-certain source lineage,
not a claim of a bit-identical rebuild of live p20. The retained binary audit found
the same MT6797 load address, Gemini panel names, and MediaTek header
(`research/LK.md:9-29`).

### What LK itself is

The Gemini target is a 32-bit ARM LK even though it boots a 64-bit payload:

> `ARCH := arm`
>
> `ARM_CPU := cortex-a53`

(`/home/grw/src/gemini-lk-android8/lk/platform/mt6797/rules.mk:3-5`)

It lives in a four-MiB window at `0x46000000` and has a 128-MiB download/scratch
window beginning at `0x46900000`:

> `MEMBASE := 0x46000000 # SDRAM`
>
> `MEMSIZE := 0x00400000 # 4MB`
>
> `SCRATCH_ADDR := 0x46900000`
>
> `SCRATCH_SIZE := 0x08000000 # 128MB`

(`/home/grw/src/gemini-lk-android8/lk/target/k97v1_64_bsp/rules.mk:16-34`)

The target explicitly enables eMMC, GPT, device trees, security/verified boot,
and secure fastboot unlock support, and names both exact Gemini panels
(`/home/grw/src/gemini-lk-android8/lk/project/k97v1_64_bsp.mk:3-20`). The bundled
security libraries are present, but their README says they were built from a
MediaTek ASF tree outside Android
(`/home/grw/src/gemini-lk-android8/lk/platform/mt6797/lib/README:10-23`). This is
why rebuilding vendor LK is useful for reference but is not the dependency of the
U-Boot route.

### Slot selection and Android-v0 loading

LK initializes eMMC, then selects a DT from `boot3`, `boot2`, or `boot` from the
live keys:

> `if (mtk_detect_key(17) && mtk_detect_key(8)) ... bldr_load_dtb("boot3")`
>
> `else if (mtk_detect_key(17)) ... bldr_load_dtb("boot2")`
>
> `else ... bldr_load_dtb("boot")`

(`/home/grw/src/gemini-lk-android8/lk/platform/mt6797/platform.c:614-643`)

It repeats that selection for the Android boot image header and payload:

> `ret = mboot_android_load_bootimg_hdr("boot3", CFG_BOOTIMG_LOAD_ADDR);`
>
> `ret = mboot_android_load_bootimg_hdr("boot2", CFG_BOOTIMG_LOAD_ADDR);`
>
> `ret = mboot_android_load_bootimg_hdr("boot", CFG_BOOTIMG_LOAD_ADDR);`

(`/home/grw/src/gemini-lk-android8/lk/app/mt_boot/mt_boot.c:2201-2235`)

The current Linux Nix wrapper emits Android-v0 geometry with the kernel at
`0x40200000` and ramdisk at `0x45000000` (`nix/mainline.nix:1864-1871`). The
separate U-Boot stage-0 carrier uses LK's native documented kernel start,
`0x40080000`. LK first
loads a 64-bit kernel field into scratch, searches backwards for the appended FDT,
subtracts it from the compressed payload, and decompresses the remainder to the
header's kernel address
(`/home/grw/src/gemini-lk-android8/lk/app/mt_boot/mt_boot.c:933-1005`). Therefore
the initial U-Boot carrier should be:

```text
Android boot-v0 kernel field = gzip(u-boot.bin) || Gemini/U-Boot control DTB
kernel_addr                 = 0x40080000 (4 KiB and 512 KiB aligned)
ramdisk                     = a tiny inert initramfs, initially
tags/FDT address            = the existing known-good value produced by the wrapper
```

Using `u-boot-dtb.bin` inside the gzip lets U-Boot use its own embedded control
tree; the second appended DTB exists for LK's parser and is also available as the
prior-stage FDT if the port later chooses to preserve x0.

### AArch32 to AArch64 and ATF

Immediately before handoff, LK disables its interrupts, cache, and MMU, kicks the
still-live watchdog, then calls `lk_jump64(entry, tags, 0, KERNEL_64BITS)`
(`/home/grw/src/gemini-lk-android8/lk/app/mt_boot/mt_boot.c:1753-1766,1806-1829`).
The actual AArch32 stub makes this SMC:

> `ldr r0, =0x82000200`
>
> `smc #0`

(`/home/grw/src/gemini-lk-android8/lk/arch/arm/exceptions.S:136-145`)

That exact SMC path already boots the project's arbitrary AArch64 Linux images.
U-Boot's AArch64 entry explicitly supports being entered at EL3, EL2, or EL1 and
documents EL2 as the recommended level when it acts only as a boot loader
(`/home/grw/src/u-boot/doc/arch/arm64.rst:13-27`; startup handling at
`/home/grw/src/u-boot/arch/arm/cpu/armv8/start.S:117-162`). Thus there is no
fundamental AArch32-to-AArch64 mismatch: ATF, not LK, changes execution state.

The MT6797 port should nevertheless record `CurrentEL`, `SCTLR_ELx`, x0-x3, and
the FDT magic at its first C instruction. The live ATF handler is known only from
static analysis; the exact register state delivered to a non-Linux payload remains
to be measured.

### Watchdog contract

LK's source says why the kick is intentional:

> “Kick watchdog before leaving lk ... watchdog is still alive.”

(`/home/grw/src/gemini-lk-android8/lk/app/mt_boot/mt_boot.c:1806-1813`)

It configures ten seconds (`lk/platform/mt6797/mtk_wdt.c:246-283`), and live Linux
has observed the handoff registers (`research/LK.md:34-52`). U-Boot must pet or
deliberately extend that watchdog in its earliest board code. It must not silently
stop it. Upstream U-Boot's generic MediaTek watchdog probe currently returns
`mtk_wdt_stop(dev)` (`/home/grw/src/u-boot/drivers/watchdog/mtk_wdt.c:122-135`),
so using that driver unchanged would violate the project's recovery contract.

## 2. Fastboot: present, but not a proven shortcut

The vendor LK contains a complete fastboot server. It registers getvar,
download, flash, erase, continue, reboot, reboot-bootloader, and—when secure
unlock support is built—RAM boot
(`/home/grw/src/gemini-lk-android8/lk/app/mt_boot/fastboot.c:609-675`). The RAM
boot handler validates the Android header and address ranges, moves the kernel and
ramdisk, stops USB, kicks the watchdog, and calls the same Linux handoff
(`/home/grw/src/gemini-lk-android8/lk/app/mt_boot/sys_commands.c:413-604`).

But two gates prevent treating `fastboot boot` as today's test method:

- `boot` is registered with `forbidden_when_lock_on = TRUE`; the dispatcher
  replies `not allowed in locked state` when `get_unlocked_status() == 0`
  (`fastboot.c:283-301,670-675`). The device's lock state is unknown.
- More importantly, the Gemini target says `MTK_FASTBOOT_SUPPORT := no`
  (`lk/target/k97v1_64_bsp/rules.mk:36-40`). In the actual non-text-menu boot
  path, both the RTC fastboot-bit check and the key check are inside
  `#ifdef MTK_FASTBOOT_SUPPORT` (`lk/platform/mt6797/boot_mode.c:180-228`). The
  target-local `fastboot_trigger()` does check RTC bit 13 and a camera key
  (`lk/target/k97v1_64_bsp/init.c:69-99`), but it is called by `app/aboot`, not by
  this target's `app/mt_boot`.

So the server is compiled in, but a reachable entry path is not established from
this source. A future read-only observation of USB after an explicitly authorized
`reboot bootloader` could settle it, but the U-Boot plan must not depend on it.
Never run `oem unlock`: the source exposes destructive unlock/erase machinery,
and it is unnecessary for p22 Flash Tool experiments.

## 3. Upstream LK versus U-Boot

The inspected trees are:

- upstream LK `/home/grw/src/lk` at `39614eaf960f3504a99fc7175ea32936a13a90e5`;
- U-Boot `/home/grw/src/u-boot` at
  `cc8c034e78eba6b2a3845783889b80753bb1af1e`.

| Area | upstream LK | U-Boot | Gemini work estimate |
|---|---|---|---|
| MT6797 base | Existing target, but 32-bit Cortex-A7, 4 MiB RAM, shell only | No MT6797 target; mature generic MediaTek ARM64 framework | LK: replace/extend target; U-Boot: ~300-700 lines of Kconfig, init, memory map, board DT |
| Console/timer | MT6797 UART, GIC and GPT exist | Generic MT6577-compatible UART already matches the DT family; generic ARM timer | U-Boot: ~50-200 lines plus DT; physical UART access remains unknown |
| Watchdog | MT6797 target disables WDT at early init | MediaTek WDT driver has the correct register model | ~100-250 lines to preserve, trace and pet the inherited watchdog |
| eMMC/GPT | No MT6797 block driver | `mtk-sd`, generic MMC/GPT/ext4/FAT stack | ~100-400 lines for MT6797 compatibility if LK's clock/pad handoff is retained; ~1.5-4k for independent clock/pinctrl/power ownership |
| USB gadget | Generic device/class code, no MTK controller | MUSB gadget core, fastboot function, and MT8518 MediaTek glue exist | ~500-1,200 lines for MT6797 MUSB/PHY/clock handoff |
| Android image | No implementation found | Parser and boot support are first-class (`CONFIG_ANDROID_BOOT_IMAGE`) | Configuration/board policy only |
| FDT/Linux boot | `lib/fdtwalk`, not a Linux boot product | libfdt, `booti`, fixups, PSCI handoff | Configuration plus MT6797 DT validation |
| extlinux/NixOS | No parser/boot flow | Existing extlinux boot method | Configuration only after eMMC works |
| Estimated new/ported code to useful boot | ~10-18k lines | ~2-6k lines using LK's initialized hardware; ~5-10k if made fully independent | U-Boot wins strongly |

The upstream-LK baseline is smaller than the old project note implied. Its MT6797
platform contains only UART, interrupt, timer/GPT, debug, and an empty platform
init; it explicitly says its MMU map “needs to be filled in” and disables the WDT
(`/home/grw/src/lk/platform/mediatek/mt6797/platform.c:25-77`). Its project adds
only `app/shell` (`/home/grw/src/lk/project/mt6797.mk:1-7`). The tree has generic
BIO, partition, ext2/FAT and a small USB device stack, but no fastboot or Android
boot-image implementation was found.

U-Boot already supplies the boring, difficult upper half. Its extlinux boot method
finds the config on a partition, reads it, and passes it to the PXE/extlinux parser
(`/home/grw/src/u-boot/boot/bootmeth_extlinux.c:135-200`). Its generic fastboot
implementation can execute a configurable `fastboot_bootcmd` or `bootm` a downloaded
image (`drivers/fastboot/fb_common.c:141-175`). Android boot images are a normal
Kconfig feature (`boot/Kconfig:5-23`).

### Reuse opportunities in U-Boot

- **UART:** `serial_mtk` matches `mediatek,mt6577-uart`
  (`drivers/serial/serial_mtk.c:290-322`), the compatible used by the Linux MT6797
  UART nodes.
- **Watchdog:** `mtk_wdt` uses the same mode/length/restart offsets and keys as
  live MT6797 (`drivers/watchdog/mtk_wdt.c:15-35`). It needs handoff policy, not a
  new register driver.
- **eMMC:** U-Boot's `mtk-sd` already has an MT7623 compatibility record with the
  same important feature shape as Linux's MT6797 record: 12-bit divider,
  `PAD_TUNE0`, async FIFO, data tuning, and no busy/stop-clock/enhanced-RX quirks
  (`drivers/mmc/mtk-sd.c:1913-1921`; Linux comparison at
  `/home/grw/src/linux-gemini-platform/drivers/mmc/host/mtk-sd.c:583-594`). A
  dedicated compatible entry should be small. The proven Linux board deliberately
  preserves firmware pad setup and runs eMMC at 25 MHz
  (`arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:302-365`). Initial U-Boot
  can likewise use fixed/no-op clock descriptions and inherited rails instead of
  porting all 731 lines of MT6797 clocks and 2,443 lines of pin data immediately.
- **USB:** U-Boot has the MUSB gadget core and a 419-line MediaTek MT8518 glue
  (`drivers/usb/musb-new/mt85xx.c`). Linux's already-proven MT6797 glue provides
  the L1 interrupt layout, endpoint target-address offset, five-endpoint FIFO
  layout and two clock names
  (`/home/grw/src/linux-gemini-platform/drivers/usb/musb/mediatek.c:21-45,184-205,404-447`).
  Porting that delta is bounded; it is not a controller rewrite.

## 4. Memory map and relocation

The firmware-supplied tree describes four GiB from `0x40000000`, but the usable
space is punctured by fixed and dynamic reservations. Fixed low reservations are:

| Region | Purpose/evidence |
|---|---|
| `0x40000000..0x40000fff` | reserved first page |
| `0x44400000..0x4440ffff` | firmware/ram-console guard |
| `0x44410000..0x444effff` | ramoops |
| `0x444f0000..0x444fffff` | project trace reservation |
| `0x44600000..0x4466ffff` | firmware/project reservations |
| `0x44800000..0x448fffff` | firmware reservation |
| `0x46000000..0x463fffff` | vendor LK |

The source is `arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:51-110`; a live
boot confirms every range and also shows dynamic CCCI, SCP, framebuffer, ATF-log
and log-store reservations at the top and middle of RAM
(`artifacts/p22-recovery-20260831-005744-3248718/dmesg-pre:7-30`).

Consequences for the port:

1. Link the first U-Boot proof at `0x40080000` and enable position-independent
   startup. U-Boot requires 4-KiB load alignment and applies its own RELA fixups
   (`arch/arm/cpu/armv8/start.S:61-104`).
2. Do not let generic relocation choose the apparent top of four-GiB RAM: it could
   land in a dynamic firmware reservation before U-Boot has imported it. For the
   first port, reserve `0x43fff000..0x43ffffff`, and cap
   `board_get_usable_ram_top()` at `0x43fff000`. The deliberately exposed stage-0
   bank is `0x40001000..0x43ffefff`, below LK's tags/FDT at `0x44000000`.
3. Before loading Linux, import both the prior-stage FDT reservations and U-Boot's
   own relocated region into the LMB. Pick kernel/initrd load addresses only after
   this. Never place U-Boot, its FDT, or temporary eMMC buffers in ramoops,
   `0x46000000..0x463fffff`, the ATF log, framebuffer, CCCI, SCP, or log-store
   regions.
4. Keep the stock ATF and PSCI. U-Boot is a non-secure EL2/EL1 boot loader, not a
   replacement BL31. Linux's live log confirms PSCIv0.2 from the firmware
   (`dmesg-pre:31-34`).

## 5. Staged implementation plan

Each device step remains a single, explicitly authorized p22-only Download-Only
transaction with exact pre/post hashes. p20, p21, p29, p30, p31, GPT, modem and ATF
partitions remain untouched during these stages.

### Stage 0: prove entry and preserve recovery visibility

Build the minimal ARM64 `mt6797_gemini_stage0_defconfig` with:

- position-independent entry at `0x40080000`;
- no relocation at or above `0x43fff000`;
- an earliest-possible watchdog snapshot and one pet at each bounded stage,
  never a reconfiguration or stop;
- embedded control DTB;
- a tiny persistent marker in a newly allocated, explicit reserved-memory record,
  plus the exact `CurrentEL`, x0-x3 and watchdog register snapshot;
- a deliberate watchdog expiry after the marker, returning to the known-good p22
  recovery cycle if no interactive transport exists.

Do not scribble an ad-hoc string into ramoops: its contents have a format and are
evidence. Either teach the proof to emit a valid ramoops console record, or add a
separate 4-KiB `u-boot-stage0` reservation and a matching read-only Linux collector.

The current implementation is on local U-Boot branch `gemini-mt6797-stage0` at
`/home/grw/src/u-boot-gemini-stage0`. Two independent builds with fixed
`SOURCE_DATE_EPOCH` produced identical `u-boot.bin` and control-DTB hashes. The
Android-v0 builder in `tools/build-android-uboot-v0.py` produces a deterministic
16-MiB p22 carrier and independently round-trips the compressed U-Boot payload.
Entry, relocation and watchdog recovery remain device-unproven. In particular,
retention of `0x43fff000` across the inherited watchdog reset must be preflighted;
absence of a record is not proof that U-Boot failed to enter until retention is
known.

Best visibility is an MT6797 MUSB gadget identity because Trex already observes the
left port. Port only enough of the Linux glue to enumerate a unique VID:PID/product
string; a shell and eMMC are not prerequisites. UART logging is useful in parallel,
but the physical Gemini UART path is not established.

Acceptance: Trex records the unique U-Boot USB identity or the next recovery boot
extracts a valid stage-0 record; watchdog recovery occurs within the bounded lease;
p22 reads back exactly; all protected partition hashes are unchanged.

### Stage 1: interactive U-Boot and RAM boot

- Finish MUSB gadget support and enable U-Boot fastboot or CDC ACM.
- Implement `fastboot boot`/`booti` of a known-good existing kernel+initrd+DTB from
  host RAM, with all loads checked against the firmware reservation map.
- Verify gadget disappears at handoff and the normal Linux gadget/SSH returns.
- Capture `CurrentEL`, final FDT, pstore, watchdog ownership, and all load addresses.

This stage gives a no-storage-write kernel iteration loop even if vendor LK's own
fastboot remains unreachable.

### Stage 2: inherited-state eMMC and extlinux

- Add `mediatek,mt6797-mmc` to `mtk-sd` using the proven Linux compatibility data.
- Initially retain LK's pad, clock, regulator, and 25-MHz state; expose fixed clocks
  to driver model and use PIO if that is the smaller first proof.
- Read GPT and p29 only. Mount ext4 read-only and list a fixture
  `/boot/extlinux/extlinux.conf`.
- Boot a known-good NixOS generation from p29. Fall back to the embedded recovery
  entry when config parsing, file hashes, or the boot lease fails.

Only after repeated read-only success should the user authorize a p29 layout
migration and install `boot.loader.generic-extlinux-compatible`. Then a remote
cross-built `nixos-rebuild --target-host` can copy a closure plus kernel/initrd/DTB
and update extlinux generation entries using ordinary filesystem writes. Rollback
becomes selection of the previous extlinux entry; it is no longer a p22 reflash.

### Stage 3: boring boot loader, normal NixOS generations

- Freeze a small, recovery-oriented U-Boot in p22.
- Put all frequently changing kernel, initrd, DTB and generation data on p29.
- Add bootcount/altbootcmd only after the storage and reset semantics are proven;
  store environment/recovery state in a file or explicitly allocated area, never
  an improvised Android partition.
- Add an operator path back through stock LK's side-button p30/p31 behavior without
  changing either partition.

Replacing p20/p21 is optional and much later. It gives little benefit once stock LK
reliably chainloads p22, while it crosses the least recoverable security boundary.

## 6. Risks and unknowns

1. **Exact entry registers and EL:** inferred from source and successful Linux boots,
   not measured with U-Boot.
2. **Relocation:** generic top-of-RAM placement can corrupt dynamic ATF/log/modem/SCP
   reservations. The first port must impose a low ceiling.
3. **Inherited watchdog:** only ten seconds are available. A silent stop would remove
   the recovery mechanism; an unserviced watchdog would reset before USB appears.
4. **Caches/coherency:** LK disables its MMU/cache, and U-Boot supports that entry
   state, but MT6797 cluster/coherency state must be recorded. Do not start secondary
   CPUs in the boot loader.
5. **USB PHY/clocks:** Linux support proves the controller, not that U-Boot's shorter
   initialization is correct. Start in PIO device-only mode and retain LK state.
6. **eMMC ownership:** inherited 25-MHz state is the shortest proof, not a full driver.
   Independent cold initialization later needs MT6797 clocks, pinctrl and MT6351
   regulator/PWRAP support. U-Boot currently supports MT6357/MT6359, not MT6351
   (`drivers/power/pmic/mtk-pwrap.c:650-662`).
7. **Fastboot entry/lock:** the code exists, but entry is compiled out in the apparent
   target configuration and lock state is unknown. Do not build the plan around it.
8. **p29 policy and migration:** current safety rules forbid writes. A normal NixOS
   boot filesystem requires a separately reviewed, user-authorized migration and a
   rollback image.
9. **Vendor-source fidelity:** the public LK source is strong lineage evidence, not
   proof of the exact live binary's every branch.
10. **No physical UART:** USB or a formatted persistent record must provide first-light
    evidence.

## Recommendation

Proceed with U-Boot, not an upstream-LK bootloader port. Keep vendor LK and ATF as
the immutable hardware-initialization and AArch32-to-AArch64 bridge; make U-Boot the
p22 payload. The first engineering milestone is not eMMC and not extlinux. It is a
position-independent, low-relocating U-Boot that preserves the inherited watchdog
and gives Trex an unambiguous USB or persistent first-light marker.

Once that is proven, U-Boot's existing MMC, ext4, extlinux, Android-image, fastboot,
FDT and AArch64 Linux machinery turns the remaining work into a bounded MT6797
driver port. That is the route to plain OEM power-on and normal NixOS generation
updates without making p20/p21 part of the experiment.
