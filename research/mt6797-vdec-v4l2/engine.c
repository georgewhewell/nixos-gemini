// SPDX-License-Identifier: GPL-2.0-only
/* Original register backend derived from this project's guarded diagnostics.
 * Public register provenance: ../mt6797-video-interface.json.
 * Bitstream staging remains private. Capture surfaces are native dma_buf
 * objects, independently retained if DMA stop cannot be proved.
 */
#include <linux/clk.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>
#include <linux/iommu.h>
#include <linux/interrupt.h>
#include <linux/iopoll.h>
#include <linux/irq.h>
#include <linux/ktime.h>
#include <linux/list.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of_address.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/unaligned.h>
#include "engine.h"
#include "../mt6797-vdec/mt6797-h264-controls.h"

#define DATA_SIZE SZ_128K
#define GUARD_SIZE SZ_128K
#define INPUT_DATA_SIZE SZ_1M
#define ALLOC_SIZE (DATA_SIZE + GUARD_SIZE)
#define MAX_NAL MT6797_MAX_NAL_BYTES
#define PICTURE_DATA_SIZE ALIGN(MT6797_MAX_WIDTH * MT6797_MAX_HEIGHT * 7 / 4, SZ_64K)
#define PICTURE_ALLOC_SIZE (PICTURE_DATA_SIZE + DATA_SIZE)

/* Public uncompressed picture area: Y + interleaved chroma + luma/4 motion. */

enum bank { MISC, VLD, TOP, MC, AVC, MV, PP, BANK_COUNT };
enum memory { INPUT, PREDICTION, VLD_WRAP, PP_WRAP, MEMORY_COUNT };

struct private_buffer {
	u8 *cpu;
	dma_addr_t dma;
	size_t bytes;
	bool device_owned;
};

struct saved_register {
	void __iomem *address;
	u32 value;
};

struct register_save {
	struct saved_register words[256];
	unsigned int count;
};

struct mt6797_engine {
	struct device *dev;
	struct regmap *gcon;
	void __iomem *banks[BANK_COUNT], *larb_mmu;
	struct clk_bulk_data clocks[2];
	struct clk *active_clock;
	struct private_buffer memory[MEMORY_COUNT];
	u8 *reference_snapshot;
	size_t snapshot_bytes;
	struct register_save saved;
	struct mt6797_h264_p_reference_words refs[2][V4L2_H264_NUM_DPB_ENTRIES];
	struct list_head contexts;
	/* The ordered frontend owns command setup; the hard IRQ owns one event.
	 * Mask each delivery immediately, including unexpected ones. No handler
	 * can outlive the disable/synchronize boundary before reset or power-off.
	 */
	int irq;
	spinlock_t irq_lock;
	struct completion irq_done;
	bool irq_enabled, irq_armed, irq_started;
	u64 irq_command, irq_received_command;
	u32 irq_events, irq_unexpected, irq_status;
	bool fenced;
};

struct mt6797_decode_context {
	struct mt6797_engine *engine;
	struct list_head list;
	struct mt6797_picture pictures[MT6797_H264_PICTURE_SLOTS];
	struct mt6797_h264_cached_picture cache[MT6797_H264_PICTURE_SLOTS];
	struct mt6797_surface_job *surface_job;
};

static void write_word(u32 value, void __iomem *address)
{
	writel(value, address);
	mb();
}

/* Public MT6797 dec_isr and upstream mtk_vcodec_dec_irq_handler both use
 * this two-write sequence. The second write must use a fresh live word.
 * Register provenance and the unresolved delivery proof are in irq-contract.json.
 */
static void acknowledge_irq(struct mt6797_engine *engine)
{
	void __iomem *word = engine->banks[MISC] + 0xa4;

	write_word(readl(word) | 0x11, word);
	write_word(readl(word) & ~BIT(4), word);
}

static irqreturn_t decoder_irq(int irq, void *data)
{
	struct mt6797_engine *engine = data;
	unsigned long flags;
	u32 gate = BIT(4), status = 0;
	bool mask, valid;
	int ret = -EIO;

	/* The syscon's MMIO regmap uses its IRQ-safe spinlock. Never touch the
	 * decoder bank if the public clock guard says it is unavailable.
	 */
	spin_lock_irqsave(&engine->irq_lock, flags);
	if (engine->irq_enabled)
		ret = regmap_read(engine->gcon, 0, &gate);
	if (!ret && !(gate & BIT(4))) {
		status = readl(engine->banks[MISC] + 0xa4);
		if (status & BIT(16))
			acknowledge_irq(engine);
	}
	valid = !ret && !(gate & BIT(4)) && (status & BIT(16)) &&
		engine->irq_armed && engine->irq_started && !engine->irq_events;
	engine->irq_events++;
	engine->irq_status = status;
	if (valid)
		engine->irq_received_command = engine->irq_command;
	else
		engine->irq_unexpected++;
	mask = engine->irq_enabled;
	engine->irq_enabled = false;
	engine->irq_armed = false;
	engine->irq_started = false;
	spin_unlock_irqrestore(&engine->irq_lock, flags);
	/* A dedicated line with an unexpected event is a failed command too.
	 * Masking on the first delivery bounds a level-triggered IRQ storm.
	 */
	if (mask)
		disable_irq_nosync(irq);
	complete(&engine->irq_done);
	return IRQ_HANDLED;
}

static void disarm_irq(struct mt6797_engine *engine)
{
	unsigned long flags;
	bool enabled;

	spin_lock_irqsave(&engine->irq_lock, flags);
	enabled = engine->irq_enabled;
	engine->irq_enabled = false;
	engine->irq_armed = false;
	engine->irq_started = false;
	spin_unlock_irqrestore(&engine->irq_lock, flags);
	if (enabled)
		disable_irq(engine->irq);
	else
		/* The handler may have masked the line but still be executing. */
		synchronize_irq(engine->irq);
}

static int arm_irq(struct mt6797_engine *engine)
{
	unsigned long flags;

	/* A stale hardware done bit must never satisfy a new command. */
	if (readl(engine->banks[MISC] + 0xa4) & BIT(16))
		return -EBUSY;
	reinit_completion(&engine->irq_done);
	spin_lock_irqsave(&engine->irq_lock, flags);
	engine->irq_events = 0;
	engine->irq_unexpected = 0;
	engine->irq_status = 0;
	engine->irq_received_command = 0;
	if (!++engine->irq_command)
		engine->irq_command++;
	engine->irq_armed = true;
	engine->irq_started = false;
	engine->irq_enabled = true;
	spin_unlock_irqrestore(&engine->irq_lock, flags);
	enable_irq(engine->irq);
	return 0;
}

static int irq_controller_state(struct mt6797_engine *engine,
				enum irqchip_irq_state which)
{
	bool value = false;
	int ret = irq_get_irqchip_state(engine->irq, which, &value);

	/* The generic IRQ API walks through MT_SYSIRQ to the parent GIC.
	 * Preserve unsupported/error results instead of reporting a false bit.
	 */
	return ret ? ret : value;
}

