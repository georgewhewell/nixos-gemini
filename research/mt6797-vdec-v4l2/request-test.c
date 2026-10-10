// SPDX-License-Identifier: GPL-2.0-only
/* Original public-API exerciser. Fixtures are generated from public H.264
 * syntax; compare-frame.py independently checks every returned sample.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <linux/media.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
typedef uint8_t u8;
#include "../mt6797-vdec/pcm64-fixture.h"

struct mapping { void *address; size_t bytes; int fd; };
struct stream {
	int video, media;
	struct mapping source, capture[2];
};
static const char *status_path;
static const char *fixture_directory;
static unsigned int width = 64, height = 64, storage_height = 64;
static int export_buffers;

static void fail(const char *operation)
{
	perror(operation);
	exit(1);
}

static void checked_ioctl(int fd, unsigned long command, void *arg, const char *operation)
{
	int ret;
	do { ret = ioctl(fd, command, arg); } while (ret < 0 && errno == EINTR);
	if (ret < 0)
		fail(operation);
}

static void allocate_queue(struct stream *stream, enum v4l2_buf_type type)
{
	struct v4l2_format format = { .type = type };
	struct v4l2_requestbuffers request = { .type = type, .memory = V4L2_MEMORY_MMAP, .count = 1 };
	struct v4l2_plane planes[2] = { 0 };
	struct v4l2_buffer buffer = { .type = type, .memory = V4L2_MEMORY_MMAP,
		.length = type == V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE ? 1 : 2, .m.planes = planes };
	checked_ioctl(stream->video, VIDIOC_G_FMT, &format, "G_FMT");
	format.fmt.pix_mp.width = width;
	format.fmt.pix_mp.height = height;
	checked_ioctl(stream->video, VIDIOC_TRY_FMT, &format, "TRY_FMT");
	checked_ioctl(stream->video, VIDIOC_S_FMT, &format, "S_FMT");
	if (format.fmt.pix_mp.width != width || format.fmt.pix_mp.height != storage_height ||
	    format.fmt.pix_mp.pixelformat != (buffer.length == 1 ? V4L2_PIX_FMT_H264_SLICE : V4L2_PIX_FMT_MM21)) {
		fprintf(stderr, "Unexpected negotiated format\n"); exit(1);
	}
	checked_ioctl(stream->video, VIDIOC_REQBUFS, &request, "REQBUFS");
	if (!request.count || (buffer.length == 1 && !(request.capabilities & V4L2_BUF_CAP_SUPPORTS_REQUESTS))) {
		fprintf(stderr, "Queue does not support the required allocation/request API\n"); exit(1);
	}
	checked_ioctl(stream->video, VIDIOC_QUERYBUF, &buffer, "QUERYBUF");
	for (unsigned int i = 0; i < buffer.length; i++) {
		struct mapping *mapping = buffer.length == 1 ? &stream->source : &stream->capture[i];
		mapping->bytes = planes[i].length;
		mapping->fd = -1;
		int fd = stream->video;
		off_t offset = planes[i].m.mem_offset;
		if (export_buffers) {
			struct v4l2_exportbuffer exported = { .type = type, .plane = i, .flags = O_RDWR | O_CLOEXEC };
			checked_ioctl(stream->video, VIDIOC_EXPBUF, &exported, "EXPBUF");
			mapping->fd = fd = exported.fd;
			offset = 0;
		}
		mapping->address = mmap(NULL, mapping->bytes, PROT_READ | PROT_WRITE, MAP_SHARED,
					fd, offset);
		if (mapping->address == MAP_FAILED)
			fail("mmap");
	}
}

static void open_stream(struct stream *stream, const char *video, const char *media)
{
	struct v4l2_capability cap;
	memset(stream, 0, sizeof(*stream));
	stream->video = open(video, O_RDWR | O_NONBLOCK | O_CLOEXEC);
	if (stream->video < 0) fail("open video");
	stream->media = open(media, O_RDWR | O_CLOEXEC);
	if (stream->media < 0) fail("open media");
	checked_ioctl(stream->video, VIDIOC_QUERYCAP, &cap, "QUERYCAP");
	if (strcmp((char *)cap.driver, "mt6797-vdec")) {
		fprintf(stderr, "Unexpected video driver\n"); exit(1);
	}
	allocate_queue(stream, V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE);
	allocate_queue(stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE);
	for (unsigned int i = 0; i < 2; i++) {
		enum v4l2_buf_type type = i ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
		checked_ioctl(stream->video, VIDIOC_STREAMON, &type, "STREAMON");
	}
}

static void close_stream(struct stream *stream)
{
	size_t luma_size = width * storage_height;
	u8 *snapshot = malloc(luma_size * 3 / 2);
	if (!snapshot) fail("snapshot allocation");
	memcpy(snapshot, stream->capture[0].address, luma_size);
	memcpy(snapshot + luma_size, stream->capture[1].address, luma_size / 2);
	for (unsigned int i = 0; i < 2; i++) {
		enum v4l2_buf_type type = i ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
		checked_ioctl(stream->video, VIDIOC_STREAMOFF, &type, "STREAMOFF");
	}
	close(stream->media);
	close(stream->video);
	/* With exported mappings, the video file can close while these independent
	 * DMA-buffer references keep the completed CPU queue storage alive.
	 */
	if (memcmp(snapshot, stream->capture[0].address, luma_size) ||
	    memcmp(snapshot + luma_size, stream->capture[1].address, luma_size / 2)) {
		fprintf(stderr, "Capture storage changed across video close\n"); exit(1);
	}
	free(snapshot);
	munmap(stream->source.address, stream->source.bytes);
	if (stream->source.fd >= 0) close(stream->source.fd);
	for (unsigned int i = 0; i < 2; i++) {
		munmap(stream->capture[i].address, stream->capture[i].bytes);
		if (stream->capture[i].fd >= 0) close(stream->capture[i].fd);
	}
}

