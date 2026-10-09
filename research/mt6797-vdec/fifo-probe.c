// SPDX-License-Identifier: GPL-2.0-only
/* Direct H.264 input DMA qualification on a real MT6797 codec DT device.
 * This is a hardware diagnostic, not a V4L2 video device or frame decoder.
 */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>
#include <linux/iommu.h>
#include <linux/iopoll.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/sizes.h>

#define FIFO_SIZE SZ_64K
#define INPUT_ALLOC_SIZE (2 * FIFO_SIZE)
#define TEST_DMA_BITS 30
#define REG_SELECT 0x84
#define PDN_SPEC 0xc8
#define PDN_MODULE 0xcc
#define AUTO_PDN_CONTROL 0xec
#define GLOBAL_DCM_CONTROL 0x18
#define IRQ_CONTROL 0xa4
#define BREAK_CONTROL 0x100
#define BREAK_STATUS 0x104
#define BREAK_IDLE (BIT(0) | BIT(4))
#define VLD_PROC 0x8c
#define VLD_READ_PTR 0xb0
#define VLD_FIFO_START 0xb4
#define VLD_FIFO_END 0xb8
#define VLD_READY_SWITCH 0xc0
#define VLD_ASYNC_CONTROL 0xd0
#define VLD_ASYNC_WRITE_ENABLE BIT(18)
#define VLD_FETCH_STATUS 0xe8
#define VLD_SRAM_STATUS 0xf4
#define VLD_SOFT_RESET 0x108
#define VLD_WRITE_PTR 0x110
#define VLD_COMMON_SRAM_RESET 0x2ec
#define AVC_CONTROL 0x84
#define AVC_RESET_SUM 0x28c
#define FETCH_COMMAND BIT(20)
#define BARREL_COMMAND BIT(23)
#define FETCH_READY BIT(0)
#define SRAM_PROCESSING BIT(15)
#define RESET_CORE (BIT(0) | BIT(8))
/* Candidate interface: AVC enable, input ready counters, memory pause,
 * SUM6 append control and data-valid control. No error bypass/concealment.
 */
#define AVC_INPUT_CONTROL (BIT(0) | GENMASK(2, 1) | BIT(27) | BIT(29) | BIT(31))

static bool fetch;
module_param(fetch, bool, 0444);
MODULE_PARM_DESC(fetch, "Fetch and compare a private input pattern through the H.264 barrel shifter; no frame starts");
static bool nonposted = true;
module_param(nonposted, bool, 0444);
MODULE_PARM_DESC(nonposted, "Use non-posted codec register mappings, matching the public MT6797 userspace resource mapping");
static bool common_reset = true;
module_param(common_reset, bool, 0444);
MODULE_PARM_DESC(common_reset, "Pulse the separate common SRAM reset from the public related-core initialization");
static bool async_write;
module_param(async_write, bool, 0444);
MODULE_PARM_DESC(async_write, "Test the older related-core asynchronous write-pointer enable after the input reset; no frame starts");
static bool clear_caller_gate;
module_param(clear_caller_gate, bool, 0444);
MODULE_PARM_DESC(clear_caller_gate, "Test clearing MISC 0xf4 bit0 from the public related-core caller; MT6797 meaning is not yet qualified");
static bool all_clocks;
module_param(all_clocks, bool, 0444);
MODULE_PARM_DESC(all_clocks, "Diagnose local clock gating by clearing both decoder power-down masks under reset");
static bool minimal_clocks;
module_param(minimal_clocks, bool, 0444);
MODULE_PARM_DESC(minimal_clocks, "Use only the bus clock vote, matching the published MT6797 kernel resource sequence");
static bool clear_legacy;
module_param(clear_legacy, bool, 0444);
MODULE_PARM_DESC(clear_legacy, "Clear lower legacy power-down bits instead of the related-core H.264 mask; retain upper controls");
static bool hold_resources;
module_param(hold_resources, bool, 0444);
MODULE_PARM_DESC(hold_resources, "Keep a resource-only power vote for a separate read-only supplier snapshot; incompatible with fetch");

static const u8 test_bytes[] = {
	0x13, 0x57, 0x9b, 0xdf, 0x24, 0x68, 0xac, 0xfe,
	0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
};

