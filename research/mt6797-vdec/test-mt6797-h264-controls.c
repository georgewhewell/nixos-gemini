/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <linux/errno.h>
#include <stdio.h>
#include <string.h>
#include "mt6797-h264-controls.h"

static struct v4l2_ctrl_h264_sps valid_sps(void)
{
	return (struct v4l2_ctrl_h264_sps) {
		.profile_idc = 66, .chroma_format_idc = 1,
		.max_num_ref_frames = 1,
		.pic_width_in_mbs_minus1 = 3,
		.pic_height_in_map_units_minus1 = 3,
		.flags = V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY |
			 V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE,
	};
}

static void reject(struct v4l2_ctrl_h264_sps sps,
		   struct v4l2_ctrl_h264_pps pps, int expected)
{
	struct mt6797_h264_header_words result, unchanged;
	memset(&result, 0xa5, sizeof(result));
	unchanged = result;
	assert(mt6797_h264_header_words(&sps, &pps, &result) == expected);
	assert(!memcmp(&result, &unchanged, sizeof(result)));
}

#define BAD_SPS(member, value, error) do { \
	struct v4l2_ctrl_h264_sps bad = sps; bad.member = value; \
	reject(bad, pps, error); \
} while (0)
#define BAD_PPS(member, value, error) do { \
	struct v4l2_ctrl_h264_pps bad = pps; bad.member = value; \
	reject(sps, bad, error); \
} while (0)

static void reject_slice(struct v4l2_ctrl_h264_sps sps,
			 struct v4l2_ctrl_h264_pps pps,
			 struct v4l2_ctrl_h264_slice_params slice,
			 struct v4l2_ctrl_h264_decode_params decode,
			 __u32 bytes, int expected)
{
	struct mt6797_h264_slice_words output, saved;
	memset(&output, 0x5a, sizeof(output));
	saved = output;
	assert(mt6797_h264_slice_words(&sps, &pps, &slice, &decode, bytes,
		&output) == expected);
	assert(!memcmp(&output, &saved, sizeof(output)));
}

#define BAD_SLICE(member, value, error) do { \
	struct v4l2_ctrl_h264_slice_params bad = slice; bad.member = value; \
	reject_slice(sps, pps, bad, decode, 64, error); \
} while (0)
#define BAD_DECODE(member, value, error) do { \
	struct v4l2_ctrl_h264_decode_params bad = decode; bad.member = value; \
	reject_slice(sps, pps, slice, bad, 64, error); \
} while (0)

static void test_p_references(void)
{
	struct v4l2_h264_dpb_entry entry = {
		.fields = V4L2_H264_FRAME_REF,
		.flags = V4L2_H264_DPB_ENTRY_FLAG_VALID | V4L2_H264_DPB_ENTRY_FLAG_ACTIVE,
	};
	struct mt6797_h264_p_reference_words output, saved;

	assert(!mt6797_h264_p_reference_words(&entry, 0, &output));
	assert(output.picture_number == 0 && output.top == 0x200000 &&
		output.bottom == 0x600000);
	entry.pic_num = (__u32)-1;
	assert(!mt6797_h264_p_reference_words(&entry, 1, &output));
	assert(output.picture_number == 0x7ffff && output.top == 0xa00000 &&
		output.bottom == 0xe00000);
	entry.flags |= V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
	entry.pic_num = 0x7ffff;
	entry.top_field_order_cnt = 4;
	entry.bottom_field_order_cnt = 2;
	assert(!mt6797_h264_p_reference_words(&entry, 15, &output));
	assert(output.picture_number == 0xfffff && output.top == 0x7900000 &&
		output.bottom == 0x7d00000);

	/* No rejected metadata may replace previously prepared reference words. */
	saved = output;
#define BAD_REF(member, value, error) do { \
	struct v4l2_h264_dpb_entry bad = entry; bad.member = value; \
	assert(mt6797_h264_p_reference_words(&bad, 0, &output) == error); \
	assert(!memcmp(&output, &saved, sizeof(output))); \
} while (0)
	BAD_REF(pic_num, 0x80000, -ERANGE);
	BAD_REF(pic_num, (__u32)-1, -ERANGE);
	BAD_REF(flags, V4L2_H264_DPB_ENTRY_FLAG_VALID, -EINVAL);
	BAD_REF(flags, entry.flags | V4L2_H264_DPB_ENTRY_FLAG_FIELD, -EOPNOTSUPP);
	BAD_REF(fields, V4L2_H264_TOP_FIELD_REF, -EOPNOTSUPP);
	BAD_REF(reserved[4], 1, -EINVAL);
	BAD_REF(top_field_order_cnt, 0x7fffffff, -EINVAL);
	BAD_REF(bottom_field_order_cnt, 0x7fffffff, -EINVAL);
	entry.flags &= ~V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
	BAD_REF(pic_num, 262144, -ERANGE);
	BAD_REF(pic_num, (__u32)-262145, -ERANGE);
	assert(mt6797_h264_p_reference_words(&entry, 16, &output) == -EINVAL);
	assert(mt6797_h264_p_reference_words(NULL, 0, &output) == -EINVAL);
	assert(mt6797_h264_p_reference_words(&entry, 0, NULL) == -EINVAL);
	assert(!memcmp(&output, &saved, sizeof(output)));
