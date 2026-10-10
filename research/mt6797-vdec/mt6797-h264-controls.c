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

int mt6797_h264_p_reference_words(const struct v4l2_h264_dpb_entry *entry,
				unsigned int frame_buffer_index,
				struct mt6797_h264_p_reference_words *output)
{
	const __u32 required = V4L2_H264_DPB_ENTRY_FLAG_VALID |
		V4L2_H264_DPB_ENTRY_FLAG_ACTIVE;
	const __u32 allowed = required | V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
	struct mt6797_h264_p_reference_words words;
	__u32 order, long_term;
	unsigned int i;

	if (!entry || !output || frame_buffer_index >= MT6797_H264_PICTURE_SLOTS)
		return -EINVAL;
	if ((entry->flags & required) != required)
		return -EINVAL;
	for (i = 0; i < sizeof(entry->reserved); i++)
		if (entry->reserved[i])
			return -EINVAL;
	if ((entry->flags & ~allowed) || entry->fields != V4L2_H264_FRAME_REF)
		return -EOPNOTSUPP;
	if (entry->top_field_order_cnt == 0x7fffffff ||
	    entry->bottom_field_order_cnt == 0x7fffffff)
		return -EINVAL;
	long_term = !!(entry->flags & V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM);
	/* pic_num represents signed PicNum for short-term references and
	 * nonnegative LongTermPicNum for long-term references. Reject overflow
	 * instead of silently wrapping the public 19-bit register field.
	 */
	if (long_term ? entry->pic_num > 0x7ffff :
	    ((__s32)entry->pic_num < -262144 || (__s32)entry->pic_num > 262143))
		return -ERANGE;
	words.picture_number = (entry->pic_num & 0x7ffff) | (long_term << 19);
	order = entry->top_field_order_cnt <= entry->bottom_field_order_cnt;
	words.top = (frame_buffer_index << 23) | (order << 21) | (long_term << 20);
	words.bottom = words.top | (1U << 22);
	*output = words;
	return 0;
}

int mt6797_h264_picture_poc(const struct v4l2_ctrl_h264_sps *sps,
			   const struct v4l2_ctrl_h264_pps *pps,
			   const struct v4l2_ctrl_h264_decode_params *decode)
{
	__u32 mask;
	__s64 bottom_delta;

	if (!sps || !pps || !decode || sps->pic_order_cnt_type > 2 ||
	    sps->log2_max_pic_order_cnt_lsb_minus4 > 12 ||
	    decode->top_field_order_cnt == 0x7fffffff ||
	    decode->bottom_field_order_cnt == 0x7fffffff)
		return -EINVAL;
	if (sps->pic_order_cnt_type != 0)
		return 0;
	mask = (1U << (sps->log2_max_pic_order_cnt_lsb_minus4 + 4)) - 1;
	bottom_delta = (pps->flags & V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT) ?
		decode->delta_pic_order_cnt_bottom : 0;
	if (((__u32)decode->top_field_order_cnt & mask) != decode->pic_order_cnt_lsb ||
	    (__s64)decode->bottom_field_order_cnt - decode->top_field_order_cnt != bottom_delta)
		return -EINVAL;
	return 0;
}

int mt6797_h264_b_reference_words(const struct v4l2_h264_dpb_entry *entry,
                                unsigned int frame_buffer_index,
                                struct mt6797_h264_p_reference_words *output)
{
        struct mt6797_h264_p_reference_words words;
        int ret;