static int64_t milliseconds(void)
{
	struct timespec now;
	if (clock_gettime(CLOCK_MONOTONIC, &now)) fail("clock_gettime");
	return now.tv_sec * 1000LL + now.tv_nsec / 1000000;
}

static int dequeue(struct stream *stream, enum v4l2_buf_type type, int expect_error,
		    unsigned int timestamp, unsigned int sequence)
{
	struct v4l2_plane planes[2] = { 0 };
	struct v4l2_buffer buffer = { .type = type, .memory = V4L2_MEMORY_MMAP,
		.length = type == V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE ? 1 : 2, .m.planes = planes };
	int64_t deadline = milliseconds() + 5000;
	for (;;) {
		if (!ioctl(stream->video, VIDIOC_DQBUF, &buffer)) break;
		if (errno == EINTR) continue;
		if (errno != EAGAIN) fail("DQBUF");
		if (milliseconds() >= deadline) {
			fprintf(stderr, "DQBUF timed out\n"); exit(1);
		}
		struct pollfd pollfd = { .fd = stream->video, .events = POLLIN | POLLOUT };
		if (poll(&pollfd, 1, 50) < 0 && errno != EINTR) fail("poll video");
	}
	int bad = 0;
	if (!!(buffer.flags & V4L2_BUF_FLAG_ERROR) != expect_error || buffer.index) {
		fprintf(stderr, "Unexpected completed buffer flags %#x\n", buffer.flags); bad = 1;
	}
	if (type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE &&
	    (buffer.timestamp.tv_sec != timestamp || buffer.timestamp.tv_usec ||
	     buffer.sequence != sequence || planes[0].bytesused != (expect_error ? 0U : width * storage_height) ||
	     planes[1].bytesused != (expect_error ? 0U : width * storage_height / 2))) {
		fprintf(stderr, "Unexpected capture metadata or payload sizes\n"); bad = 1;
	}
	return bad;
}

