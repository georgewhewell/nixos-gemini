// SPDX-License-Identifier: GPL-2.0-only
/* Temporary MT6797 register compatibility probe. No DMA or decode commands.
 * The write test selects the H.264 local clock while software reset is held.
 */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/mfd/syscon.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <dt-bindings/clock/mt6797-clk.h>
#include "mt6797-h264-controls.h"

#define PROBE_NAME "mt6797-vdec-register-probe"
#define VDEC_BASE 0x16020000
#define VDEC_SIZE 0x6000
#define VLD_SRAM_CTRL 0x10f4
#define VLD_PROCESSING BIT(15)
#define VLD_SOFT_RESET 0x1108
#define LOCAL_CLOCK_SELECT 0x84
#define AVC_CONTROL 0x3084
#define AVC_SPS 0x3088
#define AVC_PPS 0x3090
#define AVC_REFS 0x3094

static bool test_controls;
module_param(test_controls, bool, 0444);
MODULE_PARM_DESC(test_controls, "Test and restore three H.264 configuration registers; never starts decoding");

static struct platform_device *probe_device;
static int probe_result = -ENODEV;
static bool probe_completed, power_vote_released;
static u32 original[3], observed[3], restored[3], sram_status;
static u32 gcon_clock_status, gcon_reset_status, local_clock_select, local_power_down;
static u32 h264_clock_select, restored_clock_select;
static u32 original_avc_control, enabled_avc_control, restored_avc_control;
static unsigned long clock_rate;
static const unsigned int offsets[] = { AVC_SPS, AVC_PPS, AVC_REFS };

static ssize_t result_show(struct device *dev, struct device_attribute *attr,
			   char *buf)
{
	return sysfs_emit(buf,
		"{\"schema\":1,\"test_controls\":%s,\"dma_started\":false,"
		"\"decode_started\":false,\"power_vote_released\":%s,"
		"\"clock_hz\":%lu,\"sram_status\":%u,"
		"\"gcon_clock_status\":%u,\"gcon_reset_status\":%u,"
		"\"local_clock_select\":%u,\"local_power_down\":%u,"
		"\"h264_clock_select\":%u,\"restored_clock_select\":%u,"
		"\"original_avc_control\":%u,\"enabled_avc_control\":%u,"
		"\"restored_avc_control\":%u,"
		"\"original\":[%u,%u,%u],\"observed\":[%u,%u,%u],"
		"\"restored\":[%u,%u,%u],\"result\":%d}\n",
		test_controls ? "true" : "false",
		power_vote_released ? "true" : "false", clock_rate, sram_status,
		gcon_clock_status, gcon_reset_status, local_clock_select, local_power_down,
		h264_clock_select, restored_clock_select,
		original_avc_control, enabled_avc_control, restored_avc_control,
		original[0], original[1], original[2],
		observed[0], observed[1], observed[2],
		restored[0], restored[1], restored[2], probe_result);
}
static DEVICE_ATTR_RO(result);
static struct attribute *probe_attrs[] = { &dev_attr_result.attr, NULL };
ATTRIBUTE_GROUPS(probe);

static void put_clock(void *clock)
{
	clk_put(clock);
}