struct fifo_probe {
	struct device *dev;
	struct regmap *gcon;
	void __iomem *misc, *vld, *top, *mc, *avc, *larb_mmu_reg;
	struct clk_bulk_data clocks[3];
	void *input, *scratch;
	dma_addr_t input_dma, scratch_dma;
	u32 fetch_status, sram_status, first, shift, second;
	u32 fifo_start_readback, fifo_end_readback, read_ptr_readback;
	u32 clock_select_original, clock_select, power_down, power_down_programmed;
	u32 pdn_spec_original, pdn_module_original, auto_pdn_original;
	u32 pdn_spec, pdn_module;
	u32 larb_mmu, fifo_start_before_reset, read_ptr_before_reset;
	u32 after_fetch[8];
	u32 dcm_original, dcm_programmed, global_after_fetch[3];
	u32 break_original, break_status;
	u32 irq_original;
	u32 async_original, async_after_fetch, common_reset_original;
	u32 caller_controls[2], global_before[2];
	u32 caller_gate_after_fetch;
	unsigned long clock_rate;
	int result, reset_result, break_result;
	bool iommu_attached, dma_started, compared, quiesced, fenced;
	bool input_unchanged, scratch_unchanged;
	bool resources_held;
};

static int runtime_resume(struct device *dev)
{
	struct fifo_probe *p = dev_get_drvdata(dev);
	return clk_bulk_prepare_enable(minimal_clocks ? 1 : ARRAY_SIZE(p->clocks),
				       p->clocks);
}

static int runtime_suspend(struct device *dev)
{
	struct fifo_probe *p = dev_get_drvdata(dev);
	clk_bulk_disable_unprepare(minimal_clocks ? 1 : ARRAY_SIZE(p->clocks),
				   p->clocks);
	return 0;
}

static DEFINE_RUNTIME_DEV_PM_OPS(fifo_pm_ops, runtime_suspend, runtime_resume, NULL);

/* The pinned public register interface completes each APB write with a DSB.
 * arm64 mb() provides that completion barrier through the kernel API.
 */
static void write_reg(u32 value, void __iomem *address)
{
	writel(value, address);
	mb();
}

static int reset_input(struct fifo_probe *p)
{
	u32 state;
	int ret;

	/* Bits 0/8 follow the public MT8173 newer-core reset interface.
	 * Reset stays asserted until outstanding input processing is idle.
	 * This test never enables MC/PP frame DMA.
	 */
	write_reg(RESET_CORE, p->vld + VLD_SOFT_RESET);
	readl(p->vld + VLD_SOFT_RESET);
	udelay(2);
	ret = readl_poll_timeout(p->vld + VLD_SRAM_STATUS, state,
				!(state & SRAM_PROCESSING), 10, 100000);
	p->sram_status = state;
	return ret;
}