static void irq_controller_snapshot(struct mt6797_engine *engine,
				    int *masked, int *pending, int *active)
{
	*masked = irq_controller_state(engine, IRQCHIP_STATE_MASKED);
	*pending = irq_controller_state(engine, IRQCHIP_STATE_PENDING);
	*active = irq_controller_state(engine, IRQCHIP_STATE_ACTIVE);
}

static int submit_decode(struct mt6797_engine *engine,
			 struct mt6797_decode_status *status)
{
	unsigned long flags;
	int ret = arm_irq(engine);

	if (ret)
		return ret;
	status->irq_command = engine->irq_command;
	irq_controller_snapshot(engine, &status->irq_masked_before,
				&status->irq_pending_before, &status->irq_active_before);
	status->irq_controller_sampled = true;
	spin_lock_irqsave(&engine->irq_lock, flags);
	/* An interrupt delivered between unmask and hardware start belongs to
	 * no submitted command. Do not start DMA after that unexpected event.
	 * The handler takes this same lock before inspecting hardware state.
	 */
	if (!engine->irq_enabled || engine->irq_events) {
		ret = -EIO;
	} else {
		engine->irq_started = true;
		status->submitted = true;
		write_word(1, engine->banks[AVC] + 0x238);
	}
	spin_unlock_irqrestore(&engine->irq_lock, flags);
	return ret;
}

static int wait_decode_irq(struct mt6797_engine *engine)
{
	ktime_t deadline = ktime_add_ms(ktime_get(), 1000);

	do {
		/* Fatal CABAC alignment can stall without a completion interrupt.
		 * Keep this bounded error check; picture-complete polling alone
		 * deliberately cannot make an IRQ command successful.
		 */
		if (readl(engine->banks[AVC] + 0x284) & BIT(8))
			return -EIO;
		if (wait_for_completion_timeout(&engine->irq_done,
						msecs_to_jiffies(1)))
			return 0;
	} while (ktime_before(ktime_get(), deadline));
	return -ETIMEDOUT;
}

static void save_word(struct register_save *save, void __iomem *address, u32 value)
{
	/* The closed fixed-size programming sequence below uses fewer than 256.
	 * No register write can escape the save area if that sequence is extended.
	 */
	if (WARN_ON_ONCE(save->count == ARRAY_SIZE(save->words)))
		return;
	save->words[save->count++] = (struct saved_register) { address, readl(address) };
	write_word(value, address);
}

static void restore_words(struct register_save *save)
{
	while (save->count) {
		struct saved_register *word = &save->words[--save->count];
		write_word(word->value, word->address);
	}
}

static int allocate_buffer(struct mt6797_engine *engine, struct private_buffer *buf,
			   size_t bytes)
{
	buf->bytes = bytes;
	buf->device_owned = false;
	buf->cpu = dma_alloc_noncoherent(engine->dev, buf->bytes, &buf->dma, DMA_BIDIRECTIONAL, GFP_KERNEL);
	if (!buf->cpu)
		return -ENOMEM;
	if (!IS_ALIGNED(buf->dma, 2048) || buf->dma + buf->bytes - 1 > DMA_BIT_MASK(28)) {
		dma_free_noncoherent(engine->dev, buf->bytes, buf->cpu, buf->dma, DMA_BIDIRECTIONAL);
		buf->cpu = NULL;
		return -ERANGE;
	}
	memset(buf->cpu, 0xd3, buf->bytes);
	return 0;
}

static void release_buffer(struct mt6797_engine *engine, struct private_buffer *buf)
{
	if (buf->cpu)
		dma_free_noncoherent(engine->dev, buf->bytes, buf->cpu, buf->dma, DMA_BIDIRECTIONAL);
	buf->cpu = NULL;
}

int mt6797_engine_resume(struct mt6797_engine *engine)
{
	u32 word;
	int ret;

	ret = clk_bulk_prepare_enable(ARRAY_SIZE(engine->clocks), engine->clocks);
	if (ret)
		return ret;
	/* Adopt and release the inherited ACTIVE gate through CCF while powered.
	 * A different framework owner keeps its vote; never bypass that owner.
	 */
	ret = clk_prepare_enable(engine->active_clock);
	if (ret)
		goto clocks;
	clk_disable_unprepare(engine->active_clock);
	ret = regmap_read(engine->gcon, 0, &word);
	if (!ret && (word & BIT(4)))
		ret = -EBUSY;
	if (!ret)
		return 0;
clocks:
	clk_bulk_disable_unprepare(ARRAY_SIZE(engine->clocks), engine->clocks);
	return ret;
}

int mt6797_engine_suspend(struct mt6797_engine *engine)
{
	if (engine->fenced)
		return -EBUSY;
	disarm_irq(engine);
	clk_bulk_disable_unprepare(ARRAY_SIZE(engine->clocks), engine->clocks);
	return 0;
}

static void free_snapshot(void *data)
{
	struct mt6797_engine *engine = data;
	kvfree(engine->reference_snapshot);
}

static void clear_irq_flags(void *data)
{
	struct mt6797_engine *engine = data;

	irq_clear_status_flags(engine->irq, IRQ_DISABLE_UNLAZY);
}

struct mt6797_engine *mt6797_engine_create(struct platform_device *pdev)
{
	static const char *const names[] = { "misc", "vld", "vld-top", "mc", "avc-vld", "avc-mv", "pp" };
	static const resource_size_t bases[] = { 0x16020000, 0x16021000, 0x16021800,
		0x16022000, 0x16023000, 0x16024000, 0x16025000 };
	static const resource_size_t spans[] = { 0x1000, 0x800, 0x800,
		0x1000, 0x1000, 0x1000, 0x1000 };
	struct device *dev = &pdev->dev;
	struct mt6797_engine *engine;
	struct device_node *larb;
	struct resource resource;
	unsigned int i;
	int ret;

