/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT6797_VDEC_ENGINE_H
#define MT6797_VDEC_ENGINE_H

#include <linux/platform_device.h>
#include <linux/v4l2-controls.h>

struct mt6797_engine;
struct mt6797_decode_context;

/* Initial hardware boundary: progressive Baseline, one slice and one
 * short-term reference, bounded small pictures. This is original code, not firmware.
 */
struct mt6797_decode_job {
	struct v4l2_ctrl_h264_sps sps;
	struct v4l2_ctrl_h264_pps pps;
	struct v4l2_ctrl_h264_slice_params slice;
	struct v4l2_ctrl_h264_decode_params decode;
	const u8 *nal;
	size_t bytes;
	u64 timestamp;
	u16 width, height;
};

struct mt6797_decode_status {
	u32 state, error, message, irq;
	int break_result, reset_result;
	bool fetched, submitted, quiesced, guards_unchanged;
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
