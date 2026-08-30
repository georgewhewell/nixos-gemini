# MT6797 CONSYS identity to WMT/STP handoff

Status: 2026-08-30. Source audit only. No device access, firmware download,
radio command, reset, flash, or kernel/DT change was performed for this record.

## Result

0x0279 is a host MMIO identity read, not a WMT response. In the retained
vendor path it is observed while the CONMCU reset is still asserted. The
remaining path is: finish CONSYS hardware setup (MBIST and AFE), deassert
CONMCU reset, open BTIF/STP in mandatory mode, read the internal WMT chip and
version registers, then send WMT_QUERY_STP_CMD and require the exact default
event. There are two useful boundaries: the first transport-level response is
the raw GEN_HCR read, while the first scripted WMT initialization response is
the default query event. The mainline identity experiment deliberately stops
earlier and keeps reset held.

## Identity, reset, and shared EMI

The vendor DT gives CONSYS four windows in this order:

> reg = <0x18070000 0x0200>,  /*CONN_MCU_CONFIG_BASE */
>       <0x10007000 0x0100>,  /*AP_RGU_BASE */
>       <0x10000000 0x2000>,  /*TOPCKGEN_BASE */
>       <0x10006000 0x1000>;  /*SPM_BASE */

/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:3759-3764

The vendor power-on function refuses to proceed without the reserved shared
EMI base:

> if (!gConEmiPhyBase) {
>     WMT_PLAT_ERR_FUNC("EMI base address is invalid, CONNSYS can not be powered on!");
>     ...
>     return -1;
> }

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:528-539

wmt_plat_soc_init() stores the co-clock flag and invokes
mtk_wcn_consys_hw_init()
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/wmt_plat_alps.c:322-358).
The reserved-memory callback obtains gConEmiPhyBase from DT
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:1064-1072).
The vendor DT reserves an unmapped, dynamically placed, 2 MiB aligned 2 MiB
region (/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:329-335).
Hardware init then:

> emi_mpu_set_region_protection(gConEmiPhyBase + SZ_1M / 2,
>                             gConEmiPhyBase + SZ_1M - 1, ...);
> addrPhy = (gConEmiPhyBase & 0xFFF00000) >> 20;
> addrPhy = addrPhy | 0x1000;
> CONSYS_REG_WRITE(conn_reg.topckgen_base + CONSYS_EMI_MAPPING_OFFSET, ...);
> pEmibaseaddr = ioremap_nocache(gConEmiPhyBase + SZ_1M / 2, CONSYS_EMI_MEM_SIZE);
> memset_io(pEmibaseaddr, 0, CONSYS_EMI_MEM_SIZE);

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:1098-1138.
The size is 343 KiB at
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:191-199.
This is a required shared-memory/remap operation for the vendor owner, not
evidence that LK or ATF left that state reusable.

The selected vendor compile flags include PMIC control, EMI MPU, power API,
and AFE setting, while AHB clock management is zero:

> #define CONSYS_PMIC_CTRL_ENABLE         1
> #define CONSYS_EMI_MPU_SETTING          1
> #define CONSYS_AHB_CLK_MAGEMENT         0
> #define CONSYS_PWR_ON_OFF_API_AVAILABLE 1
> #define CONSYS_AFE_REG_SETTING          1

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:39-46.

## Exact post-ID hardware sequence

mtk_wcn_consys_hw_reg_ctrl(1, co_clock_type) enables VCN18, waits 240 us,
and, with the checked-in co_clock_flag=0, switches VCN28 to hardware control
and enables it
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:291-326;
/home/grw/src/nixos-gemini/blobs/WMT_SOC.cfg:1-6, SHA-256
f4a59b622a4e0c1470e475ce33f3edae43b27f1fbdeba54dc7cf07503d132880).
It sets the CONN-to-AP sleep mask at
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:328-330.

Under CONFIG_OF, the function asserts CONMCU reset through the MT6797 WDT
SWSYSRST helper and writes the SPM power-on configuration:

> mtk_wdt_swsysret_config((1 << 12), 1);
> CONSYS_REG_WRITE((conn_reg.spm_base + CONSYS_PWRON_CONFG_EN_OFFSET), CONSYS_PWRON_CONFG_EN_VALUE);

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:333-343.
The helper reads and writes MTK_WDT_SWSYSRST (TOPRGU + 0x18) with key
0x88000000; bit 12 is MTK_WDT_SWSYS_RST_CONMCU_RST
(/home/grw/src/gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/mt6797/mtk_wdt.c:396-448
and /home/grw/src/gemini-linux-kernel-3.18/drivers/watchdog/mediatek/wdt/mt6797/mt_wdt.h:18-26,85-104).

