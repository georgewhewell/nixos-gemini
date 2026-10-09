// SPDX-License-Identifier: GPL-2.0-only
/* Bounded MT6797 CKGEN measurement, with the decoder held by a separate
 * runtime-PM consumer. Changes only the idle frequency meter's debug controls;
 * no clock mux, divider, PLL, power, codec or DMA registers are programmed.
 */
#include <linux/bitfield.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>

#define MISC_CONFIG 0x104
#define DEBUG_CONFIG 0x10c
#define CALIBRATION_CONTROL 0x220
#define CALIBRATION_COUNT 0x224
#define DEBUG_SELECT (GENMASK(12, 8) | GENMASK(1, 0))
#define METER_ENABLE BIT(12)
#define METER_START BIT(4)

/* Public MT6797 CKGEN channels: AXI=1, VDEC=4, MM/SMI supplier=5. */
static const unsigned int channel[] = { 1, 4, 5 };
static unsigned int counts[3], khz[3], original[4];
static unsigned int counts_count, khz_count, original_count;
static unsigned int divider_setting;
static int result;
static bool restored;
module_param_array(counts, uint, &counts_count, 0444);
module_param_array(khz, uint, &khz_count, 0444);
module_param_array(original, uint, &original_count, 0444);
module_param(result, int, 0444);
module_param(restored, bool, 0444);
module_param(divider_setting, uint, 0444);
MODULE_PARM_DESC(counts, "Saved AXI/VDEC/MM cycle counts over 1024 reference cycles");
MODULE_PARM_DESC(khz, "Saved AXI/VDEC/MM counter-input rates after the unchanged meter divider, relative to 26 MHz");
MODULE_PARM_DESC(divider_setting, "Original CKGEN meter divider field; no upstream-rate conversion is inferred");
MODULE_PARM_DESC(original, "Original misc/debug/calibration-control/calibration-count registers");

static void write_meter(u32 value, void __iomem *address)
{
	writel(value, address);
	mb();
}

static int __init clock_probe_init(void)
{
	struct device_node *node;
	struct resource resource;
	void __iomem *base;
	u32 state;
	unsigned int i;
	int ret;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return -ENODEV;
	node = of_find_compatible_node(NULL, NULL, "mediatek,mt6797-topckgen");
	if (!node)
		return -ENODEV;
	ret = of_address_to_resource(node, 0, &resource);
	if (ret || resource.start != 0x10000000 || resource_size(&resource) != 0x1000) {
		of_node_put(node);
		return ret ?: -EINVAL;
	}
	base = of_iomap(node, 0);
	of_node_put(node);
	if (!base)
		return -ENOMEM;
	original[0] = readl(base + MISC_CONFIG);
	original[1] = readl(base + DEBUG_CONFIG);
	original[2] = readl(base + CALIBRATION_CONTROL);
	original[3] = readl(base + CALIBRATION_COUNT);
	divider_setting = FIELD_GET(GENMASK(31, 24), original[0]);
	counts_count = khz_count = ARRAY_SIZE(counts);
	original_count = ARRAY_SIZE(original);
	/* Keep the shared divider register unchanged and report its field. The
	 * count conversion gives the counter-input rate, after that divider; it
	 * does not assume an undocumented upstream divider encoding. Refuse an
	 * already running meter, reference-test mode or nonstandard window.
	 */
	if (FIELD_GET(GENMASK(25, 16), original[3]) != 1023 ||
	    original[2] & (METER_START | BIT(8) | BIT(0))) {
		result = -EBUSY;
		restored = true; /* Refused before any write. */
		iounmap(base);
		return 0;
	}
	for (i = 0; i < ARRAY_SIZE(channel); i++) {
		write_meter((original[1] & ~DEBUG_SELECT) | (channel[i] << 8) | 1,
			    base + DEBUG_CONFIG);
		write_meter(original[2] | METER_ENABLE, base + CALIBRATION_CONTROL);
		write_meter(original[2] | METER_ENABLE | METER_START,
			    base + CALIBRATION_CONTROL);
		ret = readl_poll_timeout(base + CALIBRATION_CONTROL, state,
					!(state & METER_START), 10, 100000);
		if (ret) {
			result = ret;
			break;
		}
		counts[i] = readl(base + CALIBRATION_COUNT) & 0xffff;
		khz[i] = counts[i] * 26000 / 1024;
		write_meter(original[2], base + CALIBRATION_CONTROL);
	}
	write_meter(original[2], base + CALIBRATION_CONTROL);
	write_meter(original[1], base + DEBUG_CONFIG);
	restored = readl(base + DEBUG_CONFIG) == original[1] &&
		readl(base + CALIBRATION_CONTROL) == original[2] &&
		readl(base + MISC_CONFIG) == original[0] &&
		((readl(base + CALIBRATION_COUNT) ^ original[3]) & GENMASK(25, 16)) == 0;
	if (!restored)
		result = -EIO;
	iounmap(base);
	return 0;
}

static void __exit clock_probe_exit(void) { }
module_init(clock_probe_init);
module_exit(clock_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Bounded MT6797 AXI/VDEC/MM frequency-meter diagnostic");
