// SPDX-License-Identifier: GPL-2.0-only
/* Direct H.264 input DMA qualification on a real MT6797 codec DT device.
 * Private known-input and single I_PCM frame diagnostics; no V4L2 device.
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
#include <linux/unaligned.h>
#include "mt6797-h264-controls.h"
#include "pcm64-fixture.h"

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
static bool frame;
module_param(frame, bool, 0444);
MODULE_PARM_DESC(frame, "After input proof, submit the original 64x64 I_PCM fixture to guarded private buffers; requires fetch and clear_caller_gate");
static bool frame_flat;
module_param(frame_flat, bool, 0444);
MODULE_PARM_DESC(frame_flat, "Use the independently verified compressed I_16x16 DC fixture instead of I_PCM");
static bool frame_pattern;
module_param(frame_pattern, bool, 0444);
MODULE_PARM_DESC(frame_pattern, "Use the independently verified patterned compressed intra fixture; exclusive with frame_flat");
static bool frame_error_bypass;
module_param(frame_error_bypass, bool, 0444);
MODULE_PARM_DESC(frame_error_bypass, "Diagnose the related-core AVC control bits 14/15 on a known valid frame; raw errors and pixel comparisons remain required");
static bool frame_wrapper_bypass;
module_param(frame_wrapper_bypass, bool, 0444);
MODULE_PARM_DESC(frame_wrapper_bypass, "Diagnose the small-picture wrapper extension from a disabled public reference block; default uses its active path");
static bool frame_config_only;
module_param(frame_config_only, bool, 0444);
MODULE_PARM_DESC(frame_config_only, "Configure and observe the private frame without submitting its decode command");
static unsigned int dma_bits = TEST_DMA_BITS;
module_param(dma_bits, uint, 0444);
MODULE_PARM_DESC(dma_bits, "Private diagnostic DMA aperture, 28..30 bits; smaller apertures test truncated address fields");
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

static const u8 *frame_nal(void)
{
	return frame_pattern ? pattern64_nal : frame_flat ? grey64_nal : pcm64_nal;
}

static size_t frame_nal_size(void)
{
	return frame_pattern ? sizeof(pattern64_nal) : frame_flat ? sizeof(grey64_nal) : sizeof(pcm64_nal);
}

struct fifo_probe {
	struct device *dev;
	struct regmap *gcon;
	void __iomem *misc, *vld, *top, *mc, *avc, *mv, *pp, *larb_mmu_reg;
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
	void *frame_buffers[4], *frame_snapshot, *frame_work_snapshot;
	dma_addr_t frame_dma[4]; /* output, MV, VLD wrapper, PP wrapper */
	struct { void __iomem *address; u32 value; } frame_saved[48];
	unsigned int frame_saved_count;
	u32 frame_state, frame_irq, frame_error, frame_message, frame_mbx, frame_mby;
	u32 frame_input_first, frame_input_data;
	u32 frame_setup[16], frame_status[8], frame_clock_status[6], frame_pipeline[16];
	bool frame_work_changed[4]; /* prediction, MV, VLD wrapper, PP wrapper */
	bool frame_work_before[4];
	int frame_result;
	bool slice_loaded, decode_started, frame_done, frame_guards_unchanged, snapshot_ready;
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

static int test_input(struct fifo_probe *p, bool slice)
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
	write_reg(AVC_INPUT_CONTROL | (slice && frame_error_bypass ? (3U << 14) : 0),
		  p->avc + AVC_CONTROL);
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
	write_reg(lower_32_bits(p->input_dma + (slice ? ALIGN(frame_nal_size(), 128) : 4096)),
		  p->vld + VLD_WRITE_PTR);
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
	if (slice) {
		unsigned int remaining = frame_pattern ? 38 : 28;
		p->frame_input_first = readl(p->avc);
		/* Offset is to slice_data(), including the eight-bit NAL header. */
		while (remaining) {
			unsigned int shift = min(remaining, 32U);
			p->frame_input_data = readl(p->avc + shift * 4);
			remaining -= shift;
		}
		return p->frame_input_first == get_unaligned_be32(frame_nal()) ? 0 : -EIO;
	}
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

/* Only frame configuration registers use this helper. Never use it for
 * commands or acknowledgement pulses. Restore these words after proven idle.
 */