	if (!of_machine_is_compatible("planet,gemini-pda"))
		return ERR_PTR(-ENODEV);
	engine = devm_kzalloc(dev, sizeof(*engine), GFP_KERNEL);
	if (!engine)
		return ERR_PTR(-ENOMEM);
	engine->dev = dev;
	ret = devm_add_action_or_reset(dev, free_snapshot, engine);
	if (ret)
		return ERR_PTR(ret);
	INIT_LIST_HEAD(&engine->contexts);
	spin_lock_init(&engine->irq_lock);
	init_completion(&engine->irq_done);
	engine->gcon = syscon_regmap_lookup_by_compatible("mediatek,mt6797-vdecsys");
	if (IS_ERR(engine->gcon))
		return ERR_CAST(engine->gcon);
	for (i = 0; i < BANK_COUNT; i++) {
		struct resource *res = platform_get_resource_byname(pdev, IORESOURCE_MEM, names[i]);
		struct resource nonposted;
		if (!res || res->start != bases[i] || resource_size(res) != spans[i])
			return ERR_PTR(-EINVAL);
		nonposted = *res;
		nonposted.flags |= IORESOURCE_MEM_NONPOSTED;
		engine->banks[i] = devm_ioremap_resource(dev, &nonposted);
		if (IS_ERR(engine->banks[i]))
			return ERR_CAST(engine->banks[i]);
	}
	engine->clocks[0].id = "bus";
	engine->clocks[1].id = "engine";
	engine->active_clock = devm_clk_get(dev, "active");
	if (IS_ERR(engine->active_clock))
		return ERR_CAST(engine->active_clock);
	ret = devm_clk_bulk_get(dev, ARRAY_SIZE(engine->clocks), engine->clocks);
	if (ret)
		return ERR_PTR(ret);
	if (!iommu_get_domain_for_dev(dev))
		return ERR_PTR(-ENODEV);
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(28));
	if (ret)
		return ERR_PTR(ret);
	larb = of_parse_phandle(dev->of_node, "mediatek,larbs", 0);
	if (!larb)
		return ERR_PTR(-ENODEV);
	ret = of_address_to_resource(larb, 0, &resource);
	of_node_put(larb);
	if (ret)
		return ERR_PTR(ret);
	if (resource.start != 0x16010000 || resource_size(&resource) < 0xfc4)
		return ERR_PTR(-EINVAL);
	/* Supplier-owned MMU mask: observation only, no claim or write. */
	engine->larb_mmu = devm_ioremap(dev, resource.start + 0xfc0, 4);
	if (!engine->larb_mmu)
		return ERR_PTR(-ENOMEM);
	for (i = 0; i < MEMORY_COUNT; i++) {
		ret = allocate_buffer(engine, &engine->memory[i],
				      i == INPUT ? INPUT_DATA_SIZE + GUARD_SIZE :
				      ALLOC_SIZE);
		if (ret)
			goto fail;
	}
	engine->irq = platform_get_irq(pdev, 0);
	if (engine->irq < 0) {
		ret = engine->irq;
		goto fail;
	}
	ret = devm_request_irq(dev, engine->irq, decoder_irq, IRQF_NO_AUTOEN,
			      dev_name(dev), engine);
	if (ret)
		goto fail;
	/* disable_irq_nosync must mask the GIC immediately, even on a flow
	 * handler that would otherwise defer masking until another delivery.
	 */
	irq_set_status_flags(engine->irq, IRQ_DISABLE_UNLAZY);
	ret = devm_add_action_or_reset(dev, clear_irq_flags, engine);
	if (ret)
		goto fail;
	pm_runtime_enable(dev);
	return engine;
fail:
	for (i = 0; i < MEMORY_COUNT; i++)
		release_buffer(engine, &engine->memory[i]);
	return ERR_PTR(ret);
}

struct mt6797_decode_context *mt6797_decode_context_create(struct mt6797_engine *engine)
{
	struct mt6797_decode_context *ctx;

	if (engine->fenced)
		return ERR_PTR(-EIO);
	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return ERR_PTR(-ENOMEM);
	/* Queries and unused opens need no private picture DMA allocations. */
	ctx->engine = engine;
	list_add_tail(&ctx->list, &engine->contexts);
	return ctx;
}

void mt6797_decode_context_reset(struct mt6797_decode_context *ctx)
{
	unsigned int i;

	if (ctx->engine->fenced)
		return;
	for (i = 0; i < ARRAY_SIZE(ctx->cache); i++) {
		memset(&ctx->cache[i], 0, sizeof(ctx->cache[i]));
		mt6797_picture_put(&ctx->pictures[i]);
	}
}

void mt6797_decode_context_destroy(struct mt6797_decode_context *ctx)
{
	/* On a fatal stop failure the engine retains this independent object.
	 * It holds no frontend/file/control pointers, so file close remains safe.
	 */
	if (ctx->engine->fenced)
		return;
	list_del(&ctx->list);
	mt6797_decode_context_reset(ctx);
	kfree(ctx);
}

bool mt6797_engine_fenced(const struct mt6797_engine *engine)
{
	return READ_ONCE(engine->fenced);
}

void mt6797_engine_destroy(struct mt6797_engine *engine)
{
	unsigned int i;
	if (WARN_ON(engine->fenced || !list_empty(&engine->contexts)))
		return;
	disarm_irq(engine);
	pm_runtime_disable(engine->dev);
	for (i = 0; i < MEMORY_COUNT; i++)
		release_buffer(engine, &engine->memory[i]);
}

static int reset_core(struct mt6797_engine *engine)
{
	u32 state;
	write_word(0x101, engine->banks[VLD] + 0x108);
	readl(engine->banks[VLD] + 0x108);
	udelay(2);
	return readl_poll_timeout(engine->banks[VLD] + 0xf4, state, !(state & BIT(15)), 10, 100000);
}

static int reset_whole_decoder(struct mt6797_engine *engine)
{
	u32 original, state, clock, smi, after;
	int ret, release_ret;

	ret = regmap_read(engine->gcon, 0x10, &original);
	if (ret)
		return ret;
	if (!(original & BIT(0)))
		return -EBUSY;
	ret = regmap_read(engine->gcon, 0, &clock);
	if (!ret)
		ret = regmap_read(engine->gcon, 8, &smi);
	if (ret)
		return ret;
	ret = regmap_update_bits(engine->gcon, 0x10, BIT(0), 0);
	if (!ret) {
		ret = regmap_read(engine->gcon, 0x10, &state);
		if (!ret && (state & BIT(0)))
			ret = -EIO;
		udelay(2);
	}
	release_ret = regmap_update_bits(engine->gcon, 0x10, BIT(0), BIT(0));
	if (!ret)
		ret = release_ret;
	if (!ret)
		ret = regmap_read(engine->gcon, 0x10, &state);
	if (ret || state != original)
		return ret ? ret : -EIO;
	ret = regmap_read(engine->gcon, 0, &after);
	if (ret || after != clock)
		return ret ? ret : -EIO;
	ret = regmap_read(engine->gcon, 8, &after);
	return ret ? ret : after == smi ? 0 : -EIO;
}

