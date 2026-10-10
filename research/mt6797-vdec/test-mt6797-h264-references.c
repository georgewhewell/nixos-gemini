/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <linux/errno.h>
#include <stdio.h>
#include <string.h>
#include "mt6797-h264-controls.h"

static void test_count(unsigned int count)
{
	struct v4l2_ctrl_h264_sps sps = { .max_num_ref_frames = count,
		.pic_width_in_mbs_minus1 = 3, .pic_height_in_map_units_minus1 = 3 };
	struct v4l2_ctrl_h264_slice_params slice = { .slice_type = V4L2_H264_SLICE_TYPE_P,
		.num_ref_idx_l0_active_minus1 = count - 1 };
	struct v4l2_ctrl_h264_decode_params decode = { .nal_ref_idc = 2 };
	struct mt6797_h264_cached_picture cache[MT6797_H264_PICTURE_SLOTS] = { 0 };
	struct mt6797_h264_reference_plan plan, saved;
	for (unsigned int i = 0; i < count; i++) {
		/* DPB order, private storage order and list order deliberately differ. */
		unsigned int slot = count - 1 - i;
		cache[slot] = (struct mt6797_h264_cached_picture) {
			.timestamp = i + 1, .frame_number = i, .width = 64, .height = 64,
			.top_poc = i * 2, .bottom_poc = i * 2, .allocated = 1, .valid = 1 };
		decode.dpb[i] = (struct v4l2_h264_dpb_entry) {
			.reference_ts = i + 1, .frame_num = i, .pic_num = i,
			.top_field_order_cnt = i * 2, .bottom_field_order_cnt = i * 2,
			.fields = V4L2_H264_FRAME_REF,
			.flags = V4L2_H264_DPB_ENTRY_FLAG_VALID | V4L2_H264_DPB_ENTRY_FLAG_ACTIVE };
		slice.ref_pic_list0[i].fields = V4L2_H264_FRAME_REF;
		slice.ref_pic_list0[i].index = count - 1 - i;
	}
	assert(!mt6797_h264_reference_plan(&sps, &slice, &decode, cache, 1000, &plan));
	assert(plan.count == count && plan.output == count);
	assert(plan.protected_mask == (1U << count) - 1 && plan.snapshot_mask == plan.protected_mask);
	for (unsigned int i = 0; i < count; i++) assert(plan.list0[i] == i);
	saved = plan;
#define REJECT(change, restore, expected) do { \
	change; assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==expected); \
	assert(!memcmp(&plan,&saved,sizeof(plan))); restore; \
} while (0)
	REJECT(cache[0].valid=0, cache[0].valid=1, -ENOENT);
	REJECT(cache[0].allocated=0, cache[0].allocated=1, -ENOENT);
	REJECT(cache[0].width=80, cache[0].width=64, -EINVAL);
	REJECT(cache[0].top_poc++, cache[0].top_poc--, -EINVAL);
	REJECT(cache[0].frame_number++, cache[0].frame_number--, -EINVAL);
	REJECT(decode.dpb[0].flags|=V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM,
	       decode.dpb[0].flags&=~V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM, -EOPNOTSUPP);
	REJECT(decode.dpb[0].reserved[0]=1, decode.dpb[0].reserved[0]=0, -EINVAL);
	REJECT(slice.ref_pic_list0[0].index=16, slice.ref_pic_list0[0].index=count-1, -EINVAL);
	REJECT(slice.ref_pic_list0[0].fields=V4L2_H264_TOP_FIELD_REF,
	       slice.ref_pic_list0[0].fields=V4L2_H264_FRAME_REF, -EINVAL);
	REJECT(sps.max_num_ref_frames=count-1,sps.max_num_ref_frames=count,-EINVAL);
#undef REJECT
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	/* Duplicate list entries are valid; duplicate active DPB entries are not. */
	if (count > 1) {
		slice.ref_pic_list0[1] = slice.ref_pic_list0[0];
		assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
		assert(plan.list0[1] == plan.list0[0] && plan.protected_mask == saved.protected_mask);
		decode.dpb[1] = decode.dpb[0];
		assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	}
	/* An IDR selects existing output storage while retaining a snapshot of
	 * other cached pictures; failure must not destroy those references.
	 */
	slice.slice_type = V4L2_H264_SLICE_TYPE_I;
	decode.flags = V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	assert(!plan.count && !plan.protected_mask && !plan.output);
	assert(plan.snapshot_mask == saved.protected_mask - 1);
}

int main(void)
{
	for (unsigned int count=1; count<=V4L2_H264_NUM_DPB_ENTRIES; count++) test_count(count);
	puts("PASS:1..16 reference plans, reordered/duplicate lists, protected output, retained snapshots and atomic invalid metadata rejection");
	return 0;
}
