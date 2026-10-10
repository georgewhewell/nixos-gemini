/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT6797_VDEC_ENGINE_H
#define MT6797_VDEC_ENGINE_H

#include <linux/platform_device.h>
#include <linux/v4l2-controls.h>

#define MT6797_MAX_WIDTH 1920U
#define MT6797_MAX_HEIGHT 1088U
#define MT6797_MAX_NAL_BYTES (1024U * 1024U - 256U)

struct mt6797_engine;
struct mt6797_decode_context;

/* Hardware boundary: progressive 8-bit 4:2:0, one I/P slice and one
 * short-term reference. This is original code, not firmware.
 */
struct mt6797_decode_job {
	struct v4l2_ctrl_h264_sps sps;
	struct v4l2_ctrl_h264_pps pps;
	struct v4l2_ctrl_h264_scaling_matrix scaling;
	struct v4l2_ctrl_h264_pred_weights weights;
	struct v4l2_ctrl_h264_slice_params slice;
	struct v4l2_ctrl_h264_decode_params decode;
	const u8 *nal;
	size_t bytes;
	u64 timestamp;
	/* Negotiated storage dimensions; coded dimensions come from the SPS. */
	u16 width, height;
};

struct mt6797_decode_status {
	u32 state, error, message, irq;
	u32 mbx, mby, stall, read_pointer, fetch_status, top_status;
	u32 pred_config, pred_mode, nal_bytes, header_bits;
	u32 tail_bit_offset, tail_word;
	u32 weight_start, weight_end, weight_before, weight_after, weight_state;
	u32 weight_before_word, weight_after_word, weight_start_mask, weight_end_mask;
	u64 elapsed_us;
	int engine_result;
	int break_result, reset_result;
	bool fetched, submitted, quiesced, guards_unchanged;
	bool cabac_tail_valid;
};

struct mt6797_engine *mt6797_engine_create(struct platform_device *pdev);
void mt6797_engine_destroy(struct mt6797_engine *engine);
int mt6797_engine_resume(struct mt6797_engine *engine);
int mt6797_engine_suspend(struct mt6797_engine *engine);
struct mt6797_decode_context *mt6797_decode_context_create(struct mt6797_engine *engine);
void mt6797_decode_context_destroy(struct mt6797_decode_context *ctx);
void mt6797_decode_context_reset(struct mt6797_decode_context *ctx);
int mt6797_engine_decode(struct mt6797_decode_context *ctx,
			 const struct mt6797_decode_job *job,
			 const u8 **pixels, struct mt6797_decode_status *status);

#endif
