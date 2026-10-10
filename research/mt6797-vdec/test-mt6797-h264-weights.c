/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <linux/errno.h>
#include <stdio.h>
#include <string.h>
#include "mt6797-h264-controls.h"

/* Independent syntax writer. It has no knowledge of hardware register fields
 * or of the production reader's byte/cursor implementation.
 */
struct bits { __u8 data[512]; unsigned int count; };
static void put(struct bits *bits, __u32 value, unsigned int count)
{
	assert(count <= 32 && bits->count + count <= sizeof(bits->data) * 8);
	for (unsigned int i = count; i; i--) {
		if ((value >> (i - 1)) & 1)
			bits->data[bits->count / 8] |= 1U << (7 - bits->count % 8);
		bits->count++;
	}
}
static void ue(struct bits *bits, __u32 value)
{
	unsigned int width = 0;
	__u32 number = value + 1;
	assert(number);
	for (__u32 n = number; n; n >>= 1) width++;
	put(bits, 0, width - 1);
	put(bits, number, width);
}
static void se(struct bits *bits, int value)
{
	ue(bits, value > 0 ? 2U * value - 1 : 2U * -value);
}
static unsigned int escape(const struct bits *bits, __u8 *nal)
{
	unsigned int size = 0, zeros = 0;
	for (unsigned int i = 0; i < (bits->count + 7) / 8; i++) {
		__u8 value = bits->data[i];
		if (zeros == 2 && value <= 3) {
			nal[size++] = 3;
			zeros = 0;
		}
		nal[size++] = value;
		zeros = value ? 0 : zeros + 1;
	}
	return size;
}

