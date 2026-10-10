/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT6797_H264_CONTROLS_H
#define MT6797_H264_CONTROLS_H

#include <linux/v4l2-controls.h>

/* Common H.264 control words identified in the public MT8173 test interface.
 * No DMA, register access or video device is exposed by this prototype.
 * The V4L2 backend handles private DMA, register access and slice submission.
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
#define MT6797_H264_PICTURE_SLOTS (V4L2_H264_NUM_DPB_ENTRIES + 1)

struct mt6797_h264_cached_picture {
	__u64 timestamp;
	__s32 top_poc, bottom_poc;
	__u16 frame_number, width, height;
	__u8 allocated, valid;
};

struct mt6797_h264_reference_plan {
	__u32 protected_mask, snapshot_mask, long_term_mask;
	__u8 output, count, count1, list0[V4L2_H264_NUM_DPB_ENTRIES];
	__u8 list1[V4L2_H264_NUM_DPB_ENTRIES];
};

/* Resolve public active DPB entries to private metadata and choose an output
 * outside every retained active reference. Repeated list entries are legal.
 * No cache mutation, allocation, MMIO or DMA; output is atomic on rejection.
 */
int mt6797_h264_reference_plan(const struct v4l2_ctrl_h264_sps *sps,
			      const struct v4l2_ctrl_h264_slice_params *slice,
			      const struct v4l2_ctrl_h264_decode_params *decode,
			      const struct mt6797_h264_cached_picture cache[MT6797_H264_PICTURE_SLOTS],
			      __u64 timestamp, struct mt6797_h264_reference_plan *output);

struct mt6797_h264_p_reference_words {
	__u32 picture_number; /* AVC_VLD + 0xa8 + slot * 4 */
	__u32 top;            /* AVC_MV + slot * 8 */
	__u32 bottom;         /* AVC_MV + slot * 8 + 4 */
};

/* Validate full progressive POC metadata without narrowing it to the
 * hardware field. Type0 also checks the signaled LSB and bottom-field delta.
 */
int mt6797_h264_picture_poc(const struct v4l2_ctrl_h264_sps *sps,
			   const struct v4l2_ctrl_h264_pps *pps,
			   const struct v4l2_ctrl_h264_decode_params *decode);

/* Progressive frame reference metadata from the public related-core map.
 * The caller separately resolves reference_ts to a live capture buffer and
 * writes its full DMA address to MC + 0x3dc + slot * 4. No address, lifetime,
 * timestamp resolution or MMIO is handled here.
 */
int mt6797_h264_p_reference_words(const struct v4l2_h264_dpb_entry *entry,
				unsigned int frame_buffer_index,
				struct mt6797_h264_p_reference_words *output);

/* Progressive B metadata adds the low18 POC bits to the P identity words,
 * following the public related-core helper; full POCs remain in the cache.
 * B1 separately binds each reference's retained motion address (16byte units).
 */
int mt6797_h264_b_reference_words(const struct v4l2_h264_dpb_entry *entry,
                                unsigned int frame_buffer_index,
                                struct mt6797_h264_p_reference_words *output);

struct mt6797_h264_scaling_word {
	__u32 location;
	__u32 coefficients;
};

/* Six 4x4 and two luma 8x8 matrices for 4:2:0, in Linux raster order.
 * For each word the candidate VLD SRAM protocol is:
 * Common VLD bank: write 0x260 = 0x200 + location; write 0x264 = coefficients;
 * write 0x260 = 0x100 + location. Hardware execution remains separate.
 */
int mt6797_h264_scaling_words(const struct v4l2_ctrl_h264_scaling_matrix *matrix,
			     struct mt6797_h264_scaling_word output[MT6797_H264_SCALING_WORDS]);

struct mt6797_h264_weight_range {
	__u32 start, end; /* RBSP bits from the beginning of the NAL header. */
	__u32 start_word, start_mask, end_word, end_mask;
};

/* Locate a progressive P or explicit B prediction table with up to16 entries per list and verify its
 * values and complete slice header against the public stateless controls.
 * Emulation-prevention bytes do not count as RBSP bits. No MMIO or DMA.
 * A rejected header leaves output unchanged.
 */
int mt6797_h264_weight_range(const struct v4l2_ctrl_h264_sps *sps,
			    const struct v4l2_ctrl_h264_pps *pps,
			    const struct v4l2_ctrl_h264_slice_params *slice,
			    const struct v4l2_ctrl_h264_decode_params *decode,
			    const struct v4l2_ctrl_h264_pred_weights *weights,
			    const __u8 *nal, __u32 bytes,
			    struct mt6797_h264_weight_range *output);

#endif