#undef BAD_REF
}

static void test_slices(void)
{
	struct v4l2_ctrl_h264_sps sps = valid_sps();
	struct v4l2_ctrl_h264_pps pps = { 0 };
	struct v4l2_ctrl_h264_slice_params slice = {
		.slice_type = V4L2_H264_SLICE_TYPE_I, .header_bit_size = 16,
	};
	struct v4l2_ctrl_h264_decode_params decode = {
		.nal_ref_idc = 3, .flags = V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC,
	};
	struct mt6797_h264_slice_words output;

	assert(!mt6797_h264_slice_words(&sps, &pps, &slice, &decode, 64, &output));
	assert(output.first_mb == 0 && output.header1 == 0x4000 &&
		output.header2 == 0xe0000);
	BAD_SLICE(first_mb_in_slice, 16, -EINVAL);
	BAD_SLICE(header_bit_size, 513, -EINVAL);
	BAD_SLICE(header_bit_size, 7, -EINVAL);
	BAD_SLICE(slice_qp_delta, -27, -EINVAL);
	BAD_SLICE(slice_qp_delta, 26, -EINVAL);
	BAD_SLICE(slice_alpha_c0_offset_div2, -7, -EINVAL);
	BAD_SLICE(slice_beta_offset_div2, 7, -EINVAL);
	BAD_SLICE(cabac_init_idc, 3, -EINVAL);
	BAD_SLICE(disable_deblocking_filter_idc, 3, -EINVAL);
	BAD_SLICE(num_ref_idx_l0_active_minus1, 16, -EINVAL);
	BAD_SLICE(num_ref_idx_l1_active_minus1, 16, -EINVAL);
	BAD_SLICE(reserved, 1, -EINVAL);
	BAD_SLICE(slice_type, V4L2_H264_SLICE_TYPE_P, -EINVAL);
	BAD_SLICE(colour_plane_id, 1, -EOPNOTSUPP);
	BAD_SLICE(redundant_pic_cnt, 1, -EOPNOTSUPP);
	BAD_SLICE(slice_qs_delta, 1, -EOPNOTSUPP);
	BAD_SLICE(flags, V4L2_H264_SLICE_FLAG_SP_FOR_SWITCH, -EOPNOTSUPP);
	BAD_DECODE(nal_ref_idc, 4, -EINVAL);
	BAD_DECODE(nal_ref_idc, 0, -EINVAL);
	BAD_DECODE(frame_num, 16, -EINVAL);
	BAD_DECODE(pic_order_cnt_lsb, 16, -EINVAL);
	BAD_DECODE(reserved, 1, -EINVAL);
	BAD_DECODE(flags, V4L2_H264_DECODE_PARAM_FLAG_FIELD_PIC, -EOPNOTSUPP);
	BAD_DECODE(flags, V4L2_H264_DECODE_PARAM_FLAG_PFRAME |
		V4L2_H264_DECODE_PARAM_FLAG_BFRAME, -EINVAL);
	BAD_DECODE(slice_group_change_cycle, 1, -EOPNOTSUPP);
	reject_slice(sps, pps, slice, decode, 0, -EINVAL);
	assert(mt6797_h264_slice_words(&sps, &pps, NULL, &decode, 64, &output) == -EINVAL);
	assert(mt6797_h264_slice_words(&sps, &pps, &slice, NULL, 64, &output) == -EINVAL);
	assert(mt6797_h264_slice_words(&sps, &pps, &slice, &decode, 64, NULL) == -EINVAL);

	sps.profile_idc = 77;
	pps.flags = V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE;
	slice.first_mb_in_slice = 7;
	slice.slice_type = V4L2_H264_SLICE_TYPE_B;
	slice.flags = V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED;
	slice.num_ref_idx_l0_active_minus1 = slice.num_ref_idx_l1_active_minus1 = 15;
	slice.slice_qp_delta = -26;
	slice.disable_deblocking_filter_idc = 2;
	slice.slice_alpha_c0_offset_div2 = -6;
	slice.slice_beta_offset_div2 = 6;
	slice.cabac_init_idc = 2;
	decode.flags = V4L2_H264_DECODE_PARAM_FLAG_BFRAME;
	assert(!mt6797_h264_slice_words(&sps, &pps, &slice, &decode, 64, &output));
	assert(output.first_mb == 7 && output.header1 == 0x1ef82000 &&
		output.header2 == 0x26d566);
	BAD_SLICE(slice_type, V4L2_H264_SLICE_TYPE_SP, -EOPNOTSUPP);

	sps.pic_width_in_mbs_minus1 = 255;
	sps.pic_height_in_map_units_minus1 = 31;
	slice.first_mb_in_slice = 8191;
	assert(!mt6797_h264_slice_words(&sps, &pps, &slice, &decode, 64, &output));
	assert(output.first_mb == 8191);
	sps.pic_height_in_map_units_minus1 = 32;
	BAD_SLICE(first_mb_in_slice, 8192, -EOPNOTSUPP);
	slice.header_bit_size = 0xffffffffU;
	assert(!mt6797_h264_slice_words(&sps, &pps, &slice, &decode, 0xffffffffU, &output));
}