static void decode(struct stream *stream, const char *out, const char *name,
		   const u8 *nal, size_t bytes, int predicted, int patterned,
		   int expect_error, unsigned int timestamp, unsigned int sequence)
{
	u8 input[130816];
	if (fixture_directory) {
		const char *fixture = !strcmp(name, "missing-reference") ||
			!strcmp(name, "fault-pskip") || !strcmp(name, "fault-stale") ||
			!strcmp(name, "fault-retained") || !strcmp(name, "reference-recovery") ||
			!strcmp(name, "reference-after-reject") ? "pcm64-p" :
			!strcmp(name, "motion-reference") || !strcmp(name, "fault-pcm") ||
			!strcmp(name, "fault-truncated") || !strcmp(name, "fault-scaling") ||
			!strcmp(name, "weight-reference") ? "pcm64" :
			!strcmp(name, "fault-weight") ? "weighted64-p" :
			!strcmp(name, "fault-refmissing") ? "multi16-p" :
			!strcmp(name, "fault-refmetadata") ? "multi2-p" :
			!strcmp(name, "fault-b-list1") || !strcmp(name, "fault-b-poc") ? "fault-b2" : name;
		char path[1024];
		if (snprintf(path, sizeof(path), "%s/%s.nal", fixture_directory, fixture) >= (int)sizeof(path)) {
			fprintf(stderr, "Fixture path too long\n"); exit(1);
		}
		FILE *file = fopen(path, "rb");
		if (!file) fail("open fixture");
		bytes = fread(input, 1, sizeof(input), file);
		if (ferror(file) || !bytes || fgetc(file) != EOF) {
			fprintf(stderr, "Invalid or oversized fixture\n"); exit(1);
		}
		fclose(file);
		nal = input;
	}
	if (!strcmp(name, "fault-truncated"))
		bytes = 32; /* Complete I_PCM header, insufficient first-MB PCM data. */
	if (!strcmp(name, "fault-retained") || !strcmp(name, "reference-after-reject")) {
		if (!fixture_directory) {
			memcpy(input, nal, bytes);
			nal = input;
		}
		/* Original P-skip syntax: three one-bit UE fields precede frame_num,
		 * followed by four POC bits. Change frame_num1/POC2 to2/4.
		 */
		input[1] = (input[1] & ~0x1fU) | (2U << 1);
		input[2] = (input[2] & ~0xe0U) | (4U << 5);
	}
	struct v4l2_ctrl_h264_sps sps = {
		.profile_idc = 66, .level_idc = width * height / 256 <= 99 ? 10 : 11, .constraint_set_flags = 3,
		.chroma_format_idc = 1, .max_num_ref_frames = 1,
		.pic_width_in_mbs_minus1 = width / 16 - 1, .pic_height_in_map_units_minus1 = height / 16 - 1,
		.flags = V4L2_H264_SPS_FLAG_FRAME_MBS_ONLY | V4L2_H264_SPS_FLAG_DIRECT_8X8_INFERENCE,
	};
	struct v4l2_ctrl_h264_pps pps = { .flags = V4L2_H264_PPS_FLAG_DEBLOCKING_FILTER_CONTROL_PRESENT };
	struct v4l2_ctrl_h264_slice_params slice = {
		.header_bit_size = predicted ? 26 : patterned ? 38 : 28,
		.slice_qp_delta = patterned ? 20 : 0,
		.slice_type = predicted ? V4L2_H264_SLICE_TYPE_P : V4L2_H264_SLICE_TYPE_I,
		.disable_deblocking_filter_idc = 1,
	};
	struct v4l2_ctrl_h264_decode_params params = {
		.nal_ref_idc = predicted ? 2 : 3,
		.flags = predicted ? V4L2_H264_DECODE_PARAM_FLAG_PFRAME : V4L2_H264_DECODE_PARAM_FLAG_IDR_PIC,
		.frame_num = predicted ? 1 : 0, .pic_order_cnt_lsb = predicted ? 2 : 0,
		.top_field_order_cnt = predicted ? 2 : 0, .bottom_field_order_cnt = predicted ? 2 : 0,
	};
	if (predicted) {
		params.dpb[0].reference_ts = 1000000000ULL;
		params.dpb[0].fields = V4L2_H264_FRAME_REF;
		params.dpb[0].flags = V4L2_H264_DPB_ENTRY_FLAG_VALID | V4L2_H264_DPB_ENTRY_FLAG_ACTIVE;
		slice.ref_pic_list0[0].fields = V4L2_H264_FRAME_REF;
	}
	if (!strcmp(name, "fault-retained") || !strcmp(name, "reference-after-reject")) {
		params.frame_num = 2;
		params.pic_order_cnt_lsb = 4;
		params.top_field_order_cnt = params.bottom_field_order_cnt = 4;
		params.dpb[0].reference_ts = 2000000000ULL;
		params.dpb[0].frame_num = params.dpb[0].pic_num = 1;
		params.dpb[0].top_field_order_cnt = params.dpb[0].bottom_field_order_cnt = 2;
	}
	if (!strcmp(name, "fault-refmissing") || !strcmp(name, "fault-refmetadata")) {
		unsigned int count = !strcmp(name, "fault-refmissing") ? 16 : 2;
		sps.profile_idc = 77;
		sps.constraint_set_flags = 0;
		sps.log2_max_frame_num_minus4 = 2;
		sps.log2_max_pic_order_cnt_lsb_minus4 = 2;
		sps.max_num_ref_frames = count;
		pps.num_ref_idx_l0_default_active_minus1 = count - 1;
		slice.num_ref_idx_l0_active_minus1 = count - 1;
		slice.header_bit_size = 30;
		params.frame_num = count;
		params.pic_order_cnt_lsb = count * 2;
		params.top_field_order_cnt = params.bottom_field_order_cnt = count * 2;
		for (unsigned int i = 1; i < count; i++) {
			params.dpb[i] = params.dpb[0];
			params.dpb[i].reference_ts = (i + 1) * 1000000000ULL;
			params.dpb[i].frame_num = params.dpb[i].pic_num = i;
			params.dpb[i].top_field_order_cnt = params.dpb[i].bottom_field_order_cnt = 2 * i;
			slice.ref_pic_list0[i].fields = V4L2_H264_FRAME_REF;
			slice.ref_pic_list0[i].index = i;
		}
		if (!strcmp(name, "fault-refmetadata"))
			params.dpb[1].bottom_field_order_cnt++; /* Real retained second picture; wrong metadata. */
	}
	if (!strcmp(name, "fault-b-list1") || !strcmp(name, "fault-b-poc")) {
		sps.profile_idc = 77;
		sps.constraint_set_flags = 0;
		sps.log2_max_frame_num_minus4 = sps.log2_max_pic_order_cnt_lsb_minus4 = 2;
		sps.max_num_ref_frames = 2;
		pps.num_ref_idx_l0_default_active_minus1 = pps.num_ref_idx_l1_default_active_minus1 = 1;
		slice.num_ref_idx_l0_active_minus1 = slice.num_ref_idx_l1_active_minus1 = 1;
		slice.header_bit_size = 33;
		slice.slice_type = V4L2_H264_SLICE_TYPE_B;
		slice.flags = V4L2_H264_SLICE_FLAG_DIRECT_SPATIAL_MV_PRED;
		params.flags = V4L2_H264_DECODE_PARAM_FLAG_BFRAME;
		params.nal_ref_idc = 0;
		params.frame_num = 2;
		params.pic_order_cnt_lsb = 1;
		params.top_field_order_cnt = params.bottom_field_order_cnt = 1;
		params.dpb[1] = params.dpb[0];
		params.dpb[1].reference_ts = 2000000000ULL;
		params.dpb[1].frame_num = params.dpb[1].pic_num = 1;
		params.dpb[1].top_field_order_cnt = params.dpb[1].bottom_field_order_cnt = 2;
		for (unsigned int i = 0; i < 2; i++) {
			slice.ref_pic_list0[i].fields = slice.ref_pic_list1[i].fields = V4L2_H264_FRAME_REF;
			slice.ref_pic_list0[i].index = i;
			slice.ref_pic_list1[i].index = 1 - i;
		}
		if (!strcmp(name, "fault-b-list1")) slice.ref_pic_list1[1].index = 2;
		else params.top_field_order_cnt = params.bottom_field_order_cnt = 131072;
	}
	struct v4l2_ctrl_h264_scaling_matrix scaling;
	struct v4l2_ctrl_h264_pred_weights weights = { 0 };
	memset(&scaling, 16, sizeof(scaling));
	if (!strcmp(name, "fault-weight")) {
		sps.profile_idc = 77;
		sps.constraint_set_flags = 0;
		pps.flags |= V4L2_H264_PPS_FLAG_WEIGHTED_PRED;
		slice.header_bit_size = 84;
		params.pic_order_cnt_bit_size = 4;
		params.dec_ref_pic_marking_bit_size = 1;
		weights.luma_log2_weight_denom = 1;
		weights.chroma_log2_weight_denom = 2;
		weights.weight_factors[0].luma_weight[0] = 3;
		/* In-band offset is -12: mismatch must fail before any DMA. */
		weights.weight_factors[0].luma_offset[0] = -11;
		weights.weight_factors[0].chroma_weight[0][0] = 3;
		weights.weight_factors[0].chroma_weight[0][1] = -3;
		weights.weight_factors[0].chroma_offset[0][0] = 17;
		weights.weight_factors[0].chroma_offset[0][1] = 127;
	}
	if (!strcmp(name, "fault-scaling")) {
		sps.profile_idc = 100;
		sps.constraint_set_flags = 0;
		pps.flags |= V4L2_H264_PPS_FLAG_SCALING_MATRIX_PRESENT;
		scaling.scaling_list_8x8[1][63] = 0;
	}
	struct v4l2_ext_control values[] = {
		{ .id = V4L2_CID_STATELESS_H264_SPS, .size = sizeof(sps), .ptr = &sps },
		{ .id = V4L2_CID_STATELESS_H264_PPS, .size = sizeof(pps), .ptr = &pps },
		{ .id = V4L2_CID_STATELESS_H264_SCALING_MATRIX, .size = sizeof(scaling), .ptr = &scaling },
		{ .id = V4L2_CID_STATELESS_H264_SLICE_PARAMS, .size = sizeof(slice), .ptr = &slice },
		{ .id = V4L2_CID_STATELESS_H264_DECODE_PARAMS, .size = sizeof(params), .ptr = &params },
		{ .id = V4L2_CID_STATELESS_H264_PRED_WEIGHTS, .size = sizeof(weights), .ptr = &weights },
	};
	int request;
	checked_ioctl(stream->media, MEDIA_IOC_REQUEST_ALLOC, &request, "REQUEST_ALLOC");
	struct v4l2_ext_controls controls = { .which = V4L2_CTRL_WHICH_REQUEST_VAL,
		.request_fd = request, .count = sizeof(values) / sizeof(values[0]), .controls = values };
	checked_ioctl(stream->video, VIDIOC_S_EXT_CTRLS, &controls, "S_EXT_CTRLS request");
	memcpy(stream->source.address, nal, bytes);
	memset(stream->capture[0].address, 0x79, stream->capture[0].bytes);
	memset(stream->capture[1].address, 0x79, stream->capture[1].bytes);
	struct v4l2_plane source_plane = { .bytesused = bytes, .length = stream->source.bytes };
	struct v4l2_buffer source = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,
		.memory = V4L2_MEMORY_MMAP, .length = 1, .m.planes = &source_plane,
		.flags = V4L2_BUF_FLAG_REQUEST_FD, .request_fd = request, .timestamp.tv_sec = timestamp };
	struct v4l2_plane capture_planes[] = { { .length = stream->capture[0].bytes },
		{ .length = stream->capture[1].bytes } };
	struct v4l2_buffer capture = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
		.memory = V4L2_MEMORY_MMAP, .length = 2, .m.planes = capture_planes };
	checked_ioctl(stream->video, VIDIOC_QBUF, &capture, "QBUF capture");
	checked_ioctl(stream->video, VIDIOC_QBUF, &source, "QBUF request source");
	checked_ioctl(request, MEDIA_REQUEST_IOC_QUEUE, NULL, "REQUEST_QUEUE");
	int bad = dequeue(stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, expect_error, timestamp, sequence);
	if (!strcmp(name, "fault-scaling") || !strcmp(name, "fault-weight") ||
	    !strcmp(name, "fault-refmissing") || !strcmp(name, "fault-refmetadata") ||
	    !strcmp(name, "fault-b-list1") || !strcmp(name, "fault-b-poc")) {
		for (unsigned int plane = 0; plane < 2; plane++)
			for (size_t byte = 0; byte < stream->capture[plane].bytes; byte++)
				if (((u8 *)stream->capture[plane].address)[byte] != 0x79) {
					fprintf(stderr, "Rejected control request changed capture storage\n"); exit(1);
				}
	}

	bad |= dequeue(stream, V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, expect_error, timestamp, sequence);
	struct pollfd pollfd = { .fd = request, .events = POLLPRI };
	if (poll(&pollfd, 1, 1000) != 1 || !(pollfd.revents & POLLPRI)) {
		fprintf(stderr, "Request did not complete\n"); exit(1);
	}
	if (!expect_error) {
		char path[1024];
		if (snprintf(path, sizeof(path), "%s/%s.bin", out, name) >= (int)sizeof(path)) {
			fprintf(stderr, "Output path too long\n"); exit(1);
		}
		FILE *file = fopen(path, "wb");
		if (!file) fail("output file");
		if (fwrite(stream->capture[0].address, 1, width * storage_height, file) != width * storage_height ||
		    fwrite(stream->capture[1].address, 1, width * storage_height / 2, file) != width * storage_height / 2 || fclose(file)) fail("write output");
	}
	checked_ioctl(request, MEDIA_REQUEST_IOC_REINIT, NULL, "REQUEST_REINIT");
	close(request);
	char status[2048], status_output[1024];
	FILE *status_file = fopen(status_path, "r");
	if (!status_file || !fgets(status, sizeof(status), status_file)) fail("read cached job status");
	fclose(status_file);
	if (snprintf(status_output, sizeof(status_output), "%s/%s-status.txt", out, name) >= (int)sizeof(status_output)) {
		fprintf(stderr, "Status path too long\n"); exit(1);
	}
	status_file = fopen(status_output, "w");
	if (!status_file || fputs(status, status_file) == EOF || fclose(status_file)) fail("write cached job status");
	printf("{\"fixture\":\"%s\",\"expected_error\":%d,\"timestamp\":%u,\"sequence\":%u,\"request_completed\":true}\n",
		name, expect_error, timestamp, sequence);
	fflush(stdout);
	/* Preserve completed capture bytes and cached status even on a failed
	 * metadata check; the host still independently decides qualification.
	 */
	if (bad) exit(1);
}

