// SPDX-License-Identifier: GPL-2.0-only
/* Read-only MT6797 decoder supplier snapshot. No clock/power/DMA writes.
 * Offsets come from the open clk-mt6797 and mtk-scpsys resource drivers.
 * Run while a separate decoder diagnostic holds its own runtime power vote.
 */
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>

/* VDEC power control, primary/secondary domain status, PLL control/PCW/power,
 * top-level mux: these settings are observations, not frequency measurements.
 */
static unsigned int values[7];
static unsigned int value_count;
module_param_array(values, uint, &value_count, 0444);
MODULE_PARM_DESC(values, "Saved power, two domain statuses, three PLL words and top mux");

static int read_bank(const char *compatible, resource_size_t physical,
		     const u16 *offsets, unsigned int count, unsigned int *out)
{
	struct device_node *node;
	struct resource resource;
	void __iomem *base;
	unsigned int i;
	int ret;

	node = of_find_compatible_node(NULL, NULL, compatible);
	if (!node)
		return -ENODEV;
	ret = of_address_to_resource(node, 0, &resource);
	if (ret)
		goto put_node;
	if (resource.start != physical || resource_size(&resource) != 0x1000) {
		ret = -EINVAL;
		goto put_node;
	}
	base = of_iomap(node, 0);
	if (!base) {
		ret = -ENOMEM;
		goto put_node;
	}
	/* The existing framework owns these banks. Only non-destructive control
	 * and power-status reads are performed; no resource is claimed or changed.
	 */
	for (i = 0; i < count; i++)
		out[i] = readl(base + offsets[i]);
	iounmap(base);
put_node:
	of_node_put(node);
	return ret;
}

static int __init supplier_probe_init(void)
{
	static const u16 power_offsets[] = { 0x300, 0x180, 0x184 };
	static const u16 pll_offsets[] = { 0x2e4, 0x2e8, 0x2f0 };
	static const u16 mux_offsets[] = { 0x50 };
	int ret;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return -ENODEV;
	ret = read_bank("mediatek,mt6797-scpsys", 0x10006000,
			power_offsets, ARRAY_SIZE(power_offsets), values);
	if (ret)
		return ret;
	ret = read_bank("mediatek,mt6797-apmixedsys", 0x1000c000,
			pll_offsets, ARRAY_SIZE(pll_offsets), values + 3);
	if (ret)
		return ret;
	ret = read_bank("mediatek,mt6797-topckgen", 0x10000000,
			mux_offsets, ARRAY_SIZE(mux_offsets), values + 6);
	if (ret)
		return ret;
	value_count = ARRAY_SIZE(values);
	return 0;
}

static void __exit supplier_probe_exit(void) { }
module_init(supplier_probe_init);
module_exit(supplier_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only MT6797 decoder power and clock supplier snapshot");