static void test_scaling(void)
{
	struct v4l2_ctrl_h264_scaling_matrix matrix = { 0 };
	struct mt6797_h264_scaling_word output[MT6797_H264_SCALING_WORDS], saved[MT6797_H264_SCALING_WORDS];
	unsigned int list, i;

	for (list = 0; list < 6; list++)
		for (i = 0; i < 16; i++)
			matrix.scaling_list_4x4[list][i] = list * 16 + i + 1;
	for (list = 0; list < 2; list++)
		for (i = 0; i < 64; i++)
			matrix.scaling_list_8x8[list][i] = 101 + list * 64 + i;
	assert(!mt6797_h264_scaling_words(&matrix, output));
	assert(output[0].location == 0 && output[0].coefficients == 0x01020304);
	assert(output[23].location == 92 && output[23].coefficients == 0x5d5e5f60);
	assert(output[24].location == 96 && output[24].coefficients == 0x65666768);
	assert(output[40].location == 160 && output[40].coefficients == 0xa5a6a7a8);
	assert(output[55].location == 220 && output[55].coefficients == 0xe1e2e3e4);
	/* Verify contiguous SRAM coverage with no duplicate locations. */
	for (i = 0; i < MT6797_H264_SCALING_WORDS; i++)
		assert(output[i].location == i * 4);
	memcpy(saved, output, sizeof(saved));
	/* A zero at the final coefficient must reject the entire operation. */
	matrix.scaling_list_8x8[1][63] = 0;
	assert(mt6797_h264_scaling_words(&matrix, output) == -EINVAL);
	assert(!memcmp(saved, output, sizeof(saved)));
	assert(mt6797_h264_scaling_words(NULL, output) == -EINVAL);
	assert(mt6797_h264_scaling_words(&matrix, NULL) == -EINVAL);
}