static int test_input(struct fifo_probe *p)
{
	u32 status;
	int ret;

	/* The framework configures all ten larb1 ports. This diagnostic only
	 * reads its mask while the supplier holds a runtime power vote.
	 */
	if ((p->larb_mmu & GENMASK(9, 0)) != GENMASK(9, 0))
		return -ENODEV;
	if (p->irq_original & BIT(16))
		return -EBUSY;
	/* Both the public emulated-clock setup and post-completion caller clear
	 * this control. It is initially set on MT6797. Test that one documented
	 * related-core operation before accessing the candidate input controls;
	 * retain every other bit and restore it only after proven idle.
	 */
	if (clear_caller_gate)
		write_reg(p->caller_controls[1] & ~BIT(0), p->misc + 0xf4);
	ret = reset_input(p);
	if (ret)
		return ret;
	/* MT6797 requires RISC interrupt-clear mode bit 0 always set. No IRQ
	 * clear pulse or frame command is issued by this input-only test.
	 */
	write_reg((p->irq_original & ~BIT(4)) | BIT(0), p->misc + IRQ_CONTROL);
	/* MT6797's public power sequence places these controls under reset.
	 * The H.264 masks are candidates from the public related-core interface.
	 * They enable the codec blocks without issuing a decode command.
	 */
	write_reg(all_clocks ? 0 : 0xf7, p->misc + PDN_SPEC);
	write_reg(all_clocks ? 0 : 0x13a20100, p->misc + PDN_MODULE);
	/* The newer-core public reset routine also programs the legacy control,
	 * retaining its upper control bits. Omitting it is not an equivalent
	 * initialization even with both newer power-down masks cleared.
	 */
	write_reg((p->power_down & 0xff400000) |
	       (clear_legacy ? 0 : 0x00801ff0), p->misc);
	p->power_down_programmed = readl(p->misc);
	write_reg(p->auto_pdn_original | BIT(0), p->misc + AUTO_PDN_CONTROL);
	/* MT6797 specifies both global and local automatic clock-off controls.
	 * Use the existing syscon regmap and change only the documented DCM bit;
	 * clock enable and reset registers remain owned by their frameworks.
	 */
	ret = regmap_update_bits(p->gcon, GLOBAL_DCM_CONTROL, BIT(0), BIT(0));
	if (ret)
		return ret;
	ret = regmap_read(p->gcon, GLOBAL_DCM_CONTROL, &p->dcm_programmed);
	if (ret)
		return ret;
	if (!(p->dcm_programmed & BIT(0)))
		return -EIO;
	p->pdn_spec = readl(p->misc + PDN_SPEC);
	p->pdn_module = readl(p->misc + PDN_MODULE);
	write_reg(2, p->misc + REG_SELECT);
	p->clock_select = readl(p->misc + REG_SELECT);
	write_reg(0, p->vld + VLD_SOFT_RESET);
	readl(p->vld + VLD_SOFT_RESET);
	/* The public common initializer has a distinct SRAM reset at VLD 0x2ec,
	 * separate from the barrel-reset bit at 0x108. Pulse it before any input
	 * command, with the codec clocks enabled, preserving unrelated bits.
	 */
	if (common_reset) {
		if (p->common_reset_original & BIT(8))
			return -EBUSY;
		write_reg(p->common_reset_original, p->vld + VLD_COMMON_SRAM_RESET);
		write_reg(p->common_reset_original | BIT(8), p->vld + VLD_COMMON_SRAM_RESET);
		write_reg(p->common_reset_original, p->vld + VLD_COMMON_SRAM_RESET);
	}
	write_reg(BIT(18), p->vld + VLD_READY_SWITCH);
	write_reg(AVC_INPUT_CONTROL, p->avc + AVC_CONTROL);
	/* Internal output-buffer configuration is part of input initialization;
	 * it does not submit a frame or enable any MC output DMA.
	 */
	write_reg(6, p->mc + 0x24);
	write_reg(lower_32_bits(p->scratch_dma), p->top + 0x28);
	write_reg(lower_32_bits(p->input_dma) >> 6, p->vld + VLD_FIFO_START);
	write_reg(lower_32_bits(p->input_dma + FIFO_SIZE) >> 6, p->vld + VLD_FIFO_END);
	write_reg(readl(p->vld + VLD_WRITE_PTR) | BIT(0), p->vld + VLD_WRITE_PTR);
	/* The public newer-core interface writes the read pointer twice. */
	write_reg(lower_32_bits(p->input_dma), p->vld + VLD_READ_PTR);
	write_reg(lower_32_bits(p->input_dma), p->vld + VLD_READ_PTR);
	write_reg(lower_32_bits(p->input_dma + 4096), p->vld + VLD_WRITE_PTR);
	p->fifo_start_before_reset = readl(p->vld + VLD_FIFO_START);
	p->read_ptr_before_reset = readl(p->vld + VLD_READ_PTR);
	write_reg(1, p->avc + AVC_RESET_SUM);
	write_reg(BIT(8), p->vld + VLD_SOFT_RESET);
	write_reg(0, p->vld + VLD_SOFT_RESET);
	p->fifo_start_readback = readl(p->vld + VLD_FIFO_START);
	p->fifo_end_readback = readl(p->vld + VLD_FIFO_END);
	p->read_ptr_readback = readl(p->vld + VLD_READ_PTR);
	/* Producer bytes must reach the coherent buffer before the fetch. */
	dma_wmb();
	p->dma_started = true;
	/* The older public interface enables its asynchronous write pointer.
	 * Treat that write as potentially starting input activity: buffer ordering
	 * and the software DMA fence must already be established before it.
	 */
	if (async_write)
		write_reg(p->async_original | VLD_ASYNC_WRITE_ENABLE,
			  p->vld + VLD_ASYNC_CONTROL);
	write_reg(FETCH_COMMAND, p->vld + VLD_PROC);
	ret = readl_poll_timeout(p->vld + VLD_FETCH_STATUS, status,
				status & FETCH_READY, 10, 100000);
	p->fetch_status = status;
	if (ret)
		return ret;
	write_reg(BARREL_COMMAND, p->vld + VLD_PROC);
	write_reg(0, p->avc + AVC_RESET_SUM);
	/* Peek, consume 32 bits, and peek the next word. The reference uses
	 * read offsets 0..0x80 to advance by the requested number of bits;
	 * a shift read returns the window after advancing.
	 */
	p->first = readl(p->avc);
	p->shift = readl(p->avc + 0x80);
	p->second = readl(p->avc);
	p->compared = p->first == 0x13579bdf && p->shift == 0x2468acfe &&
		p->second == 0x2468acfe;
	return p->compared ? 0 : -EIO;
}

