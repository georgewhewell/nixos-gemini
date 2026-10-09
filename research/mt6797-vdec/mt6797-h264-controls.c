/* SPDX-License-Identifier: GPL-2.0-only */
#include <linux/errno.h>
#include "mt6797-h264-controls.h"

/* Hardware field positions are recorded in mt6797-video-interface.json.
 * This implementation consumes Linux's public stateless controls directly.
 */
static __u32 flag(__u32 flags, __u32 input_mask, unsigned int shift)
{
	return (__u32)!!(flags & input_mask) << shift;
}

int mt6797_h264_header_words(const struct v4l2_ctrl_h264_sps *sps,
			    const struct v4l2_ctrl_h264_pps *pps,
			    struct mt6797_h264_header_words *output)
{
	struct mt6797_h264_header_words words = { 0 };
	const __u32 sps_flags = V4L2_H264_SPS_FLAG_DELTA_PIC_ORDER_ALWAYS_ZERO |
		V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY |
		V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE;
	const __u32 pps_flags = V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE |
		V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT |
		V4L2_H264_PPS_FLAG_WEIGHTED_PRED |
		V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT |
		V4L2_H264_PPS_FLAG_CONSTRAINED_INTRA_PRED |
		V4L2_H264_PPS_FLAG_TRANSFORM_8X8_MODE |
		V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT;

	if (!sps || !pps || !output)
		return -EINVAL;
	if (pps->seq_parameter_set_id != sps->seq_parameter_set_id ||
	    sps->seq_parameter_set_id > 31 ||
	    sps->log2_max_frame_num_minus4 > 12 ||
	    sps->pic_order_cnt_type > 2 ||
	    sps->log2_max_pic_order_cnt_lsb_minus4 > 12 ||
	    sps->max_num_ref_frames > V4L2_H264_NUM_DPB_ENTRIES ||
	    pps->num_ref_idx_l0_default_active_minus1 > 15 ||
	    pps->num_ref_idx_l1_default_active_minus1 > 15 ||
	    pps->weighted_bipred_idc > 2 ||
	    pps->pic_init_qp_minus26 < -26 || pps->pic_init_qp_minus26 > 25 ||
	    pps->pic_init_qs_minus26 < -26 || pps->pic_init_qs_minus26 > 25 ||
	    pps->chroma_qp_index_offset < -12 || pps->chroma_qp_index_offset > 12 ||
	    pps->second_chroma_qp_index_offset < -12 ||
	    pps->second_chroma_qp_index_offset > 12)
		return -EINVAL;
	/* Progressive 8-bit 4:2:0 is the initial implementation boundary.
	 * Never truncate an unsupported dimension or control into a register.
	 */
	if (sps->chroma_format_idc != 1 || sps->bit_depth_luma_minus8 ||
	    sps->bit_depth_chroma_minus8 ||
	    !(sps->flags & V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY) ||
	    (sps->flags & ~sps_flags) || (pps->flags & ~pps_flags) ||
	    pps->num_slice_groups_minus1 ||
	    (sps->profile_idc != 66 && sps->profile_idc != 77 && sps->profile_idc != 100) ||
	    sps->pic_width_in_mbs_minus1 > 255 ||
	    sps->pic_height_in_map_units_minus1 > 134)
		return -EOPNOTSUPP;

	words.width_mbs = (__u32)sps->pic_width_in_mbs_minus1 + 1;
	words.height_mbs = (__u32)sps->pic_height_in_map_units_minus1 + 1;
	words.sps = sps->chroma_format_idc |
		(__u32)sps->log2_max_frame_num_minus4 << 2 |
		(__u32)sps->pic_order_cnt_type << 6 |
		(__u32)sps->log2_max_pic_order_cnt_lsb_minus4 << 8 |
		flag(sps->flags, V4L2_H264_SPS_FLAG_DELTA_PIC_ORDER_ALWAYS_ZERO, 12) |
		(__u32)sps->max_num_ref_frames << 13 |
		flag(sps->flags, V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY, 18) |
		flag(sps->flags, V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE, 20) |
		(1U << 21);
	words.pps = flag(pps->flags, V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE, 0) |
		flag(pps->flags, V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT, 1) |
		flag(pps->flags, V4L2_H264_PPS_FLAG_WEIGHTED_PRED, 2) |
		(__u32)pps->weighted_bipred_idc << 3 |
		((__u32)pps->pic_init_qp_minus26 & 0x3f) << 5 |
		((__u32)pps->chroma_qp_index_offset & 0x1f) << 11 |
		flag(pps->flags, V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT, 16) |
		flag(pps->flags, V4L2_H264_PPS_FLAG_CONSTRAINED_INTRA_PRED, 17) |
		flag(pps->flags, V4L2_H264_PPS_FLAG_TRANSFORM_8X8_MODE, 18) |
		((__u32)pps->second_chroma_qp_index_offset & 0x1f) << 19;
	words.reference_counts = pps->num_ref_idx_l0_default_active_minus1 |
		(__u32)pps->num_ref_idx_l1_default_active_minus1 << 5;
	if (pps->flags & V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT)
		words.reference_counts |= (0xffU << 10) | (1U << 18);
	*output = words;
	return 0;
}

