// SPDX-License-Identifier: GPL-2.0-only
/* Original MT6797 encoder idle-reset diagnostic.
 * Facts: public MT6797 register table section 4.8 and matching GPL kernel reset/IRQ glue.
 * No firmware, DMA allocation, picture configuration or frame commands.
 * An idle reset does not qualify stopping an active DMA transaction.
 */
#include <linux/clk.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/delay.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <dt-bindings/clock/mt6797-clk.h>

#define PROBE_NAME "mt6797-venc-idle-reset-probe"
#define VENC_BASE 0x17002000
#define VENC_SIZE 0x1000

static struct platform_device *probe_device;
static int probe_result = -ENODEV;
static bool completed, power_vote_released;
static unsigned long engine_hz, bus_hz;
static u32 clock_status, chip_enable, dcm_control, clock_control;

#define VENC_IRQ_STATUS 0x5c
#define VENC_IRQ_ACK 0x60
#define VENC_RESET_N 0xa8
#define VENC_PAUSE 0xac
#define VENC_CE 0xec
#define PAUSE_IRQ BIT(4)
#define RESET_CYCLES 3

struct reset_cycle {
	int result, pause_result;
	u32 irq_paused, reset_asserted, reset_released, irq_after;
	bool attempted, completed, pause_seen;
};
static struct reset_cycle cycles[RESET_CYCLES];
static unsigned int control_writes, completed_cycles;
static u32 initial_irq, initial_pause, initial_reset;
static u32 restored_irq, restored_pause, restored_reset, restored_ce;
static u32 clock_status_after, dcm_after, clock_control_after;
static bool restore_attempted, controls_restored, clock_modes_preserved, fenced;

static ssize_t result_show(struct device *dev, struct device_attribute *attr,
                           char *buf)
{
	ssize_t n;
	unsigned int i;

	n = sysfs_emit(buf,
		"{\"schema\":1,\"dma_started\":false,\"encode_started\":false,"
		"\"active_dma_stop_qualified\":false,\"irq_delivery_qualified\":false,"
		"\"control_writes\":%u,\"completed_cycles\":%u,\"restore_attempted\":%s,"
		"\"controls_restored\":%s,"
		"\"clock_modes_preserved\":%s,\"fenced\":%s,\"power_vote_released\":%s,"
		"\"engine_hz\":%lu,\"bus_hz\":%lu,\"clock_status\":%u,"
		"\"clock_status_after\":%u,\"chip_enable\":%u,\"dcm_control\":%u,"
		"\"dcm_after\":%u,\"clock_control\":%u,\"clock_control_after\":%u,"
		"\"initial_irq\":%u,\"initial_pause\":%u,\"initial_reset\":%u,"
		"\"restored_irq\":%u,\"restored_pause\":%u,\"restored_reset\":%u,"
		"\"restored_ce\":%u,\"result\":%d,\"cycles\":[",
		control_writes, completed_cycles, restore_attempted ? "true" : "false",
		controls_restored ? "true" : "false",
		clock_modes_preserved ? "true" : "false", fenced ? "true" : "false",
		power_vote_released ? "true" : "false", engine_hz, bus_hz,
		clock_status, clock_status_after, chip_enable, dcm_control, dcm_after,
		clock_control, clock_control_after, initial_irq, initial_pause, initial_reset,
		restored_irq, restored_pause, restored_reset, restored_ce, probe_result);
	for (i = 0; i < RESET_CYCLES; i++) {
		const struct reset_cycle *c = &cycles[i];
		n += sysfs_emit_at(buf, n,
			"%s{\"attempted\":%s,\"completed\":%s,\"result\":%d,"
			"\"pause_result\":%d,\"pause_seen\":%s,"
			"\"irq_paused\":%u,\"reset_asserted\":%u,\"reset_released\":%u,"
			"\"irq_after\":%u}", i ? "," : "", c->attempted ? "true" : "false",
			c->completed ? "true" : "false", c->result, c->pause_result,
			c->pause_seen ? "true" : "false", c->irq_paused, c->reset_asserted,
			c->reset_released, c->irq_after);
	}
	return n + sysfs_emit_at(buf, n, "]}\n");
}

static void write_control(void __iomem *regs, u32 offset, u32 value)
{
	writel(value, regs + offset);
	control_writes++;
}