Because CONSYS_PWR_ON_OFF_API_AVAILABLE is 1, the OF path calls either
conn_power_on() when CONFIG_MTK_CLKMGR is defined or
clk_prepare_enable(clk_scp_conn_main) otherwise
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:344-355).
The checked source does not prove which of those two build configurations
produced every historical image. The OF path waits 30 us, then polls CONSYS
MCU offset 0x8 for 0x0279:

> consysHwChipId = CONSYS_REG_READ(conn_reg.mcu_base + CONSYS_CHIP_ID_OFFSET);
> if (consysHwChipId == 0x0279) {
>     ...
> }

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:401-424; offsets and reset constants are
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:72-84,166-168.

The poll precedes the next operations. The vendor then performs real-speed
MBIST configuration:

> CONSYS_REG_WRITE(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET,
>                  CONSYS_REG_READ(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET) |
>                  CONSYS_MCU_CFG_ACR_MBIST_BIT);

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:438-449; bit 18 is defined at
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:188-190.

With CONSYS_AFE_REG_SETTING=1, it maps AFE base 0x180b6000 and writes the
RCK, GPS, BT RX/TX, and Wi-Fi RX/TX AFE values
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:138-160 and
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:451-490). Only after those writes does it
release CONMCU reset:

> mtk_wdt_swsysret_config((1 << 12), 0);

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:492-496.

Therefore the identity experiment's state and the vendor WMT-ready state are
different: identity proves a readable powered CONSYS window; it does not prove
MBIST, AFE, reset release, BTIF, STP, or firmware readiness.

## Call graph to the first valid WMT response

The relevant vendor call path is:

    wmt_lib_init()
      -> wmt_plat_soc_init(co_clock_flag & 0x0f)       [setup/mapping]
      -> wmtd_thread()
      -> opfunc_func_on()
      -> opfunc_pwr_on()
      -> WMT_CTRL_HW_PWR_ON -> wmt_plat_pwr_ctrl(FUNC_ON)
      -> mtk_wcn_consys_hw_pwr_on()
      -> wmt_core_stp_init()
      -> WMT_CTRL_STP_OPEN / mandatory BTIF mode / STP enable
      -> wmt_core_hw_check()
      -> wmt_ic_ops_soc.ic_ver_check()
      -> mtk_wcn_soc_sw_init()
      -> init_table_1_2: WMT_QUERY_STP_CMD -> WMT_QUERY_STP_EVT_DEFAULT

Setup and thread creation are explicit in
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_lib.c:284-322,379-405; the WMT thread dispatches operations at
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_lib.c:1017-1075. Power-on calls platform power control and then
STP initialization at /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:1044-1067; function-on invokes
power-on when WMT is not already functional at /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:1165-1176.

For BTIF, STP open calls mtk_wcn_stp_open_btif(), registers the parser, and
registers the WMT event callback (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:500-541). Mandatory mode
is selected and STP enabled at /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:747-779. Hardware check
reads internal GEN_HCR at 0x80000008, selects the SOC operation for 0x0279,
and assigns the actual chip ID before version checking:

> case 0x0279:
>     p_ops = &wmt_ic_ops_soc;
> ...
> wmt_ic_ops_soc.icId = chipid;
> iret = p_ops->ic_ver_check();

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:909-1002. This runtime assignment supersedes the static
operation-table initializer .icId = 0x0000 at /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:957-968;
the MT6797 patch-address branch can therefore be reached after a successful
hardware check.

The first transport-level response after STP enable is the read event for
that GEN_HCR operation. `wmt_core_reg_rw_raw()` first sends `WMT_SET_REG_CMD`,
then receives `WMT_SET_REG_RD_EVT`, checks the returned address, and copies the
returned value (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:585-633):

> iRet = wmt_core_tx(WMT_SET_REG_CMD, sizeof(WMT_SET_REG_CMD), &u4Res, MTK_WCN_BOOL_FALSE);
> ...
> iRet = wmt_core_rx(evtBuf, evtLen, &u4Res);
> ...
> if (txCmdAddr != rxEvtAddr) {
>     ...
> }
> osal_memcpy(pVal, &evtBuf[12], 4);

Thus “first valid response” means this raw register-read response if transport
events are counted; the default query below is the first table-scripted WMT
initialization response. The subsequent `ic_ver_check()` performs the HVR/FVR
reads before patch policy is selected (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1614-1659).

The first scripted WMT/STP initialization response is the default query, not
the later full-mode query. The exact source vectors are:

> static UINT8 WMT_QUERY_STP_CMD[] = { 0x01, 0x04, 0x01, 0x00, 0x04 };
> static UINT8 WMT_QUERY_STP_EVT_DEFAULT[] = { 0x02, 0x04, 0x06, 0x00, 0x00, 0x04, 0x11, 0x00, 0x00, 0x00 };

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:122-124. mtk_wcn_soc_sw_init() sends that script after
mandatory STP setup (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1008-1017). Every script requires
the complete expected event and length:

> iRet = wmt_core_tx(script[i].cmd, script[i].cmdSz, ...);
> iRet = wmt_core_rx(evtBuf, script[i].evtSz, &u4Res);
> if (osal_memcmp(evtBuf, script[i].evt, script[i].evtSz) != 0) { ... }

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:634-679. TX is refused unless both STP-open and
STP-enabled state bits are set (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:327-348), and RX waits for
the WMT task event (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:262-306).

After the first response, the vendor sets STP in the chip, enables host full
mode, waits 10 ms, and queries again (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1018-1045). The
second query expects:

> static UINT8 WMT_QUERY_STP_EVT[] = { 0x02, 0x04, 0x06, 0x00, 0x00, 0x04, 0xDF, 0x0E, 0x68, 0x01 };

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:122-124.

The intended BTIF selection is explicit but not proven for current mainline
runtime: STP_BTIF_FULL is 0x03 (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/linux/include/wmt_dev.h:19-22), and
wmt_lib_set_hif() maps it to WMT_HIF_BTIF (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_lib.c:552-576).
WMT_SOC.cfg only sets co-clock and antenna/LNA fields; it does not itself
select HIF (/home/grw/src/nixos-gemini/blobs/WMT_SOC.cfg:1-6). The retained launcher audit records BTIF
selection/default strings at
/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/userspace-binary-audit.txt:7-14.

### Failure and unwind behavior

The hardware identity poll logs a timeout but, in this source, does not return
at that point. The code only emits diagnostics when `retry == 0` or the chip
ID is zero, then proceeds to the MBIST/AFE/reset-release code
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:401-449):

> if ((0 == retry) || (0 == consysHwChipId)) {
>     WMT_PLAT_ERR_FUNC("Maybe has a consys power on issue,(0x%08x)\n", consysHwChipId);
> }
> ...
> CONSYS_REG_WRITE(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET,
>                  CONSYS_REG_READ(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET) |
>                  CONSYS_MCU_CFG_ACR_MBIST_BIT);

This is a vendor-source hazard, not evidence that the identity was valid: a
failed poll can still reach later writes. At the WMT layer, a failed STP init
is explicitly unwound and retried:

> iRet = wmt_core_stp_deinit();
> iRet = opfunc_pwr_off(pWmtOp);
> ...
> goto pwr_on_rty;

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:1054-1075.
`wmt_core_stp_deinit()` un-readies, disables, and closes STP before the power
off path (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:814-873). The platform power-off path invokes
`mtk_wcn_consys_hw_reg_ctrl(0, ...)` and GPIO-off
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:817-826).
The source does not prove that every intermediate hardware write is reversed
when the identity poll fails; in particular, the timeout branch itself lacks
an immediate return or local rollback.

## Patch discovery, placement, and verification

The SOC build enables multi-patch, patch-download optimization, power-on DLM,
and result comparison:

> #define CFG_CHECK_WMT_RESULT (1)
> #define CFG_WMT_MULTI_PATCH (1)
> #define CFG_WMT_PATCH_DL_OPTM (1)
> #define CFG_WMT_POWER_ON_DLM  (1)

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:51-90.

After the initial/full STP exchange, mtk_wcn_soc_sw_init() sends power-on DLM,
asks userspace to search patches, obtains a count, and downloads each patch
followed by a WMT reset (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:1046-1091). Search is not an
in-kernel directory scan: it sends the literal command "srh_patch" through
wmt_ctrl_ul_cmd() (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2030-2040 and
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ctrl.c:545-557). Userspace supplies each sequence's filename and
four address bytes via WMT_IOCTL_SET_PATCH_NUM/INFO
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/linux/wmt_dev.c:1011-1067; structure at /home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_lib.h:150-154).
The kernel then calls request_firmware() on the selected filename
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/linux/wmt_dev.c:429-447).

The patch format is a 28-byte header followed by body; the source copies date,
platform, HW/SW version, and patch version, strips the header, and sends
1000-byte fragments (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/include/wmt_core.h:370-376 and
/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2094-2146). For dynamically assigned icId == 0x0279,
the patch-RAM command uses exact bytes 08 05, and the per-patch address command
uses 2c 0b:

> WMT_PATCH_ADDRESS_CMD[8] = 0x08;
> WMT_PATCH_ADDRESS_CMD[9] = 0x05;
> WMT_PATCH_P_ADDRESS_CMD[8] = 0x2c;
> WMT_PATCH_P_ADDRESS_CMD[9] = 0x0b;