int mt6797_h264_slice_words(const struct v4l2_ctrl_h264_sps *sps,
			   const struct v4l2_ctrl_h264_pps *pps,
			   const struct v4l2_ctrl_h264_slice_params *slice,
			   const struct v4l2_ctrl_h264_decode_params *decode,
			   __u32 payload_bytes,
			   struct mt6797_h264_slice_words *output)
{
	struct mt6797_h264_header_words header;
	struct mt6797_h264_slice_words words = { 0 };
	const __u32 decode_flags = V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC |
		V4L2_H264_DECODE_PARAM_FLAG_PFRAME | V4L2_H264_DECODE_PARAM_FLAG_BFRAME;
	int ret, qp;

	if (!slice || !decode || !output)
		return -EINVAL;
	ret = mt6797_h264_header_words(sps, pps, &header);
	if (ret)
		return ret;
	qp = 26 + pps->pic_init_qp_minus26 + slice->slice_qp_delta;
	if (slice->reserved || decode->reserved ||
	    slice->first_mb_in_slice >= header.width_mbs * header.height_mbs ||
	    slice->header_bit_size < 8 ||
	    (__u64)slice->header_bit_size > (__u64)payload_bytes * 8 ||
	    slice->cabac_init_idc > 2 ||
	    slice->disable_deblocking_filter_idc > 2 || qp < 0 || qp > 51 ||
	    slice->slice_alpha_c0_offset_div2 < -6 ||
	    slice->slice_alpha_c0_offset_div2 > 6 ||
	    slice->slice_beta_offset_div2 < -6 || slice->slice_beta_offset_div2 > 6 ||
	    slice->num_ref_idx_l0_active_minus1 > 15 ||
	    slice->num_ref_idx_l1_active_minus1 > 15 || decode->nal_ref_idc > 3 ||
	    decode->frame_num >= (1U << (sps->log2_max_frame_num_minus4 + 4)) ||
	    (sps->pic_order_cnt_type == 0 && decode->pic_order_cnt_lsb >=
		(1U << (sps->log2_max_pic_order_cnt_lsb_minus4 + 4))) ||
	    ((decode->flags & V4L2_H264_DECODE_PARAM_FLAG_PFRAME) &&
	     (decode->flags & V4L2_H264_DECODE_PARAM_FLAG_BFRAME)) ||
	    ((decode->flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) &&
	     (slice->slice_type != V4L2_H264_SLICE_TYPE_I || !decode->nal_ref_idc)))
		return -EINVAL;
	/* The public test interface only exercises a 13-bit first-MB value.
	 * Qualify the wider candidate field before using it for large slices.
	 */
	if (slice->first_mb_in_slice > 0x1fff ||
	    slice->slice_type > V4L2_H264_SLICE_TYPE_I || slice->colour_plane_id ||
	    slice->redundant_pic_cnt || slice->slice_qs_delta ||
	    (slice->flags & ~V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED) ||
	    (decode->flags & ~decode_flags) || decode->slice_group_change_cycle)
		return -EOPNOTSUPP;
	words.first_mb = slice->first_mb_in_slice;
	words.header1 = (__u32)slice->slice_type << 13 |
		flag(slice->flags, V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED, 19) |
		(__u32)slice->num_ref_idx_l0_active_minus1 << 20 |
		(__u32)slice->num_ref_idx_l1_active_minus1 << 25;
	words.header2 = ((__u32)slice->slice_qp_delta & 0x7f) |
		(__u32)slice->disable_deblocking_filter_idc << 7 |
		((__u32)slice->slice_alpha_c0_offset_div2 & 0xf) << 9 |
		((__u32)slice->slice_beta_offset_div2 & 0xf) << 13 |
		(__u32)decode->nal_ref_idc << 17 |
		flag(decode->flags, V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC, 19) |
		(__u32)slice->cabac_init_idc << 20;
	*output = words;
	return 0;
}

int mt6797_h264_scaling_words(const struct v4l2_ctrl_h264_scaling_matrix *matrix,
			     struct mt6797_h264_scaling_word output[MT6797_H264_SCALING_WORDS])
{
	unsigned int list, i, count = 0;

	if (!matrix || !output)
		return -EINVAL;
	/* Validate every consumed coefficient before changing any output. */
	for (list = 0; list < 8; list++) {
		const __u8 *coeff = list < 6 ? matrix->scaling_list_4x4[list] :
			matrix->scaling_list_8x8[list - 6];
		unsigned int size = list < 6 ? 16 : 64;

		for (i = 0; i < size; i++)
			if (!coeff[i])
				return -EINVAL;
	}
	for (list = 0; list < 8; list++) {
		const __u8 *coeff = list < 6 ? matrix->scaling_list_4x4[list] :
			matrix->scaling_list_8x8[list - 6];
		unsigned int size = list < 6 ? 16 : 64;
		unsigned int location = list < 6 ? list * 16 : 96 + (list - 6) * 64;

		for (i = 0; i < size; i += 4) {
			output[count].location = location + i;
			output[count].coefficients = (__u32)coeff[i] << 24 |
				(__u32)coeff[i + 1] << 16 | (__u32)coeff[i + 2] << 8 |
				coeff[i + 3];
			count++;
		}
	}
	return 0;
}
