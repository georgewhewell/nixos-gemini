# MT6797 BTIF runtime evidence — next gate

Date: 2026-08-30  
Scope: Gemini/MT6797 CONSYS WMT/BTIF runtime only.  This packet is
read-only research; no device write, reboot, flash, raw MMIO, or raw I2C was
performed.

The source revision reviewed is the vendor tree at
`/home/grw/src/gemini-linux-kernel-3.18` (the reviewed source revision used by
the earlier packet is `8cfe6596a503612e3332d9c26e292a19525a7f07`).  Live log
citations below are retained repository artifacts, not a new device action.

## Executive verdict

Four things are now firm:

1. The observed Gemini uses `WMT_SOC.cfg`, then
   `ROMv3_patch_1_1_hdr.bin`, then `ROMv3_patch_1_0_hdr.bin` on the captured
   boot.  This is observed runtime order, not a vendor-source filename table.
2. Those files come from Android's `system` EXT4 partition, exposed to the
   Android helper as `/system/vendor/firmware` (and helper-side
   `/vendor/firmware`).  The kernel itself requests bare names through
   `request_firmware()`; it does not contain a Gemini-specific search list.
3. The 2 MiB CONSYS reservation and its runtime address are known.  It is an
   AP/CONNSYS shared EMI/debug area, not evidence that the firmware patch body
   is loaded there.  The patch protocol's per-image address is supplied by the
   WMT patch-search owner and remains unknown from the checked-in kernel source.
4. BTIF is an internal AP↔CONSYS transport in the reviewed implementation:
   its wake signal is a BTIF register bit named `ap_wakeup_consyss`, and the
   BTIF driver has no GPIO/pinctrl/pad handling.  No external BTIF pad mux
   should be added.  Board-level CONSYS control pins (BGF EINT, GPS LNA,
   optional GPS sync/I2S) remain separate and are not resolved here.

The implementation gate is therefore **not** “guess a pin and send a patch”.
It is: obtain the exact device patch payloads or deliberately validate the
public replacement, implement one CONSYS owner with the state machine below,
and stop before any patch transfer if the per-image address metadata or the
2 MiB reservation is absent.

## Firmware provenance and exact observed sequence

The retained live capture records:

```text
/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-postreboot-20260714.txt:63-64
hif_path=vendor_WMT_initializes_HIF-SDIO_then_opens_BTIF_for_Bluetooth
firmware_sequence=WMT_SOC_cfg_then_ROMv3_patch_1_1_then_ROMv3_patch_1_0

/home/grw/src/nixos-gemini/artifacts/preloader-catch/live-gemian-20260829-194813/dmesg.txt:3625-3639
(NULL device *): Direct firmware load for WMT_SOC.cfg failed with error -2
(NULL device *): Falling back to user helper
[HIF-SDIO][I]wmt_dev_patch_get:loader firmware WMT_SOC.cfg  ok!!

/home/grw/src/nixos-gemini/artifacts/preloader-catch/live-gemian-20260829-194813/dmesg.txt:4083-4091
(NULL device *): Direct firmware load for ROMv3_patch_1_1_hdr.bin failed with error -2
(NULL device *): Falling back to user helper
[HIF-SDIO][I]wmt_dev_patch_get:loader firmware ROMv3_patch_1_1_hdr.bin  ok!!
[WMT-IC][I]...:[Patch]BuiltTime = 20180307b001005, HVer = 0x8a00, SVer = 0x8a00, PhVer = 0x00fa,Platform = 1715

/home/grw/src/nixos-gemini/artifacts/preloader-catch/live-gemian-20260829-194813/dmesg.txt:4110-4113
(NULL device *): Direct firmware load for ROMv3_patch_1_0_hdr.bin failed with error -2
(NULL device *): Falling back to user helper
[HIF-SDIO][I]wmt_dev_patch_get:loader firmware ROMv3_patch_1_0_hdr.bin  ok!!
```

The source explains why this is a sequence returned by a runtime owner rather
than a hard-coded filename list.  `wmt_ctrl_patch_search()` sends exactly
`"srh_patch"` to the userspace command owner
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:545-557`).
The returned entry is indexed by download sequence and copies both
`patchName` and four address bytes
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:570-592`).
The full name is loaded first, with a default name attempted only if that
fails (`wmt_ctrl.c:800-834`).  The Linux-side loader is just:

```c
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/linux/wmt_dev.c:428-447
iRet = request_firmware((const struct firmware **)&fw, pPatchName, NULL);
```

**Search-order result:** the exact observed runtime order is closed above.
An exact vendor filename *candidate search order* is **could not determine**:
the helper implementing `srh_patch` is outside this checked-in kernel source.
The mainline driver must use the firmware class with canonical names and must
not encode `/system/vendor/firmware` as a kernel-only assumption.

The public checked-in Android system image gives the storage boundary.  It is
`/home/grw/src/nixos-gemini/firmware/Gemini_x25_x27_06052019/system.img`, an
Android sparse image which was converted read-only to an ignored local file
for inspection.  The retained partition map identifies it as:

```text
/home/grw/src/nixos-gemini/artifacts/preloader-catch/Gemini_ixoo_default_boot_only.txt:496-505
partition_name: system
file_name: system.img
type: EXT4_IMG
linear_start_addr: 0xe000000
physical_start_addr: 0xe000000
partition_size: 0xa0000000
region: EMMC_USER
```

The following read-only artifact command output lists the actual image
directory:

```text
debugfs -R 'ls -l /vendor/firmware' .local-fw-work/system.ext4
ROMv3_patch_1_0_hdr.bin  211908
ROMv3_patch_1_1_hdr.bin   46472
WIFI_RAM_CODE_6797       451904
WMT_SOC.cfg                   80
```

The image copy and the checked-in firmware files have these hashes:

```text
WMT_SOC.cfg                 f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880
ROMv3_patch_1_0_hdr.bin     d85864206b999501568a69edd8305319f9961fb65d56f77f438be29ff05c57a8
ROMv3_patch_1_1_hdr.bin     8982bba207df136fe56be1b9d5f394d89128b3fd41977a8741928fe105399784
WIFI_RAM_CODE_6797         c28c50efd411c591372b3a57a46cb99709db56e6cd86d65022af2baa88d840a6
```

These public-image patch hashes do **not** match the hashes from the observed
Gemian installation, retained at
`/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-postreboot-20260714.txt:66-70`:

```text
ROMv3_patch_1_0_hdr.bin     450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630
ROMv3_patch_1_1_hdr.bin     5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e
```

The WMT config and Wi-Fi blob do match.  Therefore the exact production
Gemini patch payload is **not present in Git**; the sanitized live archive
records its identity but deliberately does not redistribute it.  A test using
the public image must be labelled a replacement-firmware experiment, not
“the known-good device firmware”.

## Patch address and EMI layout

The vendor source makes three distinct address facts explicit:

* The board-independent reserved-memory node is 2 MiB, no-map, 2 MiB aligned,
  allocated in `0x40000000..0xc0000000`
  (`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:329-335`).
* The live vendor boot placed it at `0xbfa00000..0xbfbfffff`, as recorded in
  `/home/grw/src/nixos-gemini/artifacts/preloader-catch/live-gemian-20260829-194813/dmesg.txt:19-21`.
  The source callback stores that DT address in `gConEmiPhyBase`
  (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:1064-1072`).
* The source maps the debug/shared area at `gConEmiPhyBase + SZ_1M / 2` and
  length `CONSYS_EMI_MEM_SIZE`; the constants are `CONSYS_EMI_FW_PHY_BASE =
  0xf0080000`, `CONSYS_EMI_MEM_SIZE = 343*KBYTE`, and dump offsets
  `0x400/0x8400/0x10400`
  (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:191-199`,
  `mtk_wcn_consys_hw.c:1034-1053`).

The patch body is a different protocol path.  The source removes a 28-byte
`WMT_PATCH` header, sends a WMT patch-address command, then sends body
fragments of at most 1000 bytes
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2094-2146`).
For `icId == 0x0279`, it mutates the base command bytes at offsets 8/9 to
`08 05` and the partial-address command bytes to `2c 0b`
(`wmt_ic_soc.c:2162-2169`).  These are exact protocol bytes and the source
comment calls them “MT6797 patch RAM base”; they are **not** proof that the
patch body belongs in AP EMI.  The second command receives the four-byte
`addressByte` returned by the `srh_patch` owner (`wmt_ic_soc.c:2194-2200`).

The numeric per-image load addresses and the helper's algorithm which chooses
them are **could not determine** from the checked-in source or sanitized
artifacts.  Do not promote `08 05`, `2c 0b`, `0xf0080000`, or the runtime AP
reservation address into a guessed universal firmware load address.

## Ownership and handshake state machine

The vendor source supports this implementation order:

```text
OFF
  -> POWERED
  -> STP_OPEN
  -> STP_MANDATORY
  -> CHIP_ID_VERIFIED
  -> SOC_INIT / BTIF_FULL
  -> PATCH_DISCOVERED
  -> PATCH_1..N_DOWNLOADED
  -> STP_READY
  -> FUNCTION_ON (HCI/GPS/Wi-Fi clients)
```

Evidence for each transition:

* `opfunc_pwr_on()` rejects an already-powered WMT owner, invokes
  `WMT_CTRL_HW_PWR_ON`, marks `DRV_STS_POWER_ON`, runs `wmt_core_stp_init()`,
  and only then marks WMT function-on
  (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:1026-1087`).
* `wmt_core_stp_init()` opens STP, disables/un-readies it, selects
  `MTKSTP_BTIF_MAND_MODE`, enables STP, and then calls `wmt_core_hw_check()`
  (`wmt_core.c:726-786`).