static int break_input(struct fifo_probe *p)
{
	/* MT6797 functional specification 6.7.4.5 requires both acknowledgements
	 * before resetting the core and releasing clocks or DMA mappings.
	 * A finished initial fetch alone cannot prove subsequent DMA is idle.
	 */
	write_reg(p->break_original | BIT(0), p->misc + BREAK_CONTROL);
	return readl_poll_timeout(p->misc + BREAK_STATUS, p->break_status,
				 (p->break_status & BREAK_IDLE) == BREAK_IDLE,
				 10, 100000);
}

static ssize_t result_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct fifo_probe *p = dev_get_drvdata(dev);
	return sysfs_emit(buf,
		"{\"schema\":1,\"dma_mask_bits\":%u,\"all_clocks\":%s,"
		"\"nonposted\":%s,"
		"\"common_reset\":%s,\"async_write\":%s,"
		"\"clear_caller_gate\":%s,\"caller_gate_after_fetch\":%u,"
		"\"common_reset_original\":%u,\"async_original\":%u,\"async_after_fetch\":%u,"
		"\"caller_controls\":{\"misc_a8\":%u,\"misc_f4\":%u},"
		"\"global_before\":{\"clock\":%u,\"reset\":%u},"
		"\"minimal_clocks\":%s,\"clear_legacy\":%s,\"resources_held\":%s,"
		"\"iommu_attached\":%s,\"dma_started\":%s,"
		"\"decode_started\":false,\"compared\":%s,\"quiesced\":%s,"
		"\"fenced\":%s,\"input_unchanged\":%s,\"scratch_unchanged\":%s,"
		"\"result\":%d,\"reset_result\":%d,"
		"\"break_result\":%d,\"break_status\":%u,"
		"\"input_iova\":%llu,\"fetch_status\":%u,\"sram_status\":%u,"
		"\"first\":%u,\"shift\":%u,\"second\":%u,"
		"\"fifo_start\":%u,\"fifo_end\":%u,\"read_ptr\":%u,"
		"\"clock_select_original\":%u,\"clock_select\":%u,"
		"\"power_down\":%u,\"power_down_programmed\":%u,\"clock_rate\":%lu,"
		"\"pdn_spec_original\":%u,\"pdn_module_original\":%u,"
		"\"pdn_spec\":%u,\"pdn_module\":%u,\"larb_mmu\":%u,"
		"\"fifo_start_before_reset\":%u,\"read_ptr_before_reset\":%u,"
		"\"dcm_original\":%u,\"dcm_programmed\":%u,"
		"\"global_after_fetch\":{\"clock\":%u,\"reset\":%u,\"dcm\":%u},"
		"\"after_fetch\":{\"clock_select\":%u,\"pdn_spec\":%u,"
		"\"pdn_module\":%u,\"auto_pdn\":%u,\"write_ptr\":%u,"
		"\"avc_control\":%u,\"sram\":%u,\"irq\":%u}}\n",
		TEST_DMA_BITS, all_clocks ? "true" : "false",
		nonposted ? "true" : "false",
		common_reset ? "true" : "false", async_write ? "true" : "false",
		clear_caller_gate ? "true" : "false", p->caller_gate_after_fetch,
		p->common_reset_original, p->async_original, p->async_after_fetch,
		p->caller_controls[0], p->caller_controls[1],
		p->global_before[0], p->global_before[1],
		minimal_clocks ? "true" : "false", clear_legacy ? "true" : "false",
		p->resources_held ? "true" : "false",
		p->iommu_attached ? "true" : "false",
		p->dma_started ? "true" : "false",
		p->compared ? "true" : "false", p->quiesced ? "true" : "false",
		p->fenced ? "true" : "false", p->input_unchanged ? "true" : "false",
		p->scratch_unchanged ? "true" : "false", p->result, p->reset_result,
		p->break_result, p->break_status,
		(unsigned long long)p->input_dma, p->fetch_status, p->sram_status,
		p->first, p->shift, p->second, p->fifo_start_readback,
		p->fifo_end_readback, p->read_ptr_readback, p->clock_select_original,
		p->clock_select, p->power_down, p->power_down_programmed, p->clock_rate,
		p->pdn_spec_original,
		p->pdn_module_original, p->pdn_spec, p->pdn_module, p->larb_mmu,
		p->fifo_start_before_reset, p->read_ptr_before_reset,
		p->dcm_original, p->dcm_programmed, p->global_after_fetch[0],
		p->global_after_fetch[1], p->global_after_fetch[2],
		p->after_fetch[0], p->after_fetch[1], p->after_fetch[2], p->after_fetch[3],
		p->after_fetch[4], p->after_fetch[5], p->after_fetch[6], p->after_fetch[7]);
}
static DEVICE_ATTR_RO(result);
static struct attribute *fifo_attrs[] = { &dev_attr_result.attr, NULL };
ATTRIBUTE_GROUPS(fifo);

