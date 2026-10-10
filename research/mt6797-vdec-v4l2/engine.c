// SPDX-License-Identifier: GPL-2.0-only
/* Original register backend derived from this project's guarded diagnostics.
 * Public register provenance: ../mt6797-video-interface.json.
 * Private bounce buffers isolate userspace queues from unproven DMA stop.
 */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>
#include <linux/iommu.h>
#include <linux/iopoll.h>
#include <linux/list.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of_address.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/unaligned.h>
#include "engine.h"
#include "../mt6797-vdec/mt6797-h264-controls.h"

#define DATA_SIZE SZ_128K
#define GUARD_SIZE SZ_128K
#define INPUT_DATA_SIZE SZ_1M
#define ALLOC_SIZE (DATA_SIZE + GUARD_SIZE)
#define MOTION_DATA_SIZE ALIGN(MT6797_MAX_WIDTH * MT6797_MAX_HEIGHT / 4, SZ_64K)
#define MAX_NAL MT6797_MAX_NAL_BYTES
#define PICTURE_DATA_SIZE ALIGN(MT6797_MAX_WIDTH * MT6797_MAX_HEIGHT * 3 / 2, SZ_64K)
#define PICTURE_ALLOC_SIZE (PICTURE_DATA_SIZE + DATA_SIZE)

static_assert(MT6797_MAX_WIDTH * MT6797_MAX_HEIGHT / 4 <= MOTION_DATA_SIZE);

enum bank { MISC, VLD, TOP, MC, AVC, MV, PP, BANK_COUNT };
enum memory { INPUT, PREDICTION, MOTION, VLD_WRAP, PP_WRAP, MEMORY_COUNT };

struct private_buffer {
	u8 *cpu;
	dma_addr_t dma;
	size_t bytes;
	bool device_owned;
};

struct mt6797_engine {
	struct device *dev;
	struct regmap *gcon;
	void __iomem *banks[BANK_COUNT], *larb_mmu;
	struct clk_bulk_data clocks[3];
	struct private_buffer memory[MEMORY_COUNT];
	u8 *reference_snapshot;
	struct list_head contexts;
	bool fenced;
};

struct mt6797_decode_context {
	struct mt6797_engine *engine;
	struct list_head list;
	struct private_buffer pictures[2];
	u64 timestamps[2];
	u16 frame_numbers[2];
	u16 widths[2], heights[2];
	s32 top_poc[2], bottom_poc[2];
	bool valid[2];
};

struct saved_register {
	void __iomem *address;
	u32 value;
};

struct register_save {
	struct saved_register words[64];
	unsigned int count;
};

static void write_word(u32 value, void __iomem *address)
{
	writel(value, address);
	mb();
}

static void save_word(struct register_save *save, void __iomem *address, u32 value)
{
	/* The closed fixed-size programming sequence below uses fewer than 64.
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
	return clk_bulk_prepare_enable(ARRAY_SIZE(engine->clocks), engine->clocks);
}

int mt6797_engine_suspend(struct mt6797_engine *engine)
{
	if (engine->fenced)
		return -EBUSY;
	clk_bulk_disable_unprepare(ARRAY_SIZE(engine->clocks), engine->clocks);
	return 0;
}

static void free_snapshot(void *snapshot)
{
	kvfree(snapshot);
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
	engine->reference_snapshot = kvmalloc(PICTURE_ALLOC_SIZE, GFP_KERNEL);
	if (!engine->reference_snapshot)
		return ERR_PTR(-ENOMEM);
	ret = devm_add_action_or_reset(dev, free_snapshot, engine->reference_snapshot);
	if (ret)
		return ERR_PTR(ret);
	INIT_LIST_HEAD(&engine->contexts);
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
	engine->clocks[1].id = "active";
	engine->clocks[2].id = "engine";
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
				      i == MOTION ? MOTION_DATA_SIZE + GUARD_SIZE : ALLOC_SIZE);
		if (ret)
			goto fail;
	}
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
	memset(ctx->valid, 0, sizeof(ctx->valid));
}

void mt6797_decode_context_destroy(struct mt6797_decode_context *ctx)
{
	unsigned int i;
	/* On a fatal stop failure the engine retains this independent object.
	 * It holds no frontend/file/control pointers, so file close remains safe.
	 */
	if (ctx->engine->fenced)
		return;
	list_del(&ctx->list);
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++)
		release_buffer(ctx->engine, &ctx->pictures[i]);
	kfree(ctx);
}

