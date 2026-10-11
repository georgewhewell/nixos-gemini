// SPDX-License-Identifier: GPL-2.0-only
/* Original Request-API multislice/lifetime exerciser. Hardware is selected
 * explicitly; all returned pixels and cached command counters are checked. */
#define main single_slice_main
#include "request-test.c"
#undef main
#include <assert.h>
#include "../mt6797-vdec/multislice64-fixture.h"

static unsigned int ue_size(unsigned int value)
{
	unsigned int bits = 1;
	while ((value + 1) >> bits) bits++;
	return 2 * bits - 1;
}

static void save_status(const char *out, const char *name, int error, int collected)
{
	char text[4096], path[1024];
	FILE *file = fopen(status_path, "r");
	if (!file || !fgets(text, sizeof(text), file)) fail("read multislice status");
	fclose(file);
	char expected[64];
	snprintf(expected, sizeof(expected), " result=%d ", error);
	if (!strstr(text, expected)) { fprintf(stderr, "Unexpected status: %s", text); exit(1); }
	if (collected && (!strstr(text, "fetched=0 submitted=0 ") ||
		!strstr(text, "collected=1 ") || !strstr(text, "quiesced=1 guards=1 "))) {
		fprintf(stderr, "Nonfinal slice reached DMA or lost collection state: %s", text); exit(1);
	}
	if (error && (!strstr(text, "fetched=0 submitted=0 ") || !strstr(text, "collected=0 "))) {
		fprintf(stderr, "Rejected batch reached DMA: %s", text); exit(1);
	}
	if (snprintf(path, sizeof(path), "%s/%s-status.txt", out, name) >= (int)sizeof(path)) exit(1);
	file = fopen(path, "w");
	if (!file || fputs(text, file) == EOF || fclose(file)) fail("write multislice status");
}