static int validate_job(struct mt6797_decode_context *ctx,
			const struct mt6797_decode_job *job,
			struct mt6797_h264_header_words *header,
			struct mt6797_h264_slice_words *slice,
			struct mt6797_h264_reference_plan *plan,
			bool continuation)
{
	int ret;

	if (!job->nal || job->bytes < 4 || job->bytes > MAX_NAL)
		return -EINVAL;
	ret = mt6797_h264_header_words(&job->sps, &job->pps, header);
	if (ret)
		return ret;
	ret = mt6797_h264_slice_words(&job->sps, &job->pps, &job->slice,
				    &job->decode, job->bytes, slice);
	if (ret)
		return ret;
	if ((job->sps.profile_idc != 66 && job->sps.profile_idc != 77 &&
	     job->sps.profile_idc != 100) ||
	    (job->sps.profile_idc == 66 &&
	     (job->pps.flags & (V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE |
			       V4L2_H264_PPS_FLAG_WEIGHTED_PRED))) ||
	    job->width < 64 || job->width > MT6797_MAX_WIDTH || job->width % 16 ||
	    job->height < 64 || job->height > MT6797_MAX_HEIGHT || job->height % 32 ||
	    header->width_mbs * 16 != job->width || header->height_mbs * 16 < 64 ||
	    ALIGN(header->height_mbs * 16, 32) != job->height ||
	    (!continuation && job->slice.first_mb_in_slice) ||
	    (job->sps.profile_idc != 100 &&
	     (job->pps.flags & (V4L2_H264_PPS_FLAG_TRANSFORM_8X8_MODE |
			       V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT))) ||
	    (job->sps.profile_idc == 66 && job->slice.slice_type == V4L2_H264_SLICE_TYPE_B) ||
	    (!!(job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_PFRAME) !=
	     (job->slice.slice_type == V4L2_H264_SLICE_TYPE_P)) ||
	    (!!(job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_BFRAME) !=
	     (job->slice.slice_type == V4L2_H264_SLICE_TYPE_B)) ||
	    (job->nal[0] & 0x80) || ((job->nal[0] >> 5) & 3) != job->decode.nal_ref_idc ||
	    ((job->nal[0] & 31) != ((job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) ? 5 : 1)))
		return -EOPNOTSUPP;
	ret = mt6797_h264_picture_poc(&job->sps, &job->pps, &job->decode);
	if (ret)
		return ret;
	return mt6797_h264_reference_plan(&job->sps, &job->slice, &job->decode,
					 ctx->cache, job->timestamp, plan);
}

int mt6797_engine_validate_slice(struct mt6797_decode_context *ctx,
			       const struct mt6797_decode_job *job)
{
	struct mt6797_h264_header_words header;
	struct mt6797_h264_slice_words slice;
	struct mt6797_h264_reference_plan plan;
	struct mt6797_h264_weight_range weights;
	struct mt6797_h264_scaling_word scaling[MT6797_H264_SCALING_WORDS];
	int ret;

	if (ctx->engine->fenced)
		return -EIO;
	ret = validate_job(ctx, job, &header, &slice, &plan, true);
	if (ret)
		return ret;
	if (V4L2_H264_CTRL_PRED_WEIGHTS_REQUIRED(&job->pps, &job->slice)) {
		ret = mt6797_h264_weight_range(&job->sps, &job->pps, &job->slice,
					     &job->decode, &job->weights,
					     job->nal, job->bytes, &weights);
		if (ret)
			return ret;
	}
	return job->pps.flags & V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT ?
		mt6797_h264_scaling_words(&job->scaling, scaling) : 0;
}

/* Every buffer starts CPU-owned. Only the serialized worker gives it to
 * hardware, and returns ownership after a proven stop. Fatal fencing retains
 * device ownership and the allocations until reboot.
 */
static void buffers_to_device(struct mt6797_decode_context *ctx)
{
	struct mt6797_engine *engine = ctx->engine;
	unsigned int i;

	for (i = 0; i < MEMORY_COUNT; i++) {
		struct private_buffer *buf = &engine->memory[i];
		dma_sync_single_for_device(engine->dev, buf->dma, buf->bytes, DMA_BIDIRECTIONAL);
		buf->device_owned = true;
	}
	mt6797_surface_job_to_device(ctx->surface_job);
}

static void buffers_to_cpu(struct mt6797_decode_context *ctx)
{
	struct mt6797_engine *engine = ctx->engine;
	unsigned int i;

	for (i = 0; i < MEMORY_COUNT; i++) {
		struct private_buffer *buf = &engine->memory[i];
		if (buf->device_owned) {
			dma_sync_single_for_cpu(engine->dev, buf->dma, buf->bytes, DMA_BIDIRECTIONAL);
			buf->device_owned = false;
		}
	}
	mt6797_surface_job_to_cpu(ctx->surface_job);
}

static int prepare_pictures(struct mt6797_decode_context *ctx, size_t luma_size,
			    struct mt6797_h264_reference_plan *plan,
			    const struct mt6797_picture *capture)
{
	size_t bytes = mt6797_picture_bytes(luma_size);
	unsigned int i;

	if (!capture->buffer || bytes > PICTURE_ALLOC_SIZE ||
	    plan->output >= ARRAY_SIZE(ctx->pictures) || capture->bytes != bytes)
		return -EOVERFLOW;
	if (mt6797_picture_poisoned(capture))
		return -EIO;
	/* A current DPB reference cannot be overwritten through another view
	 * or fd of the same allocation, even if the output slot is different.
	 */
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++)
		if ((plan->protected_mask & BIT(i)) &&
		    ctx->pictures[i].buffer == capture->buffer)
			return -EBUSY;
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++) {
		if (i != plan->output && ctx->cache[i].valid &&
		    ctx->pictures[i].buffer != capture->buffer)
			continue;
		memset(&ctx->cache[i], 0, sizeof(ctx->cache[i]));
		mt6797_picture_put(&ctx->pictures[i]);
	}
	mt6797_picture_get(&ctx->pictures[plan->output], capture);
	ctx->cache[plan->output].allocated = true;
	return 0;
}

static int prepare_reference_snapshot(struct mt6797_decode_context *ctx,
				       struct mt6797_h264_reference_plan *plan)
{
	struct mt6797_engine *engine = ctx->engine;
	size_t bytes = 0;
	unsigned int i;
	u8 *snapshot;

	/* A geometry resize may have invalidated the old plan's cached pictures. */
	plan->snapshot_mask = 0;
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++)
		if (i != plan->output && ctx->cache[i].valid && ctx->pictures[i].cpu) {
			plan->snapshot_mask |= BIT(i);
			bytes += ctx->pictures[i].bytes;
		}
	if (bytes > V4L2_H264_NUM_DPB_ENTRIES * PICTURE_ALLOC_SIZE)
		return -EOVERFLOW;
	if (bytes > engine->snapshot_bytes) {
		snapshot = kvmalloc(bytes, GFP_KERNEL);
		if (!snapshot)
			return -ENOMEM;
		kvfree(engine->reference_snapshot);
		engine->reference_snapshot = snapshot;
		engine->snapshot_bytes = bytes;
	}
	bytes = 0;
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++)
		if (plan->snapshot_mask & BIT(i)) {
			memcpy(engine->reference_snapshot + bytes, ctx->pictures[i].cpu,
			       ctx->pictures[i].bytes);
			bytes += ctx->pictures[i].bytes;
		}
	return 0;
}

/* Read-only, powered observations. A failed sample is absent in the valid
 * mask; sysfs only exposes this cache and never accesses live hardware.
 */
static void snapshot_clock(struct mt6797_engine *engine,
			   struct mt6797_decode_status *status,
			   enum mt6797_clock_phase phase)
{
	u32 word;

	if (!regmap_read(engine->gcon, 0, &word)) {
		status->irq_clock_trace[phase] = word;
		status->irq_clock_trace_valid |= BIT(phase);
	}
}