static void frame_reg(struct fifo_probe *p, void __iomem *address, u32 value)
{
	unsigned int index = p->frame_saved_count++;
	p->frame_saved[index].address = address;
	p->frame_saved[index].value = readl(address);
	write_reg(value, address);
}

static int test_frame(struct fifo_probe *p)
{
	const struct v4l2_ctrl_h264_sps sps = {
		.profile_idc = 66, .level_idc = 10, .constraint_set_flags = 3,
		.chroma_format_idc = 1, .max_num_ref_frames = 1,
		.pic_width_in_mbs_minus1 = 3, .pic_height_in_map_units_minus1 = 3,
		.flags = V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY |
			 V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE,
	};
	const struct v4l2_ctrl_h264_pps pps = {
		.flags = V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT,
	};
	const struct v4l2_ctrl_h264_slice_params slice = {
		.header_bit_size = frame_pattern ? 38 : 28,
		.slice_qp_delta = frame_pattern ? 20 : 0,
		.slice_type = V4L2_H264_SLICE_TYPE_I,
		.disable_deblocking_filter_idc = 1,
	};
	const struct v4l2_ctrl_h264_decode_params decode = {
		.nal_ref_idc = 3, .flags = V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC,
	};
	struct mt6797_h264_header_words header;
	struct mt6797_h264_slice_words words;
	unsigned int i;
	u32 state;
	int ret;

	ret = mt6797_h264_header_words(&sps, &pps, &header);
	if (ret)
		return ret;
	ret = mt6797_h264_slice_words(&sps, &pps, &slice, &decode,
				    frame_nal_size(), &words);
	if (ret)
		return ret;
	/* Stop the known-word fetch before replacing producer bytes. */
	ret = break_input(p);
	if (ret)
		return ret;
	ret = reset_input(p);
	if (ret)
		return ret;
	dma_rmb();
	if (memcmp(p->input, test_bytes, sizeof(test_bytes)) ||
	    memchr_inv(p->input + sizeof(test_bytes), 0xa5,
		       INPUT_ALLOC_SIZE - sizeof(test_bytes)) ||
	    memchr_inv(p->scratch, 0xd3, INPUT_ALLOC_SIZE))
		return -EIO;
	memcpy(p->input, frame_nal(), frame_nal_size());
	/* Working data starts at zero; trailing guards retain their sentinel.
	 * Keep output poisoned so zero/flat software storage cannot fake pixels.
	 */
	memset(p->scratch, 0, FIFO_SIZE);
	memset(p->frame_buffers[1], 0, FIFO_SIZE);
	memset(p->frame_buffers[2], 0, FIFO_SIZE);
	memset(p->frame_buffers[3], 0, FIFO_SIZE);
	p->slice_loaded = true;
	/* Release the prior break request before reinitializing the input core. */
	write_reg(p->break_original & ~BIT(0), p->misc + BREAK_CONTROL);
	ret = test_input(p, true);
	if (ret)
		return ret;

	/* Candidate frame contract from the pinned GPL MT8173 register interface.
 * Every DMA destination is private, aligned, bounded and already allocated.
 * IDR I_PCM has no reference-picture reads or scaling/transform dependency.
 */
	frame_reg(p, p->avc + 0x88, header.sps);
	frame_reg(p, p->avc + 0x90, header.pps);
	frame_reg(p, p->avc + 0x94, header.reference_counts);
	frame_reg(p, p->avc + 0x8c, (readl(p->avc + 0x8c) & ~0x1ffff) | words.first_mb);
	frame_reg(p, p->avc + 0x98, (readl(p->avc + 0x98) & 0x1fff) | words.header1);
	frame_reg(p, p->avc + 0x9c, words.header2);
	write_reg(1, p->avc + 0x228); /* reset picture-number SRAM */
	ret = readl_poll_timeout(p->avc + 0x228, state, !(state & BIT(0)), 10, 100000);
	if (ret)
		return ret;
	frame_reg(p, p->avc + 0xa0, 16);
	frame_reg(p, p->avc + 0xa4, 0);
	/* The public verification mask omits only its two unsupported checks.
 * Raw error/message words are retained even if completion is observed.
 */
	frame_reg(p, p->avc + 0x280, ~(u32)(BIT(14) | BIT(21)));
	frame_reg(p, p->avc + 0x2c8, readl(p->avc + 0x2c8) & ~BIT(5));
	frame_reg(p, p->top + 0x68, 3 | (3 << 16));
	frame_reg(p, p->top + 0x58, 0xffffffff);
	frame_reg(p, p->top + 0x6c, 16);
	frame_reg(p, p->top + 0x50, 0xffffffff);
	frame_reg(p, p->top + 0x54, readl(p->top + 0x54) | BIT(0));
	/* These three operations are inside #if 0 in the pinned reference.
	 * Keep the active path as the default; qualify the extension separately.
	 */
	if (frame_wrapper_bypass) {
		frame_reg(p, p->top + 0x94, lower_32_bits(p->scratch_dma + (4 * 5 - 1) * 16));
		frame_reg(p, p->top + 0x2c, readl(p->top + 0x2c) | BIT(30));
		frame_reg(p, p->top + 0x40, (readl(p->top + 0x40) & ~GENMASK(5, 4)) | BIT(5));
	}
	frame_reg(p, p->misc + 0xf0, readl(p->misc + 0xf0) | BIT(0));
	frame_reg(p, p->mc + 0x90, 4); /* candidate address-swap-off mode */
	frame_reg(p, p->mc + 0x768, (readl(p->mc + 0x768) & ~GENMASK(2, 0)) | 4);
	frame_reg(p, p->mc + 0x208, 64);
	frame_reg(p, p->mc + 0x20c, 64);
	frame_reg(p, p->mc + 0x220, 1);
	frame_reg(p, p->mc + 0x224, lower_32_bits(p->frame_dma[0]) >> 9);
	frame_reg(p, p->mc + 0x228, lower_32_bits(p->frame_dma[0] + 4096) >> 8);
	frame_reg(p, p->mc + 0x22c, 4);
	frame_reg(p, p->mc + 0x238, 3);
	frame_reg(p, p->mc + 0x250, 1);
	frame_reg(p, p->mc + 0x260, 3);
	frame_reg(p, p->mc + 0x264, 3);
	frame_reg(p, p->mc + 0x560, lower_32_bits(p->frame_dma[0]));
	frame_reg(p, p->mc + 0x55c, 4096);
	frame_reg(p, p->mc + 0x980, 4);
	frame_reg(p, p->mc + 0xa20, lower_32_bits(p->frame_dma[2]));
	frame_reg(p, p->mc + 0xa24, lower_32_bits(p->frame_dma[3]));
	frame_reg(p, p->mc + 0x5e4, readl(p->mc + 0x5e4) | BIT(12));
	frame_reg(p, p->mv + 0x200, 0);
	frame_reg(p, p->mv + 0x204, 0);
	frame_reg(p, p->mv + 0x208, 0);
	frame_reg(p, p->mv + 0x20c, lower_32_bits(p->frame_dma[1]) >> 4);
	frame_reg(p, p->pp + 0x804, readl(p->pp + 0x804) & ~BIT(4));
	ret = readl_poll_timeout(p->avc + 0x25c, state, !(state & BIT(25)), 10, 100000);
	if (ret)
		return ret;
	p->frame_setup[0] = readl(p->avc + 0x88);
	p->frame_setup[1] = readl(p->avc + 0x8c);
	p->frame_setup[2] = readl(p->avc + 0x90);
	p->frame_setup[3] = readl(p->avc + 0x98);
	p->frame_setup[4] = readl(p->avc + 0x9c);
	p->frame_setup[5] = readl(p->top + 0x68);
	p->frame_setup[6] = readl(p->top + 0x6c);
	p->frame_setup[7] = readl(p->top + 0x28);
	p->frame_setup[8] = readl(p->mc + 0x560);
	p->frame_setup[9] = readl(p->mc + 0x55c);
	p->frame_setup[10] = readl(p->mc + 0x224);
	p->frame_setup[11] = readl(p->mc + 0x228);
	p->frame_setup[12] = readl(p->mc + 0x980);
	p->frame_setup[13] = readl(p->mv + 0x20c);
	p->frame_setup[14] = readl(p->mc + 0xa20);
	p->frame_setup[15] = readl(p->mc + 0xa24);
	dma_rmb();
	p->frame_work_before[0] = !!memchr_inv(p->scratch, 0, FIFO_SIZE);
	for (i = 1; i < ARRAY_SIZE(p->frame_buffers); i++)
		p->frame_work_before[i] = !!memchr_inv(p->frame_buffers[i], 0, FIFO_SIZE);
	ret = 0;
	if (!frame_config_only) {
		dma_wmb();
		p->decode_started = true; /* Software submission, not decoded-frame proof. */
		write_reg(1, p->avc + 0x238);
		ret = readl_poll_timeout(p->avc + 0x278, p->frame_state,
					p->frame_state & BIT(31), 100, 1000000);
		p->frame_done = !ret;
	} else {
		p->frame_state = readl(p->avc + 0x278);
	}
	p->frame_irq = readl(p->misc + IRQ_CONTROL);
	p->frame_error = readl(p->avc + 0x284);
	p->frame_message = readl(p->avc + 0x270);
	p->frame_mbx = readl(p->mc + 0x28);
	p->frame_mby = readl(p->mc + 0x2c);
	p->frame_status[0] = readl(p->avc + 0x25c);
	p->frame_status[1] = readl(p->avc + 0x274);
	p->frame_status[2] = readl(p->avc + 0x84);
	p->frame_status[3] = readl(p->vld + VLD_PROC);
	p->frame_status[4] = readl(p->vld + VLD_READ_PTR);
	p->frame_status[5] = readl(p->vld + VLD_FETCH_STATUS);
	p->frame_status[6] = readl(p->top + 0x80);
	regmap_read(p->gcon, 0x8, &p->frame_status[7]);
	p->frame_clock_status[0] = readl(p->misc + PDN_SPEC);
	p->frame_clock_status[1] = readl(p->misc + PDN_MODULE);
	p->frame_clock_status[2] = readl(p->misc);
	p->frame_clock_status[3] = readl(p->top + 0x2c);
	p->frame_clock_status[4] = readl(p->top + 0x40);
	p->frame_clock_status[5] = readl(p->top + 0x94);
	/* Public RO/status and stable configuration words; no advancing barrel,
	 * command, acknowledgement or debug-selector access in this snapshot.
	 */
	p->frame_pipeline[0] = readl(p->mc + 0x94);
	p->frame_pipeline[1] = readl(p->mc + 0x64);
	p->frame_pipeline[2] = readl(p->mc + 0x6c);
	p->frame_pipeline[3] = readl(p->mc + 0x68);
	p->frame_pipeline[4] = readl(p->mc + 0x3c);
	p->frame_pipeline[5] = readl(p->mc + 0x220);
	p->frame_pipeline[6] = readl(p->mc + 0x250);
	p->frame_pipeline[7] = readl(p->mc + 0x24);
	p->frame_pipeline[8] = readl(p->mc + 0x7fc);
	p->frame_pipeline[9] = readl(p->mc + 0x800);
	p->frame_pipeline[10] = readl(p->mc + 0x834);
	p->frame_pipeline[11] = readl(p->mc + 0x5e4);
	p->frame_pipeline[12] = readl(p->pp + 0x804);
	p->frame_pipeline[13] = readl(p->top + 0x54);
	p->frame_pipeline[14] = readl(p->vld + 0xfc);
	p->frame_pipeline[15] = readl(p->vld + 0xec);
	return ret;
}