        if (!output)
                return -EINVAL;
        ret = mt6797_h264_p_reference_words(entry, frame_buffer_index, &words);
        if (ret)
                return ret;
        /* Public SetBRefPicListReg masks full counts into the18bit field.
         * Timestamp/geometry/full-POC checks happen before this translation.
         */
        words.top |= (__u32)entry->top_field_order_cnt & 0x3ffff;
        words.bottom |= (__u32)entry->bottom_field_order_cnt & 0x3ffff;
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

/* Original bounded reader for the public H.264 slice-header syntax. The
 * hardware weighting operation consumes in-band syntax, so a control-only
 * register translation cannot establish its start/end or validate its data.
 */
struct weight_reader {
	const __u8 *nal;
	__u32 bytes, source, position, limit;
	__u8 current, remaining, zeros;
	int error;
};

static __u32 weight_bits(struct weight_reader *reader, unsigned int count)
{
	__u32 value = 0;
	unsigned int i;

	if (count > 32) {
		reader->error = -EINVAL;
		return 0;
	}
	for (i = 0; i < count && !reader->error; i++) {
		if (reader->position == reader->limit) {
			reader->error = -EINVAL;
			break;
		}
		if (!reader->remaining) {
			__u8 byte;

			if (reader->source == reader->bytes) {
				reader->error = -EINVAL;
				break;
			}
			byte = reader->nal[reader->source++];
			if (reader->zeros == 2 && byte == 3) {
				if (reader->source == reader->bytes || reader->nal[reader->source] > 3) {
					reader->error = -EINVAL;
					break;
				}
				byte = reader->nal[reader->source++];
				reader->zeros = 0;
			}
			reader->zeros = byte == 0 ? (reader->zeros < 2 ? reader->zeros + 1 : 2) : 0;
			reader->current = byte;
			reader->remaining = 8;
		}
		reader->remaining--;
		reader->position++;
		value = (value << 1) | ((reader->current >> reader->remaining) & 1);
	}
	return value;
}

static __u32 weight_ue(struct weight_reader *reader)
{
	unsigned int zeros = 0;

	while (!reader->error && !weight_bits(reader, 1)) {
		if (++zeros == 32) {
			reader->error = -ERANGE;
			return 0;
		}
	}
	return reader->error ? 0 : ((1U << zeros) - 1) + weight_bits(reader, zeros);
}

static __s32 weight_se(struct weight_reader *reader)
{
	__u32 code = weight_ue(reader);

	if (code & 1)
		return (__s32)(((__u64)code + 1) / 2);
	return -(__s32)(code / 2);
}

static void weight_expect(struct weight_reader *reader, __s64 actual, __s64 expected)
{
	if (!reader->error && actual != expected)
		reader->error = -EINVAL;
}

int mt6797_h264_slice_headers_match(
	const struct v4l2_ctrl_h264_slice_params *first,
	const __u8 *first_nal, __u32 first_bytes,
	const struct v4l2_ctrl_h264_slice_params *next,
	const __u8 *next_nal, __u32 next_bytes)
{
	struct weight_reader a = { .nal = first_nal, .bytes = first_bytes };
	struct weight_reader b = { .nal = next_nal, .bytes = next_bytes };
	__u32 remaining;

	if (!first || !next || !first_nal || !next_nal ||
	    first_bytes < 4 || next_bytes < 4 ||
	    first->header_bit_size < 9 || next->header_bit_size < 9 ||
	    first->header_bit_size > 16384 || next->header_bit_size > 16384 ||
	    (__u64)first->header_bit_size > (__u64)first_bytes * 8 ||
	    (__u64)next->header_bit_size > (__u64)next_bytes * 8)
		return -EINVAL;
	a.limit = first->header_bit_size;
	b.limit = next->header_bit_size;
	if (weight_bits(&a, 8) != weight_bits(&b, 8))
		return -EINVAL;
	weight_expect(&a, weight_ue(&a), first->first_mb_in_slice);
	weight_expect(&b, weight_ue(&b), next->first_mb_in_slice);
	if (a.error || b.error || a.limit - a.position != b.limit - b.position)
		return -EINVAL;
	remaining = a.limit - a.position;
	while (remaining && !a.error && !b.error) {
		unsigned int count = remaining < 32 ? remaining : 32;
		if (weight_bits(&a, count) != weight_bits(&b, count))
			return -EINVAL;
		remaining -= count;
	}
	return a.error ? a.error : b.error;
}

static __s32 weight_factor(struct weight_reader *reader, __s16 expected)
{
	__s32 value = weight_se(reader);

	if (!reader->error && (value < -128 || value > 127))
		reader->error = -ERANGE;
	weight_expect(reader, value, expected);
	return value;
}

/* A bounded, non-consuming RBSP lookahead verifies the hardware barrel
 * contents independently of the cursor counter. Ignore bits beyond the NAL:
 * the private hardware FIFO supplies padding and an end marker there.
 */
static int weight_window(struct weight_reader reader, __u32 *word, __u32 *mask)
{
	unsigned int count = 0;
	__u32 value = 0;

	reader.limit = reader.position + 32;
	while (count < 32 && (reader.remaining || reader.source < reader.bytes)) {
		value = (value << 1) | weight_bits(&reader, 1);
		if (reader.error)
			return reader.error;
		count++;
	}
	if (!count)
		return -EINVAL;
	*word = count == 32 ? value : value << (32 - count);
	*mask = count == 32 ? ~0U : ~0U << (32 - count);
	return 0;
}

int mt6797_h264_weight_range(const struct v4l2_ctrl_h264_sps *sps,
			    const struct v4l2_ctrl_h264_pps *pps,
			    const struct v4l2_ctrl_h264_slice_params *slice,
			    const struct v4l2_ctrl_h264_decode_params *decode,
			    const struct v4l2_ctrl_h264_pred_weights *weights,
			    const __u8 *nal, __u32 bytes,
			    struct mt6797_h264_weight_range *output)
{
	struct mt6797_h264_slice_words ignored;
	struct mt6797_h264_weight_range range;
	struct weight_reader reader = { .nal = nal, .bytes = bytes };
	const struct v4l2_h264_weight_factors *factors;
	__u32 begin, value, iterations;
	unsigned int component, reference, list, lists, counts[2];
	int ret;