static void test_header(unsigned int mode, unsigned int references, unsigned int b_picture)
{
	struct v4l2_ctrl_h264_sps sps = {
		.profile_idc = 77, .chroma_format_idc = 1, .max_num_ref_frames = 1,
		.pic_width_in_mbs_minus1 = 3, .pic_height_in_map_units_minus1 = 3,
		.flags = V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY,
	};
	struct v4l2_ctrl_h264_pps pps = { .flags = V4L2_H264_PPS_FLAG_WEIGHTED_PRED |
		V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT };
	struct v4l2_ctrl_h264_slice_params slice = {
		.slice_type = V4L2_H264_SLICE_TYPE_P, .slice_qp_delta = -2,
		.disable_deblocking_filter_idc = 0, .slice_alpha_c0_offset_div2 = -3,
		.slice_beta_offset_div2 = 4,
	};
	struct v4l2_ctrl_h264_decode_params decode = {
		.nal_ref_idc = 2, .frame_num = 1, .pic_order_cnt_lsb = 2,
		.flags = V4L2_H264_DECODE_PARAM_FLAG_PFRAME,
	};
	struct v4l2_ctrl_h264_pred_weights weights = {
		.luma_log2_weight_denom = 3, .chroma_log2_weight_denom = 2,
	};
	struct mt6797_h264_weight_range output = { 0 }, saved;
	struct bits bits = { 0 };
	__u8 nal[1024];
	unsigned int begin, start, end, bytes;
	int explicit = mode & 1, cabac = mode & 2;
	unsigned int lists = b_picture ? 2 : 1;
	if (b_picture) {
		slice.slice_type = V4L2_H264_SLICE_TYPE_B;
		decode.flags = V4L2_H264_DECODE_PARAM_FLAG_BFRAME;
		pps.weighted_bipred_idc = 1;
		pps.flags &= ~V4L2_H264_PPS_FLAG_WEIGHTED_PRED;
		if (mode & 1) slice.flags = V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED;
		if (mode & 4) decode.nal_ref_idc = 0;
		slice.num_ref_idx_l1_active_minus1 = references - 1;
		pps.num_ref_idx_l1_default_active_minus1 = references - 1;
	}
	sps.max_num_ref_frames = references;
	slice.num_ref_idx_l0_active_minus1 = references - 1;
	pps.num_ref_idx_l0_default_active_minus1 = references - 1;

	if (cabac) pps.flags |= V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE;
	if (mode & 4) {
		sps.log2_max_frame_num_minus4 = 12;
		sps.log2_max_pic_order_cnt_lsb_minus4 = 12;
		decode.frame_num = decode.pic_order_cnt_lsb = 0;
	}
	if (mode & 8) {
		sps.pic_order_cnt_type = 1;
		pps.flags |= V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT;
		decode.delta_pic_order_cnt0 = -5;
		decode.delta_pic_order_cnt1 = 6;
	}
	if (mode & 16) sps.pic_order_cnt_type = 2;
	if (mode & 32) {
		weights.luma_log2_weight_denom = weights.chroma_log2_weight_denom = 7;
		explicit = 0;
	}
	for (unsigned int list = 0; list < lists; list++)
		for (unsigned int ref = 0; ref < references; ref++) {
			int encoded = explicit && !(ref % 3 == 1);
			weights.weight_factors[list].luma_weight[ref] = encoded ? -7 + (int)ref + (int)list : 1 << weights.luma_log2_weight_denom;
			weights.weight_factors[list].luma_offset[ref] = encoded ? -128 + (int)ref : 0;
			for (unsigned int j = 0; j < 2; j++) {
				weights.weight_factors[list].chroma_weight[ref][j] = encoded ? 5 + (int)j + (int)ref : 1 << weights.chroma_log2_weight_denom;
				weights.weight_factors[list].chroma_offset[ref][j] = encoded ? 127 - 130 * (int)j - (int)ref - (int)list : 0;
			}
		}
	put(&bits, (decode.nal_ref_idc << 5) | 1, 8);
	ue(&bits, 0); ue(&bits, slice.slice_type + 5); ue(&bits, 0);
	put(&bits, decode.frame_num, sps.log2_max_frame_num_minus4 + 4);
	begin = bits.count;
	if (!sps.pic_order_cnt_type)
		put(&bits, decode.pic_order_cnt_lsb, sps.log2_max_pic_order_cnt_lsb_minus4 + 4);
	else if (sps.pic_order_cnt_type == 1) {
		se(&bits, decode.delta_pic_order_cnt0);
		se(&bits, decode.delta_pic_order_cnt1);
	}
	decode.pic_order_cnt_bit_size = bits.count - begin;
	if (b_picture) put(&bits, !!(slice.flags & V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED), 1);
	put(&bits, 1, 1); ue(&bits, references - 1); /* explicit active-list override */
	if (b_picture) ue(&bits, references - 1);
	for (unsigned int list = 0; list < lists; list++) {
		put(&bits, 1, 1); ue(&bits, 0); ue(&bits, 0); ue(&bits, 3); /* short-term list modification */
	}
	start = bits.count;
	ue(&bits, weights.luma_log2_weight_denom);
	ue(&bits, weights.chroma_log2_weight_denom);
	for (unsigned int list = 0; list < lists; list++)
		for (unsigned int ref = 0; ref < references; ref++) {
			int encoded = explicit && !(ref % 3 == 1);
			put(&bits, encoded, 1);
			if (encoded) {
				se(&bits, weights.weight_factors[list].luma_weight[ref]);
				se(&bits, weights.weight_factors[list].luma_offset[ref]);
			}
			put(&bits, encoded, 1);
			if (encoded)
				for (unsigned int j = 0; j < 2; j++) {
					se(&bits, weights.weight_factors[list].chroma_weight[ref][j]);
					se(&bits, weights.weight_factors[list].chroma_offset[ref][j]);
				}
		}
	end = begin = bits.count;
	if (decode.nal_ref_idc) {
		put(&bits, 1, 1); ue(&bits, 1); ue(&bits, 0); ue(&bits, 0); /* MMCO1, then terminator */
	}
	decode.dec_ref_pic_marking_bit_size = bits.count - begin;
	if (cabac) ue(&bits, slice.cabac_init_idc);
	se(&bits, slice.slice_qp_delta);
	ue(&bits, slice.disable_deblocking_filter_idc);
	se(&bits, slice.slice_alpha_c0_offset_div2);
	se(&bits, slice.slice_beta_offset_div2);
	slice.header_bit_size = bits.count;
	put(&bits, 0xff, 8); /* data beyond the declared header must not be parsed */
	bytes = escape(&bits, nal);
	assert(!mt6797_h264_weight_range(&sps, &pps, &slice, &decode, &weights, nal, bytes, &output));
	assert(output.start == start && output.end == end);
	/* Compare lookahead against the independent unescaped writer, including
	 * partial final bytes. No production reader computes this oracle.
	 */
	for (unsigned int point = 0; point < 2; point++) {
		unsigned int position = point ? end : start;
		unsigned int available = (bits.count + 7) / 8 * 8 - position;
		unsigned int count = available < 32 ? available : 32;
		__u32 word = 0, mask = count == 32 ? ~0U : ~0U << (32 - count);
		for (unsigned int bit = 0; bit < count; bit++)
			word |= ((__u32)(bits.data[(position + bit) / 8] >>
				 (7 - (position + bit) % 8)) & 1U) << (31 - bit);
		assert((point ? output.end_word : output.start_word) == word);
		assert((point ? output.end_mask : output.start_mask) == mask);
	}
	saved = output;
#define REJECT(changes, expected) do { \
	struct v4l2_ctrl_h264_pred_weights bad = weights; changes; \
	assert(mt6797_h264_weight_range(&sps, &pps, &slice, &decode, &bad, nal, bytes, &output) == expected); \
	assert(!memcmp(&output, &saved, sizeof(output))); \
} while (0)
	REJECT(bad.luma_log2_weight_denom = 8, -ERANGE);
	REJECT(bad.weight_factors[0].luma_offset[0]++, -EINVAL);
	REJECT(bad.weight_factors[0].chroma_weight[references - 1][1]++, -EINVAL);
	if (b_picture) {
		REJECT(bad.weight_factors[1].luma_weight[references - 1]++, -EINVAL);
		REJECT(bad.weight_factors[1].chroma_offset[0][0]++, -EINVAL);
	}
