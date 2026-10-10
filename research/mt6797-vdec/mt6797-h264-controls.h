/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT6797_H264_CONTROLS_H
#define MT6797_H264_CONTROLS_H

#include <linux/v4l2-controls.h>

/* Common H.264 control words identified in the public MT8173 test interface.
 * No DMA, register access or video device is exposed by this prototype.
 * DMA setup, reference programming and actual slice submission remain.
 */
struct mt6797_h264_header_words {
	__u32 sps;             /* AVC_VLD + 0x88 */
	__u32 pps;             /* AVC_VLD + 0x90 */
	__u32 reference_counts; /* AVC_VLD + 0x94 */
	__u32 width_mbs;
	__u32 height_mbs;
};

/* Reject unsupported controls before changing output. Scaling SRAM must be
 * programmed separately when SCALING_MATRIX_PRESENT is set.
 */
int mt6797_h264_header_words(const struct v4l2_ctrl_h264_sps *sps,
			    const struct v4l2_ctrl_h264_pps *pps,
			    struct mt6797_h264_header_words *output);

struct mt6797_h264_slice_words {
	__u32 first_mb; /* AVC_VLD + 0x8c, low field; preserve other bits */
	__u32 header1;  /* AVC_VLD + 0x98, high field; preserve bits 0..12 */
	__u32 header2;  /* AVC_VLD + 0x9c */
};

/* Progressive I/P/B headers only. Payload bytes include the NAL header;
 * header_bit_size is the public V4L2 offset to slice_data(). No parsing,
 * bitstream barrel shifting, reference mapping or register writes occur.
 */
int mt6797_h264_slice_words(const struct v4l2_ctrl_h264_sps *sps,
			   const struct v4l2_ctrl_h264_pps *pps,
			   const struct v4l2_ctrl_h264_slice_params *slice,
			   const struct v4l2_ctrl_h264_decode_params *decode,
			   __u32 payload_bytes,
			   struct mt6797_h264_slice_words *output);

#define MT6797_H264_SCALING_WORDS 56
struct mt6797_h264_p_reference_words {
	__u32 picture_number; /* AVC_VLD + 0xa8 + slot * 4 */
	__u32 top;            /* AVC_MV + slot * 8 */
	__u32 bottom;         /* AVC_MV + slot * 8 + 4 */
};

/* Progressive frame reference metadata from the public related-core map.
 * The caller separately resolves reference_ts to a live capture buffer and
 * writes its full DMA address to MC + 0x3dc + slot * 4. No address, lifetime,
 * timestamp resolution or MMIO is handled here. MT6797 execution is pending.
 */
int mt6797_h264_p_reference_words(const struct v4l2_h264_dpb_entry *entry,
				unsigned int frame_buffer_index,
				struct mt6797_h264_p_reference_words *output);

struct mt6797_h264_scaling_word {
	__u32 location;
	__u32 coefficients;
};

/* Six 4x4 and two luma 8x8 matrices for 4:2:0, in Linux raster order.
 * For each word the candidate VLD SRAM protocol is:
 * write 0x260 = 0x200 + location; write 0x264 = coefficients;
 * write 0x260 = 0x100 + location. Hardware execution remains separate.
 */
int mt6797_h264_scaling_words(const struct v4l2_ctrl_h264_scaling_matrix *matrix,
			     struct mt6797_h264_scaling_word output[MT6797_H264_SCALING_WORDS]);

#endif