/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2162-2169. Address events and every fragment event are
length-checked and compared when CFG_CHECK_WMT_RESULT is enabled
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:2171-2219,2222-2308). This is protocol-response
validation, not a cryptographic signature or body hash. The helper
wmt_core_patch_check() only compares major version fields and has no caller
in this source tree (/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_core.c:898-907; repository search found only
its declaration and definition).

Local evidence consists of ROMv3_patch_1_0_hdr.bin (210,904 bytes, SHA-256
450c2b0949cf879217ac9aef81b18b860982f0e69340784b448b54365d8cf630) and
ROMv3_patch_1_1_hdr.bin (46,472 bytes, SHA-256
5732c0730380e937b48ad169f2805b65e8d4a178265566c5083cb2cc2d249f1e). Nix
installs those exact names, plus WMT_SOC.cfg, under /lib/firmware
(/home/grw/src/nixos-gemini/nixos/firmware.nix:8-20). Presence does not prove launcher selection or live
acceptance. The bounded vendor capture records patch date 20180307 and active
owners but explicitly says firmware load was not attempted by the collector:
/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:53-77.

All three MT6797 ROM table entries set bWorkWithoutPatch = FALSE
(/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/core/wmt_ic_soc.c:875-904). That proves the vendor's complete SOC
initialization treats a patch as required; it does not move patch download
before the first default STP query.

## LK/ATF reuse audit

The retained LK analysis proves watchdog setup and final smc 0x82000200, but
contains no source or binary evidence of CONSYS/WMT patch loading or BTIF/STP
initialization. Exact quotes:

> FUN_4600d9d8 (0xd9d8): _DAT_10007008 = 0x1971;
> 0x46023880  mov r1,r0
> 0x46023884  ldr r0,[0x4602396c]   ; value 0x82000200
> 0x46023888  smc 0

/home/grw/src/nixos-gemini/artifacts/lk-analysis/REVERSE_ENGINEERING.md:11,47-65.
The p20 LK string scan has MT6797 platform/display/storage/watchdog anchors
but no CONSYS, WMT, or BTIF anchor; this is supporting negative evidence only,
not proof against computed MMIO accesses. The exact ATF image audit establishes
the normal SMC target's watchdog behavior, not CONSYS firmware residency
(/home/grw/src/nixos-gemini/research/ATF_WATCHDOG_HANDOFF.md:35-64,99-120).

The vendor Linux capture proves a later fully running Gemian system had
18070000.consys -> mtk_wmt, BTIF DMA activity, and WMT status
MT279_ROM=E1 ... patch=20180307, but also says "Firmware presence and hashes
remain evidence of an installed boundary, not ... proof that every image was
loaded" (/home/grw/src/nixos-gemini/artifacts/ixoo-7199e822/experiments/2026-07-12-connectivity-wmt-recovery/results/live-connectivity-rerun-20260713.txt:19-32,47-72). It provides no
timestamped LK-to-Linux state handoff. Thus:

- Proven: LK arms/kicks its watchdog and enters ATF; vendor Linux has explicit
  CONSYS setup, reset release, WMT/STP exchange, and patch protocol; current
  source assigns actual SOC ID before patch-address selection.
- Inferred: a cold mainline identity result cannot be treated as a WMT-ready
  CONSYS lease; the normal vendor owner must perform the post-ID sequence.
- Could not determine: whether LK, preloader, or ATF on this handset ever
  powers CONSYS, downloads a patch, or leaves reusable CONSYS/BTIF/STP state.
  No retained LK/ATF source or exact binary trace proves that boundary.

## Safe next slices and hardware-risk boundary

The smallest independently testable slice is static: validate pure WMT script
vectors, exact response matching, 28-byte patch-header parsing, and 0x0279
address-byte selection against captured/local files. Existing mainline KUnit
and session tests exercise STP framing and leases without transport
(/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-stp-session.c:1210-1285).
No firmware bytes need to be transmitted for this slice.

The next source/DT integration slice must keep CONSYS, AFE, firmware loading,
BTIF, and WMT transmission default-gated. First provide explicit resource
ownership for the full post-ID lifecycle, then a fake-ops test for MBIST/AFE/
reset ordering and reverse unwind. The current mainline runtime comments state
the boundary:

> The lifecycle core purposefully ends at identity observation.
> ... never deasserts reset, touches AFE/shared EMI, starts BTIF, loads firmware, sends WMT ...

/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:17-20.

Any real post-ID action is hardware-risky and irreversible for that boot:
reset release, AFE writes, EMI clearing/remap, BTIF/STP enable, DLM commands,
patch download, WMT reset, and RF calibration all change shared state. A first
live WMT query must wait for explicit CONSYS/BTIF clocks, reset, reserved-EMI,
HIF, firmware-selection, watchdog-margin, and rollback gates. A successful
0x0279 identity read alone is not authorization to send it.
