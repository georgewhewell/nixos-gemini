// SPDX-License-Identifier: GPL-2.0-only
/* Original, command-free MT6797 encoder resource diagnostic.
 * Interface facts: published MT6797 register table4.8 and public Linux DT.
 * No codec library, firmware, DMA allocation or encoder register writes.
 */
#include <linux/clk.h>
#include <linux/io.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <dt-bindings/clock/mt6797-clk.h>

#define PROBE_NAME "mt6797-venc-resource-probe"
#define VENC_BASE 0x17002000
#define VENC_SIZE 0x1000

static struct platform_device *probe_device;
static int probe_result = -ENODEV;
static bool completed, power_vote_released;
static unsigned long engine_hz, bus_hz;
static u32 clock_status, chip_enable, dcm_control, clock_control;

static ssize_t result_show(struct device *dev, struct device_attribute *attr,
			   char *buf)
{
	return sysfs_emit(buf,
		"{\"schema\":1,\"dma_started\":false,\"encode_started\":false,"
		"\"encoder_registers_written\":false,\"power_vote_released\":%s,"
		"\"engine_hz\":%lu,\"bus_hz\":%lu,\"clock_status\":%u,"
		"\"chip_enable\":%u,\"dcm_control\":%u,\"clock_control\":%u,"
		"\"result\":%d}\n",
		power_vote_released ? "true" : "false", engine_hz, bus_hz,
		clock_status, chip_enable, dcm_control, clock_control, probe_result);
}
static DEVICE_ATTR_RO(result);
static struct attribute *probe_attrs[] = { &dev_attr_result.attr, NULL };
ATTRIBUTE_GROUPS(probe);

static void put_clock(void *clock)
{
	clk_put(clock);
}

static int probe_resources(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct device_node *node;
	struct clk_bulk_data clocks[2];
	struct of_phandle_args spec = { .args_count = 1 };
	const unsigned int ids[] = { CLK_VENC_1, CLK_VENC_0 };
	struct regmap *gcon;
	void __iomem *regs;
	int ret, pm_ret, i;

	/* Bind privately before borrowing the disabled encoder node's domain.
	 * Larb3 already serves JPEG on Gemini and remains supplier-owned. No DMA
	 * configuration or larb register access is needed for these CPU reads.
	 * Platform-device release owns the encoder node reference.
	 */
	node = of_find_node_by_path("/video-codec@17002000");
	if (!node || !of_device_is_compatible(node, "mediatek,mt6797-vcodec-enc") ||
	    of_device_is_available(node)) {
		of_node_put(node);
		ret = -EBUSY;
		goto done;
	}
	dev->of_node = node;
	device_set_node(dev, of_fwnode_handle(node));
	spec.np = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-vencsys");
	if (!spec.np) {
		ret = -ENODEV;
		goto done;
	}
	for (i = 0; i < ARRAY_SIZE(clocks); i++) {
		spec.args[0] = ids[i];
		clocks[i].clk = of_clk_get_from_provider(&spec);
		if (IS_ERR(clocks[i].clk)) {
			ret = PTR_ERR(clocks[i].clk);
			break;
		}
		ret = devm_add_action_or_reset(dev, put_clock, clocks[i].clk);
		if (ret)
			break;
	}
	of_node_put(spec.np);
	if (ret)
		goto done;
	gcon = syscon_regmap_lookup_by_compatible("mediatek,mt6797-vencsys");
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
	engine_hz = clk_get_rate(clocks[0].clk);
	bus_hz = clk_get_rate(clocks[1].clk);
	if (!engine_hz || !bus_hz) {
		ret = -EIO;
		goto disable_clk;
	}
	ret = regmap_read(gcon, 0, &clock_status);
	if (ret)
		goto disable_clk;
	/* These three words have a published register contract. Snapshot only;
	 * frame commands, unknown frame registers and IRQ state stay untouched.
	 */
	chip_enable = readl(regs + 0xec);
	dcm_control = readl(regs + 0xf4);
	clock_control = readl(regs + 0xfc);
	completed = true;
disable_clk:
	clk_bulk_disable_unprepare(ARRAY_SIZE(clocks), clocks);
put_pm:
	pm_ret = pm_runtime_put_sync_suspend(dev);
	power_vote_released = pm_ret >= 0;
	if (!ret && pm_ret < 0)
		ret = pm_ret;
disable_pm:
	pm_runtime_disable(dev);
detach:
	dev_pm_domain_detach(dev, true);
done:
	probe_result = ret;
	return completed ? 0 : ret;
}

static struct platform_driver probe_driver = {
	.probe = probe_resources,
	.prevent_deferred_probe = true,
	.driver = {
		.name = PROBE_NAME,
		.owner = THIS_MODULE,
		.dev_groups = probe_groups,
		.suppress_bind_attrs = true,
	},
};

static int __init register_probe(void)
{
	static const struct resource resource = {
		.start = VENC_BASE, .end = VENC_BASE + VENC_SIZE - 1,
		.flags = IORESOURCE_MEM | IORESOURCE_MEM_NONPOSTED,
	};
	int ret;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return -ENODEV;
	ret = platform_driver_register(&probe_driver);
	if (ret)
		return ret;
	probe_device = platform_device_register_simple(PROBE_NAME, -1, &resource, 1);
	if (IS_ERR(probe_device)) {
		ret = PTR_ERR(probe_device);
		goto unregister_driver;
	}
	if (!completed) {
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
MODULE_DESCRIPTION("Command-free MT6797 encoder power/clock/register diagnostic");