	if (!sps || !pps || !slice || !decode || !weights || !nal || !output || bytes < 4)
		return -EINVAL;
	ret = mt6797_h264_slice_words(sps, pps, slice, decode, bytes, &ignored);
	if (ret)
		return ret;
	if (!V4L2_H264_CTRL_PRED_WEIGHTS_REQUIRED(pps, slice) ||
	    (slice->slice_type != V4L2_H264_SLICE_TYPE_P &&
	     slice->slice_type != V4L2_H264_SLICE_TYPE_B) ||
	    (decode->flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) ||
	    (slice->slice_type == V4L2_H264_SLICE_TYPE_P && slice->num_ref_idx_l1_active_minus1) ||
	    sps->profile_idc == 66)
		return -EOPNOTSUPP;
	lists = slice->slice_type == V4L2_H264_SLICE_TYPE_B ? 2 : 1;
	counts[0] = slice->num_ref_idx_l0_active_minus1 + 1;
	counts[1] = slice->num_ref_idx_l1_active_minus1 + 1;
	if (weights->luma_log2_weight_denom > 7 || weights->chroma_log2_weight_denom > 7)
		return -ERANGE;
	reader.limit = slice->header_bit_size;
	/* The admitted one-slice progressive boundary has no colour-plane,
	 * field, IDR, redundant-picture or slice-group syntax.
	 */
	weight_expect(&reader, weight_bits(&reader, 8), (decode->nal_ref_idc << 5) | 1);
	weight_expect(&reader, weight_ue(&reader), slice->first_mb_in_slice);
	value = weight_ue(&reader);
	if (value != slice->slice_type && value != slice->slice_type + 5U)
		reader.error = -EINVAL;
	weight_expect(&reader, weight_ue(&reader), pps->pic_parameter_set_id);
	weight_expect(&reader, weight_bits(&reader, sps->log2_max_frame_num_minus4 + 4),
		      decode->frame_num);
	begin = reader.position;
	if (sps->pic_order_cnt_type == 0) {
		weight_expect(&reader, weight_bits(&reader, sps->log2_max_pic_order_cnt_lsb_minus4 + 4),
			      decode->pic_order_cnt_lsb);
		if (pps->flags & V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT)
			weight_expect(&reader, weight_se(&reader), decode->delta_pic_order_cnt_bottom);
	} else if (sps->pic_order_cnt_type == 1 &&
		   !(sps->flags & V4L2_H264_SPS_FLAG_DELTA_PIC_ORDER_ALWAYS_ZERO)) {
		weight_expect(&reader, weight_se(&reader), decode->delta_pic_order_cnt0);
		if (pps->flags & V4L2_H264_PPS_FLAG_BOTTOM_FIELD_PIC_ORDER_IN_FRAME_PRESENT)
			weight_expect(&reader, weight_se(&reader), decode->delta_pic_order_cnt1);
	}
	weight_expect(&reader, reader.position - begin, decode->pic_order_cnt_bit_size);
	if (lists == 2)
		weight_expect(&reader, weight_bits(&reader, 1),
			      !!(slice->flags & V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED));
	if (weight_bits(&reader, 1)) {
		for (list = 0; list < lists; list++)
			weight_expect(&reader, weight_ue(&reader), counts[list] - 1);
	} else {
		weight_expect(&reader, counts[0] - 1, pps->num_ref_idx_l0_default_active_minus1);
		if (lists == 2)
			weight_expect(&reader, counts[1] - 1, pps->num_ref_idx_l1_default_active_minus1);
	}
	/* Parse finite list modification operations; private binding is separate. */
	for (list = 0; list < lists; list++)
		if (weight_bits(&reader, 1)) {
			for (iterations = 0; iterations < 32 && !reader.error; iterations++) {
				value = weight_ue(&reader);
				if (value == 3)
					break;
				if (value > 3) {
					reader.error = -EINVAL;
					break;
				}
				weight_ue(&reader);
			}
			if (iterations == 32)
				reader.error = -EOPNOTSUPP;
		}
	range.start = reader.position;
	ret = weight_window(reader, &range.start_word, &range.start_mask);
	if (ret)
		return ret;
	weight_expect(&reader, weight_ue(&reader), weights->luma_log2_weight_denom);
	weight_expect(&reader, weight_ue(&reader), weights->chroma_log2_weight_denom);
	for (list = 0; list < lists; list++) {
		factors = &weights->weight_factors[list];
		for (reference = 0; reference < counts[list]; reference++) {
			if (weight_bits(&reader, 1)) {
				weight_factor(&reader, factors->luma_weight[reference]);
				weight_factor(&reader, factors->luma_offset[reference]);
			} else {
				weight_expect(&reader, factors->luma_weight[reference],
					      1U << weights->luma_log2_weight_denom);
				weight_expect(&reader, factors->luma_offset[reference], 0);
			}
			if (weight_bits(&reader, 1)) {
				for (component = 0; component < 2; component++) {
					weight_factor(&reader, factors->chroma_weight[reference][component]);
					weight_factor(&reader, factors->chroma_offset[reference][component]);
				}
			} else {
				for (component = 0; component < 2; component++) {
					weight_expect(&reader, factors->chroma_weight[reference][component],
						      1U << weights->chroma_log2_weight_denom);
					weight_expect(&reader, factors->chroma_offset[reference][component], 0);
				}
			}
		}
	}
	range.end = reader.position;
	ret = weight_window(reader, &range.end_word, &range.end_mask);
	if (ret)
		return ret;
	begin = reader.position;
	if (decode->nal_ref_idc && weight_bits(&reader, 1)) {
		for (iterations = 0; iterations < 32 && !reader.error; iterations++) {
			value = weight_ue(&reader);
			if (!value)
				break;
			if (value > 6) {
				reader.error = -EINVAL;
				break;
			}
			if (value == 1 || value == 3)
				weight_ue(&reader);
			if (value == 2)
				weight_ue(&reader);
			if (value == 3 || value == 6)
				weight_ue(&reader);
			if (value == 4)
				weight_ue(&reader);
		}
		if (iterations == 32)
			reader.error = -EOPNOTSUPP;
	}
	weight_expect(&reader, reader.position - begin, decode->dec_ref_pic_marking_bit_size);
	if (pps->flags & V4L2_H264_PPS_FLAG_ENTROPY_CODING_MODE)
		weight_expect(&reader, weight_ue(&reader), slice->cabac_init_idc);
	weight_expect(&reader, weight_se(&reader), slice->slice_qp_delta);
	if (pps->flags & V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT) {
		weight_expect(&reader, weight_ue(&reader), slice->disable_deblocking_filter_idc);
		if (slice->disable_deblocking_filter_idc != 1) {
			weight_expect(&reader, weight_se(&reader), slice->slice_alpha_c0_offset_div2);
			weight_expect(&reader, weight_se(&reader), slice->slice_beta_offset_div2);
		}
	}
	weight_expect(&reader, reader.position, slice->header_bit_size);
	if (reader.error)
		return reader.error;
	*output = range;
	return 0;
}

int mt6797_h264_reference_plan(const struct v4l2_ctrl_h264_sps *sps,
			      const struct v4l2_ctrl_h264_slice_params *slice,
			      const struct v4l2_ctrl_h264_decode_params *decode,
			      const struct mt6797_h264_cached_picture cache[MT6797_H264_PICTURE_SLOTS],
			      __u64 timestamp, struct mt6797_h264_reference_plan *output)
{
	struct mt6797_h264_reference_plan plan = { 0 };
	__u8 mapping[V4L2_H264_NUM_DPB_ENTRIES];
	unsigned int dpb, slot, active = 0, pass;
	__u32 long_term_indices = 0;
	int found = -1;

	if (!sps || !slice || !decode || !cache || !output ||
	    sps->max_num_ref_frames > V4L2_H264_NUM_DPB_ENTRIES)
		return -EINVAL;
	if (slice->slice_type != V4L2_H264_SLICE_TYPE_I &&
	    slice->slice_type != V4L2_H264_SLICE_TYPE_P &&
	    slice->slice_type != V4L2_H264_SLICE_TYPE_B)
		return -EOPNOTSUPP;
	if ((slice->slice_type != V4L2_H264_SLICE_TYPE_I &&
	     slice->num_ref_idx_l0_active_minus1 >= V4L2_H264_NUM_DPB_ENTRIES) ||
	    slice->num_ref_idx_l1_active_minus1 >= V4L2_H264_NUM_DPB_ENTRIES ||
	    (slice->slice_type == V4L2_H264_SLICE_TYPE_P && slice->num_ref_idx_l1_active_minus1))
		return -EOPNOTSUPP;
	if ((decode->flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) &&
	    slice->slice_type != V4L2_H264_SLICE_TYPE_I)
		return -EINVAL;
	for (dpb = 0; dpb < V4L2_H264_NUM_DPB_ENTRIES; dpb++) {
		const struct v4l2_h264_dpb_entry *entry = &decode->dpb[dpb];
		struct mt6797_h264_p_reference_words ignored;
		int ret;

		mapping[dpb] = MT6797_H264_PICTURE_SLOTS;
		if ((decode->flags & V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC) ||
		    !(entry->flags & V4L2_H264_DPB_ENTRY_FLAG_ACTIVE))
			continue;
		if (entry->flags & V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM) {
			/* Progressive LongTermPicNum equals LongTermFrameIdx. Linux
			 * carries that index in frame_num, rather than the NAL frame_num.
			 */
			if (entry->frame_num >= sps->max_num_ref_frames ||
			    entry->pic_num != entry->frame_num ||
			    (long_term_indices & (1U << entry->frame_num)))
				return -EINVAL;
			long_term_indices |= 1U << entry->frame_num;
		}
		ret = mt6797_h264_p_reference_words(entry, 0, &ignored);
		if (ret)
			return ret;
		if (++active > sps->max_num_ref_frames)
			return -EINVAL;
		for (slot = 0; slot < MT6797_H264_PICTURE_SLOTS; slot++)
			if (cache[slot].valid && cache[slot].allocated &&
			    cache[slot].timestamp == entry->reference_ts)
				break;
		if (slot == MT6797_H264_PICTURE_SLOTS)
			return -ENOENT;
		if ((plan.protected_mask & (1U << slot)) ||
		    (!(entry->flags & V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM) &&
		     cache[slot].frame_number != entry->frame_num) ||
		    cache[slot].width != ((__u32)sps->pic_width_in_mbs_minus1 + 1) * 16 ||
		    cache[slot].height != ((__u32)sps->pic_height_in_map_units_minus1 + 1) * 16 ||
		    cache[slot].top_poc != entry->top_field_order_cnt ||
		    cache[slot].bottom_poc != entry->bottom_field_order_cnt ||
		    (decode->nal_ref_idc && timestamp == entry->reference_ts))
			return -EINVAL;
		mapping[dpb] = slot;
		plan.protected_mask |= 1U << slot;
		if (entry->flags & V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM)
			plan.long_term_mask |= 1U << slot;
	}
	if (slice->slice_type != V4L2_H264_SLICE_TYPE_I) {
		plan.count = slice->num_ref_idx_l0_active_minus1 + 1;
		for (slot = 0; slot < plan.count; slot++) {
			dpb = slice->ref_pic_list0[slot].index;
			if (dpb >= V4L2_H264_NUM_DPB_ENTRIES ||
			    slice->ref_pic_list0[slot].fields != V4L2_H264_FRAME_REF)
				return -EINVAL;
			if (mapping[dpb] == MT6797_H264_PICTURE_SLOTS)
				return -ENOENT;
			plan.list0[slot] = mapping[dpb];
		}
	}
	if (slice->slice_type == V4L2_H264_SLICE_TYPE_B) {
		plan.count1 = slice->num_ref_idx_l1_active_minus1 + 1;
		for (slot = 0; slot < plan.count1; slot++) {
			dpb = slice->ref_pic_list1[slot].index;
			if (dpb >= V4L2_H264_NUM_DPB_ENTRIES ||
			    slice->ref_pic_list1[slot].fields != V4L2_H264_FRAME_REF)
				return -EINVAL;
			if (mapping[dpb] == MT6797_H264_PICTURE_SLOTS)
				return -ENOENT;
			plan.list1[slot] = mapping[dpb];
		}
	}
	/* Reuse unprotected allocated storage before allocating another slot.
	 * This preserves the two-buffer path for single-reference streams.
	 */
	for (pass = 0; pass < 2 && found < 0; pass++)
		for (slot = 0; slot < MT6797_H264_PICTURE_SLOTS; slot++)
			if (!(plan.protected_mask & (1U << slot)) &&
			    !!cache[slot].allocated == !pass) {
				found = slot;
				break;
			}
	if (found < 0)
		return -ENOSPC;
	plan.output = found;
	for (slot = 0; slot < MT6797_H264_PICTURE_SLOTS; slot++)
		if (slot != plan.output && cache[slot].valid && cache[slot].allocated)
			plan.snapshot_mask |= 1U << slot;
	*output = plan;
	return 0;
}