static int probe_registers(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device_node *node;
	struct clk_bulk_data clocks[3] = { { .id = "bus" },
		{ .id = "active" }, { .id = "engine" } };
	struct of_phandle_args spec = { .args_count = 1 };
	const unsigned int clock_ids[] = { CLK_VDEC_ACTIVE, CLK_VDEC_CKEN_ENG };
	struct regmap *gcon;
	void __iomem *regs;
	struct v4l2_ctrl_h264_sps sps = {
		.profile_idc = 66, .chroma_format_idc = 1,
		.max_num_ref_frames = 2,
		.pic_width_in_mbs_minus1 = 3,
		.pic_height_in_map_units_minus1 = 3,
		.flags = V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY |
			 V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE,
	};
	struct v4l2_ctrl_h264_pps pps = {
		.num_ref_idx_l0_default_active_minus1 = 1,
		.num_ref_idx_l1_default_active_minus1 = 1,
		.flags = V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT,
	};
	struct mt6797_h264_header_words words;
	u32 values[3];
	int ret, pm_ret, i;

	probe_completed = power_vote_released = false;
	ret = mt6797_h264_header_words(&sps, &pps, &words);
	if (ret)
		goto done;
	values[0] = words.sps;
	values[1] = words.pps;
	values[2] = words.reference_counts;

	/* Borrow only the disabled larb's clock/domain description. Set it
	 * after binding this private driver, so the SMI driver cannot match.
	 * The platform device owns the node reference until its release.
	 */
	node = of_find_node_by_path("/larb@16010000");
	if (!node || !of_device_is_compatible(node, "mediatek,mt6797-smi-larb") ||
	    of_device_is_available(node)) {
		of_node_put(node);
		ret = -EBUSY;
		goto done;
	}
	dev->of_node = node;
	device_set_node(dev, of_fwnode_handle(node));
	clocks[0].clk = devm_clk_get(dev, "apb");
	if (IS_ERR(clocks[0].clk)) {
		ret = PTR_ERR(clocks[0].clk);
		goto done;
	}
	spec.np = of_parse_phandle(node, "clocks", 0);
	if (!spec.np) {
		ret = -ENODEV;
		goto done;
	}
	for (i = 0; i < ARRAY_SIZE(clock_ids); i++) {
		spec.args[0] = clock_ids[i];
		clocks[i + 1].clk = of_clk_get_from_provider(&spec);
		if (IS_ERR(clocks[i + 1].clk)) {
			ret = PTR_ERR(clocks[i + 1].clk);
			break;
		}
		ret = devm_add_action_or_reset(dev, put_clock, clocks[i + 1].clk);
		if (ret)
			break;
	}
	of_node_put(spec.np);
	if (ret)
		goto done;
	gcon = syscon_regmap_lookup_by_compatible("mediatek,mt6797-vdecsys");
	if (IS_ERR(gcon)) {
		ret = PTR_ERR(gcon);
		goto done;
	}
	regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(regs)) {
		ret = PTR_ERR(regs);
		goto done;
	}
	ret = dev_pm_domain_attach(dev, PD_FLAG_ATTACH_POWER_ON);
	if (ret)
		goto done;
	if (!dev->pm_domain) {
		ret = -ENODEV;
		goto detach;
	}
	pm_runtime_enable(dev);
	ret = pm_runtime_resume_and_get(dev);
	if (ret < 0)
		goto disable_pm;
	ret = clk_bulk_prepare_enable(ARRAY_SIZE(clocks), clocks);
	if (ret)
		goto put_pm;
	clock_rate = clk_get_rate(clocks[0].clk);
	if (!clock_rate) {
		ret = -EIO;
		goto disable_clk;
	}
	ret = regmap_read(gcon, 0, &gcon_clock_status);
	if (ret)
		goto disable_clk;
	ret = regmap_read(gcon, 0x10, &gcon_reset_status);
	if (ret)
		goto disable_clk;
	local_clock_select = readl(regs + LOCAL_CLOCK_SELECT);
	local_power_down = readl(regs);
	original_avc_control = readl(regs + AVC_CONTROL);
	sram_status = readl(regs + VLD_SRAM_CTRL);
	if (sram_status & VLD_PROCESSING) {
		ret = -EBUSY;
		goto disable_clk;
	}
	for (i = 0; i < ARRAY_SIZE(offsets); i++)
		original[i] = readl(regs + offsets[i]);
	/* The temporary write test is limited to an unused, pristine core.
	 * Its reset sequence must never discard an existing decode context.
	 */
	if (test_controls && (local_clock_select || original_avc_control || original[0] ||
			      original[1] || original[2])) {
		ret = -EBUSY;
		goto disable_clk;
	}
	if (test_controls) {
		/* MT6797 specification section 6.7 documents VLD register 66
		 * bit 0 as software reset. Use only that documented bit.
		 * The related public interface selects H.264 with MISC + 0x84
		 * equal to 2 while reset is held. Never issue VLD fetch/init
		 * or AVC + 0x238 (the actual frame-start command).
		 */
		if (readl(regs + VLD_SOFT_RESET) & BIT(0)) {
			ret = -EBUSY;
			goto disable_clk;
		}
		writel(BIT(0), regs + VLD_SOFT_RESET);
		readl(regs + VLD_SOFT_RESET);
		udelay(1);
		writel(2, regs + LOCAL_CLOCK_SELECT);
		writel(0, regs + VLD_SOFT_RESET);
		readl(regs + VLD_SOFT_RESET);
		/* AVC_EN selects the H.264 parser; FIFO fetch and frame start
		 * are separate commands that this probe never issues.
		 */
		writel(BIT(0), regs + AVC_CONTROL);
	}
	h264_clock_select = readl(regs + LOCAL_CLOCK_SELECT);
	enabled_avc_control = readl(regs + AVC_CONTROL);
	if (test_controls)
		for (i = 0; i < ARRAY_SIZE(offsets); i++)
			writel(values[i], regs + offsets[i]);
	for (i = 0; i < ARRAY_SIZE(offsets); i++)
		observed[i] = readl(regs + offsets[i]);
	/* Restore all registers before evaluating a mismatch. No early return
	 * after writes, and no writes to any command or DMA address register.
	 */
	if (test_controls)
		for (i = 0; i < ARRAY_SIZE(offsets); i++)
			writel(original[i], regs + offsets[i]);
	for (i = 0; i < ARRAY_SIZE(offsets); i++) {
		restored[i] = readl(regs + offsets[i]);
		if (restored[i] != original[i] ||
		    (test_controls && observed[i] != values[i]))
			ret = -EIO;
	}
	if (test_controls) {
		writel(original_avc_control, regs + AVC_CONTROL);
		restored_avc_control = readl(regs + AVC_CONTROL);
		writel(BIT(0), regs + VLD_SOFT_RESET);
		readl(regs + VLD_SOFT_RESET);
		udelay(1);
		writel(local_clock_select, regs + LOCAL_CLOCK_SELECT);
		writel(0, regs + VLD_SOFT_RESET);
		readl(regs + VLD_SOFT_RESET);
	}
	restored_clock_select = readl(regs + LOCAL_CLOCK_SELECT);
	if (restored_clock_select != local_clock_select ||
	    (test_controls && (h264_clock_select != 2 ||
			       enabled_avc_control != BIT(0) ||
			       restored_avc_control != original_avc_control)))
		ret = -EIO;
	probe_completed = true;