static ssize_t frame_registers_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct fifo_probe *p = dev_get_drvdata(dev);
	return sysfs_emit(buf,
		"{\"setup\":{\"sps\":%u,\"first_mb\":%u,\"pps\":%u,\"shdr1\":%u,"
		"\"shdr2\":%u,\"mb_size\":%u,\"total_mbs\":%u,\"prediction\":%u,"
		"\"mc_y\":%u,\"mc_chroma_offset\":%u,\"pp_y\":%u,\"pp_c\":%u,"
		"\"width_mbs\":%u,\"mv\":%u,\"vld_wrapper\":%u,\"pp_wrapper\":%u},"
		"\"status\":{\"avc_status\":%u,\"avc_complete\":%u,\"avc_control\":%u,"
		"\"vld_proc\":%u,\"read_ptr\":%u,\"fetch\":%u,\"cycle\":%u,\"smi_clock\":%u},"
		"\"local\":{\"pdn_spec\":%u,\"pdn_module\":%u,\"pdn_legacy\":%u,"
		"\"wrapper_control\":%u,\"wrapper_burst\":%u,\"prediction_end\":%u},"
		"\"pipeline\":{\"mc_status\":%u,\"mb_intra\":%u,\"cbp\":%u,\"frame_dct\":%u,"
		"\"mv_valid\":%u,\"pp_enable\":%u,\"post_writeback\":%u,\"opbuf\":%u,"
		"\"ddr0\":%u,\"ddr1\":%u,\"ddr3\":%u,\"mc_mode\":%u,\"pp_wrapper_control\":%u,"
		"\"cycle_enable\":%u,\"dram_read_ptr\":%u,\"sram_pointers\":%u}}\n",
		p->frame_setup[0], p->frame_setup[1], p->frame_setup[2], p->frame_setup[3],
		p->frame_setup[4], p->frame_setup[5], p->frame_setup[6], p->frame_setup[7],
		p->frame_setup[8], p->frame_setup[9], p->frame_setup[10], p->frame_setup[11],
		p->frame_setup[12], p->frame_setup[13], p->frame_setup[14], p->frame_setup[15],
		p->frame_status[0], p->frame_status[1], p->frame_status[2], p->frame_status[3],
		p->frame_status[4], p->frame_status[5], p->frame_status[6], p->frame_status[7],
		p->frame_clock_status[0], p->frame_clock_status[1], p->frame_clock_status[2],
		p->frame_clock_status[3], p->frame_clock_status[4], p->frame_clock_status[5],
		p->frame_pipeline[0], p->frame_pipeline[1], p->frame_pipeline[2], p->frame_pipeline[3],
		p->frame_pipeline[4], p->frame_pipeline[5], p->frame_pipeline[6], p->frame_pipeline[7],
		p->frame_pipeline[8], p->frame_pipeline[9], p->frame_pipeline[10], p->frame_pipeline[11],
		p->frame_pipeline[12], p->frame_pipeline[13], p->frame_pipeline[14], p->frame_pipeline[15]);
}
static DEVICE_ATTR_RO(frame_registers);

