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

	REJECT(decode.dpb[0].reserved[0]=1, decode.dpb[0].reserved[0]=0, -EINVAL);
	REJECT(slice.ref_pic_list0[0].index=16, slice.ref_pic_list0[0].index=count-1, -EINVAL);
	REJECT(slice.ref_pic_list0[0].fields=V4L2_H264_TOP_FIELD_REF,
	       slice.ref_pic_list0[0].fields=V4L2_H264_FRAME_REF, -EINVAL);
	REJECT(sps.max_num_ref_frames=count-1,sps.max_num_ref_frames=count,-EINVAL);
#undef REJECT
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	/* B lists have separate order and count; private identity remains stable. */
	slice.slice_type = V4L2_H264_SLICE_TYPE_B;
	slice.num_ref_idx_l1_active_minus1 = count - 1;
	for (unsigned int i = 0; i < count; i++) {
		slice.ref_pic_list1[i].fields = V4L2_H264_FRAME_REF;
		slice.ref_pic_list1[i].index = i;
	}
	assert(!mt6797_h264_reference_plan(&sps, &slice, &decode, cache, 1000, &plan));
	assert(plan.count1 == count);
	for (unsigned int i = 0; i < count; i++)
		assert(plan.list1[i] == count - 1 - i && plan.list0[i] == i);
	/* Full metadata must remain authoritative even when low hardware bits
	 * coincide. This checks both DPB POCs, rather than a narrowed cache.
	 */
	for (unsigned int i = 0; i < count; i++) {
		decode.dpb[i].top_field_order_cnt += 262144;
		decode.dpb[i].bottom_field_order_cnt += 262144;
		cache[count - 1 - i].top_poc += 262144;
		cache[count - 1 - i].bottom_poc += 262144;
	}
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	saved = plan;
	decode.dpb[0].top_field_order_cnt += 262144;
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	decode.dpb[0].top_field_order_cnt -= 262144;
	for (unsigned int i = 0; i < count; i++) {
		decode.dpb[i].top_field_order_cnt -= 262144;
		decode.dpb[i].bottom_field_order_cnt -= 262144;
		cache[count - 1 - i].top_poc -= 262144;
		cache[count - 1 - i].bottom_poc -= 262144;
	}
	saved = plan;
	slice.ref_pic_list1[count - 1].index = 16;
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	slice.ref_pic_list1[count - 1].index = count - 1;
	slice.slice_type = V4L2_H264_SLICE_TYPE_P;
	slice.num_ref_idx_l1_active_minus1 = 0;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	saved = plan;
	/* Long-term frame_num is an index, which may differ from the cached
	 * NAL frame number. Timestamp, POC and geometry remain authoritative.
	 */
	for (unsigned int i = 0; i < count; i++) {
		decode.dpb[i].flags |= V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
		decode.dpb[i].frame_num = decode.dpb[i].pic_num = count - 1 - i;
	}
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	assert(plan.long_term_mask == saved.protected_mask);
	saved = plan;
	decode.dpb[0].pic_num++;
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	decode.dpb[0].pic_num--;
	decode.dpb[0].frame_num = decode.dpb[0].pic_num = count;
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	decode.dpb[0].frame_num = decode.dpb[0].pic_num = 65535;
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	decode.dpb[0].frame_num = decode.dpb[0].pic_num = count - 1;
	/* Invalid POC still fails for a long-term entry. */
	cache[count - 1].bottom_poc++;
	assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
	assert(!memcmp(&plan,&saved,sizeof(plan)));
	cache[count - 1].bottom_poc--;
	slice.slice_type = V4L2_H264_SLICE_TYPE_B;
	slice.num_ref_idx_l1_active_minus1 = count - 1;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	assert(plan.count1 == count && plan.long_term_mask == plan.protected_mask);
	for (unsigned int i = 0; i < count; i++)
		assert(plan.list1[i] == count - 1 - i && plan.list0[i] == i);
	slice.slice_type = V4L2_H264_SLICE_TYPE_P;
	slice.num_ref_idx_l1_active_minus1 = 0;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	saved = plan;
	if (count > 1) {
		decode.dpb[1].frame_num = decode.dpb[1].pic_num = count - 1;
		assert(mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan)==-EINVAL);
		assert(!memcmp(&plan,&saved,sizeof(plan)));
	}
	for (unsigned int i = 0; i < count; i++) {
		decode.dpb[i].flags &= ~V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
		decode.dpb[i].frame_num = decode.dpb[i].pic_num = i;
	}
	/* Same frame_num is legal across short-term and long-term namespaces. */
	decode.dpb[0].flags |= V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
	decode.dpb[0].frame_num = decode.dpb[0].pic_num = count - 1;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	assert(plan.long_term_mask == (1U << (count - 1)));
	slice.slice_type = V4L2_H264_SLICE_TYPE_B;
	slice.num_ref_idx_l1_active_minus1 = count - 1;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	assert(plan.count1 == count && plan.long_term_mask == (1U << (count - 1)));
	slice.slice_type = V4L2_H264_SLICE_TYPE_P;
	slice.num_ref_idx_l1_active_minus1 = 0;
	decode.dpb[0].flags &= ~V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
	decode.dpb[0].frame_num = decode.dpb[0].pic_num = 0;
	assert(!mt6797_h264_reference_plan(&sps,&slice,&decode,cache,1000,&plan));
	saved = plan;
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
	puts("PASS:1..16 short/long-term P/B reference plans with independent lists, reordered/duplicate lists, protected output, retained snapshots and atomic invalid metadata rejection");
	return 0;
}
