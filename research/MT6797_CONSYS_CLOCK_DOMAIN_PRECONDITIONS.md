# MT6797 CONSYS AFE clock and power-domain preconditions

This report closes the clock/power-domain part of the `0x180b6000` AFE
question.  The source proves that the vendor `conn` vote is the CONN
MTCMOS/power-gate transaction and that it must remain held while the AFE is
written.  It does **not** prove that the current mainline tree exposes every
vendor clock, or that the CONN domain alone satisfies an additional analog
clock or access-firewall requirement.

## Verdict

* A **resource lease alone is not sufficient**.  In the current runtime
  provider it only pins the provider device and fences removal; it performs no
  rail, domain, reset, or clock operation.
* The **identity/lifecycle lease is the required power lifetime** for a future
  AFE backend.  Its enable path turns on VCN18/VCN28, asserts the external
  CONMCU reset, writes PWRON, votes the CONN genpd, waits, and polls `0x0279`.
  The lease remains pinned through post-ID and therefore must remain held
  through MBIST, AFE writes, and reset release.
* Mainline MT6797 SCPSYS has a CONN domain whose power-on implementation
  clears the SPM `PWR_CLK_DIS` bit, but its domain data has no associated CCF
  clock (`CLK_NONE`).  This is a strong source-level correspondence to the
  vendor `pg_conn` power gate, not proof that an extra analog clock is
  unnecessary.
* I could not determine from the retained source whether Gemini needs a
  separate AFE clock, an AP access permission, or a secure-firmware vote in
  addition to CONN MTCMOS.  Do not invent a clock ID or use the unrelated
  audio block at `0x11220000`.

## Vendor proof

The vendor selects both PMIC control and the power-on API, while explicitly
disabling its optional AHB clock-management block:

> `#define CONSYS_PMIC_CTRL_ENABLE         1`
>
> `#define CONSYS_AHB_CLK_MAGEMENT         0`
>
> `#define CONSYS_PWR_ON_OFF_API_AVAILABLE 1`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:39-46`

The active OF sequence first enables VCN18, waits 240 us, enables VCN28,
sets the sleep mask, asserts the AP RGU CONMCU reset, and writes
`PWRON_CONFG_EN`:

> `udelay(240);`
>
> `regulator_set_voltage(reg_VCN28, 2800000, 2800000);`
>
> `CONSYS_REG_WRITE(conn_reg.topckgen_base + CONSYS_CONN2AP_SLEEP_MASK_OFFSET,`
>
> `mtk_wdt_swsysret_config((1 << 12), 1);`
>
> `CONSYS_REG_WRITE((conn_reg.spm_base + CONSYS_PWRON_CONFG_EN_OFFSET), CONSYS_PWRON_CONFG_EN_VALUE);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:293-343`

For the non-`CONFIG_MTK_CLKMGR` branch, the driver obtains the DT clock
named `conn` and prepares it:

> `clk_scp_conn_main = devm_clk_get(&pdev->dev, "conn");`
>
> `iRet = clk_prepare_enable(clk_scp_conn_main);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:226-244,344-355`

The alternative `CONFIG_MTK_CLKMGR` branch calls the owner API instead:

> `iRet = conn_power_on();	/* consult clkmgr owner. */`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:344-349`

The vendor DT identifies that `conn` clock as `SCP_SYS_CONN` from the
SCPSYS node:

> `clocks = <&scpsys SCP_SYS_CONN>;`
>
> `clock-names = "conn";`

`/home/grw/src/gemini-linux-kernel-3.18/arch/arm64/boot/dts/mt6797.dtsi:3759-3769`

That is not merely a parent/source clock.  The vendor power-gate table maps
`SCP_SYS_CONN` to `pg_conn` and `SYS_CONN`, with no pre-clock:

> `PGATE(SCP_SYS_CONN, pg_conn, NULL, NULL, SYS_CONN),`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/clk/mediatek/clk-mt6797-pg.c:2523-2527`

`pg_prepare()` calls the power-gate enable operation; that operation calls
the CONN subsystem operation:

> `return enable_subsys(pg->pd_id);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/clk/mediatek/clk-mt6797-pg.c:2372-2382`

> `static int CONN_sys_enable_op(struct subsys *sys)`
>
> `return spm_mtcmos_ctrl_conn(STA_POWER_ON);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/clk/mediatek/clk-mt6797-pg.c:1914-1918`

The vendor CONN MTCMOS power-on writes SPM `CONN_PWR_CON` at `0x32c`, waits
for both status bits at `0x180`/`0x184`, clears `PWR_CLK_DIS`, clears ISO,
sets its internal power reset, and clears bus protection when configured:

> `spm_write(CONN_PWR_CON, spm_read(CONN_PWR_CON) | PWR_ON);`
>
> `spm_write(CONN_PWR_CON, spm_read(CONN_PWR_CON) | PWR_ON_2ND);`
>
> `while (!(spm_read(PWR_STATUS) & CONN_PWR_STA_MASK)`
>
> `spm_write(CONN_PWR_CON, spm_read(CONN_PWR_CON) & ~PWR_CLK_DIS);`
>
> `spm_write(CONN_PWR_CON, spm_read(CONN_PWR_CON) & ~PWR_ISO);`
>
> `spm_write(CONN_PWR_CON, spm_read(CONN_PWR_CON) | PWR_RST_B);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/clk/mediatek/clk-mt6797-pg.c:574-655`

The connectivity driver waits 30 us after the domain/clock transaction,
polls MCU chip ID `0x0279`, then performs MBIST and AFE operations while the
external CONMCU reset remains asserted:

> `udelay(30);`
>
> `if (consysHwChipId == 0x0279) {`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:395-424`

> `CONSYS_REG_WRITE(conn_reg.mcu_base + CONSYS_MCU_CFG_ACR_OFFSET,`
>
> `... | CONSYS_MCU_CFG_ACR_MBIST_BIT);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:438-449`

> `consys_afe_reg_base = ioremap_nocache(CONSYS_AFE_REG_BASE, 0x100);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:451-453`

The first AFE write is at `0x180b6020`; the final AFE write is at
`0x180b6090`, followed by reset release:

> `CONSYS_REG_WRITE(consys_afe_reg_base + CONSYS_AFE_REG_WBG_RCK_01_OFFSET,`
>
> `CONSYS_REG_WRITE(consys_afe_reg_base + CONSYS_AFE_REG_WBG_WF_TX_03_OFFSET,`
>
> `mtk_wdt_swsysret_config((1 << 12), 0);`

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/mtk_wcn_consys_hw.c:459-496`

The base and offsets are defined at:

`/home/grw/src/gemini-linux-kernel-3.18/drivers/misc/mediatek/connectivity/common/common_main/mt6797/include/mtk_wcn_consys_hw.h:138-159`

## Mainline comparison

### SCPSYS power-on

The current MT6797 SCPSYS provider describes the CONN domain as SPM offset
`0x32c`, status bit 1, protection bits 17 and 18, and **no associated
clock**:

> `.name = "conn",`
>
> `.sta_mask = BIT(1),`
>
> `.ctl_offs = 0x32c,`
>
> `.bus_prot_mask = BIT(17) | BIT(18),`
>
> `.clk_id = {CLK_NONE},`

`/home/grw/src/linux-gemini-platform/drivers/pmdomain/mediatek/mtk-scpsys.c:885-900`

The generic power-on implementation enables any configured domain regulator,
enables any configured clocks, sets SPM power-on bits, waits for both power
acknowledgements, clears `PWR_CLK_DIS` and ISO, sets the internal SPM reset,
then clears bus protection:

> `ret = scpsys_regulator_enable(scpd);`
>
> `ret = scpsys_clk_enable(scpd->clk, MAX_CLKS);`
>
> `val |= PWR_ON_BIT;`
>
> `val |= PWR_ON_2ND_BIT;`
>
> `val &= ~PWR_CLK_DIS_BIT;`
>
> `val &= ~PWR_ISO_BIT;`
>
> `val |= PWR_RST_B_BIT;`
>
> `ret = scpsys_bus_protect_disable(scpd);`

`/home/grw/src/linux-gemini-platform/drivers/pmdomain/mediatek/mtk-scpsys.c:312-362`

The provider obtains clock handles only from the domain's `clk_id` entries;
`CLK_NONE` therefore means no CONN CCF handle is prepared:

> `for (j = 0; j < MAX_CLKS && data->clk_id[j]; j++) {`
>
> `scpd->clk[j] = c;`

`/home/grw/src/linux-gemini-platform/drivers/pmdomain/mediatek/mtk-scpsys.c:499-525`

The base DT supplies only MFG/MM/VDEC SCPSYS clock names, not a CONN clock:

> `clock-names = "mfg", "mfg_52m", "mm", "vdec";`

`/home/grw/src/linux-gemini-platform/arch/arm64/boot/dts/mediatek/mt6797.dtsi:315-325`

The current ordinary MT6797 clock provider contains an `infra_pmic_conn`
gate, but the audited source contains no `conn_main` or `SCP_SYS_CONN`
clock declaration:

> `GATE_ICG0(CLK_INFRA_PMIC_CONN, "infra_pmic_conn", "pmicspi_sel", 3),`

`/home/grw/src/linux-gemini-platform/drivers/clk/mediatek/clk-mt6797.c:446-451`

This is not evidence that `infra_pmic_conn` is the vendor `conn` power gate;
it has a different provider/name and must not be substituted without a
hardware-specific proof.

### Runtime lease and PM ordering

The runtime resource lease only checks `RESOURCES_READY`, calls
`get_device()`, and increments `external_users`:

> `if (runtime->provider_state !=`
>
> `MT6797_CONSYS_RUNTIME_PROVIDER_RESOURCES_READY)`
>
> `lease->device = get_device(dev);`
>
> `runtime->external_users++;`

`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:534-565`

It does not enable power.  Identity acquisition is the operation that calls
the lifecycle prefix and transitions to `IDENTITY_HELD`:

> `ret = mt6797_consys_runtime_lease_acquire(&runtime->lifecycle,`
>
> `runtime->provider_state =`
>
> `MT6797_CONSYS_RUNTIME_PROVIDER_IDENTITY_HELD;`

`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:595-647`

The lifecycle prefix order is VCN18, 240-us delay, VCN28, sleep mask, reset
assert, PWRON, CONN-domain vote, 30-us delay, and ID poll:

> `vcn18 = true;`
>
> `mt6797_consys_delay(lifecycle, MT6797_CONSYS_VCN18_SETTLE_US);`
>
> `ret = lifecycle->ops->enable_scp_sys_conn(lifecycle->context);`
>
> `mt6797_consys_delay(lifecycle, MT6797_CONSYS_DOMAIN_SETTLE_US);`
>
> `ret = mt6797_consys_wait(lifecycle,`

`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-core.c:88-135`

The domain callback attaches the parsed CONN genpd, enables runtime PM, and
calls `pm_runtime_resume_and_get()`:

> `ret = of_genpd_add_device(&runtime->conn_domain, runtime->dev);`
>
> `pm_runtime_enable(runtime->dev);`
>
> `ret = pm_runtime_resume_and_get(runtime->dev);`

`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-runtime.c:292-307`

Generic genpd runtime resume invokes `genpd_power_on()` before starting the
device:

> `genpd_power_on(genpd, 0);`

`/home/grw/src/linux-gemini-platform/drivers/pmdomain/core.c:1290-1327`

Thus the identity lease is sufficient to keep the current mainline CONN
genpd vote alive, and the generic provider performs the SPM power/clock-gate
transaction.  It is not sufficient to claim a distinct vendor analog clock
unless that provider is added and independently validated.

The current AFE/post-ID owner must retain this identity lease across all
post-ID callbacks.  Its callback order is MBIST, AFE, then reset release:

> `ret = owner->ops->configure_mbist(owner->context);`
>
> `ret = owner->ops->configure_afe(owner->context);`
>
> `ret = owner->ops->release_reset(owner->context);`

`/home/grw/src/linux-gemini-platform/drivers/soc/mediatek/mt6797-consys-postid.c:89-109`

## Required changes before any live AFE access

1. Keep the existing resource lease as a removal fence, but reject any AFE
   operation that lacks the canonical identity/lifecycle lease.  A future
   AFE mapping must be a separately declared exact resource
   `<0 0x180b6000 0 0x100>`; the current four-resource contract has no AFE
   mapping (`.../mediatek,mt6797-consys.yaml:42-54`).
2. Keep the identity lease pinned while the CONN genpd vote is held and while
   MBIST, every AFE write, and reset release run.  Do not release the domain
   between ID polling and post-ID.
3. Treat the current generic SCPSYS CONN domain as the only mainline-proven
   power/clock-gate owner.  Before adding a named `conn` clock, first prove
   that it is a separate provider resource.  The vendor `conn` clock is a
   power-gate output, not one of the ordinary `clk-mt6797.c` infrastructure
   gates.
4. Do not enable the vendor AHB/bus clock for this AFE-only slice: the vendor
   build explicitly has `CONSYS_AHB_CLK_MAGEMENT 0`.  A later BTIF/STP owner
   may need a separate bus clock, but that is outside this proof.
5. Keep the external WDT reset asserted until the last AFE write.  Reuse the
   current exclusive `conn-mcu` reset; do not write WDT MMIO from the AFE
   backend.
6. Make any AFE-attempt failure sticky unless a reviewed register snapshot
   and restore protocol is added.  The vendor power-off path disables the
   domain and rails but contains no AFE restore, while the current generic
   post-ID failure path returns to `IDLE` after reset assertion
   (`.../mt6797-consys-postid.c:35-50`).  That state transition is unsafe
   after a partial persistent AFE write.

## Test oracle and acceptance gates

The hardware-neutral KUnit oracle should record this order and reject all
other orders:

`resource lease -> identity/lifecycle lease -> VCN18 -> 240 us -> VCN28 -> sleep mask -> external reset assert -> PWRON -> CONN domain/clock vote -> 30 us -> ID 0x0279 -> MBIST -> AFE writes -> external reset deassert`

It should also prove:

* resource lease alone cannot call MBIST, AFE, or reset release;
* domain/clock-vote failure performs no ID-dependent operation;
* ID timeout leaves reset asserted and unwinds only reversible rails/domain;
* MBIST failure performs no AFE write and no reset release;
* AFE failure asserts reset, records terminal/sticky error, and retains the
  lease unless a real restore path exists;
* removal waits for both resource and identity/post-ID leases; and
* no fake test invokes live MMIO, `ioremap`, regulator, genpd, or reset APIs.

The smallest live acceptance sequence is therefore: validate the future
`afe` resource and existing CONN genpd metadata; run the already gated
identity-only transaction and capture CONN status/reset/rail evidence; add a
second independent gate for AFE writes; then perform one AFE transaction
with reset asserted and a terminal failure policy.  The first two stages do
not establish that an analog clock or access firewall is present.  That
remains **unknown** until the target hardware's clock/status evidence or a
more specific vendor/SoC register specification closes it.