static ssize_t frame_result_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct fifo_probe *p = dev_get_drvdata(dev);
	return sysfs_emit(buf,
		"{\"requested\":%s,\"flat\":%s,\"pattern\":%s,\"error_bypass\":%s,\"wrapper_bypass\":%s,\"config_only\":%s,"
		"\"decode_started\":%s,\"done\":%s,\"result\":%d,"
		"\"guards_unchanged\":%s,\"snapshot_ready\":%s,\"state\":%u,"
		"\"irq\":%u,\"error\":%u,\"message\":%u,\"mbx\":%u,\"mby\":%u,"
		"\"input_first\":%u,\"input_data\":%u,\"width\":64,\"height\":64,"
		"\"work_changed\":{\"prediction\":%s,\"mv\":%s,\"vld_wrapper\":%s,\"pp_wrapper\":%s},"
		"\"work_before\":{\"prediction\":%s,\"mv\":%s,\"vld_wrapper\":%s,\"pp_wrapper\":%s},"
		"\"stride\":64,\"chroma_offset\":4096,\"output_iova\":%llu,"
		"\"mv_iova\":%llu,\"vld_wrapper_iova\":%llu,\"pp_wrapper_iova\":%llu}\n",
		frame ? "true" : "false", frame_flat ? "true" : "false",
		frame_pattern ? "true" : "false",
		frame_error_bypass ? "true" : "false", frame_wrapper_bypass ? "true" : "false",
		frame_config_only ? "true" : "false",
		p->decode_started ? "true" : "false",
		p->frame_done ? "true" : "false", p->frame_result,
		p->frame_guards_unchanged ? "true" : "false", p->snapshot_ready ? "true" : "false",
		p->frame_state, p->frame_irq, p->frame_error, p->frame_message,
		p->frame_mbx, p->frame_mby, p->frame_input_first, p->frame_input_data,
		p->frame_work_changed[0] ? "true" : "false", p->frame_work_changed[1] ? "true" : "false",
		p->frame_work_changed[2] ? "true" : "false", p->frame_work_changed[3] ? "true" : "false",
		p->frame_work_before[0] ? "true" : "false", p->frame_work_before[1] ? "true" : "false",
		p->frame_work_before[2] ? "true" : "false", p->frame_work_before[3] ? "true" : "false",
		(unsigned long long)p->frame_dma[0], (unsigned long long)p->frame_dma[1],
		(unsigned long long)p->frame_dma[2], (unsigned long long)p->frame_dma[3]);
}
static DEVICE_ATTR_RO(frame_result);