#undef REJECT
	decode.dec_ref_pic_marking_bit_size++;
	assert(mt6797_h264_weight_range(&sps, &pps, &slice, &decode, &weights, nal, bytes, &output) == -EINVAL);
	decode.dec_ref_pic_marking_bit_size--;
	for (unsigned int n = 0; n < (slice.header_bit_size + 7) / 8; n++) {
		assert(mt6797_h264_weight_range(&sps, &pps, &slice, &decode, &weights, nal, n, &output) < 0);
		assert(!memcmp(&output, &saved, sizeof(output)));
	}
	assert(mt6797_h264_weight_range(&sps, &pps, &slice, &decode, NULL, nal, bytes, &output) == -EINVAL);
	assert(mt6797_h264_weight_range(&sps, &pps, &slice, &decode, &weights, NULL, bytes, &output) == -EINVAL);
	/* Denominator and syntax mismatch errors must not bypass the bound. */
	for (unsigned int bit = 8; bit < start; bit++) {
		__u8 changed[1024];
		struct bits malformed = bits;
		malformed.data[bit / 8] ^= 1U << (7 - bit % 8);
		unsigned int size = escape(&malformed, changed);
		struct mt6797_h264_weight_range before = output;
		int ret = mt6797_h264_weight_range(&sps, &pps, &slice, &decode, &weights, changed, size, &output);
		if (ret) assert(!memcmp(&output, &before, sizeof(output)));
		else assert(output.start < output.end && output.end < slice.header_bit_size);
	}
}

int main(void)
{
	const unsigned int counts[] = {1, 2, 4, 16};
	for (unsigned int i = 0; i < sizeof(counts) / sizeof(counts[0]); i++)
		for (unsigned int mode = 0; mode < 64; mode++)
			for (unsigned int b = 0; b < 2; b++) test_header(mode, counts[i], b);
	puts("PASS:512 independently written1/2/4/16-entry weighted P/B headers across both lists, signed/default weights, POC variants, escaping, control mismatches and truncation bounds");
	return 0;
}