disable_clk:
	clk_bulk_disable_unprepare(ARRAY_SIZE(clocks), clocks);
put_pm:
	pm_ret = pm_runtime_put_sync_suspend(dev);
	power_vote_released = pm_ret >= 0;
	if (ret >= 0 && pm_ret < 0)
		ret = pm_ret;
disable_pm:
	pm_runtime_disable(dev);
detach:
	dev_pm_domain_detach(dev, true);
done:
	probe_result = ret < 0 ? ret : 0;
	/* Preserve a completed mismatch report for userspace to inspect. */
	return probe_completed ? 0 : probe_result;
}

static struct platform_driver probe_driver = {
	.probe = probe_registers,
	.prevent_deferred_probe = true,
	.driver = { .name = PROBE_NAME, .dev_groups = probe_groups },
};

static int __init register_probe(void)
{
	static const struct resource resource = {
		.start = VDEC_BASE, .end = VDEC_BASE + VDEC_SIZE - 1,
		.flags = IORESOURCE_MEM,
	};
	int ret;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return -ENODEV;
	ret = platform_driver_register(&probe_driver);
	if (ret)
		return ret;
	/* No OF node during initial driver matching or DMA configuration. */
	probe_device = platform_device_register_simple(PROBE_NAME, -1, &resource, 1);
	if (IS_ERR(probe_device)) {
		ret = PTR_ERR(probe_device);
		goto unregister_driver;
	}
	if (!probe_completed) {
		ret = probe_result;
		platform_device_unregister(probe_device);
		goto unregister_driver;
	}
	return 0;
unregister_driver:
	platform_driver_unregister(&probe_driver);
	return ret;
}

static void __exit unregister_probe(void)
{
	platform_device_unregister(probe_device);
	platform_driver_unregister(&probe_driver);
}
module_init(register_probe);
module_exit(unregister_probe);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Temporary non-DMA MT6797 H.264 register compatibility probe");