static ssize_t frame_output_read(struct file *file, struct kobject *kobj,
				const struct bin_attribute *attr, char *buf,
				loff_t offset, size_t count)
{
	struct fifo_probe *p = dev_get_drvdata(kobj_to_dev(kobj));
	if (!p->snapshot_ready)
		return -ENODATA;
	return memory_read_from_buffer(buf, count, &offset, p->frame_snapshot, INPUT_ALLOC_SIZE);
}
static const BIN_ATTR_RO(frame_output, INPUT_ALLOC_SIZE);

/* Four 64-KiB working regions in order: prediction, MV, VLD, PP. */
static ssize_t frame_work_read(struct file *file, struct kobject *kobj,
			      const struct bin_attribute *attr, char *buf,
			      loff_t offset, size_t count)
{
	struct fifo_probe *p = dev_get_drvdata(kobj_to_dev(kobj));
	if (!p->snapshot_ready)
		return -ENODATA;
	return memory_read_from_buffer(buf, count, &offset, p->frame_work_snapshot, 4 * FIFO_SIZE);
}
static const BIN_ATTR_RO(frame_work, 4 * FIFO_SIZE);

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
		"\"decode_started\":%s,\"compared\":%s,\"quiesced\":%s,"
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
		dma_bits, all_clocks ? "true" : "false",
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
		p->decode_started ? "true" : "false",
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
static struct attribute *fifo_attrs[] = {
	&dev_attr_result.attr, &dev_attr_frame_result.attr, &dev_attr_frame_registers.attr, NULL
};
static const struct bin_attribute *const fifo_bin_attrs[] = {
	&bin_attr_frame_output, &bin_attr_frame_work, NULL
};
static const struct attribute_group fifo_group = {
	.attrs = fifo_attrs, .bin_attrs = fifo_bin_attrs,
};
static const struct attribute_group *fifo_groups[] = { &fifo_group, NULL };