static int exercise_idle_reset(void __iomem *regs)
{
	unsigned int i;
	int ret = 0;
	u32 word;

	initial_irq = readl(regs + VENC_IRQ_STATUS);
	initial_pause = readl(regs + VENC_PAUSE);
	initial_reset = readl(regs + VENC_RESET_N);
	/* This candidate boot has no encoder driver. Refuse pre-existing activity
	 * rather than taking ownership of unknown state or acknowledging its IRQ.
	 * The matching public glue uses only whole-word zero/one reset controls.
	 */
	if (chip_enable || initial_irq || initial_pause || initial_reset > 1)
		return -EBUSY;
	write_control(regs, VENC_RESET_N, 0);
	if (readl(regs + VENC_RESET_N)) {
		ret = -EIO;
		goto restore;
	}
	/* Hold reset while enabling the idle engine;
	 * no address, codec/picture setup or start register is ever written.
	 */
	write_control(regs, VENC_CE, 1);
	if (readl(regs + VENC_CE) != 1) {
		ret = -EIO;
		goto restore;
	}
	write_control(regs, VENC_RESET_N, 1);
	if (readl(regs + VENC_RESET_N) != 1) {
		ret = -EIO;
		goto restore;
	}
	for (i = 0; i < RESET_CYCLES; i++) {
		struct reset_cycle *c = &cycles[i];

		c->attempted = true;
		write_control(regs, VENC_PAUSE, 1);
		if (readl(regs + VENC_PAUSE) != 1) {
			ret = c->result = -EIO;
			goto restore;
		}
		c->pause_result = readl_poll_timeout(regs + VENC_IRQ_STATUS,
                                     c->irq_paused,
                                     c->irq_paused & PAUSE_IRQ, 10, 2000);
		c->pause_seen = !!(c->irq_paused & PAUSE_IRQ);
		if (c->irq_paused & ~PAUSE_IRQ) {
			ret = c->result = -EIO;
			goto restore;
		}
		if (c->pause_seen) {
			/* The public IRQ handler acknowledges the pause bit individually. */
			write_control(regs, VENC_IRQ_ACK, PAUSE_IRQ);
			c->result = readl_poll_timeout(regs + VENC_IRQ_STATUS, word,
                                 !word, 10, 2000);
			if (c->result) {
				ret = c->result;
				goto restore;
			}
			write_control(regs, VENC_RESET_N, 0);
			write_control(regs, VENC_PAUSE, 0);
		} else {
			/* Public idle/timeout branch: clear pause, then assert reset. A timeout
			 * does not prove a DMA stop; it is recorded separately from readbacks.
			 */
			udelay(200);
			write_control(regs, VENC_PAUSE, 0);
			write_control(regs, VENC_RESET_N, 0);
		}
		c->reset_asserted = readl(regs + VENC_RESET_N);
		if (c->reset_asserted || readl(regs + VENC_PAUSE)) {
			ret = c->result = -EIO;
			goto restore;
		}
		write_control(regs, VENC_RESET_N, 1);
		c->reset_released = readl(regs + VENC_RESET_N);
		c->irq_after = readl(regs + VENC_IRQ_STATUS);
		if (c->reset_released != 1 || c->irq_after) {
			ret = c->result = -EIO;
			goto restore;
		}
		c->completed = true;
		completed_cycles++;
	}
restore:
	/* Return the unused engine to its original disabled state while reset is
	 * held. If these readbacks fail, retain device/power ownership for reboot.
	 */
	restore_attempted = true;
	write_control(regs, VENC_RESET_N, 0);
	write_control(regs, VENC_PAUSE, initial_pause);
	write_control(regs, VENC_CE, chip_enable);
	restored_ce = readl(regs + VENC_CE);
	write_control(regs, VENC_RESET_N, initial_reset);
	restored_reset = readl(regs + VENC_RESET_N);
	restored_pause = readl(regs + VENC_PAUSE);
	restored_irq = readl(regs + VENC_IRQ_STATUS);
	controls_restored = restored_ce == chip_enable &&
                     restored_reset == initial_reset &&
                     restored_pause == initial_pause &&
                     restored_irq == initial_irq;
	if (!controls_restored)
		ret = -EIO;
	return ret;
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
	 * configuration or larb register access is needed for these idle controls.
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
	/* Clock-control modes are observed but never changed. */
	chip_enable = readl(regs + 0xec);
	dcm_control = readl(regs + 0xf4);
	clock_control = readl(regs + 0xfc);
	ret = exercise_idle_reset(regs);
	completed = true;
	if (control_writes && !controls_restored) {
		fenced = true;
		probe_result = ret;
		__module_get(THIS_MODULE);
		dev_err(dev, "encoder idle controls not restored; ownership retained until reboot\n");
		return 0;
	}
	dcm_after = readl(regs + 0xf4);
	clock_control_after = readl(regs + 0xfc);
	pm_ret = regmap_read(gcon, 0, &clock_status_after);
	clock_modes_preserved = !pm_ret && clock_status_after == clock_status &&
		(dcm_after & BIT(0)) == (dcm_control & BIT(0)) &&
		clock_control_after == clock_control;
	if (!ret && !clock_modes_preserved)
		ret = -EIO;
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
MODULE_DESCRIPTION("MT6797 encoder idle-reset diagnostic; no DMA or frame commands");