static void write_capture(struct stream *stream, const char *out, const char *name)
{
	char path[1024];
	if (snprintf(path, sizeof(path), "%s/%s.bin", out, name) >= (int)sizeof(path)) exit(1);
	FILE *file = fopen(path, "wb");
	sync_capture(stream, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ);
	if (!file || fwrite(plane_data(&stream->capture[0]), 1, 4096, file) != 4096 ||
	    fwrite(plane_data(&stream->capture[1]), 1, 2048, file) != 2048 || fclose(file)) fail("write capture");
	sync_capture(stream, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
}

/* Every OUTPUT request completes independently. Only a final request queues
 * a completed CAPTURE; nonfinal requests leave its CPU storage untouched. */
static void submit_slice(struct stream *stream, const char *out, const char *name,
			 const u8 *nal, size_t bytes, unsigned int first_mb,
			 int predicted, unsigned int timestamp, unsigned int reference_ts,
			 int hold, int first, int error, unsigned int sequence, int change_controls)
{
	struct v4l2_ctrl_h264_sps sps = {
		.profile_idc = 66, .level_idc = 10, .constraint_set_flags = 3,
		.chroma_format_idc = 1, .max_num_ref_frames = 1,
		.pic_width_in_mbs_minus1 = 3, .pic_height_in_map_units_minus1 = 3,
		.flags = V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY | V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE,
	};
	struct v4l2_ctrl_h264_pps pps = { .flags = V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT };
	struct v4l2_ctrl_h264_slice_params slice = {
		.header_bit_size = (predicted ? 25 : 27) + ue_size(first_mb),
		.first_mb_in_slice = first_mb,
		.slice_type = predicted ? V4L2_H264_SLICE_TYPE_P : V4L2_H264_SLICE_TYPE_I,
		.disable_deblocking_filter_idc = 1,
	};
	struct v4l2_ctrl_h264_decode_params params = {
		.nal_ref_idc = predicted ? 2 : 3, .frame_num = predicted ? 1 : 0,
		.pic_order_cnt_lsb = predicted ? 2 : 0,
		.top_field_order_cnt = predicted ? 2 : 0, .bottom_field_order_cnt = predicted ? 2 : 0,
		.pic_order_cnt_bit_size = 4, .dec_ref_pic_marking_bit_size = predicted ? 1 : 2,
		.flags = predicted ? V4L2_H264_DECODE_PARAM_FLAG_PFRAME : V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC,
	};
	if (predicted) {
		params.dpb[0].reference_ts = reference_ts * 1000000000ULL;
		params.dpb[0].fields = slice.ref_pic_list0[0].fields = V4L2_H264_FRAME_REF;
		params.dpb[0].flags = V4L2_H264_DPB_ENTRY_FLAG_VALID | V4L2_H264_DPB_ENTRY_FLAG_ACTIVE;
	}
	if (change_controls) {
		params.pic_order_cnt_lsb = 2;
		params.top_field_order_cnt = params.bottom_field_order_cnt = 2;
	}
	struct v4l2_ctrl_h264_scaling_matrix scaling;
	struct v4l2_ctrl_h264_pred_weights weights = { 0 };
	memset(&scaling, 16, sizeof(scaling));
	struct v4l2_ext_control values[] = {
		{ .id=V4L2_CID_STATELESS_H264_SPS, .size=sizeof(sps), .ptr=&sps },
		{ .id=V4L2_CID_STATELESS_H264_PPS, .size=sizeof(pps), .ptr=&pps },
		{ .id=V4L2_CID_STATELESS_H264_SCALING_MATRIX, .size=sizeof(scaling), .ptr=&scaling },
		{ .id=V4L2_CID_STATELESS_H264_SLICE_PARAMS, .size=sizeof(slice), .ptr=&slice },
		{ .id=V4L2_CID_STATELESS_H264_DECODE_PARAMS, .size=sizeof(params), .ptr=&params },
		{ .id=V4L2_CID_STATELESS_H264_PRED_WEIGHTS, .size=sizeof(weights), .ptr=&weights },
	};
	int request;
	checked_ioctl(stream->media, MEDIA_IOC_REQUEST_ALLOC, &request, "REQUEST_ALLOC multislice");
	struct v4l2_ext_controls controls = { .which=V4L2_CTRL_WHICH_REQUEST_VAL,
		.request_fd=request, .count=sizeof(values)/sizeof(values[0]), .controls=values };
	checked_ioctl(stream->video, VIDIOC_S_EXT_CTRLS, &controls, "S_EXT_CTRLS multislice");
	assert(bytes <= stream->source.bytes);
	sync_mapping(&stream->source, DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE);
	memcpy(stream->source.address, nal, bytes);
	sync_mapping(&stream->source, DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
	struct v4l2_plane plane = { .bytesused=bytes, .length=stream->source.bytes };
	struct v4l2_buffer source = { .type=V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, .memory=V4L2_MEMORY_MMAP,
		.length=1, .m.planes=&plane, .request_fd=request, .timestamp.tv_sec=timestamp,
		.flags=V4L2_BUF_FLAG_REQUEST_FD | (hold ? V4L2_BUF_FLAG_M2M_HOLD_CAPTURE_BUF : 0) };
	if (first) {
		select_capture(stream, &params);
		fill_capture(stream);
		struct v4l2_plane planes[] = { {.length=stream->capture[0].bytes}, {.length=stream->capture[1].bytes} };
		struct v4l2_buffer capture = { .type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, .memory=V4L2_MEMORY_MMAP,
			.index=stream->capture_index, .length=2, .m.planes=planes };
		checked_ioctl(stream->video, VIDIOC_QBUF, &capture, "QBUF multislice capture");
	}
	checked_ioctl(stream->video, VIDIOC_QBUF, &source, "QBUF multislice source");
	checked_ioctl(request, MEDIA_REQUEST_IOC_QUEUE, NULL, "QUEUE multislice request");
	if (dequeue(stream, V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, !!error, timestamp, sequence)) exit(1);
	struct pollfd pollfd = { .fd=request, .events=POLLPRI };
	if (poll(&pollfd, 1, 1000) != 1 || !(pollfd.revents & POLLPRI)) fail("multislice request completion");
	if (hold && !error) {
		struct v4l2_plane planes[2] = { 0 };
		struct v4l2_buffer capture = { .type=V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
			.memory=V4L2_MEMORY_MMAP, .length=2, .m.planes=planes };
		if (!ioctl(stream->video, VIDIOC_DQBUF, &capture) || errno != EAGAIN) {
			fprintf(stderr, "Nonfinal request released its capture picture\n"); exit(1);
		}
		capture_untouched(stream);
	} else {
		if (dequeue(stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, !!error, timestamp, sequence)) exit(1);
		if (error) capture_untouched(stream);
		else write_capture(stream, out, name);
	}
	save_status(out, name, error, hold && !error);
	checked_ioctl(request, MEDIA_REQUEST_IOC_REINIT, NULL, "REINIT multislice request");
	close(request);
	printf("{\"slice\":\"%s\",\"first_mb\":%u,\"hold\":%d,\"error\":%d,\"timestamp\":%u}\n",
		name, first_mb, hold, error, timestamp);
	fflush(stdout);
}

static void run_picture(struct stream *stream, const char *out, const char *name,
			const u8 *packet, size_t bytes, const unsigned int *counts,
			unsigned int count, int predicted, unsigned int timestamp,
			unsigned int reference_ts, unsigned int sequence)
{
	size_t offset=0;
	unsigned int mb=0;
	for (unsigned int index=0; index<count; index++) {
		size_t end=offset;
		while (end<bytes && !(end+4<=bytes && !memcmp(packet+end,"\0\0\0\1",4))) end++;
		char label[160];
		if (index+1==count) snprintf(label,sizeof(label),"%s",name);
		else snprintf(label,sizeof(label),"%s-slice-%u",name,index);
		submit_slice(stream,out,label,packet+offset,end-offset,mb,predicted,timestamp,reference_ts,
			     index+1<count,index==0,0,sequence,0);
		mb+=counts[index];offset=end==bytes?end:end+4;
	}
	assert(mb==16 && offset==bytes);
}

int main(int argc, char **argv)
{
	if (argc!=5) { fprintf(stderr,"Usage: %s VIDEO MEDIA OUT STATUS\n",argv[0]);return 2; }
	status_path=argv[4];export_buffers=1;
	struct stream stream;
	const unsigned int two[]={8,8},four[]={4,4,4,4},uneven[]={1,5,3,7},one[]={16};
	unsigned int sixteen[16];for(unsigned int i=0;i<16;i++)sixteen[i]=1;
	struct { const char *name; const u8 *i,*p; size_t ni,np; const unsigned int *counts; unsigned int count; } cases[]={
		{"two",multislice_packet,multislice_two_p_packet,sizeof(multislice_packet),sizeof(multislice_two_p_packet),two,2},
		{"four",multislice_four_packet,multislice_four_p_packet,sizeof(multislice_four_packet),sizeof(multislice_four_p_packet),four,4},
		{"sixteen",multislice_sixteen_packet,multislice_sixteen_p_packet,sizeof(multislice_sixteen_packet),sizeof(multislice_sixteen_p_packet),sixteen,16},
		{"uneven",multislice_uneven_packet,multislice_uneven_p_packet,sizeof(multislice_uneven_packet),sizeof(multislice_uneven_p_packet),uneven,4},
		{"one",multislice_full_nal,multislice_full_p_nal,sizeof(multislice_full_nal),sizeof(multislice_full_p_nal),one,1},
	};
	for(unsigned int i=0;i<sizeof(cases)/sizeof(cases[0]);i++) {
		open_stream(&stream,argv[1],argv[2]);char label[64];
		snprintf(label,sizeof(label),"%s-i",cases[i].name);
		run_picture(&stream,argv[3],label,cases[i].i,cases[i].ni,cases[i].counts,cases[i].count,0,1,0,0);
		snprintf(label,sizeof(label),"%s-p",cases[i].name);
		run_picture(&stream,argv[3],label,cases[i].p,cases[i].np,cases[i].counts,cases[i].count,1,2,1,1);
		close_stream(&stream);
	}
	/* Every rejected batch must leave the earlier reference usable. */
	const char *faults[]={"timestamp","order","controls","header","capacity"};
	for(unsigned int i=0;i<sizeof(faults)/sizeof(faults[0]);i++) {
		open_stream(&stream,argv[1],argv[2]);char label[80];
		snprintf(label,sizeof(label),"fault-%s-reference",faults[i]);
		run_picture(&stream,argv[3],label,multislice_full_nal,sizeof(multislice_full_nal),one,1,0,1,0,0);
		snprintf(label,sizeof(label),"fault-%s-pending",faults[i]);
		u8 *large=NULL;size_t bytes=sizeof(multislice_first_nal);const u8 *initial=multislice_first_nal;
		if(i==4) { bytes=1024*1024-256;large=malloc(bytes);if(!large)fail("capacity fixture");memset(large,0xff,bytes);memcpy(large,initial,sizeof(multislice_first_nal));initial=large; }
		submit_slice(&stream,argv[3],label,initial,bytes,0,0,3,0,1,1,0,1,0);free(large);
		u8 modified[sizeof(multislice_last_nal)];memcpy(modified,multislice_last_nal,sizeof(modified));
		if(i==3)modified[20/8]^=1U<<(7-20%8);
		snprintf(label,sizeof(label),"fault-%s",faults[i]);
		submit_slice(&stream,argv[3],label,i==1?multislice_first_nal:modified,
			     i==1?sizeof(multislice_first_nal):sizeof(modified),i==1?0:8,0,i==0?4:3,0,0,0,i==4?-ENOSPC:-EINVAL,1,i==2);
		snprintf(label,sizeof(label),"fault-%s-recovery",faults[i]);
		run_picture(&stream,argv[3],label,multislice_full_p_nal,sizeof(multislice_full_p_nal),one,1,1,5,1,2);
		close_stream(&stream);
	}
	/* OUTPUT-only and CAPTURE-only streamoff release incomplete CPU packets. */
	for(unsigned int i=0;i<2;i++) {
		open_stream(&stream,argv[1],argv[2]);char label[80];
		snprintf(label,sizeof(label),"streamoff-%u-pending",i);
		submit_slice(&stream,argv[3],label,multislice_first_nal,sizeof(multislice_first_nal),0,0,7,0,1,1,0,0,0);
		enum v4l2_buf_type type=i?V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE:V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
		checked_ioctl(stream.video,VIDIOC_STREAMOFF,&type,"partial STREAMOFF");capture_untouched(&stream);
		if(!i && dequeue(&stream,V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,1,7,0))exit(1);
		checked_ioctl(stream.video,VIDIOC_STREAMON,&type,"partial STREAMON");
		snprintf(label,sizeof(label),"streamoff-%u-recovery",i);
		run_picture(&stream,argv[3],label,multislice_full_nal,sizeof(multislice_full_nal),one,1,0,8,0,1);
		close_stream(&stream);
	}
	open_stream(&stream,argv[1],argv[2]);
	submit_slice(&stream,argv[3],"close-pending",multislice_first_nal,sizeof(multislice_first_nal),0,0,7,0,1,1,0,0,0);
	close_stream(&stream);
	open_stream(&stream,argv[1],argv[2]);
	run_picture(&stream,argv[3],"close-recovery",multislice_full_nal,sizeof(multislice_full_nal),one,1,0,8,0,0);
	close_stream(&stream);
	/* Interleave held pictures on independent contexts before either final DMA. */
	struct stream other;open_stream(&stream,argv[1],argv[2]);open_stream(&other,argv[1],argv[2]);
	submit_slice(&stream,argv[3],"context-0-pending",multislice_first_nal,sizeof(multislice_first_nal),0,0,11,0,1,1,0,0,0);
	submit_slice(&other,argv[3],"context-1-pending",multislice_first_nal,sizeof(multislice_first_nal),0,0,21,0,1,1,0,0,0);
	submit_slice(&other,argv[3],"context-1-i",multislice_last_nal,sizeof(multislice_last_nal),8,0,21,0,0,0,0,0,0);
	submit_slice(&stream,argv[3],"context-0-i",multislice_last_nal,sizeof(multislice_last_nal),8,0,11,0,0,0,0,0,0);
	run_picture(&other,argv[3],"context-1-p",multislice_full_p_nal,sizeof(multislice_full_p_nal),one,1,1,22,21,1);
	run_picture(&stream,argv[3],"context-0-p",multislice_full_p_nal,sizeof(multislice_full_p_nal),one,1,1,12,11,1);
	close_stream(&other);close_stream(&stream);
	puts("{\"multislice_request_test_passed\":true}");return 0;
}