void mt6797_engine_destroy(struct mt6797_engine *engine)
{
	unsigned int i;
	if (WARN_ON(engine->fenced || !list_empty(&engine->contexts)))
		return;
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
			int *reference, unsigned int *output)
{
	const struct v4l2_h264_dpb_entry *entry;
	unsigned int index, active = 0;
	int retained = -1;
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
	    job->sps.max_num_ref_frames > 1 || job->slice.first_mb_in_slice ||
	    (job->sps.profile_idc != 100 &&
	     (job->pps.flags & (V4L2_H264_PPS_FLAG_TRANSFORM_8X8_MODE |
			       V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT))) ||
	    job->pps.weighted_bipred_idc || job->slice.slice_type == V4L2_H264_SLICE_TYPE_B ||
	    (!!(job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_PFRAME) !=
	     (job->slice.slice_type == V4L2_H264_SLICE_TYPE_P)) ||
	    (job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_BFRAME) ||
	    (job->nal[0] & 0x80) || ((job->nal[0] >> 5) & 3) != job->decode.nal_ref_idc ||
	    ((job->nal[0] & 31) != ((job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) ? 5 : 1)))
		return -EOPNOTSUPP;
	*reference = -1;
	*output = 0;
	if (!(job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC)) {
		for (index = 0; index < V4L2_H264_NUM_DPB_ENTRIES; index++) {
			unsigned int cached;
			entry = &job->decode.dpb[index];
			if (!(entry->flags & V4L2_H264_DPB_ENTRY_FLAG_ACTIVE))
				continue;
			if (!(entry->flags & V4L2_H264_DPB_ENTRY_FLAG_VALID))
				return -EINVAL;
			if (++active > 1)
				return -EOPNOTSUPP;
			for (cached = 0; cached < ARRAY_SIZE(ctx->pictures); cached++)
				if (ctx->valid[cached] && ctx->timestamps[cached] == entry->reference_ts) {
					retained = cached;
					break;
				}
			if (retained < 0)
				return -ENOENT;
			if (ctx->frame_numbers[retained] != entry->frame_num ||
			    ctx->widths[retained] != header->width_mbs * 16 ||
			    ctx->heights[retained] != header->height_mbs * 16 ||
			    ctx->top_poc[retained] != entry->top_field_order_cnt ||
			    ctx->bottom_poc[retained] != entry->bottom_field_order_cnt)
				return -EINVAL;
			if (job->decode.nal_ref_idc && job->timestamp == entry->reference_ts)
				return -EINVAL;
		}
	}
	if (job->slice.slice_type == V4L2_H264_SLICE_TYPE_I) {
		if (retained >= 0)
			*output = retained ^ 1;
		return 0;
	}
	if (job->slice.num_ref_idx_l0_active_minus1 || job->pps.num_ref_idx_l0_default_active_minus1)
		return -EOPNOTSUPP;
	index = job->slice.ref_pic_list0[0].index;
	if (index >= V4L2_H264_NUM_DPB_ENTRIES ||
	    job->slice.ref_pic_list0[0].fields != V4L2_H264_FRAME_REF)
		return -EINVAL;
	entry = &job->decode.dpb[index];
	if (entry->flags & V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM)
		return -EOPNOTSUPP;
	for (index = 0; index < ARRAY_SIZE(ctx->pictures); index++) {
		if (ctx->valid[index] && ctx->timestamps[index] == entry->reference_ts) {
			if (job->timestamp == entry->reference_ts)
				return -EINVAL;
			*reference = index;
			*output = index ^ 1;
			return 0;
		}
	}
	return -ENOENT;
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
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++) {
		struct private_buffer *buf = &ctx->pictures[i];
		dma_sync_single_for_device(engine->dev, buf->dma, buf->bytes, DMA_BIDIRECTIONAL);
		buf->device_owned = true;
	}
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
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++) {
		struct private_buffer *buf = &ctx->pictures[i];
		if (buf->device_owned) {
			dma_sync_single_for_cpu(engine->dev, buf->dma, buf->bytes, DMA_BIDIRECTIONAL);
			buf->device_owned = false;
		}
	}
}