static void free_buffers(struct fifo_probe *p)
{
	if (p->input)
		dma_free_coherent(p->dev, INPUT_ALLOC_SIZE, p->input, p->input_dma);
	if (p->scratch)
		dma_free_coherent(p->dev, FIFO_SIZE, p->scratch, p->scratch_dma);
	p->input = p->scratch = NULL;
}

static void __iomem *map_codec_bank(struct platform_device *pdev, const char *name)
{
	struct resource *resource, mapping;

	resource = platform_get_resource_byname(pdev, IORESOURCE_MEM, name);
	if (!resource)
		return ERR_PTR(-ENODEV);
	mapping = *resource;
	/* The public MT6797 resource driver maps codec userspace registers with
	 * pgprot_noncached(), which is Device-nGnRnE in that arm64 kernel.
	 * The standard current arm64 ioremap permits early write acknowledgement.
	 * Use the kernel's resource flag/API to request the matching attributes.
	 */
	if (nonposted)
		mapping.flags |= IORESOURCE_MEM_NONPOSTED;
	return devm_ioremap_resource(&pdev->dev, &mapping);
}

static int fifo_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct fifo_probe *p;
	struct device_node *larb;
	struct resource resource;
	int ret, pm_ret;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return -ENODEV;
	if (fetch && hold_resources)
		return -EINVAL;
	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->dev = dev;
	p->gcon = syscon_regmap_lookup_by_compatible("mediatek,mt6797-vdecsys");
	if (IS_ERR(p->gcon))
		return dev_err_probe(dev, PTR_ERR(p->gcon), "decoder syscon unavailable\n");
	p->clocks[0].id = "bus";
	p->clocks[1].id = "active";
	p->clocks[2].id = "engine";
	platform_set_drvdata(pdev, p);
	ret = devm_clk_bulk_get(dev, ARRAY_SIZE(p->clocks), p->clocks);
	if (ret)
		return dev_err_probe(dev, ret, "decoder clocks unavailable\n");
	p->misc = map_codec_bank(pdev, "misc");
	if (IS_ERR(p->misc))
		return PTR_ERR(p->misc);
	p->vld = map_codec_bank(pdev, "vld");
	if (IS_ERR(p->vld))
		return PTR_ERR(p->vld);
	p->top = map_codec_bank(pdev, "vld-top");
	if (IS_ERR(p->top))
		return PTR_ERR(p->top);
	p->mc = map_codec_bank(pdev, "mc");
	if (IS_ERR(p->mc))
		return PTR_ERR(p->mc);
	p->avc = map_codec_bank(pdev, "avc-vld");
	if (IS_ERR(p->avc))
		return PTR_ERR(p->avc);
	larb = of_parse_phandle(dev->of_node, "mediatek,larbs", 0);
	if (!larb)
		return -ENODEV;
	ret = of_address_to_resource(larb, 0, &resource);
	of_node_put(larb);
	if (ret)
		return ret;
	if (resource.start != 0x16010000 || resource_size(&resource) < 0xfc4)
		return -EINVAL;
	/* The SMI driver owns this resource. Do not claim or write it; observe
	 * the MMU mask programmed by its existing MT6797 runtime callback.
	 */
	p->larb_mmu_reg = devm_ioremap(dev, resource.start + 0xfc0, 4);
	if (!p->larb_mmu_reg)
		return -ENOMEM;
	p->iommu_attached = iommu_get_domain_for_dev(dev) != NULL;
	if (!p->iommu_attached)
		return dev_err_probe(dev, -ENODEV, "decoder has no IOMMU domain\n");
	/* Start below 1 GiB so the shifted FIFO addresses fit 24 bits. This
	 * deliberately conservative diagnostic limit does not establish the
	 * actual MT6797 address width; high-address DMA still needs testing.
	 */
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(TEST_DMA_BITS));
	if (ret)
		return ret;
	pm_runtime_enable(dev);
	ret = pm_runtime_resume_and_get(dev);
	if (ret < 0)
		goto disable_pm;
	p->clock_rate = clk_get_rate(p->clocks[2].clk);
	p->clock_select_original = readl(p->misc + REG_SELECT);
	p->power_down = readl(p->misc);
	p->pdn_spec_original = readl(p->misc + PDN_SPEC);
	p->pdn_module_original = readl(p->misc + PDN_MODULE);
	p->auto_pdn_original = readl(p->misc + AUTO_PDN_CONTROL);
	p->break_original = readl(p->misc + BREAK_CONTROL);
	p->irq_original = readl(p->misc + IRQ_CONTROL);
	p->async_original = readl(p->vld + VLD_ASYNC_CONTROL);
	p->common_reset_original = readl(p->vld + VLD_COMMON_SRAM_RESET);
	/* Read-only observations of the extra controls changed by the public
	 * caller's post-completion path. Their MT6797 meanings are not qualified.
	 */
	p->caller_controls[0] = readl(p->misc + 0xa8);
	p->caller_controls[1] = readl(p->misc + 0xf4);
	ret = regmap_read(p->gcon, 0, &p->global_before[0]);
	if (ret)
		goto put_pm;
	ret = regmap_read(p->gcon, 0x10, &p->global_before[1]);
	if (ret)
		goto put_pm;
	p->larb_mmu = readl(p->larb_mmu_reg);
	ret = regmap_read(p->gcon, GLOBAL_DCM_CONTROL, &p->dcm_original);
	if (ret)
		goto put_pm;
	if (!fetch) {
		p->quiesced = true; /* This invocation never enables DMA. */
		if (hold_resources) {
			p->resources_held = true;
			return 0;
		}
		goto put_pm;
	}
	/* Reserve a trailing guard area so an allocation at the DMA aperture's
	 * upper edge cannot put the programmed exclusive FIFO end at 1 << 30.
	 * Both shifted endpoint words must fit the diagnostic's 24-bit limit.
	 */
	p->input = dma_alloc_coherent(dev, INPUT_ALLOC_SIZE, &p->input_dma, GFP_KERNEL);
	p->scratch = dma_alloc_coherent(dev, FIFO_SIZE, &p->scratch_dma, GFP_KERNEL);
	if (!p->input || !p->scratch) {
		ret = -ENOMEM;
		goto free;
	}
	if (p->input_dma + FIFO_SIZE > DMA_BIT_MASK(TEST_DMA_BITS) ||
	    upper_32_bits(p->scratch_dma + FIFO_SIZE) ||
	    !IS_ALIGNED(p->input_dma, 64)) {
		ret = -ERANGE;
		goto free;
	}
	memset(p->input, 0xa5, INPUT_ALLOC_SIZE);
	memcpy(p->input, test_bytes, sizeof(test_bytes));
	memset(p->scratch, 0xd3, FIFO_SIZE);
	p->result = test_input(p);
	/* Capture clock/control state before cleanup reset can change it. */
	p->after_fetch[0] = readl(p->misc + REG_SELECT);
	p->after_fetch[1] = readl(p->misc + PDN_SPEC);
	p->after_fetch[2] = readl(p->misc + PDN_MODULE);
	p->after_fetch[3] = readl(p->misc + AUTO_PDN_CONTROL);
	p->after_fetch[4] = readl(p->vld + VLD_WRITE_PTR);
	p->after_fetch[5] = readl(p->avc + AVC_CONTROL);
	p->after_fetch[6] = readl(p->vld + VLD_SRAM_STATUS);
	p->after_fetch[7] = readl(p->misc + 0xa4);
	p->async_after_fetch = readl(p->vld + VLD_ASYNC_CONTROL);
	p->caller_gate_after_fetch = readl(p->misc + 0xf4);
	regmap_read(p->gcon, 0, &p->global_after_fetch[0]);
	regmap_read(p->gcon, 0x10, &p->global_after_fetch[1]);
	regmap_read(p->gcon, GLOBAL_DCM_CONTROL, &p->global_after_fetch[2]);
	if (p->dma_started)
		p->break_result = break_input(p);
	p->reset_result = reset_input(p);
	dma_rmb();
	p->input_unchanged = !memcmp(p->input, test_bytes, sizeof(test_bytes)) &&
		!memchr_inv(p->input + sizeof(test_bytes), 0xa5,
			    INPUT_ALLOC_SIZE - sizeof(test_bytes));
	p->scratch_unchanged = !memchr_inv(p->scratch, 0xd3, FIFO_SIZE);
	if (!p->input_unchanged || !p->scratch_unchanged)
		p->result = -EIO;
	/* Documented break acknowledgement plus idle reset must precede freeing.
	 * On uncertainty retain mappings, clocks and the module until reboot.
	 * Forced unload is not used; bind/unbind sysfs attributes are suppressed.
	 */
	p->quiesced = !p->reset_result &&
		(!p->dma_started || !p->break_result);
	if (!p->quiesced) {
		p->fenced = true;
		__module_get(THIS_MODULE);
		dev_err(dev, "input DMA not proven idle; retaining buffers until reboot\n");
		return 0;
	}
	write_reg(p->clock_select_original, p->misc + REG_SELECT);
	write_reg(p->power_down, p->misc);
	write_reg(p->pdn_spec_original, p->misc + PDN_SPEC);
	write_reg(p->pdn_module_original, p->misc + PDN_MODULE);
	write_reg(p->auto_pdn_original, p->misc + AUTO_PDN_CONTROL);
	write_reg(p->break_original, p->misc + BREAK_CONTROL);
	write_reg(p->irq_original & ~BIT(4), p->misc + IRQ_CONTROL);
	if (async_write)
		write_reg(p->async_original, p->vld + VLD_ASYNC_CONTROL);
	ret = regmap_update_bits(p->gcon, GLOBAL_DCM_CONTROL, BIT(0),
				 p->dcm_original & BIT(0));
	write_reg(0, p->vld + VLD_SOFT_RESET);
	if (clear_caller_gate)
		write_reg(p->caller_controls[1], p->misc + 0xf4);
