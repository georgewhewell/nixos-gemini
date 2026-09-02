# A chainloaded U-Boot for the Gemini PDA

Status: source-backed feasibility study, 2026-09-02. Every load-bearing claim
carries a `file:line` citation that was re-checked against the trees named in
section 0 on 2026-09-02. No device was touched for this study. A stage-0 U-Boot
tree exists locally (section 4) but has never been written to the device.

## Verdict

A 64-bit U-Boot, carried as the *kernel* field of an ordinary Android-v0 boot
image in p22 and entered through the unchanged vendor LK and ATF, is feasible and
is the shortest route to the chosen UEFI boot architecture:

```text
power button
  -> preloader
  -> stock p20/p21 LK (AArch32)
  -> ATF BL31 (SMC 0x82000200, switches to AArch64, enters payload at EL2)
  -> p22 Android-v0 wrapper whose "kernel" is gzip(u-boot.bin) || DTB
  -> U-Boot EFI loader + inherited-framebuffer GOP + Simple Text Input
  -> EFI/BOOT/BOOTAA64.EFI (systemd-bootaa64.efi) on a FAT ESP
  -> NixOS UKI / generation
```

p20/p21 stay untouched. The first U-Boot proof is just another bounded p22
payload under the existing p22-only Flash Tool transaction rules
(`CATCHUP.md:225-233`: "Experimental boot writes are **p22 only**", "Never write
p29/p30/p31, the bootloader, GPT, or modem partitions p13-p16.").

Two qualifications:

1. The chainload contract is strong on LK source evidence and on the fact that
   this path already boots the project's arbitrary AArch64 Linux images. The
   final LK/ATF-to-payload register state is nevertheless inferred from an
   historical MT6795 TF-A implementation plus live Linux observations, not a
   decoded copy of the exact live MT6797 BL31. Stage 0 must measure it. No U-Boot
   binary has yet crossed the path on this board.
2. Normal `nixos-rebuild` updates require a reviewed FAT ESP layout, EFI boot
   files and a rollback plan. The intended migration uses p29, but p29 is not
   currently authorised for writes or reformatting. That migration is a later,
   separate operation; feasibility is not authorisation. Until then extlinux is
   only a diagnostic fallback, not the target boot architecture
   (`campaign/00-roadmap-and-status.md:60`).

## 0. Trees examined

| Tree | Path | Revision |
|---|---|---|
| Vendor LK (Planet Android 8) | `/home/grw/src/gemini-lk-android8/lk` | `f4988d74bb70a0a15d7f362f412afba7e7fcda46` ("Initial commit") |
| Upstream LK | `/home/grw/src/lk` | `39614eaf960f3504a99fc7175ea32936a13a90e5` |
| U-Boot | `/home/grw/src/u-boot` | `cc8c034e` (2026-09-01, master) |
| U-Boot stage-0 branch | `/home/grw/src/u-boot-gemini-stage0` | `94a4e9d7` on top of `cc8c034e` |
| TF-A upstream | `/home/grw/src/arm-trusted-firmware` | `cd708ee` (2026-08-28) |
| TF-A v1.5 reference files | `/home/grw/src/atf-history/` | raw files from tag v1.5 (mt6795/common port, the last upstream copy of `boot_to_kernel`) |
| Mainline Linux (project) | `/home/grw/src/linux-gemini-platform` | `da6e93b0b` (2026-08-31) |
| Vendor Linux 3.18 | `/home/grw/src/gemini-linux-kernel-3.18` | as cloned |

The p20 binary evidence (`artifacts/lk-analysis/REVERSE_ENGINEERING.md`,
`artifacts/lk-analysis/lk-p20_strings.txt`) matches this LK source lineage: same
MT6797 load address, panel names, MediaTek header, `smc 0x82000200`, WDT argument
10 and kick `0x1971` (`research/LK.md:9-29,34-52`). It is lineage, not a
bit-identical rebuild; where the binary and the source disagree this document says
so (section 1.5).

## 1. The vendor boot contract

### 1.1 What LK is

A 32-bit LK that boots a 64-bit payload:

> `ARCH := arm`
> `ARM_CPU := cortex-a53`

(`lk/platform/mt6797/rules.mk:3-4`)

> `MEMBASE := 0x46000000 # SDRAM`
> `MEMSIZE := 0x00400000 # 4MB`
> `SCRATCH_ADDR := 0x46900000`
> `SCRATCH_SIZE := 0x08000000 # 128MB`
> `MTK_FASTBOOT_SUPPORT := no`
> `DEVICE_TREE_SUPPORT := yes`

(`lk/target/k97v1_64_bsp/rules.mk:19,29,33,34,38,40`)

The project enables eMMC/GPT, verified boot, and secure fastboot unlock, and names
both Gemini panels (`lk/project/k97v1_64_bsp.mk:6,9,16,18-20`). The security
functions (`get_unlocked_status`, `seclib_sec_boot_enabled`, `sec_img_auth`,
`sec_query_device_lock`) are only present as binaries
(`lk/platform/mt6797/lib/{libsec.a,libsecplat.a,libdevinfo.a,libcrypto.a,libscp.a}`;
the README says "lk security library is built from Mediatek ASF code base and it's
not part of android", `lib/README:18`).

Vendor `platform/mt6797` is ~61 k lines of C in 95 files; the pieces a port would
otherwise have to reinvent are `msdc.c` 3486 + `mmc_core.c` 3710 + `msdc_dma.c`
1053 (eMMC), `mt_usb.c` 2889 + `mt_ssusb_qmu.c` 479 + `mt_usbphy.c` 994 (USB device
on the SSUSB/MTU3 controller at `USB3_BASE (0x11270000)`,
`include/platform/mt_reg_base.h:248`), `uart.c` 366, `mt_i2c.c` 948, `mt_gpio.c`
921, `mt_disp_drv.c` 529, `mtk_wdt.c` 446, `mt_rtc.c` 345 (`wc -l`, 2026-09-02).

### 1.2 Slot selection and image loading

`platform_init()` initialises eMMC (`mmc_legacy_init(1)`, `platform.c:612`) and
picks the DT source from the live keys:

> `if (mtk_detect_key(17) && mtk_detect_key(8)) { // 8 = POWER KEY`
> `    if (bldr_load_dtb("boot3")<0) dprintf(CRITICAL, "bldr_load_dtb fail\n");`
> `} else if (mtk_detect_key(17)) { // 17 = SIDE BUTTON KEY`
> `    ... bldr_load_dtb("boot2") ...`
> `} else { ... bldr_load_dtb("boot") ...`

(`lk/platform/mt6797/platform.c:633-643`; `MT65XX_BOOT_MENU_KEY 17 /* KEY_VOLUMEUP */`,
`lk/target/k97v1_64_bsp/inc/cust_key.h`). The same three-way selection is
repeated for the boot image header and body in `boot_linux_from_storage`
(`lk/app/mt_boot/mt_boot.c:2208-2235`).

`bldr_load_dtb` reads the Android header from the partition, then
`platform_parse_bootopt` decides the payload width from the *cmdline*:

> `if (strncmp(&bootopt_str[i + 0x12], "64", 2) == 0) g_is_64bit_kernel = 1;`

(`mt_boot.c:573-601`, i.e. `bootopt=64S3,32N2,64N2` must be present and the
characters at offset 0x12 of the `bootopt=` token must be `64`). The 64-bit path
then requires:

- kernel_addr 512 KiB aligned:
  `if (g_boot_hdr->kernel_addr & 0x7FFFF) { dprintf(CRITICAL, "64 bit kernel can't boot..."); while(1); }`
  (`mt_boot.c:933-949`);
- a DTB *appended* to the kernel field, found by a backward magic search from the
  end of the field, copied to `tags_addr` (`mt_boot.c:951-1005`, "Can't find device
  tree" -> `while (1)` at `mt_boot.c:1023-1025`);
- a **gzip** payload: `decompress_kernel()` is gunzip only and rejects anything
  where `src[2] != Z_DEFLATED` (`lk/app/mt_boot/decompressor.c:60-144`); the
  decompressed size limit is `KERNEL_DECOMPRESS_SIZE := 0x03200000` (50 MiB,
  `platform/mt6797/rules.mk:12`).

LK then fixes up the DTB (`fdt_setprop_string(fdt, offset, "bootargs", cmdline_get())`,
`mt_boot.c:1697`; memory node, boot state, serial etc.).

The current Nix wrapper produces exactly this geometry:
`--page-size 2048 --kernel-addr 0x40200000 --ramdisk-addr 0x45000000
--second-addr 0x40f00000 --tags-addr 0x44000000 --cmdline "bootopt=64S3,32N2,64N2"`
with `--dtb-mode append` (`nix/mainline.nix:1868-1880`). The stage-0 U-Boot carrier
uses LK's native `0x40080000` instead (also 512 KiB aligned; both work).

### 1.3 The jump: AArch32 LK -> ATF -> AArch64 payload

Immediately before handoff (`mt_boot.c:1753-1825`):

> `enter_critical_section();`
> `platform_uninit();`
> `arch_disable_cache(UCACHE);`
> `arch_disable_mmu();`

(`mt_boot.c:1753-1761`), then `platform_sec_post_init()` (`mt_boot.c:1764-1766`,
which is `mt_secure_call(0x82000101, 0, 0, 0)`, `platform.c:1024-1032`, a DAPC
SMC), then the watchdog kick (section 1.5), the log line
`"lk finished --> jump to linux kernel %s"` (`mt_boot.c:1819`) and

> `if (g_is_64bit_kernel) lk_jump64((u32)entry, (u32)tags, 0, KERNEL_64BITS);`

(`mt_boot.c:1824-1825`; `KERNEL_64BITS` = 1, `mt_boot.c:187`).
`lk_jump64` calls `jumparch64_smc(addr, arg1, arg2, arg3)` and then spins
(`mt_boot.c:807-815`). The stub:

> `FUNCTION(jumparch64_smc)`
> `  push {r4}; mov r4, r3; mov r3, r2; mov r2, r1; mov r1, r0`
> `  ldr r0, =0x82000200 /*MTK_SIP_KERNEL_BOOT_AARCH32*/`
> `  smc #0`

(`lk/arch/arm/exceptions.S:136-145`). So the SMC arguments are
x1 = entry (`kernel_addr`), x2 = tags (DTB physical address), x3 = 0, x4 = 1.

Upstream TF-A still routes that ID (`case MTK_SIP_KERNEL_BOOT_AARCH32: boot_to_kernel(x1, x2, x3, x4);`,
`arm-trusted-firmware/plat/mediatek/common/mtk_sip_svc.c:72-75`) but the
implementation was removed after v1.5. The v1.5 reference (mt6795 port, same
`mtk_plat_common.c` family as the mt6797 vendor ATF) is:

> `save_kernel_info(x1, x2, x3, x4); bl31_prepare_kernel_entry(x4);`

(`atf-history/mtk_plat_common.c-v1.5:81-96`, guarded by a `kernel_boot_once_flag`,
so **the SMC works once per ATF lifetime**), where for the 64-bit case
`k_info.r0 = r0; k_info.r1 = r1;` (`mtk_plat_common.c-v1.5:39-58`, r0 = LK's x2 =
tags) and

> `if (EL_IMPLEMENTED(2)) mode = MODE_EL2; else mode = MODE_EL1;`
> `next_image_info->spsr = SPSR_64(mode, MODE_SP_ELX, DISABLE_ALL_EXCEPTIONS);`
> `next_image_info->pc = get_kernel_info_pc();`
> `next_image_info->args.arg0 = get_kernel_info_r0();`
> `next_image_info->args.arg1 = get_kernel_info_r1();`

(`atf-history/mt6795-bl31_plat_setup-v1.5.c:349-360`), followed by
`cm_init_context(read_mpidr_el1(), next_image_info); cm_prepare_el3_exit(...)`
(`:426-450`).

**Probable kernel-entry contract (what the payload should expect, pending the
stage-0 measurement):**

| Item | Value | Evidence |
|---|---|---|
| Execution state | AArch64 | `SPSR_64(...)` above |
| Exception level | **EL2** is strongly expected; SP_ELx and masked DAIF follow the v1.5 reference | v1.5 source above; live device: `CPU: All CPU(s) started at EL2` (`artifacts/p22-recovery-20260831-005744-3248718/dmesg-pre:186`) |
| MMU / caches | LK disables both before the SMC; the v1.5 TF-A path then prepares a fresh non-secure context | `mt_boot.c:1759-1761`; exact live BL31 dispatch not decoded |
| x0 | expected physical address of the fixed-up DTB (`tags_addr`, 0x44000000) | LK SMC argument plus the v1.5 `save_kernel_info` path |
| x1 | expected 0 | LK passes `0` as arg2; final live BL31 mapping remains to be measured |
| x2, x3 | not defined by the contract; treat as garbage | -- |
| PC | `kernel_addr` (decompressed image start) | `mt_boot.c:1825` |
| CPUs | only CPU0 released; secondaries via PSCI | `dmesg-pre:31-34`: `psci: PSCIv0.2 detected in firmware.` |
| ATF residency | BL31 is resident and PSCI remains available. The `TZRAM_BASE (0x100000)` / `BL31_BASE (TZRAM_BASE + 0x1000)` constants are from the related mt8173 port (`plat/mediatek/mt8173/include/platform_def.h:74,93`), not an exact MT6797 source; they are consistent with the MT6797 disassembly VAs 0x100000-0x117000 in `ATF_WATCHDOG_HANDOFF.md`. DRAM side-areas are `atf-reserved-memory@44600000`, `atf-ramdump@44610000` (`gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:278-375`) and dynamic `mblock-2-atf-log-reserved` at `0x7ff40000` (`dmesg-pre:17`) | related-source inference plus exact disassembly/live DT evidence |
| Watchdog | **running**, 10 s, just kicked | section 1.5 |
| Payload constraints | gzip; 512 KiB-aligned `kernel_addr`; DTB appended; `bootopt=...64...`; <= 50 MiB decompressed | section 1.2 |

This expected state is one U-Boot's AArch64 `start.S` supports: "Could be
EL3/EL2/EL1, Initial State: Little Endian, MMU Disabled, i/dCache Disabled"
(`u-boot/arch/arm/cpu/armv8/start.S:117-119`) with the EL2 branch at `:127-134`,
and `doc/arch/arm64.rst:16-20`: "U-Boot can be entered in EL2 when its main
purpose is that of a boot loader." The LK packaging path itself is not
Linux-specific, so U-Boot is a credible payload when packaged like the accepted
Image.gz. This remains a testable conclusion, not proof of the exact live BL31
ABI. U-Boot must enter Linux directly and must *not* re-issue SMC 0x82000200;
the once-only behaviour comes from the historical v1.5 implementation and is a
constraint to preserve until the live firmware is understood more precisely.

### 1.4 Fastboot: server present, entry compiled out, `boot` gated by lock state

Registration API:

> `void fastboot_register(const char *prefix, void (*handle)(...), unsigned allowed_when_security_on, unsigned forbidden_when_lock_on)`

(`lk/app/mt_boot/fastboot.c:104-105`). Dispatcher (`fastboot.c:283-301`):

> `if ( !(sec_usbdl_enabled() || seclib_sec_boot_enabled(1)) || cmd->allowed_when_security_on )`
> `    if ((!cmd->forbidden_when_lock_on) || (0 != get_unlocked_status()))`
> `        cmd->handle(...)`
> ... `fastboot_fail("not support on security");` / `fastboot_fail("not allowed in locked state");`

Registration table, verbatim from `fastboot_init` (`fastboot.c:625-692`;
arguments are `(allowed_when_security_on, forbidden_when_lock_on)`):

```c
fastboot_register("getvar:", cmd_getvar, TRUE, FALSE);
fastboot_register("signature", cmd_install_sig, FALSE, TRUE);
fastboot_register("flash:", cmd_flash_mmc, TRUE, TRUE);
fastboot_register("erase:", cmd_erase_mmc, TRUE, TRUE);
fastboot_register("continue", cmd_continue, FALSE, FALSE);
fastboot_register("reboot", cmd_reboot, TRUE, FALSE);
fastboot_register("reboot-bootloader", cmd_reboot_bootloader, TRUE, FALSE);
fastboot_register("download:", cmd_download, TRUE, FALSE);
fastboot_register("oem p2u", cmd_oem_p2u, TRUE, FALSE);
fastboot_register("oem reboot-recovery",cmd_oem_reboot2recovery, TRUE, FALSE);
fastboot_register("oem unlock",fastboot_oem_unlock, TRUE, FALSE);
fastboot_register("oem lock",fastboot_oem_lock, TRUE, FALSE);
fastboot_register("oem key",fastboot_oem_key,TRUE, FALSE);
fastboot_register("oem lks",fastboot_oem_query_lock_state,TRUE, FALSE);
/* allowed when secure boot and unlocked */
fastboot_register("boot", cmd_boot, TRUE, TRUE);
fastboot_register("flashing unlock",fastboot_oem_unlock, TRUE, FALSE);
fastboot_register("flashing lock",fastboot_oem_lock, TRUE, FALSE);
fastboot_register("flashing get_unlock_ability", fastboot_get_unlock_ability, TRUE, FALSE);
```

(`oem off-mode-charge`, `oem ap_jtag`, `oem scp_status`, `oem usb2jtag`,
`oem mtkreboot`/`oem mrdump`, `set_active` are under feature `#ifdef`s that the
Gemini project does not set.) The lock-state default is `LKS_LOCK`
(`lk/platform/mt6797/sec_policy.c:101-108`); the live value comes from `libsec.a`.
The p20 binary contains `not support on security`, `not allowed in locked state`,
`[SEC_POLICY] lock_state = 0x%x`, `Orange State` / `Your device has been unlocked
and can't be trusted` (`lk-p20_strings.txt:2489-2491,3529-3531,4095-4096`), so the
gating code is compiled in. **Lock state of the device: I could not determine it
from source or strings; it is answered by whether the boot splash ever showed
"Orange State".**

`cmd_boot` (`lk/app/mt_boot/sys_commands.c:413-608`) is the RAM-boot path: header
and range checks against `DRAM_PHY_ADDR`, `_heap_end`, `MEMBASE`, `SCRATCH_ADDR`,
then `if (g_is_64bit_kernel) memmove((void *) SCRATCH_ADDR, ptr + page_sz, kernel_sz)`
(`:530-531`, note: uses the `g_is_64bit_kernel` computed earlier from the *partition*
header, not re-parsed from the RAM image), `cmdline_append(boot_hdr->cmdline)`
(`:567`), `udc_stop(); timer_cancel(&wdt_timer); mtk_wdt_restart();` (`:588-591`)
and `boot_linux(...)` (`:601`). `reboot-bootloader` is
`Set_Clr_RTC_PDN1_bit13(true); mtk_arch_reset(1);` (`sys_commands.c:401-407`).

How LK *enters* fastboot (`boot_mode_select`, `lk/platform/mt6797/boot_mode.c:81-261`):

- `meta_detection()` copies the preloader's boot mode: `g_boot_mode = FASTBOOT`
  when `g_boot_arg->boot_mode == FASTBOOT` (`lk/platform/common/meta.c:60-95`).
- `HAVE_LK_TEXT_MENU` is commented out for mt6797
  (`//#define HAVE_LK_TEXT_MENU`, `include/platform/mt_reg_base.h:530`), so the
  `#else` branch runs (`boot_mode.c:180-251`), where both the RTC check
  `Check_RTC_PDN1_bit13()` (`:185-192`, prints `[FASTBOOT] reboot to boot loader`)
  and the key check `mtk_detect_key(MT_CAMERA_KEY)` (`:222-228`) are inside
  `#ifdef MTK_FASTBOOT_SUPPORT`, and the target sets `MTK_FASTBOOT_SUPPORT := no`.
- The p20 strings contain ` => FASTBOOT mode...` (`lk-p20_strings.txt:2431`) but
  **not** `[FASTBOOT] reboot to boot loader` nor `[Fastboot    Mode]`
  (`boot_mode_menu.c:37`), consistent with the source configuration.
- `target/k97v1_64_bsp/init.c:70-99 fastboot_trigger()` does check RTC bit 13 and
  `MT_CAMERA_KEY` (=9, `cust_key.h:8`), but its only caller is `app/aboot/aboot.c:1364`,
  which this project does not build (`MODULES += app/mt_boot`, `k97v1_64_bsp.mk:4`).

The RTC mechanism itself is real: `RTC_PDN1 (RTC_BASE + 0x002c)`,
`RTC_PDN1_FAST_BOOT (1U << 13)` (`include/platform/mt_rtc_hw.h:174,185`), written
via PWRAP with `rtc_writeif_unlock`/`RTC_WRTGR` (`mt_rtc.c:85-97,263-286`), and the
vendor kernel sets it on `reboot bootloader`:
`else if (cmd && !strcmp(cmd, "bootloader")) { rtc_mark_fast(); }`
(`gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdk/wd_api.c:598-599`,
`rtc_mark_fast` -> `hal_rtc_set_spare_register(RTC_FAST_BOOT, 0x1)`,
`drivers/misc/mediatek/rtc/mtk_rtc_common.c:366-374`). **From this source the
only compiled-in ways into fastboot are the preloader passing `FASTBOOT` as boot
mode (META/preloader key handling, outside LK) and the mrdump USB path.** Whether
the preloader honours RTC bit 13 could not be determined here (no preloader
source). Do not build the plan on vendor fastboot; never run `oem unlock`.

### 1.5 Watchdog: armed at 10 s in early init, kicked, never stopped on the normal path

Arming happens in `platform_early_init()` (`platform.c:428`) via `mtk_wdt_init()`
(`platform.c:471`):

> `mtk_wdt_mode_config(FALSE, FALSE, FALSE, FALSE, FALSE);` ...
> `/* Setting timeout 10s */`
> `mtk_wdt_set_time_out_value(10);` ...
> `#if (!LK_WDT_DISABLE)`
> `    mtk_wdt_mode_config(TRUE, TRUE, TRUE, FALSE, TRUE);`
> `    mtk_wdt_restart();`
> `#endif`

(`lk/platform/mt6797/mtk_wdt.c:246-283`; `LK_WDT_DISABLE (0)`,
`include/platform/mtk_wdt.h:40`). `mtk_wdt_set_time_out_value`:
`timeout = value*(1<<6); timeout <<= 5; DRV_WriteReg32(MTK_WDT_LENGTH, timeout | MTK_WDT_LENGTH_KEY);`
(`mtk_wdt.c:171-182`) = 10*64<<5 | 0x8 = **0x5000 | 8**, which is exactly the
`length=0x00005000` Linux reads at probe (`dmesg-pre:1273`:
`mtk-wdt 10007000.watchdog: boot handoff: mode=0x00000035 length=0x00005000 status=0x00000000 interval=0x00000ffd`).

Mode discrepancy, stated honestly: the source call
`mtk_wdt_mode_config(dual_mode_en=TRUE, irq=TRUE, ext_en=TRUE, ext_pol=FALSE, wdt_en=TRUE)`
(`mtk_wdt.c:72-123`) would produce `DUAL_MODE|IRQ|EXTEN|AUTO_RESTART|ENABLE` =
0x5D, but the device reports 0x35 = `IN_DIS(0x20)|AUTO_RESTART(0x10)|EXTEN(0x4)|ENABLE(0x1)`
(bit names from `mtk_wdt.h:64-70`). I could not determine from source whether the
live p20 was built with different mode arguments or whether ATF/preloader rewrote
the mode word. What matters for the port is the same either way: **ENABLE is set,
IRQ is clear, so expiry is a hard reset, not an interrupt**, and the length is 10 s.
The live value 0x35 does **not** contain MT6797's `MTK_WDT_MODE_DDR_RESERVE`
bit 0x80 (`gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/mt6797/mt_wdt.h:46-53`).
The vendor kernel can set or clear that bit (`mtk_wdt.c:380-389`), but neither
the live handoff word nor the LK source proves that DRAM survives a TOPRGU reset.

The pre-jump kick:

> `/* Kick watchdog before leaving lk to avoid watchdog reset if kernel initialization has longer execution time. Of course watchdog will still be triggered if kernel hangs because watchdog is still alive. */`
> `mtk_wdt_restart();`

(`mt_boot.c:1806-1813`, ~12 lines before `lk_jump64`); `mtk_wdt_restart` is
`DRV_WriteReg32(MTK_WDT_RESTART, MTK_WDT_RESTART_KEY)` = `0x10007008 <- 0x1971`
(`mtk_wdt.c:184-190`). There is no `mtk_wdt_disable()` anywhere on the normal
boot path. Failure paths:

| LK situation | WDT behaviour | Evidence |
|---|---|---|
| `bldr_load_dtb fail` (DT partition unreadable) | only `dprintf`, boot continues; WDT untouched | `platform.c:634-641` |
| `kernel_addr` not 512 KiB aligned; gunzip fails; DTB not found; FDT edits fail | `while (1)` **with WDT running** -> hardware reset within <= 10 s | `mt_boot.c:949,1004,1024,1177-1195` |
| boot-image header unreadable / body unreadable / **verified-boot red state** | `msg_header_error`/`msg_img_error`: print banner, then `mtk_wdt_disable(); mdelay(8000); mtk_arch_reset(1);` -- WDT stopped but LK resets itself 8 s later | `mt_boot.c:279-315`, `2217-2218,2238-2239`; red path: `verified_boot_flow` -> `show_warning` -> `red_state_warning` ("Your device will boot in 5 seconds", kicks WDT around a 5 s delay) returns -1 -> `mboot_android_load_bootimg` returns `-EIO` | `load_image.c:190-205,225-234,319-393,1021-1024` |
| Orange state (unlocked) | 5 s splash with WDT kicks, then boots | `load_image.c:173-187` |
| boot menu (not compiled: `HAVE_LK_TEXT_MENU` off) | `mtk_wdt_disable(); ... boot_mode_menu_select(); mtk_wdt_init();` | `boot_mode.c:159-168` |
| DOWNLOAD_BOOT (SP Flash Tool DA) | `mtk_wdt_disable(); //Disable wdt before jump to DA` then `jump_da` | `platform.c:781-790` |
| fastboot mode | WDT kept alive by a 5 s periodic kick: `//mtk_wdt_disable();` `timer_set_periodic(&wdt_timer, 5000, mtk_wdt_restart)`; `cmd_boot` cancels the timer and kicks once before `boot_linux` | `fastboot.c:621-623`, `sys_commands.c:588-591` |

Conclusion: on the **normal post-handoff path**, LK deliberately hands the
payload a live 10 s watchdog, so a hang resets the device while that watchdog
remains enabled. This is not universal across LK: image/header/red-state,
DOWNLOAD_BOOT and menu paths explicitly stop it and then follow their own reset
or handoff behaviour, as the table shows. A chainloaded U-Boot inherits the live
normal-path counter: it must kick within 10 s of entry, keep kicking, and must not
silently stop the only established unattended-recovery mechanism.

## 2. Upstream LK versus U-Boot

### 2.1 Upstream LK (`/home/grw/src/lk`)

- `platform/mediatek/mt6797/`: `debug.c interrupts.c mt_gpt.c platform.c timer.c
  uart.c` + headers, **1415 lines total**; `ARCH := arm`, `ARM_CPU := cortex-a7`,
  `WITH_SMP ?= 0` (`platform/mediatek/mt6797/rules.mk:5-8`); MMU map marked
  `// XXX needs to be filled in`; `platform_early_init` does `uart_init_early();
  platform_init_interrupts(); gpt_init(); /* disable WDT */ DRV_WriteReg32(MTK_WDT_MODE, 0x22000000);`
  (`platform.c:25-77`). Project `mt6797.mk` adds only `app/shell` (`project/mt6797.mk:1-7`).
- No MediaTek MSDC, USB device controller, PMIC/PWRAP, pinctrl or clock driver.
  `dev/usb` is a generic device stack (`dev/usb/usb.c`, `dev/usb/class`) with no
  MTU3/MUSB glue. `lib/bootimage` is LK's own image format, not Android boot-v0.
  The only "fastboot" in the tree is the UEFI/GBL protocol header set under
  `lib/uefi/include/uefi/protocols/gbl_efi_fastboot*.h` (LK-as-UEFI-host for
  Android's Generic Bootloader), not a native fastboot server.
- No extlinux, no ext4 write path relevant to NixOS generations, no AArch64 port
  of any MediaTek platform (the mt6797 target is 32-bit).

### 2.2 U-Boot (`/home/grw/src/u-boot`)

| Area | What exists | Gemini gap |
|---|---|---|
| SoC framework | `arch/arm/mach-mediatek/{mt7622,7623,7629,7981,7986,7987,7988,8183,8188,8189,8195,8365,8512,8516,8518}`, `armv8-mem-map.c`, `cpu.c`, `spl.c`, `tzcfg.c` | no `mt6797`; the stage-0 branch adds `mach-mediatek/mt6797/{init.c,lowlevel_init.S}` (105 lines) |
| Entry from EL2, PIE | `start.S:61-104` (4 KiB alignment check + `.rela.dyn` fixup), `:117-162` (EL3/2/1 switch) | none |
| UART | `serial_mtk` matches `mediatek,hsuart` and `mediatek,mt6577-uart` (`drivers/serial/serial_mtk.c:308-311`); Gemini's uart0 is `mediatek,mt6577-uart`-compatible in the project DT and Linux `earlycon: mtk8250 at MMIO32 0x11002000 (921600n8)` works (`dmesg-pre:4`) | DT only; physical access to the UART pads remains unestablished |
| Watchdog | `drivers/watchdog/mtk_wdt.c:15-35` has the same offsets/keys (`MODE 0x00`, `LENGTH 0x04`, `RESTART 0x08`, `WDT_MODE_KEY (0x22 << 24)`, `WDT_LENGTH_KEY 0x8`, `WDT_RESTART_KEY 0x1971`); compatibles `mediatek,wdt`, `mediatek,mt6589-wdt`, ... (`:145-149`) | **probe ends with `return mtk_wdt_stop(dev);`** (`:122-135`). Using it unmodified would stop the inherited WDT; it needs an explicit "keep running, just pet" policy. |
| eMMC | `drivers/mmc/mtk-sd.c` with compatibles mt7620/7621/7622/7623/7986/7987/7981/8512/8516/8183/8189 (`:1995-2005`); `mt7623_compat` = `{clk_div_bits=12, pad_tune0, async_fifo, data_tune, busy_check=false, stop_clk_fix=false, enhance_rx=false}` (`:1913-1921`) | Linux `mt6797_compat` has **the same feature shape as mt7623** (`linux-gemini-platform/drivers/mmc/host/mtk-sd.c:583-594`, compatible at `:733`), so a compat entry is plausible. That is only compile-time matching: U-Boot requires named `source` and `hclk`, enables clocks and initializes the controller (`u-boot/drivers/mmc/mtk-sd.c:1724-1777,1806-1818`). The project Linux DT's 25 MHz/pinmux setup (`mt6797-gemini-pda.dts:302-365`) does not prove U-Boot runtime ownership. Read-only hardware validation is required. |
| USB device | **`drivers/usb/mtu3/`** provides the generic MTU3 gadget controller (compatible `mediatek,mtu3`, `mtu3_plat.c:463-475`) and `drivers/phy/phy-mtk-tphy.c` provides `mediatek,generic-tphy-v1/v2` (`:908-921`). Gemini's **left USB-C (the port Trex watches) is MTU3** at 0x11271000; the MUSB `usb11` at 0x11200000 is the host right port (`linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:159-188`; board mode/property at `mt6797-gemini-pda.dts:606-622`). This avoids a controller rewrite, but it is not just passive handoff: U-Boot enables clocks/regulator, initializes and powers PHYs, then resets the whole SSUSB IP (`u-boot/drivers/usb/mtu3/mtu3_plat.c:91-133,174-191`). Linux's `mediatek,force-b-session-valid` is not consumed by U-Boot, which reads `mediatek,force-vbus` and drives `VBUS_FRC_EN|VBUS_ON` (`mtu3_core.c:616-621,835-846`). The DT/property policy, MT6797 clocks and reset effects need validation. |
| fastboot | `drivers/fastboot/{fb_command,fb_common,fb_getvar,fb_mmc,...}`, `fastboot_boot()` runs `fastboot_bootcmd` or `bootm` (`fb_common.c:141-175`) | config |
| Android image | `boot/image-android.c`, `CONFIG_ANDROID_BOOT_IMAGE` (`boot/Kconfig:7-11`) | config |
| UEFI | `CONFIG_CMD_BOOTEFI=y` + `CONFIG_EFI_LOADER=y` enable UEFI applications on ARM; EFI loader requires block-device support (`doc/develop/uefi/uefi.rst:25-42`, `lib/efi_loader/Kconfig:3-40`) | Enable the EFI loader, block/FAT support and PE/COFF execution; prove `ExitBootServices()` repeatedly before calling the path reliable. |
| GOP / display | EFI setup registers GOP when `CONFIG_VIDEO` is enabled (`lib/efi_loader/efi_setup.c:352-356`). U-Boot's `simple-framebuffer` driver consumes base/size/width/height/stride/format (`drivers/video/simplefb.c:15-102`). | LK leaves scanout running (`lk/platform/mt6797/platform.c:909-921`) and writes framebuffer base/size into `/chosen` (`mt_disp_drv.c:450-468`); its framebuffer is 32-bit ARGB8888 and the panel is 1080x2160 (`primary_display.c:32-33`; `aeon_ssd2092_fhd_dsi_solomon.c:203-204`). First bind this inherited buffer; do not begin with a full MT6797 DSI port. Rotation and cache/stride details remain to be proven. |
| EFI console input | EFI installs Simple Text Input and Simple Text Input Ex (`lib/efi_loader/efi_console.c:1317-1330`) and polls U-Boot stdin (`:931-955`). | Gemini's keyboard is a polled AW9523 GPIO expander on I2C5 plus an 8x7 GPIO matrix (`linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:485-602`). U-Boot has neither an AW9523 driver nor a generic GPIO-matrix-keypad consumer. Its key-matrix helper can decode `linux,keymap` and optional `linux,fn-keymap` (`drivers/input/key_matrix.c:140-175`), but the current Gemini DT describes no Fn key/map. |
| extlinux | `boot/bootmeth_extlinux.c` (`extlinux_read_bootflow`, `:135`) | early diagnostic fallback only; it is not the NixOS destination |
| PMIC | `drivers/power/pmic/mtk-pwrap.c` supports `mediatek,mt6357` and `mediatek,mt6359` only (`:650-662`) | MT6351 absent; not needed while rails are inherited from LK |
| pinctrl / clk | `drivers/pinctrl/mediatek/pinctrl-mt{7622..8518}.c`, `drivers/clk/mediatek/clk-mt{...}.c`; none for mt6797 | Linux has `clk-mt6797.c` (731 lines) and `pinctrl-mtk-mt6797.h` (2443 lines) to port *later*; not needed for the inherited-state stages |

### 2.3 Side-by-side capability comparison

| | upstream LK | U-Boot |
|---|---|---|
| MT6797 base | 32-bit A7 target, UART/GIC/GPT only, WDT disabled | none upstream; a minimal stage-0 exists locally |
| AArch64 | generic `arch/arm64` exists, but no MediaTek AArch64 platform at all | first-class |
| Console/timer | UART exists (32-bit target) | `serial_mtk` + arch timer: DT only |
| Watchdog | must implement | driver exists; inherited-counter policy must change |
| eMMC + GPT + FAT/ext4 | must port MSDC | matching controller shape exists; clocks/reset/runtime ownership remain unproven |
| USB gadget + fastboot | must port MTU3 and fastboot | MTU3, generic T-PHY and fastboot exist; MT6797 resources/property policy remain |
| Android-v0 image / `booti` / FDT fixup / PSCI | must implement or integrate | exists |
| UEFI / GOP / systemd-boot | no complete path here | EFI loader and GOP exist; Gemini framebuffer and input integration remain |
| Native keyboard | no AW9523/matrix path | no AW9523/matrix consumer; EFI console can use one once added |

U-Boot wins decisively because the high-level boot, EFI, block and USB stacks
already exist. This comparison does not predict the amount of MT6797-specific
bring-up work; inherited clocks, resets and PHY state must be tested rather than
priced by source-line estimates.

## 3. Chainload analysis and memory map

Fixed low reservations (`mt6797-gemini-pda.dts:51-110`, confirmed live at
`dmesg-pre:7-28`):

| Region | Purpose |
|---|---|
| `0x40000000..0x40000fff` | first page, no-map |
| `0x44000000` | LK tags/DTB (`--tags-addr 0x44000000`) |
| `0x44400000..0x4440ffff` | ram_console |
| `0x44410000..0x444effff` | ramoops/pstore |
| `0x444f0000..0x444fffff` | minirdump / project trace |
| `0x44600000..0x4460ffff` | ATF reserved (no-map) |
| `0x44610000..0x4463ffff` | ATF ramdump |
| `0x44640000..0x4466ffff` | cache-dump |
| `0x44800000..0x448fffff` | preloader |
| `0x45000000` | ramdisk load address (Android header) |
| `0x46000000..0x463fffff` | vendor LK (4 MiB) |
| `0x46900000..0x4e8fffff` | LK scratch / download area (128 MiB; 64-bit kernel field is staged here before gunzip) |

plus dynamic firmware reservations near the top of the 2 GiB boot bank: CCCI
`0x88000000-`, `0xb4000000-0xbebfffff`, framebuffer `0x7dfb0000-0x7ff3ffff`,
ATF log `0x7ff40000-0x7ff7ffff`, log-store `0x7ff80000-0x7fffffff`, SCP
`0x8f000000`, `0xbfdf0000` (`dmesg-pre:7-18`).

Consequences:

1. **Load/link at `0x40080000`** (LK's native kernel address; 512 KiB aligned for
   LK, 4 KiB aligned for U-Boot PIE). `u-boot.bin` is well under the 50 MiB gunzip
   limit. At the moment of entry LK's copy of the still-compressed field sits in
   scratch at `0x46900000+`, the DTB at `0x44000000`, the ramdisk at `0x45000000`;
   U-Boot's image and early stack at `0x40080000..~0x40400000` collide with none of
   them.
2. **Relocation ceiling.** U-Boot relocates itself to the top of `gd->ram_size`;
   left to itself that is `0x13fffffff`, inside dynamic reservations U-Boot has not
   imported. Cap `board_get_usable_ram_top()` below `0x44000000` for the early
   stages (the stage-0 branch exposes `0x40001000..0x43ffefff` and reserves
   `0x43fff000` as a trace page, `u-boot-gemini-stage0/arch/arm/dts/mt6797-gemini-pda.dts:23-38`).
3. **Before booting Linux**, import the prior-stage DTB's `/reserved-memory` (the
   one in x0) plus U-Boot's own region into LMB, then choose kernel/initrd
   addresses. Never place anything in ramoops, `0x46000000..0x463fffff`, the ATF
   areas, or the dynamic CCCI/SCP/framebuffer/log regions.
4. **Keep the stock ATF and PSCI.** U-Boot runs at EL2, non-secure; BL31 stays
   resident; secondaries come up through PSCI v0.2 as today. Do not attempt SMP in
   the loader. Do not call SMC 0x82000200 again: the once-only flag is evidenced
   by the historical implementation, and there is no reason to depend on a
   second invocation from the live firmware (section 1.3).
5. **AArch32 -> AArch64** is ATF's job and already done by the time U-Boot runs;
   there is no execution-state problem to solve in U-Boot.
6. **Watchdog**: record the inherited registers, force direct-reset mode, and
   kick at the first instruction that can (stage-0 does this in
   `save_boot_params`), then kick from `board_early_init_f`,
   `board_init`, `board_late_init`, and from the main loop via the WDT uclass with
   a driver that *does not* stop the counter at probe.
7. **DTB for Linux**: U-Boot can either pass through the LK-fixed-up DTB from x0
   (which carries LK's bootargs, memory node, boot-state, serial number and the
   dynamic reservations) or load its own from p29 and copy `/reserved-memory`
   from the x0 tree. Pass-through is the safer first step.

## 4. Staged plan

Each U-Boot payload update in stages 0-5 is a single, explicitly authorised
p22-only Download-Only transaction with pre/post hashes
(`CATCHUP.md:225-233`). p20, p21, p29-p31, GPT, modem and ATF partitions are not
written in those stages. Stage 6 is a separate p29 migration with its own review,
authorisation, backup and rollback procedure; it is not covered by p22 approval.

### Stage 0: prove entry, preserve recovery (exists, device-unproven)

`/home/grw/src/u-boot-gemini-stage0` commit `94a4e9d7` "arm: mediatek: add Gemini
MT6797 stage-0 target": `configs/mt6797_gemini_stage0_defconfig`
(`CONFIG_POSITION_INDEPENDENT=y`, `CONFIG_TEXT_BASE=0x40080000`,
`CONFIG_COUNTER_FREQUENCY=13000000`, `CONFIG_NULLDEV_SERIAL=y`, PSCI reset and
all commands off), `arch/arm/mach-mediatek/mt6797/lowlevel_init.S`
(`save_boot_params`: records x0-x3, `CurrentEL`, `SCTLR_ELx`, MPIDR, CNTFRQ,
CNTVCT and the four WDT registers into a 0xa8-byte record at `0x43fff000`, kicks
the WDT with `0x1971`, magic-last commit), `board/planet/gemini/gemini.c` (stage
markers 2/3/4 from `board_early_init_f`/`board_init`/`board_late_init`, each with a
WDT kick, then `msr daifset, #0xf; wfi` forever: "Do not pet or stop LK's
watchdog: recovery is the stage-0 exit path"). After recording LK's original
mode word, the first-instruction path preserves unrelated mode bits, clears
`DUAL_MODE|IRQ|EXT_POL`, and sets `AUTO_RESTART|EXTEN|ENABLE` with the hardware
write key before the first kick. Thus even an LK image that selected IRQ/dual
mode cannot leave stage 0 waiting forever. The carrier builder is
`/home/grw/src/nixos-gemini/tools/build-android-uboot-v0.py`.

Acceptance: after the deliberate WDT reset the next recovery boot reads a valid
record at `0x43fff000` with `current_el == 0x8`, `args[0] == 0x44000000`, and
`wdt_mode/length` matching `dmesg-pre:1273`. Unknown to preflight: **whether
`0x43fff000` survives the WDT reset** (DRAM retention through TOPRGU reset is not
established; absence of a record is not proof of non-entry). A USB identity is
the better first-light signal if stage 1's gadget can be brought up cheaply.

### Stage 1: USB gadget + fastboot boot (no storage writes)

- Add `mediatek,mt6797-mtu3` to the U-Boot DT with the Linux node/PHY/clock
  description; `CONFIG_USB_MTU3_GADGET`, `CONFIG_USB_FUNCTION_FASTBOOT`, unique
  VID:PID so Trex can distinguish it from Linux's gadget. U-Boot's driver enables
  resources, powers the PHY and resets SSUSB; do not describe this as merely
  preserving LK's PHY state (`mtu3_plat.c:91-133,174-191`). Resolve the Linux
  `mediatek,force-b-session-valid` versus U-Boot `mediatek,force-vbus` mismatch
  explicitly and validate the safe forced-VBUS behaviour before enabling it
  (`mtu3_core.c:616-621,835-846`).
- `fastboot boot` a known-good `Image.gz`+initrd+DTB from the host; U-Boot
  `bootm` handles the Android-v0 container (`CONFIG_ANDROID_BOOT_IMAGE`), or use
  `fastboot_bootcmd` = `booti` with explicit addresses checked against section 3.
- Gives a storage-write-free kernel iteration loop even though vendor fastboot
  is unreachable.

### Stage 2: UEFI execution smoke test (no storage writes)

- Enable `CONFIG_CMD_BOOTEFI`, `CONFIG_EFI_LOADER`, block support and PE/COFF
  execution (`u-boot/doc/develop/uefi/uefi.rst:25-42`,
  `u-boot/lib/efi_loader/Kconfig:3-40`). Keep non-volatile EFI variables disabled
  with `CONFIG_EFI_VARIABLE_NO_STORE` during all read-only stages
  (`lib/efi_loader/Kconfig:112-169`).
- Download a small AArch64 EFI application over the Stage-1 USB path and invoke
  it with `fastboot_bootcmd=bootefi ...`. This proves the EFI entry/return path
  without an ESP, GPT change or block-device write.
- Repeat the test across watchdog resets and recovery boots. A downloaded
  systemd-boot binary may be a later smoke payload, but it is not yet the boot
  path because there is no approved ESP or input/display contract.

### Stage 3: read-only eMMC and diagnostic fallback

- Add the `mediatek,mt6797-mmc` compatible using the mt7623 feature shape, then
  supply and validate the required `source`/`hclk`, reset and pin state. Start at
  25 MHz and 8-bit as described by the project DT. U-Boot actively enables
  clocks and initializes MSDC (`u-boot/drivers/mmc/mtk-sd.c:1724-1777,1806-1818`),
  so inherited hardware state is a hypothesis, not the implementation.
- Enumerate GPT and list/read the existing p29 filesystem. Verify kernel, initrd,
  DTB and EFI-file hashes against Trex. Do not create a filesystem, repair one,
  save an environment, persist EFI variables or write any partition.
- An extlinux entry may be exercised here as a diagnostic fallback if the
  existing filesystem permits it. It does not become the update or menu design.

### Stage 4: inherited-framebuffer GOP

- Keep LK's already-running panel/scanout. A Gemini board shim reads
  `atag,videolfb-fb_base_{h,l}` and `atag,videolfb-vramSize` from the prior DT's
  `/chosen` (`gemini-lk-android8/lk/platform/mt6797/mt_disp_drv.c:450-468`),
  reserves that memory, and supplies a `simple-framebuffer` node with validated
  base, size, 1080x2160 dimensions, stride and 32-bit ARGB format. U-Boot's
  simplefb driver consumes those properties (`u-boot/drivers/video/simplefb.c:15-102`).
- Enable `CONFIG_VIDEO`; EFI then registers GOP
  (`u-boot/lib/efi_loader/efi_setup.c:352-356`). Acceptance is stable U-Boot text,
  an EFI application's graphics output and repeated handoff without corrupting
  the inherited scanout. Panel rotation, stride and cache coherency must be
  measured; a native MT6797 DSI driver is later work only if inheritance fails.

### Stage 5: native keyboard -> EFI Simple Text Input

- Bring up I2C5 read-only first. Linux maps `mediatek,mt6797-i2c` to its mt8173
  data (`linux-gemini-platform/drivers/i2c/busses/i2c-mt65xx.c:753-754`), while
  U-Boot's MediaTek I2C table has no MT6797 entry
  (`u-boot/drivers/i2c/mtk_i2c.c:814-881`); clocks and pin state still need proof.
- Add a minimal AW9523 GPIO-expander driver and a polling GPIO-matrix keyboard
  consumer for the board's 8x7 matrix
  (`linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797-gemini-pda.dts:485-602`).
  Connect it to U-Boot stdin. EFI's console layer then exposes Simple Text Input
  and Simple Text Input Ex and polls that stdin (`u-boot/lib/efi_loader/efi_console.c:931-955,1317-1330`).
- First acceptance is reliable arrows and Enter in an EFI menu. Then validate
  Shift/Ctrl/Alt/Meta modifiers. The physical Fn modifier is a known unresolved
  hardware/software gap: the current Gemini keymap has neither a Fn matrix entry
  nor `linux,fn-keymap`, although U-Boot's helper can decode an optional Fn map
  (`u-boot/drivers/input/key_matrix.c:140-175`). Do not claim full keyboard input
  until Fn and modifier behaviour are measured and mapped.

### Stage 6: authorised p29 FAT ESP + systemd-boot + NixOS UKIs

- Review p29's current contents and produce verified backup, restore and
  power-loss rollback procedures. Only a new, explicit authorisation may migrate
  p29 to the chosen FAT ESP layout. Stages 0-5 do not imply this permission.
- Install `systemd-bootaa64.efi` at the architecture fallback path
  `EFI/BOOT/BOOTAA64.EFI`, plus the reviewed systemd-boot/UKI layout for NixOS.
  U-Boot provides EFI loader, GOP and Simple Text Input; systemd-boot provides
  the graphical generation menu; the selected UKI enters NixOS. Extlinux remains
  a diagnostic fallback.
- Choose EFI-variable persistence deliberately. The safe pre-migration policy is
  `CONFIG_EFI_VARIABLE_NO_STORE`. If persistent variables are required after the
  ESP exists, `CONFIG_EFI_VARIABLE_FILE_STORE` stores `/ubootefi.var` on the ESP
  (`u-boot/lib/efi_loader/Kconfig:112-169`); that file is then part of the p29
  write/backup policy, not an accidental side effect. The fallback EFI path keeps
  first boot independent of a pre-existing Boot#### variable.
- Acceptance requires repeated graphical-menu boots, native-keyboard selection,
  successful `ExitBootServices()`, NixOS UKI rollback, watchdog recovery and a
  demonstrated p29 restore. Only then may NixOS manage normal boot updates.

### Stage 7 (optional, much later): p20 with p21 fallback

Only worth it if the p22-chainload path proves insufficient (it should not).
p20-p26 are behind eMMC power-on write protection
(`MTK_POWER_ON_WRITE_PROTECT`, `platform/mt6797/rules.mk:77-83`) and are the
least recoverable partitions; a U-Boot in p20 would need the MTK LK header
(magic `0x58881688`) and would have to re-implement everything LK does before the
jump (DRAM is preloader's job, but PMIC rails, pads, clocks, display, eMMC init and
the SMC handoff are LK's). Keep vendor LK.

## 5. Risks and unknowns

1. **Entry state measured only for Linux.** EL2/x0 are source-derived plus
   `All CPU(s) started at EL2`; stage 0 records the exact registers.
2. **Relocation into firmware reservations** if the RAM ceiling is not capped.
3. **Inherited 10 s watchdog**: too slow to kick -> reset before USB enumerates;
   `mtk_wdt` probe stops it -> recovery mechanism lost. Stage 0 now also forces
   direct-reset mode before its first kick, so it does not trust LK's IRQ/dual
   selection. These are policy bugs to avoid, not hardware limits.
4. **DRAM retention across WDT reset** is unknown. Live WDT mode 0x35 lacks the
   DDR-reserve bit 0x80, so a missing stage-0 record cannot distinguish failed
   entry from lost DRAM.
5. **USB reset/PHY/clock ownership**: U-Boot enables resources and resets SSUSB;
   it does not simply continue LK's state. Linux's
   `mediatek,force-b-session-valid` also has no direct U-Boot equivalent; the
   driver's `mediatek,force-vbus` behaviour must be reviewed and measured.
6. **eMMC ownership** requires named clocks and active controller initialization;
   matching mt7623's feature shape is not a hardware proof. Independent later
   bring-up may need MT6797 clk/pinctrl and MT6351 PWRAP (absent in U-Boot;
   MT6357/MT6359 only).
7. **Vendor fastboot unreachable and lock state unknown**; never `oem unlock`.
8. **p29 policy**: writing it is forbidden today; the migration needs its own
   authorisation and a rollback image.
9. **Source/binary fidelity**: the WDT mode word (0x35 vs 0x5D) shows the live
   binary is not byte-for-byte this source; other branches may differ too.
10. **No proven UART access**; first light must be USB or a memory record.
11. **Once-only SMC**: a payload that expects to re-enter ATF's kernel-boot SMC
    may hang; the flag is historical-source evidence, not a decoded property of
    the exact live BL31. U-Boot has no need to call it and must enter Linux itself.
12. **Inherited framebuffer details**: base/size are passed, but stride, rotation,
    cache policy and continued scanout across U-Boot operations remain unproven.
13. **Native keyboard gap**: U-Boot lacks the AW9523/matrix consumer; the physical
    Fn modifier is not represented by the current keymap.
14. **EFI state and shutdown**: choose no-store versus `/ubootefi.var`
    deliberately, and test repeated `ExitBootServices()` rather than assuming an
    EFI application that starts once proves an OS handoff.

## Recommendation

Proceed with **U-Boot, chainloaded from the unchanged vendor LK/ATF as the p22
kernel payload**. Do not port upstream LK and do not replace p20/p21. Package
U-Boot as gzip at 512 KiB-aligned `0x40080000` with a DTB appended and
`bootopt=64S3,32N2,64N2`, cap relocation below `0x44000000`, put the inherited
watchdog in direct-reset mode before the first kick, keep it running, and give
Trex a unique USB identity. Treat
EL2, x0 = DTB at 0x44000000, disabled MMU/caches and the historical once-only SMC
as strong expectations for stage 0 to measure, not an exact decoded live ABI.

The destination is **stock LK/ATF -> p22 U-Boot -> UEFI/GOP/Simple Text Input ->
`systemd-bootaa64.efi` -> NixOS UKI**. Reach it in reversible gates: USB and a
downloaded EFI smoke payload; read-only eMMC; inherited-framebuffer GOP; native
AW9523/matrix input; then, and only with separate authorisation, a backed-up p29
FAT ESP migration with an explicit EFI-variable policy and tested rollback.
Extlinux is an early diagnostic fallback, not the architecture. U-Boot remains
the right base because its EFI, graphics-console, block, MTU3, fastboot and image
frameworks already exist, but MT6797 clocks, resets, PHY, framebuffer and input
integration are real bring-up work whose size should not be guessed in advance.