static int prepare_pictures(struct mt6797_decode_context *ctx, size_t luma_size)
{
	size_t bytes = ALIGN(luma_size * 3 / 2, SZ_64K) + GUARD_SIZE;
	unsigned int i;
	int ret;

	if (bytes > PICTURE_ALLOC_SIZE)
		return -EOVERFLOW;
	if (ctx->pictures[0].cpu && ctx->pictures[1].cpu && ctx->pictures[0].bytes == bytes)
		return 0;
	/* A resized allocation cannot retain timestamps for its old storage. */
	mt6797_decode_context_reset(ctx);
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++)
		release_buffer(ctx->engine, &ctx->pictures[i]);
	for (i = 0; i < ARRAY_SIZE(ctx->pictures); i++) {
		ret = allocate_buffer(ctx->engine, &ctx->pictures[i], bytes);
		if (ret) {
			while (i)
				release_buffer(ctx->engine, &ctx->pictures[--i]);
			return ret;
		}
	}
	return 0;
}

/* Frontend calls are serialized by the mem2mem scheduler. All hardware DMA
 * addresses below belong to private allocations created before any command.
 */
int mt6797_engine_decode(struct mt6797_decode_context *ctx,
			 const struct mt6797_decode_job *job,
			 const u8 **pixels, struct mt6797_decode_status *status)
{
	static const u8 eos[] = { 0, 0, 0, 1, 0x0a };
	bool cabac = job->pps.flags & V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE;
	const u8 *ending = eos;
	size_t ending_bytes = sizeof(eos);
	struct mt6797_engine *engine = ctx->engine;
	struct mt6797_h264_header_words header;
	struct mt6797_h264_slice_words slice;
	struct mt6797_h264_p_reference_words ref_words;
	struct mt6797_h264_weight_range weights = { 0 };
	struct mt6797_h264_scaling_word scaling[MT6797_H264_SCALING_WORDS];
	struct register_save saved = { 0 };
	void __iomem *misc = engine->banks[MISC], *vld = engine->banks[VLD];
	void __iomem *top = engine->banks[TOP], *mc = engine->banks[MC];
	void __iomem *avc = engine->banks[AVC], *mv = engine->banks[MV], *pp = engine->banks[PP];
	struct private_buffer *input = &engine->memory[INPUT], *prediction = &engine->memory[PREDICTION];
	struct private_buffer *picture;
	u32 state, original_dcm, original_irq, original_break, original_gate;
	unsigned int output, remaining, i, luma_size = job->width * job->height;
	int reference, ret, stop_ret;
	bool dma_started = false;

	static_assert(ALIGN(MAX_NAL + sizeof(eos), 128) + 128 <= INPUT_DATA_SIZE);
	memset(status, 0, sizeof(*status));
	*pixels = NULL;
	if (engine->fenced)
		return -EIO;
	ret = validate_job(ctx, job, &header, &slice, &reference, &output);
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
	if (reference >= 0) {
		/* One logical hardware reference slot, independent of the private
		 * cache allocation index. Full decoder reset precedes every job.
		 */
		ret = mt6797_h264_p_reference_words(&job->decode.dpb[job->slice.ref_pic_list0[0].index],
						   0, &ref_words);
		if (ret)
			return ret;
	}
	ret = prepare_pictures(ctx, luma_size);
	if (ret)
		return ret;
	picture = &ctx->pictures[output];
	/* Overwriting storage invalidates its previous timestamp even if this
	 * attempt fails before a replacement picture can be retained.
	 */
	ctx->valid[output] = false;
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
	if (reference >= 0)
		memcpy(engine->reference_snapshot, ctx->pictures[reference].cpu,
		       ctx->pictures[reference].bytes);
	ret = pm_runtime_resume_and_get(engine->dev);
	if (ret < 0)
		return ret;
	if ((readl(engine->larb_mmu) & GENMASK(9, 0)) != GENMASK(9, 0)) {
		ret = -EIO;
		goto power;
	}
	ret = reset_whole_decoder(engine);
	if (ret)
		goto power;
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
#define SAVE(address, value) save_word(&saved, (address), (value))
	write_word(original_gate & ~BIT(0), misc + 0xf4);
	ret = reset_core(engine);
	if (ret)
		goto cleanup;
	write_word((original_irq | BIT(0)) & ~BIT(4), misc + 0xa4);
	SAVE(misc + 0xc8, 0);
	SAVE(misc + 0xcc, 0);
	SAVE(misc + 0x178, 0);
	SAVE(misc, readl(misc) & 0xff400000);
	SAVE(misc + 0xec, readl(misc + 0xec) | BIT(0));
	ret = regmap_update_bits(engine->gcon, 0x18, BIT(0), BIT(0));
	if (ret)
		goto cleanup;
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
	if (reference >= 0) {
		SAVE(mc + 0x564, 0);
		SAVE(mc + 0x3dc, lower_32_bits(ctx->pictures[reference].dma));
		SAVE(avc + 0xa8, ref_words.picture_number);
		SAVE(mv, ref_words.top);
		SAVE(mv + 4, ref_words.bottom);
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
	SAVE(mv + 0x20c, lower_32_bits(engine->memory[MOTION].dma) >> 4);
	SAVE(pp + 0x804, readl(pp + 0x804) & ~BIT(4));
	ret = readl_poll_timeout(avc + 0x25c, state, !(state & BIT(25)), 10, 100000);
	if (ret)
		goto cleanup;
	dma_wmb();
	status->submitted = true;
	write_word(1, avc + 0x238);
	/* CABAC alignment is an explicit fatal syntax error. It can stall before
	 * picture completion; stop it promptly instead of racing userspace's
	 * one-second request deadline. The trailer flag is classified below.
	 */
	ret = readl_poll_timeout(avc + 0x278, status->state,
				 (status->state & BIT(31)) || (readl(avc + 0x284) & BIT(8)),
				 100, 1000000);
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
	 * Other errors, incomplete pictures and failed DMA guards stay fatal.
	 */
	if (!ret && (status->state & BIT(31)) && cabac && status->error == BIT(14) &&
	    status->message == BIT(14) &&
	    status->mbx == header.width_mbs - 1 &&
	    status->mby == header.height_mbs - 1) {
		status->tail_bit_offset = (readl(avc + 0x84) >> 16) & 0x3f;
		remaining = (-status->tail_bit_offset) & 7;
		if (remaining)
			readl(avc + remaining * 4);
		status->tail_word = readl(avc);
		status->cabac_tail_valid = !status->tail_word ||
			status->tail_word == 1 || (status->tail_word >> 8) == 1;
	}
	if (!ret && (!(status->state & BIT(31)) ||
		     ((status->error || status->message) && !status->cabac_tail_valid) ||
		     status->mbx != header.width_mbs - 1 ||
		     status->mby != header.height_mbs - 1))
		ret = -EIO;
cleanup:
	if (dma_started) {
		write_word(original_break | BIT(0), misc + 0x100);
		status->break_result = readl_poll_timeout(misc + 0x104, state,
						      (state & 0x11) == 0x11, 10, 100000);
	}
	status->reset_result = reset_core(engine);
	status->quiesced = !status->reset_result && (!dma_started || !status->break_result);
	if (!status->quiesced) {
		engine->fenced = true;
		__module_get(THIS_MODULE);
		dev_err(engine->dev, "decoder stop failed; private DMA/power retained until reboot\n");
		return -EIO;
	}
	buffers_to_cpu(ctx);
	dma_rmb();
	status->guards_unchanged = !memcmp(input->cpu, job->nal, job->bytes) &&
		!memcmp(input->cpu + job->bytes, ending, ending_bytes) &&
		!memchr_inv(input->cpu + job->bytes + ending_bytes, 0,
			    INPUT_DATA_SIZE - job->bytes - ending_bytes) &&
		!memchr_inv(input->cpu + INPUT_DATA_SIZE, 0xa5, GUARD_SIZE) &&
		!memchr_inv(picture->cpu + luma_size * 3 / 2, 0xd3,
			    picture->bytes - luma_size * 3 / 2);
	for (i = PREDICTION; i < MEMORY_COUNT; i++)
		if (memchr_inv(engine->memory[i].cpu + engine->memory[i].bytes - GUARD_SIZE,
				0xd3, GUARD_SIZE))
			status->guards_unchanged = false;
	if (reference >= 0 && memcmp(ctx->pictures[reference].cpu, engine->reference_snapshot,
			      ctx->pictures[reference].bytes))
		status->guards_unchanged = false;
	if (!status->guards_unchanged) {
		mt6797_decode_context_reset(ctx);
		ret = -EIO;
	}
	if (status->submitted) {
		state = readl(misc + 0xa4);
		write_word(state | 0x11, misc + 0xa4);
		write_word((state | BIT(0)) & ~BIT(4), misc + 0xa4);
	}
	restore_words(&saved);
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
		if (job->decode.flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC)
			mt6797_decode_context_reset(ctx);
		ctx->timestamps[output] = job->timestamp;
		ctx->frame_numbers[output] = job->decode.frame_num;
		ctx->widths[output] = header.width_mbs * 16;
		ctx->heights[output] = header.height_mbs * 16;
		ctx->top_poc[output] = job->decode.top_field_order_cnt;
		ctx->bottom_poc[output] = job->decode.bottom_field_order_cnt;
		ctx->valid[output] = job->decode.nal_ref_idc != 0;
		*pixels = picture->cpu;
	}
	return ret;
}