int mt6797_engine_decode(struct mt6797_decode_context *ctx,
			 const struct mt6797_decode_job *job,
			 const struct mt6797_picture *capture,
			 struct mt6797_decode_status *status)
{
	static const u8 eos[] = { 0, 0, 0, 1, 0x0a };
	bool cabac = job->pps.flags & V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE;
	const u8 *ending = eos;
	size_t ending_bytes = sizeof(eos);
	struct mt6797_engine *engine = ctx->engine;
	struct mt6797_h264_header_words header;
	struct mt6797_h264_slice_words slice;
	struct mt6797_h264_p_reference_words (*ref_words)[V4L2_H264_NUM_DPB_ENTRIES] = engine->refs;
	struct mt6797_h264_reference_plan plan;
	struct mt6797_h264_weight_range weights = { 0 };
	struct mt6797_h264_scaling_word scaling[MT6797_H264_SCALING_WORDS];
	struct register_save *saved = &engine->saved;
	void __iomem *misc = engine->banks[MISC], *vld = engine->banks[VLD];
	void __iomem *top = engine->banks[TOP], *mc = engine->banks[MC];
	void __iomem *avc = engine->banks[AVC], *mv = engine->banks[MV], *pp = engine->banks[PP];
	struct private_buffer *input = &engine->memory[INPUT], *prediction = &engine->memory[PREDICTION];
	struct mt6797_picture *picture;
	u32 state, original_dcm, original_irq, original_break, original_gate;
	unsigned int remaining, i, list, luma_size = job->width * job->height;
	unsigned int pixel_bytes = luma_size * 3 / 2, motion_bytes = luma_size / 4;
	bool b_picture = job->slice.slice_type == V4L2_H264_SLICE_TYPE_B;
	int ret, stop_ret, reference_error = 0;
	size_t snapshot_offset;
	bool dma_started = false, reference_poc_seen = false;

	static_assert(ALIGN(MAX_NAL + sizeof(eos), 128) + 128 <= INPUT_DATA_SIZE);
	memset(status, 0, sizeof(*status));
	status->irq_clock_result = -ENODATA;
	status->irq_masked_before = status->irq_pending_before = status->irq_active_before = -ENODATA;
	status->irq_masked_after = status->irq_pending_after = status->irq_active_after = -ENODATA;
	status->current_poc = job->decode.top_field_order_cnt;
	if (engine->fenced)
		return -EIO;
	saved->count = 0;
	ret = validate_job(ctx, job, &header, &slice, &plan, false);
	if (ret)
		return ret;
	if (V4L2_H264_CTRL_PRED_WEIGHTS_REQUIRED(&job->pps, &job->slice)) {
		ret = mt6797_h264_weight_range(&job->sps, &job->pps, &job->slice,
					     &job->decode, &job->weights,
					     job->nal, job->bytes, &weights);
		if (ret)
			return ret;
		status->weight_start = weights.start;
		status->weight_end = weights.end;
		status->weight_start_mask = weights.start_mask;
		status->weight_end_mask = weights.end_mask;
	}
	/* All consumed coefficients must be valid before allocating picture
	 * storage, taking a power vote or transferring private DMA ownership.
	 */
	if (job->pps.flags & V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT) {
		ret = mt6797_h264_scaling_words(&job->scaling, scaling);
		if (ret)
			return ret;
	}
	for (list = 0; list < (b_picture ? 2 : 1); list++)
		for (i = 0; i < (list ? plan.count1 : plan.count); i++) {
			const struct v4l2_h264_reference *ref = list ?
				&job->slice.ref_pic_list1[i] : &job->slice.ref_pic_list0[i];
			unsigned int identity = list ? plan.list1[i] : plan.list0[i];
			ret = b_picture ?
				mt6797_h264_b_reference_words(&job->decode.dpb[ref->index], identity, &ref_words[list][i]) :
				mt6797_h264_p_reference_words(&job->decode.dpb[ref->index], identity, &ref_words[list][i]);
			if (ret)
				return ret;
		}
	ret = prepare_pictures(ctx, luma_size, &plan, capture);
	if (ret)
		return ret;
	ctx->surface_job = mt6797_surface_job_begin(ctx->pictures,
						 ARRAY_SIZE(ctx->pictures), plan.output);
	if (IS_ERR(ctx->surface_job)) {
		ret = PTR_ERR(ctx->surface_job);
		ctx->surface_job = NULL;
		return ret;
	}
	ret = prepare_reference_snapshot(ctx, &plan);
	if (ret)
		goto surfaces;
	picture = &ctx->pictures[plan.output];
	status->reference_count = plan.count;
	status->reference_count1 = plan.count1;
	status->motion_bytes = motion_bytes;
	status->reference_mask = plan.protected_mask;
	status->long_term_mask = plan.long_term_mask;
	status->snapshot_mask = plan.snapshot_mask;
	status->picture_slot = plan.output;
	for (i = 0; i < V4L2_H264_NUM_DPB_ENTRIES; i++) {
		const struct v4l2_h264_dpb_entry *entry = &job->decode.dpb[i];
		if ((job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) ||
		    !(entry->flags & V4L2_H264_DPB_ENTRY_FLAG_ACTIVE))
			continue;
		if (!reference_poc_seen) {
			status->reference_min_poc = status->reference_max_poc = entry->top_field_order_cnt;
			reference_poc_seen = true;
		}
		status->reference_min_poc = min(status->reference_min_poc,
			min(entry->top_field_order_cnt, entry->bottom_field_order_cnt));
		status->reference_max_poc = max(status->reference_max_poc,
			max(entry->top_field_order_cnt, entry->bottom_field_order_cnt));
	}
	/* An attempted overwrite invalidates the old timestamp even on failure. */
	ctx->cache[plan.output].valid = false;
	memset(input->cpu, 0xa5, input->bytes);
	memcpy(input->cpu, job->nal, job->bytes);
	memset(input->cpu + job->bytes, 0, INPUT_DATA_SIZE - job->bytes);
	/* Private end marker and readable zero padding; userspace remains untouched. */
	memcpy(input->cpu + job->bytes, ending, ending_bytes);
	for (i = PREDICTION; i < MEMORY_COUNT; i++) {
		size_t data_bytes = engine->memory[i].bytes - GUARD_SIZE;
		memset(engine->memory[i].cpu, 0, data_bytes);
		memset(engine->memory[i].cpu + data_bytes, 0xd3, GUARD_SIZE);
	}
	memset(picture->cpu, 0xd3, picture->bytes);
	memset(picture->cpu + pixel_bytes, 0, motion_bytes);