int main(int argc, char **argv)
{
	struct stream stream;
	if (argc != 5 && argc != 9 && argc != 10) {
		fprintf(stderr, "Usage: %s VIDEO MEDIA OUTPUT_DIRECTORY CACHED_STATUS_PATH [FIXTURES WIDTH HEIGHT mmap|export [faults]]\n", argv[0]); return 2;
	}
	status_path = argv[4];
	if (argc >= 9) {
		fixture_directory = argv[5];
		width = strtoul(argv[6], NULL, 10);
		height = strtoul(argv[7], NULL, 10);
		if (width < 64 || width > 320 || width % 16 || height < 64 || height > 256 || height % 16 ||
		    (strcmp(argv[8], "mmap") && strcmp(argv[8], "export")) ||
		    (argc == 10 && strcmp(argv[9], "faults"))) {
			fprintf(stderr, "Invalid test geometry or mapping mode\n"); return 2;
		}
		export_buffers = !strcmp(argv[8], "export");
	}
	storage_height = (height + 31) & ~31U;
	open_stream(&stream, argv[1], argv[2]);
	decode(&stream, argv[3], "pcm64", pcm64_nal, sizeof(pcm64_nal), 0, 0, 0, 1, 0);
	decode(&stream, argv[3], "pcm64-p", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 2, 1);
	close_stream(&stream);
	open_stream(&stream, argv[1], argv[2]);
	decode(&stream, argv[3], "grey64", grey64_nal, sizeof(grey64_nal), 0, 0, 0, 1, 0);
	decode(&stream, argv[3], "pattern64", pattern64_nal, sizeof(pattern64_nal), 0, 1, 0, 2, 1);
	close_stream(&stream);
	open_stream(&stream, argv[1], argv[2]);
	decode(&stream, argv[3], "missing-reference", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 2, 0);
	close_stream(&stream);
	if (fixture_directory) {
		char path[1024];
		if (snprintf(path, sizeof(path), "%s/pcm64-motion.nal", fixture_directory) >= (int)sizeof(path)) return 2;
		if (!access(path, R_OK)) {
			open_stream(&stream, argv[1], argv[2]);
			decode(&stream, argv[3], "motion-reference", pcm64_nal, sizeof(pcm64_nal), 0, 0, 0, 1, 0);
			decode(&stream, argv[3], "pcm64-motion", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 2, 1);
			close_stream(&stream);
		}
	}
	if (argc == 10) {
		open_stream(&stream, argv[1], argv[2]);
		decode(&stream, argv[3], "fault-pcm", pcm64_nal, sizeof(pcm64_nal), 0, 0, 0, 1, 0);
		decode(&stream, argv[3], "fault-pskip", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 2, 1);
		decode(&stream, argv[3], "fault-truncated", pcm64_nal, sizeof(pcm64_nal), 0, 0, 1, 3, 2);
		decode(&stream, argv[3], "fault-stale", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 4, 3);
		decode(&stream, argv[3], "fault-retained", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 5, 4);
		decode(&stream, argv[3], "fault-scaling", pcm64_nal, sizeof(pcm64_nal), 0, 0, 1, 6, 5);
		close_stream(&stream);
		if (width == 64 && height == 64) {
			open_stream(&stream, argv[1], argv[2]);
			decode(&stream, argv[3], "weight-reference", pcm64_nal, sizeof(pcm64_nal), 0, 0, 0, 1, 0);
			decode(&stream, argv[3], "fault-weight", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 2, 1);
			decode(&stream, argv[3], "reference-recovery", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 2, 2);
			decode(&stream, argv[3], "fault-refmissing", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 3, 3);
			decode(&stream, argv[3], "fault-refmetadata", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 4, 4);
			decode(&stream, argv[3], "fault-b-list1", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 5, 5);
			decode(&stream, argv[3], "fault-b-poc", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 6, 6);
			decode(&stream, argv[3], "reference-after-reject", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 7, 7);
			close_stream(&stream);
		}
	}
	puts("{\"public_api_test_passed\":true}");
	return 0;
}