* `wmt_core_hw_check()` reads the chip ID, accepts `0x0279` into the SOC ops
  table, runs version checking, and stores the selected SOC operation
  (`wmt_core.c:909-1002`).  The captured device answered `0x279` and
  `SOC_CONSYS.E1 (0x8a00/0x8a00)` at
  `/home/grw/src/nixos-gemini/artifacts/preloader-catch/live-gemian-20260829-194813/dmesg.txt:4054-4061`.
* `mtk_wcn_soc_sw_init()` for BTIF performs the STP query/set sequence,
  switches host mode to `MTKSTP_BTIF_FULL_MODE`, enables it, waits 10 ms,
  queries again, and only then enters patch preparation
  (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1008-1055`).
* Patch preparation is an explicit `WMT_CTRL_PATCH_SEARCH`, followed by
  per-index name/address retrieval and full-name firmware loading
  (`wmt_ic_soc.c:2030-2040`, `wmt_ic_soc.c:2072-2087`; `wmt_ctrl.c:570-592,
  800-834`).  Every patch address and fragment has a corresponding event
  length/status check (`wmt_ic_soc.c:2171-2220`, `2222-2266`).
* Only after SOC init returns does the core set `WMT_STP_CONF_RDY = 1`
  (`wmt_core.c:795-811`).  The live log shows this exact late transition:
  `mtk_wcn_stp_ready:[I] set ready (1)` at
  `/home/grw/src/nixos-gemini/artifacts/preloader-catch/live-gemian-20260829-194813/dmesg.txt:4291-4295`.

The BTIF user-owner handshake is separate from the CONSYS power owner.  The
BTIF public API requires an owner ID and calls `btif_open()` before adding the
user (`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/mtk_btif_exp.c:74-149`).
The wake operation is only valid for that opened owner and calls
`btif_raise_wak_signal()` (`mtk_btif_exp.c:348-373`).  The core then pulls the
internal register bit low for 64–96 µs and high again; the source comments
name the signal `ap_wakeup_consyss`
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:1078-1111`).

## Pad/mux conclusion

The BTIF DT node supplies only `reg`, one interrupt, and the two clocks
(`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:2511-2517`).
The BTIF platform code obtains its register base with `of_iomap()`, parses the
interrupt, and obtains `btifc`/`apdmac` clocks
(`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/btif_plat.c:192-205`,
`264-279`).  A bounded source search of the complete BTIF directory found no
GPIO, pinctrl, pinmux, or pad API use.  The wake register is explicitly:

```c
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/btif/common/plat_inc/btif_priv.h:39-45
#define BTIF_WAK(base) (unsigned long)(base + 0x64) /*BTIF module wakeup Register: write only */
#define BTIF_HANDSHAKE(base) (unsigned long)(base + 0x6C) /*BTIF New Handshake Control Register */
```

Therefore the working conclusion is **no external BTIF pad mux is evidenced;
BTIF is an internal AP↔CONNSYS path**.  This is stronger than “pads not yet
found”, but it does not resolve board-level CONSYS EINT or optional GPS/I2S
pins.  The latter are handled by the CONSYS owner (`PIN_BGF_EINT`,
`PIN_GPS_SYNC`, `PIN_GPS_LNA`, `PIN_I2S_GRP`) at
`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:757-789`.

## Negative gates for implementation

Do not proceed to a live patch transfer unless all of these are true:

* A single CONSYS owner has acquired the four rails/clocks and the 2 MiB
  no-map reservation; absent reservation is a hard failure, not a reason to
  fall back to ordinary DMA memory.
* BTIF/APDMA is opened and the transport has a verified mandatory STP parser;
  no HCI, Wi-Fi, GPS, or arbitrary TX consumer may bypass this owner.
* The chip query returns `0x0279` and the SOC version check accepts the E1
  tuple `0x8a00/0x8a00` (or a newly evidenced tuple).
* `srh_patch`-equivalent discovery returns each canonical filename **and its
  four address bytes**.  Missing address metadata is a hard stop.
* Each patch-address command receives the expected event, every fragment is
  acknowledged, and only then is STP marked ready.
* The exact device patch hashes are either supplied privately for the test or
  the public-image substitution is explicitly recorded as unvalidated.  The
  checked-in public patch bytes are not the hashes observed on Gemian.
* No GPIO83/84, GPIO224–233, GPS LNA, or UART pin is assigned to BTIF by
  analogy.  External mux work requires a separate board-level artifact.

## Exact next implementation/hardware gate

Implementation may begin against the internal BTIF register path and the
vendor state machine, with firmware loading abstracted behind a strict
`name + 4-byte address` discovery interface.  The next decisive gate is a
read-only artifact or controlled lab trace that reveals the two production
patch `addressByte[4]` values returned after `srh_patch`, and establishes
whether the public 20180615 payload can replace the observed 20180307 payload.
Until that gate closes, a safe RX-only test may validate register/clock/STP
parser plumbing only; it must not send patch data, HCI commands, or radio
traffic.