int main(void)
{
	struct v4l2_ctrl_h264_sps sps = valid_sps();
	struct v4l2_ctrl_h264_pps pps = {
		.flags = V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT,
	};
	struct mt6797_h264_header_words result;
	int qp;

	assert(!mt6797_h264_header_words(&sps, &pps, &result));
	assert(result.sps == 0x00342001 && result.pps == 0x00010000);
	assert(result.reference_counts == 0);
	assert(result.width_mbs == 4 && result.height_mbs == 4);
	for (qp = -26; qp <= 25; qp++) {
		int decoded;
		pps.pic_init_qp_minus26 = qp;
		assert(!mt6797_h264_header_words(&sps, &pps, &result));
		decoded = (result.pps >> 5) & 63;
		if (decoded >= 32) decoded -= 64;
		assert(decoded == qp);
		assert((result.pps & ~0x7e0U) == 0x00010000);
	}
	pps.pic_init_qp_minus26 = 0;

	BAD_SPS(log2_max_frame_num_minus4, 13, -EINVAL);
	BAD_SPS(pic_order_cnt_type, 3, -EINVAL);
	BAD_SPS(log2_max_pic_order_cnt_lsb_minus4, 13, -EINVAL);
	BAD_SPS(max_num_ref_frames, 17, -EINVAL);
	BAD_SPS(seq_parameter_set_id, 32, -EINVAL);
	BAD_SPS(chroma_format_idc, 2, -EOPNOTSUPP);
	BAD_SPS(bit_depth_luma_minus8, 2, -EOPNOTSUPP);
	BAD_SPS(bit_depth_chroma_minus8, 2, -EOPNOTSUPP);
	BAD_SPS(profile_idc, 244, -EOPNOTSUPP);
	BAD_SPS(flags, 0, -EOPNOTSUPP);
	BAD_SPS(flags, sps.flags | V4L2_H264_SPS_FLAG_MB_ADAPTIVE_FRAME_FIELD, -EOPNOTSUPP);
	BAD_SPS(flags, sps.flags | 0x80000000U, -EOPNOTSUPP);
	BAD_SPS(pic_width_in_mbs_minus1, 256, -EOPNOTSUPP);
	BAD_SPS(pic_height_in_map_units_minus1, 135, -EOPNOTSUPP);
	BAD_PPS(seq_parameter_set_id, 1, -EINVAL);
	BAD_PPS(num_ref_idx_l0_default_active_minus1, 16, -EINVAL);
	BAD_PPS(num_ref_idx_l1_default_active_minus1, 16, -EINVAL);
	BAD_PPS(weighted_bipred_idc, 3, -EINVAL);
	BAD_PPS(pic_init_qp_minus26, -27, -EINVAL);
	BAD_PPS(pic_init_qp_minus26, 26, -EINVAL);
	BAD_PPS(pic_init_qs_minus26, -27, -EINVAL);
	BAD_PPS(pic_init_qs_minus26, 26, -EINVAL);
	BAD_PPS(chroma_qp_index_offset, -13, -EINVAL);
	BAD_PPS(chroma_qp_index_offset, 13, -EINVAL);
	BAD_PPS(second_chroma_qp_index_offset, -13, -EINVAL);
	BAD_PPS(second_chroma_qp_index_offset, 13, -EINVAL);
	BAD_PPS(num_slice_groups_minus1, 1, -EOPNOTSUPP);
	BAD_PPS(flags, V4L2_H264_PPS_FLAG_REDUNDANT_PIC_CNT_PRESENT, -EOPNOTSUPP);
	BAD_PPS(flags, 0x8000, -EOPNOTSUPP);
	assert(mt6797_h264_header_words(0, &pps, &result) == -EINVAL);
	assert(mt6797_h264_header_words(&sps, 0, &result) == -EINVAL);
	assert(mt6797_h264_header_words(&sps, &pps, 0) == -EINVAL);

	sps.log2_max_frame_num_minus4 = 12;
	sps.pic_order_cnt_type = 1;
	sps.log2_max_pic_order_cnt_lsb_minus4 = 12;
	sps.max_num_ref_frames = 16;
	sps.flags |= V4L2_H264_SPS_FLAG_DELTA_PIC_ORDER_ALWAYS_ZERO;
	sps.pic_width_in_mbs_minus1 = 255;
	sps.pic_height_in_map_units_minus1 = 134;
	pps.flags = V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE |
		V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT |
		V4L2_H264_PPS_FLAG_WEIGHTED_PRED |
		V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT |
		V4L2_H264_PPS_FLAG_CONSTRAINED_INTRA_PRED |
		V4L2_H264_PPS_FLAG_TRANSFORM_8X8_MODE |
		V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT;
	pps.weighted_bipred_idc = 2;
	pps.pic_init_qp_minus26 = -26;
	pps.chroma_qp_index_offset = -12;
	pps.second_chroma_qp_index_offset = 12;
	pps.num_ref_idx_l0_default_active_minus1 = 15;
	pps.num_ref_idx_l1_default_active_minus1 = 15;
	assert(!mt6797_h264_header_words(&sps, &pps, &result));
	assert(result.sps == 0x00361c71 && result.pps == 0x0067a4d7);
	assert(result.reference_counts == 0x0007fdef);
	assert(result.width_mbs == 256 && result.height_mbs == 135);
	test_slices();
	test_p_references();
	test_scaling();
	puts("PASS: H.264 SPS/PPS, slice fields, P-reference metadata, scaling SRAM words and atomic rejection");
	return 0;
}