free:
	free_buffers(p);
put_pm:
	pm_ret = pm_runtime_put_sync_suspend(dev);
	if (ret >= 0 && pm_ret < 0)
		ret = pm_ret;
disable_pm:
	if (ret < 0) {
		pm_runtime_disable(dev);
		return ret;
	}
	return 0;
}

static void fifo_remove(struct platform_device *pdev)
{
	struct fifo_probe *p = platform_get_drvdata(pdev);
	/* A fenced test pins this module, so ordinary unload cannot get here. */
	WARN_ON(p->fenced);
	if (!p->fenced)
		free_buffers(p);
	if (p->resources_held) {
		pm_runtime_put_sync_suspend(&pdev->dev);
		p->resources_held = false;
	}
	pm_runtime_disable(&pdev->dev);
}

static const struct of_device_id fifo_of_match[] = {
	{ .compatible = "mediatek,mt6797-vcodec-dec" }, { }
};
MODULE_DEVICE_TABLE(of, fifo_of_match);

static struct platform_driver fifo_driver = {
	.probe = fifo_probe,
	.remove = fifo_remove,
	.driver = {
		.name = "mt6797-vdec-fifo-probe",
		.of_match_table = fifo_of_match,
		.pm = pm_ptr(&fifo_pm_ops),
		.dev_groups = fifo_groups,
		.suppress_bind_attrs = true,
	},
};
module_platform_driver(fifo_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("MT6797 direct H.264 input FIFO DMA qualification");