	ret = pm_runtime_resume_and_get(engine->dev);
	if (ret < 0)
		goto surfaces;
	snapshot_clock(engine, status, MT6797_CLOCK_POWERED);
	if ((readl(engine->larb_mmu) & GENMASK(9, 0)) != GENMASK(9, 0)) {
		ret = -EIO;
		goto power;
	}
	ret = reset_whole_decoder(engine);
	if (ret)
		goto power;
	snapshot_clock(engine, status, MT6797_CLOCK_RESET);
	if ((readl(engine->larb_mmu) & GENMASK(9, 0)) != GENMASK(9, 0)) {
		ret = -EIO;
		goto power;
	}
	ret = regmap_read(engine->gcon, 0x18, &original_dcm);
	if (ret)
		goto power;
	original_irq = readl(misc + 0xa4);
	original_break = readl(misc + 0x100);
	original_gate = readl(misc + 0xf4);
	if (original_irq & BIT(16)) {
		ret = -EBUSY;
		goto power;
	}
#define SAVE(address, value) save_word(saved, (address), (value))
	write_word(original_gate & ~BIT(0), misc + 0xf4);
	ret = reset_core(engine);
	if (ret)
		goto cleanup;
	snapshot_clock(engine, status, MT6797_CLOCK_CORE_RESET);
	write_word((original_irq | BIT(0)) & ~BIT(4), misc + 0xa4);
	SAVE(misc + 0xc8, 0);
	SAVE(misc + 0xcc, 0);
	SAVE(misc + 0x178, 0);
	SAVE(misc, readl(misc) & 0xff400000);
	SAVE(misc + 0xec, readl(misc + 0xec) | BIT(0));
	ret = regmap_update_bits(engine->gcon, 0x18, BIT(0), BIT(0));
	if (ret)
		goto cleanup;
	snapshot_clock(engine, status, MT6797_CLOCK_DCM_OFF);
	SAVE(misc + 0x84, 2);
	write_word(0, vld + 0x108);
	if (readl(vld + 0x2ec) & BIT(8)) {
		ret = -EBUSY;
		goto cleanup;
	}
	write_word(readl(vld + 0x2ec) | BIT(8), vld + 0x2ec);
	write_word(readl(vld + 0x2ec) & ~BIT(8), vld + 0x2ec);
	SAVE(vld + 0xc0, readl(vld + 0xc0) | BIT(18));
	SAVE(avc + 0x84, 0xa8000007);
	SAVE(mc + 0x24, 6);
	SAVE(top + 0x28, lower_32_bits(prediction->dma));
	write_word(lower_32_bits(input->dma) >> 6, vld + 0xb4);
	write_word(lower_32_bits(input->dma + INPUT_DATA_SIZE) >> 6, vld + 0xb8);
	write_word(readl(vld + 0x110) | BIT(0), vld + 0x110);
	write_word(lower_32_bits(input->dma), vld + 0xb0);
	write_word(lower_32_bits(input->dma), vld + 0xb0);
	/* The barrel reader can require lookahead past the end marker. Keep a
	 * further complete 128-byte zero block readable, inside private data.
	 * MAX_NAL reserves that block and the alignment/end-marker overhead.
	 * A 17-byte readable tail stalled two independently encoded pictures
	 * near their final macroblocks despite otherwise intact DMA guards.
	 */
	write_word(lower_32_bits(input->dma + ALIGN(job->bytes + ending_bytes, 128) + 128),
		   vld + 0x110);
	write_word(1, avc + 0x28c);
	write_word(BIT(8), vld + 0x108);
	write_word(0, vld + 0x108);
	buffers_to_device(ctx);
	dma_wmb();
	dma_started = true;
	status->fetched = true;
	write_word(BIT(20), vld + 0x8c);
	ret = readl_poll_timeout(vld + 0xe8, state, state & BIT(0), 10, 100000);
	if (ret)
		goto cleanup;
	write_word(BIT(23), vld + 0x8c);
	write_word(0, avc + 0x28c);
	if (readl(avc) != get_unaligned_be32(job->nal)) {
		ret = -EIO;
		goto cleanup;
	}
	if (weights.end) {
		/* The public weight-table operation parses at the current barrel
		 * position using the programmed PPS and active-reference count.
		 * Keep the unweighted initialization sequence unchanged.
		 */
		SAVE(avc + 0x88, header.sps);
		SAVE(avc + 0x90, header.pps);
		SAVE(avc + 0x94, header.reference_counts);
		SAVE(avc + 0x98, (readl(avc + 0x98) & 0x1fff) | slice.header1);
	}
	remaining = weights.end ? weights.start : job->slice.header_bit_size;
	while (remaining) {
		unsigned int advance = min(remaining, 32U);
		readl(avc + advance * 4);
		remaining -= advance;
	}
	if (weights.end) {
		u32 original_weight_select = readl(misc + 0xf0);

		/* The related helper reports six counter bits, but trial48 reports
		 * 15 for a table ending at bit47 with this SUM6 input mode. Check
		 * the low five counter bits and the actual following RBSP bits;
		 * retain the full observed counter in cached diagnostic status.
		 */
		status->weight_before = (readl(avc + 0x84) >> 16) & 63;
		status->weight_before_word = readl(avc);
		if ((status->weight_before & 31) != (weights.start & 31) ||
		    (status->weight_before_word & weights.start_mask) != weights.start_word) {
			ret = -EIO;
			goto cleanup;
		}
		SAVE(misc + 0xf0, original_weight_select | BIT(0));
		write_word(1, avc + 0x230);
		ret = readl_poll_timeout(avc + 0x230, state, state, 10, 100000);
		status->weight_state = state;
		write_word(original_weight_select, misc + 0xf0);
		if (ret)
			goto cleanup;
		status->weight_after = (readl(avc + 0x84) >> 16) & 63;
		status->weight_after_word = readl(avc);
		if ((status->weight_after & 31) != (weights.end & 31) ||
		    (status->weight_after_word & weights.end_mask) != weights.end_word) {
			ret = -EIO;
			goto cleanup;
		}
		remaining = job->slice.header_bit_size - weights.end;
		while (remaining) {
			unsigned int advance = min(remaining, 32U);
			readl(avc + advance * 4);
			remaining -= advance;
		}
	}
	write_word(1, avc + 0x228);
	ret = readl_poll_timeout(avc + 0x228, state, !(state & BIT(0)), 10, 100000);
	if (ret)
		goto cleanup;
	SAVE(avc + 0xa0, 1U << (job->sps.log2_max_frame_num_minus4 + 4));
	SAVE(avc + 0xa4, job->decode.frame_num);
	/* The related public GPL common-VLD interface consumes raster coefficients
	 * in eight SRAM lists: six 4x4 and two luma 8x8. The PPS word below
	 * selects these lists; when absent the core uses flat scaling.
	 */
	if (job->pps.flags & V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT)
		for (i = 0; i < ARRAY_SIZE(scaling); i++) {
			write_word(0x200 + scaling[i].location, vld + 0x260);
			write_word(scaling[i].coefficients, vld + 0x264);
			write_word(0x100 + scaling[i].location, vld + 0x260);
			/* The public SRAM dump reads the selected word at 0x264.
			 * A failed round-trip must not start picture reconstruction.
			 */
			if (readl(vld + 0x264) != scaling[i].coefficients) {
				ret = -EIO;
				goto cleanup;
			}
		}
	SAVE(avc + 0x88, header.sps);
	SAVE(avc + 0x90, header.pps);
	SAVE(avc + 0x94, header.reference_counts);
	SAVE(avc + 0x8c, (readl(avc + 0x8c) & ~0x1ffff) | slice.first_mb);
	SAVE(avc + 0x98, (readl(avc + 0x98) & 0x1fff) | slice.header1);
	SAVE(avc + 0x9c, slice.header2);
	/* Public related-core interface: AVC + 0x234 initializes CABAC
	 * context SRAM from the programmed PPS and slice/QP words.
	 */
	if (job->pps.flags & V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE)
		write_word(1, avc + 0x234);
	if (b_picture) {
		SAVE(mc + 0x568, 0);
		SAVE(mc + 0x56c, 0);
		for (list = 0; list < 2; list++)
			for (i = 0; i < (list ? plan.count1 : plan.count); i++) {
				unsigned int identity = list ? plan.list1[i] : plan.list0[i];
				dma_addr_t address = ctx->pictures[identity].dma;
				SAVE(mc + (list ? 0x4dc : 0x45c) + i * 4, lower_32_bits(address));
				SAVE(avc + (list ? 0x1a8 : 0x128) + i * 4, ref_words[list][i].picture_number);
				SAVE(mv + (list ? 0x100 : 0x80) + i * 8, ref_words[list][i].top);
				SAVE(mv + (list ? 0x100 : 0x80) + i * 8 + 4, ref_words[list][i].bottom);
				if (list) {
					/* Public full motion layout: bottom-field base is64bytes
					 * after top; retain the whole buffer with its picture.
					 */
					u32 motion = lower_32_bits(address + pixel_bytes) >> 4;
					SAVE(mv + 0x180 + i * 8, motion);
					SAVE(mv + 0x180 + i * 8 + 4, motion + 4);
				}
			}
	} else if (plan.count) {
		SAVE(mc + 0x564, 0);
		for (i = 0; i < plan.count; i++) {
			SAVE(mc + 0x3dc + i * 4, lower_32_bits(ctx->pictures[plan.list0[i]].dma));
			SAVE(avc + 0xa8 + i * 4, ref_words[0][i].picture_number);
			SAVE(mv + i * 8, ref_words[0][i].top);
			SAVE(mv + i * 8 + 4, ref_words[0][i].bottom);
		}
	}
	SAVE(avc + 0x280, ~(u32)(BIT(14) | BIT(21)));
	SAVE(avc + 0x2c8, readl(avc + 0x2c8) & ~BIT(5));
	SAVE(top + 0x68, (header.width_mbs - 1) | ((header.height_mbs - 1) << 16));
	/* Coded dimensions govern prediction; MM21's allocation height is rounded
	 * to 32 luma rows and only controls the plane offsets and payload size.
	 */
	SAVE(top + 0x70, (header.width_mbs * 16) | ((u32)header.height_mbs * 16 << 16));
	SAVE(top + 0x58, 0xffffffff);
	SAVE(top + 0x6c, header.width_mbs * header.height_mbs);
	SAVE(top + 0x50, 0xffffffff);
	SAVE(top + 0x54, readl(top + 0x54) | BIT(0));
	SAVE(misc + 0xf0, readl(misc + 0xf0) | BIT(0));
	SAVE(mc + 0x90, 4);
	SAVE(mc + 0x768, (readl(mc + 0x768) & ~GENMASK(2, 0)) | 4);
	SAVE(mc + 0x208, job->width);
	/* Public related-core definitions identify separate unrestricted-motion
	 * picture width/height words. A width written as height clips references
	 * below row 63 in the independently observed 64x96 inter-picture test.
	 */
	SAVE(mc + 0x20c, header.height_mbs * 16);
	SAVE(mc + 0x220, 1);
	SAVE(mc + 0x224, lower_32_bits(picture->dma) >> 9);
	SAVE(mc + 0x228, lower_32_bits(picture->dma + luma_size) >> 8);
	SAVE(mc + 0x22c, header.width_mbs);
	SAVE(mc + 0x238, 3);
	SAVE(mc + 0x250, 1);
	SAVE(mc + 0x260, header.width_mbs - 1);
	SAVE(mc + 0x264, header.height_mbs - 1);
	SAVE(mc + 0x268, 1);
	SAVE(mc + 0x560, lower_32_bits(picture->dma));
	SAVE(mc + 0x55c, luma_size);
	SAVE(mc + 0x980, header.width_mbs);
	SAVE(mc + 0xa20, lower_32_bits(engine->memory[VLD_WRAP].dma));
	SAVE(mc + 0xa24, lower_32_bits(engine->memory[PP_WRAP].dma));
	SAVE(mc + 0x5e4, readl(mc + 0x5e4) | BIT(12));
	SAVE(mc + 0x920, readl(mc + 0x920) | BIT(24));
	SAVE(mv + 0x200, min(job->decode.top_field_order_cnt, job->decode.bottom_field_order_cnt) & 0x3ffff);
	SAVE(mv + 0x204, job->decode.top_field_order_cnt & 0x3ffff);
	SAVE(mv + 0x208, job->decode.bottom_field_order_cnt & 0x3ffff);
	status->current_poc_word = readl(mv + 0x200);
	if (status->current_poc_word !=
	    ((u32)min(job->decode.top_field_order_cnt, job->decode.bottom_field_order_cnt) & 0x3ffff)) {
		ret = -EIO;
		goto cleanup;
	}
	SAVE(mv + 0x220, readl(mv + 0x220) & ~BIT(5));
	SAVE(mv + 0x20c, lower_32_bits(picture->dma + pixel_bytes) >> 4);
	SAVE(pp + 0x804, readl(pp + 0x804) & ~BIT(4));
	ret = readl_poll_timeout(avc + 0x25c, state, !(state & BIT(25)), 10, 100000);
	if (ret)
		goto cleanup;
	dma_wmb();
	snapshot_clock(engine, status, MT6797_CLOCK_SUBMIT);
	ret = submit_decode(engine, status);
	if (ret)
		goto cleanup;
	ret = wait_decode_irq(engine);
	/* Sample the controller before disarm masks the line. These are cached
	 * observations only; no pending bit or register is written by this probe.
	 * Full AVC completion (0x274) and picture state (0x278) are distinct.
	 */
	irq_controller_snapshot(engine, &status->irq_masked_after,
				&status->irq_pending_after, &status->irq_active_after);
	status->irq_complete = readl(avc + 0x274);
	status->irq_clock_result = regmap_read(engine->gcon, 0, &status->irq_clock_guard);
	disarm_irq(engine);
	status->irq_command = engine->irq_command;
	status->irq_received_command = engine->irq_received_command;
	status->irq_events = engine->irq_events;
	status->irq_unexpected = engine->irq_unexpected;
	status->irq_status = engine->irq_status;
	if (!ret && (status->irq_events != 1 || status->irq_unexpected ||
		     status->irq_received_command != status->irq_command ||
		     !(status->irq_status & BIT(16)) || !status->irq_complete))
		ret = -EIO;
	status->state = readl(avc + 0x278);
	status->irq = readl(misc + 0xa4);
	status->error = readl(avc + 0x284);
	status->message = readl(avc + 0x270);
	/* Public read-only progress and stable configuration words. Cache these
	 * before stopping the engine; sysfs never accesses live hardware.
	 */
	status->mbx = readl(mc + 0x28);
	status->mby = readl(mc + 0x2c);
	status->stall = readl(avc + 0x25c);
	status->read_pointer = readl(vld + 0xb0);
	status->fetch_status = readl(vld + 0xe8);
	status->top_status = readl(top + 0x80);
	status->pred_config = readl(top + 0x2c);
	status->pred_mode = readl(top + 0x40);
	/* The public related-core interface identifies bit 14 as a CABAC
	 * trailer check. A completed picture may report this alone when the
	 * byte-aligned parser window is already at a zero word/start code.
	 * Verify that condition; retain both raw error words for diagnostics.
	 * The error accumulator retains the trailer flag independently of the
	 * current message. The public classifier does not require their equality;
	 * Gemini's completed multislice cases expose a zero current message.
	 * Admit only these known messages with the sole accumulated trailer bit
	 * and a verified window, full picture completion and final macroblock.
	 * Other errors, incomplete pictures and failed DMA guards stay fatal.
	 */
	if (!ret && (status->state & BIT(31)) && cabac && status->error == BIT(14) &&
	    (status->message == BIT(14) || !status->message) &&
	    status->mbx == header.width_mbs - 1 &&
	    status->mby == header.height_mbs - 1) {
		status->cabac_tail_checked = true;
		status->tail_bit_offset = (readl(avc + 0x84) >> 16) & 0x3f;
		remaining = (-status->tail_bit_offset) & 7;
		if (remaining)
			readl(avc + remaining * 4);
		status->tail_word = readl(avc);
		status->cabac_tail_window_valid = !status->tail_word ||
			status->tail_word == 1 || (status->tail_word >> 8) == 1;
		status->cabac_tail_valid = status->cabac_tail_window_valid;
	}
	if (!ret && (!(status->state & BIT(31)) ||
		     ((status->error || status->message) && !status->cabac_tail_valid) ||
		     status->mbx != header.width_mbs - 1 ||
		     status->mby != header.height_mbs - 1))
		ret = -EIO;
cleanup:
	/* Even a fatal stop failure must leave the IRQ line masked and every
	 * handler retired before retaining private DMA/power for recovery.
	 */
	disarm_irq(engine);
	if (status->irq_command) {
		status->irq_received_command = engine->irq_received_command;
		status->irq_events = engine->irq_events;
		status->irq_unexpected = engine->irq_unexpected;
		status->irq_status = engine->irq_status;
	}
	if (dma_started) {
		write_word(original_break | BIT(0), misc + 0x100);
		status->break_result = readl_poll_timeout(misc + 0x104, state,
						      (state & 0x11) == 0x11, 10, 100000);
	}
	status->reset_result = reset_core(engine);
	status->quiesced = !status->reset_result && (!dma_started || !status->break_result);
	if (!status->quiesced) {
		engine->fenced = true;
		mt6797_surface_job_poison(ctx->surface_job);
		__module_get(THIS_MODULE);
		dev_err(engine->dev, "decoder stop failed; shared DMA/fence/power retained until reboot\n");
		return -EIO;
	}
	buffers_to_cpu(ctx);
	dma_rmb();
	status->guards_unchanged = !memcmp(input->cpu, job->nal, job->bytes) &&
		!memcmp(input->cpu + job->bytes, ending, ending_bytes) &&
		!memchr_inv(input->cpu + job->bytes + ending_bytes, 0,
			    INPUT_DATA_SIZE - job->bytes - ending_bytes) &&
		!memchr_inv(input->cpu + INPUT_DATA_SIZE, 0xa5, GUARD_SIZE) &&
		!memchr_inv(picture->cpu + pixel_bytes + motion_bytes, 0xd3,
			    picture->bytes - pixel_bytes - motion_bytes);
	for (i = PREDICTION; i < MEMORY_COUNT; i++)
		if (memchr_inv(engine->memory[i].cpu + engine->memory[i].bytes - GUARD_SIZE,
				0xd3, GUARD_SIZE))
			status->guards_unchanged = false;
	snapshot_offset = 0;
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++) {
		struct mt6797_picture *buf = &ctx->pictures[i];
		if (!buf->cpu)
			continue;
		if (memchr_inv(buf->cpu + pixel_bytes + motion_bytes, 0xd3,
			       buf->bytes - pixel_bytes - motion_bytes)) {
			status->guards_unchanged = false;
			if (plan.snapshot_mask & BIT(i))
				reference_error = -EIO;
		}
		if (plan.snapshot_mask & BIT(i)) {
			if (memcmp(buf->cpu, engine->reference_snapshot + snapshot_offset, buf->bytes)) {
				status->guards_unchanged = false;
				reference_error = -EIO;
			}
			snapshot_offset += buf->bytes;
			status->reference_guard_count++;
			status->motion_guard_count++;
		}
	}
	if (!status->guards_unchanged) {
		mt6797_decode_context_reset(ctx);
		ret = -EIO;
	}
	if (status->submitted)
		acknowledge_irq(engine);
	status->registers_saved = saved->count;
	restore_words(saved);
	write_word(original_break, misc + 0x100);
	write_word(original_irq & ~BIT(4), misc + 0xa4);
	stop_ret = regmap_update_bits(engine->gcon, 0x18, BIT(0), original_dcm & BIT(0));
	if (!ret && stop_ret)
		ret = stop_ret;
	write_word(0, vld + 0x108);
	write_word(original_gate, misc + 0xf4);
#undef SAVE
power:
	stop_ret = pm_runtime_put_sync_suspend(engine->dev);
	if (!ret && stop_ret < 0)
		ret = stop_ret;
	if (!ret) {
		/* Retire old IDR/reused identities without dropping this output's
		 * independent surface reference before it becomes the new DPB slot.
		 */
		for (i = 0; i < ARRAY_SIZE(ctx->cache); i++)
			if (i != plan.output &&
			    ((job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) ||
			     ctx->cache[i].timestamp == job->timestamp)) {
				memset(&ctx->cache[i], 0, sizeof(ctx->cache[i]));
				mt6797_picture_put(&ctx->pictures[i]);
			}
		ctx->cache[plan.output] = (struct mt6797_h264_cached_picture) {
			.timestamp = job->timestamp, .frame_number = job->decode.frame_num,
			.width = header.width_mbs * 16, .height = header.height_mbs * 16,
			.top_poc = job->decode.top_field_order_cnt,
			.bottom_poc = job->decode.bottom_field_order_cnt,
			.allocated = true, .valid = job->decode.nal_ref_idc != 0,
		};
	}
surfaces:
	mt6797_surface_job_finish(ctx->surface_job, ret, reference_error);
	ctx->surface_job = NULL;
	return ret;
}