static void free_buffers(struct fifo_probe *p)
{
	unsigned int i;
	if (p->input)
		dma_free_coherent(p->dev, INPUT_ALLOC_SIZE, p->input, p->input_dma);
	if (p->scratch)
		dma_free_coherent(p->dev, frame ? INPUT_ALLOC_SIZE : FIFO_SIZE,
				  p->scratch, p->scratch_dma);
	for (i = 0; i < ARRAY_SIZE(p->frame_buffers); i++) {
		if (p->frame_buffers[i])
			dma_free_coherent(p->dev, INPUT_ALLOC_SIZE,
					  p->frame_buffers[i], p->frame_dma[i]);
		p->frame_buffers[i] = NULL;
	}
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
	unsigned int i;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return -ENODEV;
	if (fetch && hold_resources)
		return -EINVAL;
	if (frame && (!fetch || !clear_caller_gate || hold_resources))
		return -EINVAL;
	if ((!frame && (frame_flat || frame_pattern || frame_error_bypass || frame_wrapper_bypass || frame_config_only)) ||
	    (frame_flat && frame_pattern))
		return -EINVAL;
	if (dma_bits < 28 || dma_bits > TEST_DMA_BITS)
		return -EINVAL;
	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p)
		return -ENOMEM;
	p->dev = dev;
	p->frame_result = -ENODATA;
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
	if (frame) {
		p->mv = map_codec_bank(pdev, "avc-mv");
		if (IS_ERR(p->mv))
			return PTR_ERR(p->mv);
		p->pp = map_codec_bank(pdev, "pp");
		if (IS_ERR(p->pp))
			return PTR_ERR(p->pp);
	}
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
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(dma_bits));
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
	p->scratch = dma_alloc_coherent(dev, frame ? INPUT_ALLOC_SIZE : FIFO_SIZE,
					&p->scratch_dma, GFP_KERNEL);
	if (!p->input || !p->scratch) {
		ret = -ENOMEM;
		goto free;
	}
	if (frame) {
		p->frame_snapshot = devm_kmalloc(dev, INPUT_ALLOC_SIZE, GFP_KERNEL);
		p->frame_work_snapshot = devm_kmalloc(dev, 4 * FIFO_SIZE, GFP_KERNEL);
		if (!p->frame_snapshot || !p->frame_work_snapshot) {
			ret = -ENOMEM;
			goto free;
		}
		for (i = 0; i < ARRAY_SIZE(p->frame_buffers); i++) {
			p->frame_buffers[i] = dma_alloc_coherent(dev, INPUT_ALLOC_SIZE,
							      &p->frame_dma[i], GFP_KERNEL);
			if (!p->frame_buffers[i]) {
				ret = -ENOMEM;
				goto free;
			}
			if (!IS_ALIGNED(p->frame_dma[i], 512) ||
			    p->frame_dma[i] + INPUT_ALLOC_SIZE - 1 > DMA_BIT_MASK(dma_bits)) {
				ret = -ERANGE;
				goto free;
			}
			memset(p->frame_buffers[i], 0xd3, INPUT_ALLOC_SIZE);
		}
	}
	if (p->input_dma + FIFO_SIZE > DMA_BIT_MASK(dma_bits) ||
	    upper_32_bits(p->scratch_dma + FIFO_SIZE) ||
	    !IS_ALIGNED(p->input_dma, 64)) {
		ret = -ERANGE;
		goto free;
	}
	memset(p->input, 0xa5, INPUT_ALLOC_SIZE);
	memcpy(p->input, test_bytes, sizeof(test_bytes));
	memset(p->scratch, 0xd3, frame ? INPUT_ALLOC_SIZE : FIFO_SIZE);
	p->result = test_input(p, false);
	if (frame && !p->result)
		p->frame_result = test_frame(p);
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
	p->input_unchanged = p->slice_loaded ?
		!memcmp(p->input, frame_nal(), frame_nal_size()) &&
		!memchr_inv(p->input + frame_nal_size(), 0xa5,
			    INPUT_ALLOC_SIZE - frame_nal_size()) :
		!memcmp(p->input, test_bytes, sizeof(test_bytes)) &&
		!memchr_inv(p->input + sizeof(test_bytes), 0xa5,
			    INPUT_ALLOC_SIZE - sizeof(test_bytes));
	/* Prediction data can change during a frame; its trailing guard cannot. */
	p->scratch_unchanged = !memchr_inv(p->scratch + (p->slice_loaded ? FIFO_SIZE : 0),
					 0xd3, FIFO_SIZE);
	if (frame) {
		p->frame_guards_unchanged = p->input_unchanged && p->scratch_unchanged;
		for (i = 0; i < ARRAY_SIZE(p->frame_buffers); i++)
			if (memchr_inv(p->frame_buffers[i] + FIFO_SIZE, 0xd3, FIFO_SIZE))
				p->frame_guards_unchanged = false;
	}
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
	if (frame) {
		/* Copy only after both stop acknowledgements and the idle reset.
		 * Userspace receives CPU storage, never a live DMA mapping.
		 */
		memcpy(p->frame_snapshot, p->frame_buffers[0], INPUT_ALLOC_SIZE);
		memcpy(p->frame_work_snapshot, p->scratch, FIFO_SIZE);
		for (i = 1; i < ARRAY_SIZE(p->frame_buffers); i++)
			memcpy(p->frame_work_snapshot + i * FIFO_SIZE, p->frame_buffers[i], FIFO_SIZE);
		p->snapshot_ready = true;
		if (p->slice_loaded) {
			p->frame_work_changed[0] = !!memchr_inv(p->scratch, 0, FIFO_SIZE);
			for (i = 1; i < ARRAY_SIZE(p->frame_buffers); i++)
				p->frame_work_changed[i] = !!memchr_inv(p->frame_buffers[i], 0, FIFO_SIZE);
		}
		if (!p->frame_guards_unchanged)
			p->frame_result = -EIO;
		if (p->decode_started) {
			u32 irq = readl(p->misc + IRQ_CONTROL);
			write_reg(irq | BIT(0) | BIT(4), p->misc + IRQ_CONTROL);
			write_reg((irq | BIT(0)) & ~BIT(4), p->misc + IRQ_CONTROL);
		}
		while (p->frame_saved_count) {
			i = --p->frame_saved_count;
			write_reg(p->frame_saved[i].value, p->frame_saved[i].address);
		}
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
