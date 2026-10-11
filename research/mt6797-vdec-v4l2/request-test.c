// SPDX-License-Identifier: GPL-2.0-only
/* Original public-API exerciser. Fixtures are generated from public H.264
 * syntax; compare-frame.py independently checks every returned sample.
 */
#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <drm/drm.h>
#include <drm/panfrost_drm.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/dma-buf.h>
#include <linux/media.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
typedef uint8_t u8;
#include "../mt6797-vdec/pcm64-fixture.h"

#define CAPTURE_COUNT (V4L2_H264_NUM_DPB_ENTRIES + 1)
struct mapping { void *address; size_t bytes, data_offset; int fd; };
struct stream {
	int video, media;
	struct mapping source, storage[CAPTURE_COUNT][2], *capture;
	uint64_t timestamps[CAPTURE_COUNT];
	unsigned int capture_count, capture_index;
};
static const char *status_path;
static const char *fixture_directory;
static unsigned int width = 64, height = 64, storage_height = 64;
static int export_buffers;
static int buffers_only;
static int create_buffers_checked;

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

/* Exported mappings need cache ownership even when their exporter happens to
 * be coherent. The two capture views may refer to the same complete object.
 */
static void sync_mapping(struct mapping *mapping, uint64_t flags)
{
	if (mapping->fd < 0) return;
	struct dma_buf_sync sync = { .flags = flags };
	int ret;
	do { ret = ioctl(mapping->fd, DMA_BUF_IOCTL_SYNC, &sync); }
	while (ret < 0 && (errno == EINTR || errno == EAGAIN));
	if (ret < 0) fail("DMA_BUF_IOCTL_SYNC");
}

static u8 *plane_data(struct mapping *mapping)
{
	return (u8 *)mapping->address + mapping->data_offset;
}

static void sync_capture(struct stream *stream, uint64_t flags)
{
	for (unsigned int i = 0; i < 2; i++) sync_mapping(&stream->capture[i], flags);
}

static void fill_capture(struct stream *stream)
{
	size_t luma = width * storage_height;
	sync_capture(stream, DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE);
	memset(plane_data(&stream->capture[0]), 0x79, luma);
	memset(plane_data(&stream->capture[1]), 0x79, luma / 2);
	sync_capture(stream, DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
}

static void capture_untouched(struct stream *stream)
{
	size_t luma = width * storage_height;
	sync_capture(stream, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ);
	for (unsigned int i = 0; i < 2; i++)
		for (size_t byte = 0; byte < (i ? luma / 2 : luma); byte++)
			if (plane_data(&stream->capture[i])[byte] != 0x79) {
				fprintf(stderr, "Incomplete/rejected picture changed capture pixels\n"); exit(1);
			}
	sync_capture(stream, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
}

static void select_capture(struct stream *stream,
			   const struct v4l2_ctrl_h264_decode_params *params)
{
	for (unsigned int i = 0; i < stream->capture_count; i++) {
		int protected = 0;
		for (unsigned int j = 0; j < V4L2_H264_NUM_DPB_ENTRIES; j++) {
			const struct v4l2_h264_dpb_entry *entry = &params->dpb[j];
			unsigned int flags = V4L2_H264_DPB_ENTRY_FLAG_VALID | V4L2_H264_DPB_ENTRY_FLAG_ACTIVE;
			if (stream->timestamps[i] && (entry->flags & flags) == flags &&
			    entry->reference_ts == stream->timestamps[i]) protected = 1;
		}
		if (!protected) {
			stream->capture_index = i;
			stream->capture = stream->storage[i];
			stream->timestamps[i] = 0;
			return;
		}
	}
	fprintf(stderr, "No capture buffer outside the active DPB\n"); exit(1);
}

static void allocate_queue(struct stream *stream, enum v4l2_buf_type type)
{
	struct v4l2_format format = { .type = type };
	struct v4l2_requestbuffers request = { .type = type, .memory = V4L2_MEMORY_MMAP,
		.count = type == V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE ? 1 : CAPTURE_COUNT };
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
	if (!request.count || (buffer.length == 2 && request.count < CAPTURE_COUNT) ||
	    (buffers_only && request.count != CAPTURE_COUNT) ||
	    (buffer.length == 1 && !(request.capabilities & V4L2_BUF_CAP_SUPPORTS_REQUESTS))) {
		fprintf(stderr, "Queue does not support the required allocation/request API\n"); exit(1);
	}
	if (buffer.length == 2) stream->capture_count = CAPTURE_COUNT;
	for (unsigned int index = 0; index < (buffer.length == 1 ? 1 : stream->capture_count); index++) {
		buffer.index = index;
		checked_ioctl(stream->video, VIDIOC_QUERYBUF, &buffer, "QUERYBUF");
		for (unsigned int i = 0; i < buffer.length; i++) {
			struct mapping *mapping = buffer.length == 1 ? &stream->source : &stream->storage[index][i];
			mapping->bytes = planes[i].length;
			mapping->data_offset = planes[i].data_offset;
			size_t payload = buffer.length == 1 ? 0 : width * storage_height / (i ? 2 : 1);
			if (mapping->data_offset > mapping->bytes || payload > mapping->bytes - mapping->data_offset) {
				fprintf(stderr, "Capture offset exceeds mapped storage\n"); exit(1);
			}
			mapping->fd = -1;
			int fd = stream->video;
			off_t offset = planes[i].m.mem_offset;
			if (export_buffers) {
				struct v4l2_exportbuffer exported = { .type = type, .index = index,
					.plane = i, .flags = O_RDWR | O_CLOEXEC };
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
	if (buffer.length == 2) stream->capture = stream->storage[0];
}

static void open_device(struct stream *stream, const char *video, const char *media)
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
}

static void open_stream(struct stream *stream, const char *video, const char *media)
{
	open_device(stream, video, media);
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
	sync_capture(stream, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ);
	memcpy(snapshot, plane_data(&stream->capture[0]), luma_size);
	memcpy(snapshot + luma_size, plane_data(&stream->capture[1]), luma_size / 2);
	sync_capture(stream, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
	for (unsigned int i = 0; i < 2; i++) {
		enum v4l2_buf_type type = i ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
		checked_ioctl(stream->video, VIDIOC_STREAMOFF, &type, "STREAMOFF");
	}
	close(stream->media);
	close(stream->video);
	/* With exported mappings, the video file can close while these independent
	 * DMA-buffer references keep the completed hardware storage alive.
	 */
	sync_capture(stream, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ);
	if (memcmp(snapshot, plane_data(&stream->capture[0]), luma_size) ||
	    memcmp(snapshot + luma_size, plane_data(&stream->capture[1]), luma_size / 2)) {
		fprintf(stderr, "Capture storage changed across video close\n"); exit(1);
	}
	sync_capture(stream, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
	free(snapshot);
	munmap(stream->source.address, stream->source.bytes);
	if (stream->source.fd >= 0) close(stream->source.fd);
	for (unsigned int index = 0; index < stream->capture_count; index++)
		for (unsigned int i = 0; i < 2; i++) {
			struct mapping *mapping = &stream->storage[index][i];
			munmap(mapping->address, mapping->bytes);
			if (mapping->fd >= 0) close(mapping->fd);
		}
}

/* CREATE_BUFS preserves requested view lengths, while both exports own the
 * complete page-aligned Y/C/motion allocation. No queue is streamed here.
 */
static void test_create_buffers(const char *video, const char *media)
{
	const unsigned int luma = 5120, backing = 196608;
	const unsigned int valid[][2] = {
		{ luma, luma * 3 / 2 }, { backing + 1, backing + 8193 },
		{ backing + 12289, backing + 3 }, { backing, backing },
	};
	const unsigned int invalid[][2] = {
		{ luma, luma / 2 }, { luma - 1, luma * 3 / 2 },
		{ backing, luma * 3 / 2 - 1 }, { UINT32_MAX, backing },
		{ backing, UINT32_MAX },
	};
	struct stream stream;
	struct v4l2_format format = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE };
	long page = sysconf(_SC_PAGESIZE);
	if (page <= 0 || ((unsigned long)page & ((unsigned long)page - 1)))
		fail("CREATE_BUFS page size");
	open_device(&stream, video, media);
	format.fmt.pix_mp.width = width;
	format.fmt.pix_mp.height = height;
	checked_ioctl(stream.video, VIDIOC_S_FMT, &format, "CREATE_BUFS output geometry");
	format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
	checked_ioctl(stream.video, VIDIOC_G_FMT, &format, "CREATE_BUFS capture format");
	if (format.fmt.pix_mp.width != 80 || format.fmt.pix_mp.height != 64 ||
	    format.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_MM21 ||
	    format.fmt.pix_mp.num_planes != 2 ||
	    format.fmt.pix_mp.plane_fmt[0].sizeimage != valid[0][0] ||
	    format.fmt.pix_mp.plane_fmt[1].sizeimage != valid[0][1]) {
		fprintf(stderr, "Unexpected CREATE_BUFS format\n"); exit(1);
	}
	for (unsigned int i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
		struct v4l2_create_buffers create = { .count = 1,
			.memory = V4L2_MEMORY_MMAP, .format = format };
		for (unsigned int p = 0; p < 2; p++)
			create.format.fmt.pix_mp.plane_fmt[p].sizeimage = invalid[i][p];
		int ret;
		do { ret = ioctl(stream.video, VIDIOC_CREATE_BUFS, &create); }
		while (ret < 0 && errno == EINTR);
		if (ret != -1 || errno != EINVAL) {
			fprintf(stderr, "Invalid CREATE_BUFS request accepted or wrong error\n"); exit(1);
		}
	}
	for (unsigned int i = 0; i < sizeof(valid) / sizeof(valid[0]); i++) {
		struct v4l2_create_buffers create = { .count = 1,
			.memory = V4L2_MEMORY_MMAP, .format = format };
		/* The first allocation must work directly from the advertised format. */
		if (i)
			for (unsigned int p = 0; p < 2; p++)
				create.format.fmt.pix_mp.plane_fmt[p].sizeimage = valid[i][p];
		checked_ioctl(stream.video, VIDIOC_CREATE_BUFS, &create, "CREATE_BUFS");
		if (create.count != 1 || create.index != i ||
		    create.format.fmt.pix_mp.plane_fmt[0].sizeimage != valid[i][0] ||
		    create.format.fmt.pix_mp.plane_fmt[1].sizeimage != valid[i][1]) {
			fprintf(stderr, "CREATE_BUFS changed requested lengths/index\n"); exit(1);
		}
	}
	/* Inspect after all four allocations: later CREATE_BUFS calls must not
	 * change the lengths or capacity of an existing buffer.
	 */
	for (unsigned int i = 0; i < sizeof(valid) / sizeof(valid[0]); i++) {
		struct v4l2_plane planes[2] = { 0 };
		struct v4l2_buffer buffer = { .type = format.type, .memory = V4L2_MEMORY_MMAP,
			.index = i, .length = 2, .m.planes = planes };
		struct mapping exported[2], mapped[2];
		size_t capacity = backing;
		for (unsigned int p = 0; p < 2; p++)
			if (capacity < valid[i][p]) capacity = valid[i][p];
		capacity = (capacity + page - 1) & ~((size_t)page - 1);
		checked_ioctl(stream.video, VIDIOC_QUERYBUF, &buffer, "QUERYBUF created capture");
		for (unsigned int p = 0; p < 2; p++) {
			struct v4l2_exportbuffer exp = { .type = format.type, .index = i,
				.plane = p, .flags = O_RDWR | O_CLOEXEC };
			if (planes[p].length != valid[i][p] ||
			    planes[p].data_offset != (p ? luma : 0) ||
			    planes[p].bytesused != planes[p].data_offset) {
				fprintf(stderr, "CREATE_BUFS queried lengths/offsets changed\n"); exit(1);
			}
			checked_ioctl(stream.video, VIDIOC_EXPBUF, &exp, "EXPBUF created capture");
			if (lseek(exp.fd, 0, SEEK_END) != (off_t)capacity) {
				fprintf(stderr, "CREATE_BUFS export capacity differs\n"); exit(1);
			}
			exported[p] = (struct mapping) { .fd = exp.fd, .bytes = capacity };
			exported[p].address = mmap(NULL, capacity, PROT_READ | PROT_WRITE,
				MAP_SHARED, exp.fd, 0);
			mapped[p] = (struct mapping) { .fd = -1,
				.bytes = (valid[i][p] + page - 1) & ~((size_t)page - 1) };
			mapped[p].address = mmap(NULL, mapped[p].bytes, PROT_READ | PROT_WRITE,
				MAP_SHARED, stream.video, planes[p].m.mem_offset);
			if (exported[p].address == MAP_FAILED || mapped[p].address == MAP_FAILED)
				fail("mmap created capture");
		}
		sync_mapping(&exported[0], DMA_BUF_SYNC_START | DMA_BUF_SYNC_RW);
		for (size_t byte = 0; byte < capacity; byte++)
			if (((u8 *)exported[0].address)[byte]) {
				fprintf(stderr, "CREATE_BUFS allocation is not zeroed\n"); exit(1);
			}
		memset(exported[0].address, 0x41 + i, capacity);
		sync_mapping(&exported[1], DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ);
		for (size_t byte = 0; byte < capacity; byte++)
			if (((u8 *)exported[0].address)[byte] != 0x41 + i) {
				fprintf(stderr, "CREATE_BUFS nested access lost contents\n"); exit(1);
			}
		for (unsigned int p = 0; p < 2; p++) {
			if (memcmp(exported[0].address, exported[p].address, capacity) ||
			    memcmp(exported[0].address, mapped[p].address, mapped[p].bytes)) {
				fprintf(stderr, "CREATE_BUFS aliases differ\n"); exit(1);
			}
		}
		sync_mapping(&exported[0], DMA_BUF_SYNC_END | DMA_BUF_SYNC_RW);
		sync_mapping(&exported[1], DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
		checked_ioctl(stream.video, VIDIOC_QBUF, &buffer, "QBUF created capture only");
		for (unsigned int p = 0; p < 2; p++) {
			if (munmap(mapped[p].address, mapped[p].bytes) ||
			    munmap(exported[p].address, exported[p].bytes) || close(exported[p].fd))
				fail("release created capture views");
		}
	}
	struct v4l2_requestbuffers release = { .type = format.type,
		.memory = V4L2_MEMORY_MMAP, .count = 0 };
	checked_ioctl(stream.video, VIDIOC_REQBUFS, &release, "release created capture queue");
	if (close(stream.media) || close(stream.video)) fail("close CREATE_BUFS device");
	create_buffers_checked = 1;
}

static u8 native_buffer_pattern(unsigned int index, size_t byte, size_t luma)
{
	return byte < luma ? 0x31 + index : byte < luma * 3 / 2 ? 0x91 + index : 0x51 + index;
}

static void check_native_aliases(struct stream *stream,
				struct mapping exported[CAPTURE_COUNT][2],
				int initialize, int written, int video_mapped)
{
	size_t luma = width * storage_height;
	uint64_t access = initialize ? DMA_BUF_SYNC_RW : DMA_BUF_SYNC_READ;

	for (unsigned int index = 0; index < stream->capture_count; index++) {
		struct mapping *views = exported[index];
		struct mapping *aliases[] = { &stream->storage[index][0],
			&stream->storage[index][1], &views[0], &views[1] };
		sync_mapping(&views[0], DMA_BUF_SYNC_START | access);
		/* Full-backing patterns belong only to this no-command mode.
		 * Write before the nested alias begins, detecting a second cache
		 * invalidation that would discard already dirty CPU contents.
		 */
		if (initialize) {
			u8 *data = stream->storage[index][0].address;
			for (size_t byte = 0; byte < views[0].bytes; byte++)
				data[byte] = native_buffer_pattern(index, byte, luma);
		}
		sync_mapping(&views[1], DMA_BUF_SYNC_START | access);
		for (unsigned int alias = video_mapped ? 0 : 2; alias < 4; alias++) {
			u8 *data = aliases[alias]->address;
			for (size_t byte = 0; byte < views[0].bytes; byte++)
				if (data[byte] != (written ? native_buffer_pattern(index, byte, luma) : 0)) {
					fprintf(stderr, "Native capture alias contents differ\n"); exit(1);
				}
		}
		sync_mapping(&views[0], DMA_BUF_SYNC_END | access);
		sync_mapping(&views[1], DMA_BUF_SYNC_END | access);
	}
}

static void test_native_buffers(struct stream *stream, const char *video,
				const char *media, const char *render)
{
	struct mapping exported[CAPTURE_COUNT][2];
	uint32_t handles[CAPTURE_COUNT];
	uint64_t gpu_offsets[CAPTURE_COUNT];
	const size_t luma = 5120, backing = 196608;
	struct v4l2_format format = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE };
	struct v4l2_plane planes[2];
	struct v4l2_buffer buffer = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
		.memory = V4L2_MEMORY_MMAP, .length = 2, .m.planes = planes };
	long page_size = sysconf(_SC_PAGESIZE);
	char driver[32] = { 0 };
	struct drm_version version = { .name_len = sizeof(driver) - 1, .name = driver };
	int gpu;

	if (page_size <= 0) fail("page size");
	if (!create_buffers_checked) {
		fprintf(stderr, "CREATE_BUFS checks were not completed\n"); exit(1);
	}
	open_device(stream, video, media);
	format.fmt.pix_mp.width = width;
	format.fmt.pix_mp.height = height;
	checked_ioctl(stream->video, VIDIOC_S_FMT, &format, "S_FMT output geometry");
	if (format.fmt.pix_mp.width != 80 || format.fmt.pix_mp.height != 64 ||
	    format.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_H264_SLICE) {
		fprintf(stderr, "Unexpected native buffer geometry\n"); exit(1);
	}
	allocate_queue(stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE);
	format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
	checked_ioctl(stream->video, VIDIOC_G_FMT, &format, "G_FMT native capture");
	if (format.fmt.pix_mp.num_planes != 2 ||
	    format.fmt.pix_mp.plane_fmt[0].sizeimage != luma ||
	    format.fmt.pix_mp.plane_fmt[1].sizeimage != luma * 3 / 2) {
		fprintf(stderr, "Unexpected native capture minimum extents\n"); exit(1);
	}
	gpu = open(render, O_RDWR | O_CLOEXEC);
	if (gpu < 0) fail("open render node");
	checked_ioctl(gpu, DRM_IOCTL_VERSION, &version, "DRM_VERSION");
	if (version.name_len != strlen("panfrost") || strcmp(driver, "panfrost")) {
		fprintf(stderr, "Unexpected render driver\n"); exit(1);
	}
	for (unsigned int index = 0; index < stream->capture_count; index++) {
		buffer.index = index;
		memset(planes, 0, sizeof(planes));
		checked_ioctl(stream->video, VIDIOC_QUERYBUF, &buffer, "QUERYBUF native capture");
		for (unsigned int plane = 0; plane < 2; plane++) {
			struct mapping *view = &exported[index][plane];
			struct v4l2_exportbuffer exp = { .type = buffer.type, .index = index,
				.plane = plane, .flags = O_RDWR | O_CLOEXEC };
			struct drm_prime_handle imported = { 0 };
			if (planes[plane].length != backing ||
			    planes[plane].data_offset != (plane ? luma : 0) ||
			    planes[plane].bytesused != planes[plane].data_offset) {
				fprintf(stderr, "Unexpected queried native capture layout\n"); exit(1);
			}
			checked_ioctl(stream->video, VIDIOC_EXPBUF, &exp, "EXPBUF native capture");
			*view = (struct mapping) { .bytes = backing,
				.data_offset = planes[plane].data_offset, .fd = exp.fd };
			view->address = mmap(NULL, backing, PROT_READ | PROT_WRITE,
					     MAP_SHARED, view->fd, 0);
			if (view->address == MAP_FAILED) fail("mmap native export");
			imported.fd = view->fd;
			checked_ioctl(gpu, DRM_IOCTL_PRIME_FD_TO_HANDLE, &imported, "PRIME native capture");
			if (!imported.handle || (plane && imported.handle != handles[index])) {
				fprintf(stderr, "Native export aliases have different GEM handles\n"); exit(1);
			}
			if (!plane) {
				for (unsigned int previous = 0; previous < index; previous++)
					if (handles[previous] == imported.handle) {
						fprintf(stderr, "Distinct capture buffers share a GEM handle\n"); exit(1);
					}
				handles[index] = imported.handle;
			}
		}
		struct drm_panfrost_get_bo_offset offset = { .handle = handles[index] };
		checked_ioctl(gpu, DRM_IOCTL_PANFROST_GET_BO_OFFSET, &offset, "GET_BO_OFFSET native capture");
		if (!offset.offset || offset.offset % (uint64_t)page_size) {
			fprintf(stderr, "Invalid native GPU mapping offset\n"); exit(1);
		}
		gpu_offsets[index] = offset.offset;
	}
	check_native_aliases(stream, exported, 0, 0, 1);
	check_native_aliases(stream, exported, 1, 1, 1);
	/* CAPTURE preparation and queue cancellation exercise VB2 cache hooks.
	 * Neither queue is streamed, no source/Request is queued, and no codec
	 * or GPU command is submitted anywhere in this mode.
	 */
	for (unsigned int index = 0; index < stream->capture_count; index++) {
		buffer.index = index;
		memset(planes, 0, sizeof(planes));
		planes[0].length = planes[1].length = backing;
		checked_ioctl(stream->video, VIDIOC_QBUF, &buffer, "QBUF native capture only");
		for (unsigned int plane = 0; plane < 2; plane++)
			if (munmap(stream->storage[index][plane].address, backing))
				fail("munmap native video view");
	}
	if (close(stream->media) || close(stream->video)) fail("close native video");
	check_native_aliases(stream, exported, 0, 1, 0);
	for (unsigned int index = 0; index < stream->capture_count; index++) {
		struct drm_panfrost_get_bo_offset offset = { .handle = handles[index] };
		checked_ioctl(gpu, DRM_IOCTL_PANFROST_GET_BO_OFFSET, &offset, "GET_BO_OFFSET after video close");
		if (offset.offset != gpu_offsets[index]) {
			fprintf(stderr, "Native GPU mapping changed across video close\n"); exit(1);
		}
		if (close(exported[index][0].fd)) fail("close first export alias");
		exported[index][0].fd = -1;
	}
	check_native_aliases(stream, exported, 0, 1, 0);
	/* PRIME deduplicates plane aliases: close each unique handle once. */
	for (unsigned int index = 0; index < stream->capture_count; index++) {
		struct drm_gem_close close_bo = { .handle = handles[index] };
		checked_ioctl(gpu, DRM_IOCTL_GEM_CLOSE, &close_bo, "GEM_CLOSE native capture");
	}
	if (close(gpu)) fail("close render node");
	check_native_aliases(stream, exported, 0, 1, 0);
	for (unsigned int index = 0; index < stream->capture_count; index++) {
		for (unsigned int plane = 0; plane < 2; plane++)
			if (munmap(exported[index][plane].address, backing)) fail("munmap native export");
		if (close(exported[index][1].fd)) fail("close last export alias");
	}
	puts("{\"native_buffers_test_passed\":true,\"scope\":\"native-buffers\","
	     "\"width\":80,\"height\":64,\"capture_buffers\":17,\"planes_per_buffer\":2,"
	     "\"sizeimage\":[5120,7680],\"plane_lengths\":[196608,196608],"
	     "\"data_offsets\":[0,5120],\"exported_fds\":34,\"prime_handles\":17,"
	     "\"prime_aliases_same_handle\":true,\"prime_gpu_va_verified\":true,"
	     "\"mmap_export_aliases_verified\":true,\"queue_cache_cycle_verified\":true,"
	     "\"video_close_lifetime_verified\":true,\"closed_fd_aliases_verified\":true,"
	     "\"prime_release_lifetime_verified\":true,\"all_user_refs_released\":true,"
	     "\"create_bufs_cases\":9,\"create_bufs_lengths_preserved\":true,"
	     "\"create_bufs_full_backing_verified\":true,\"create_bufs_queue_prepare_verified\":true,"
	     "\"codec_submissions\":0,\"gpu_submissions\":0,\"decode_qualified\":false,"
	     "\"gpu_rendering_qualified\":false}");
}

/* Feed an original fixture through the standard Mesa MM21 import path. CPU
 * writes initialize the test input only; the renderer samples exported storage
 * through EGL and has no CPU input conversion or mapping.
 */
static void test_native_gpu(const char *video, const char *media, const char *render,
			    const char *helper, const char *out)
{
	static const u8 colors[][3] = { {81,90,240}, {145,54,34}, {41,240,110}, {128,128,128} };
	struct stream stream;
	struct v4l2_format format = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE };
	struct v4l2_plane planes[2] = { 0 };
	struct v4l2_buffer buffer = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
		.memory = V4L2_MEMORY_MMAP, .length = 2, .m.planes = planes };
	struct mapping exports[2] = { {.fd=-1}, {.fd=-1} };
	const size_t luma = 5120, capacity = 196608;
	char log_path[1024], fd_text[2][32];
	open_device(&stream, video, media);
	format.fmt.pix_mp.width = width;
	format.fmt.pix_mp.height = height;
	checked_ioctl(stream.video, VIDIOC_S_FMT, &format, "GPU output geometry");
	format.type = buffer.type;
	checked_ioctl(stream.video, VIDIOC_G_FMT, &format, "GPU capture format");
	if (format.fmt.pix_mp.width != 80 || format.fmt.pix_mp.height != 64 ||
	    format.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_MM21 || format.fmt.pix_mp.num_planes != 2 ||
	    format.fmt.pix_mp.plane_fmt[0].sizeimage != luma ||
	    format.fmt.pix_mp.plane_fmt[1].sizeimage != luma * 3 / 2) {
		fprintf(stderr, "Unexpected native GPU capture geometry\n"); exit(1);
	}
	struct v4l2_create_buffers create = { .count=1, .memory=V4L2_MEMORY_MMAP, .format=format };
	checked_ioctl(stream.video, VIDIOC_CREATE_BUFS, &create, "GPU CREATE_BUFS");
	if (create.count != 1 || create.index != 0) {
		fprintf(stderr, "Unexpected native GPU buffer count\n"); exit(1);
	}
	checked_ioctl(stream.video, VIDIOC_QUERYBUF, &buffer, "GPU QUERYBUF");
	for (unsigned p = 0; p < 2; p++) {
		struct v4l2_exportbuffer exp = { .type=buffer.type, .plane=p,
			.flags=O_RDWR | O_CLOEXEC };
		if (planes[p].length != luma * (p ? 3 : 2) / 2 ||
		    planes[p].data_offset != (p ? luma : 0) ||
		    planes[p].bytesused != planes[p].data_offset) {
			fprintf(stderr, "Unexpected native GPU plane metadata\n"); exit(1);
		}
		checked_ioctl(stream.video, VIDIOC_EXPBUF, &exp, "GPU EXPBUF");
		exports[p].fd = exp.fd;
		if (exp.fd < 3 || (p && exp.fd == exports[0].fd) ||
		    lseek(exp.fd, 0, SEEK_END) != (off_t)capacity) {
			fprintf(stderr, "Unexpected native GPU export capacity/fd\n"); exit(1);
		}
	}
	exports[0].address = mmap(NULL, capacity, PROT_READ | PROT_WRITE, MAP_SHARED, exports[0].fd, 0);
	if (exports[0].address == MAP_FAILED) fail("GPU input mmap");
	sync_mapping(&exports[0], DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE);
	u8 *data = exports[0].address;
	for (unsigned y = 0; y < 64; y++)
		for (unsigned x = 0; x < 80; x++) {
			unsigned cell = (x / 8 + 3 * (y / 8)) % 4;
			size_t address = ((y / 32) * 5 + x / 16) * 512 + (y % 32) * 16 + x % 16;
			data[address] = colors[cell][0];
		}
	for (unsigned y = 0; y < 32; y++)
		for (unsigned x = 0; x < 40; x++) {
			unsigned cell = (x / 4 + 3 * (y / 4)) % 4;
			size_t address = luma + ((y / 16) * 5 + x / 8) * 256 + (y % 16) * 16 + 2 * (x % 8);
			data[address] = colors[cell][1]; data[address+1] = colors[cell][2];
		}
	sync_mapping(&exports[0], DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
	if (munmap(exports[0].address, capacity)) fail("GPU input munmap");
	if (snprintf(log_path, sizeof(log_path), "%s/native-gpu.txt", out) >= (int)sizeof(log_path)) {
		fprintf(stderr, "Native GPU output path too long\n"); exit(1);
	}
	int log = open(log_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	if (log < 0) fail("GPU helper output");
	for (unsigned p = 0; p < 2; p++) snprintf(fd_text[p], sizeof(fd_text[p]), "%d", exports[p].fd);
	pid_t child = fork();
	if (child < 0) fail("GPU helper fork");
	if (!child) {
		if (dup2(log, STDOUT_FILENO) < 0 || dup2(log, STDERR_FILENO) < 0) _exit(126);
		close(log);
		for (unsigned p = 0; p < 2; p++)
			if (fcntl(exports[p].fd, F_SETFD, 0) < 0) _exit(126);
		execl(helper, helper, render, "--native-mm21", fd_text[0], fd_text[1], (char *)NULL);
		_exit(127);
	}
	/* The child alone owns the original exports before EGL imports them.
	 * It closes them after import; retained EGL/PRIME refs own the draw.
	 * The existing observer's process-group timeout bounds parent and child.
	 */
	if (close(log) || close(stream.media) || close(stream.video) ||
	    close(exports[0].fd) || close(exports[1].fd)) fail("GPU parent release");
	int status;
	pid_t waited;
	do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
	if (waited != child || !WIFEXITED(status) || WEXITSTATUS(status)) {
		fprintf(stderr, "Native GPU helper failed; retain module until recovery\n"); exit(1);
	}
	puts("{\"native_gpu_test_passed\":true,\"scope\":\"synthetic-native-mm21-gpu\","
	     "\"width\":80,\"height\":64,\"pixels\":5120,\"rgb_tolerance\":2,"
	     "\"exported_fds\":2,\"export_capacity\":196608,\"api_draws\":1,"
	     "\"parent_refs_released\":true,\"codec_submissions\":0,\"decode_qualified\":false}");
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
	unsigned int expected_index = type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE ? stream->capture_index : 0;
	if (!!(buffer.flags & V4L2_BUF_FLAG_ERROR) != expect_error || buffer.index != expected_index) {
		fprintf(stderr, "Unexpected completed buffer flags %#x\n", buffer.flags); bad = 1;
	}
	if (type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE) {
		if (buffer.timestamp.tv_sec != timestamp || buffer.timestamp.tv_usec || buffer.sequence != sequence) bad = 1;
		for (unsigned int i = 0; i < 2; i++) {
			struct mapping *mapping = &stream->capture[i];
			unsigned int payload = width * storage_height / (i ? 2 : 1);
			if (planes[i].length != mapping->bytes || planes[i].data_offset != mapping->data_offset ||
			    planes[i].bytesused > mapping->bytes ||
			    planes[i].bytesused < planes[i].data_offset ||
			    planes[i].bytesused - planes[i].data_offset !=
			    (buffer.flags & V4L2_BUF_FLAG_ERROR ? 0 : payload)) bad = 1;
		}
		if (!bad && !(buffer.flags & V4L2_BUF_FLAG_ERROR))
			stream->timestamps[buffer.index] = (uint64_t)timestamp * 1000000000ULL;
		if (bad) fprintf(stderr, "Unexpected capture metadata or payload bounds\n");
	}
	return bad;
}

static int cached_cpu_access_safe(const char *status)
{
	const char *keys[] = { "fetched", "submitted", "quiesced", "guards", "break", "reset" };
	unsigned int values[6] = { 0 }, seen[6] = { 0 };

	while (*status) {
		while (isspace((unsigned char)*status)) status++;
		const char *end = status;
		while (*end && !isspace((unsigned char)*end)) end++;
		for (unsigned int i = 0; i < 6; i++) {
			size_t length = strlen(keys[i]);
			if ((size_t)(end - status) <= length ||
			    strncmp(status, keys[i], length) || status[length] != '=') continue;
			const char *number = status + length + 1;
			if (seen[i]) return 0;
			if (i < 4) {
				if (end - number != 1 || *number < '0' || *number > '1') return 0;
				values[i] = *number - '0';
			} else if (end - number == 1 && *number == '0') {
				values[i] = 0;
			} else {
				/* Native status emits signed decimal errno values. */
				if (number < end && *number == '-') number++;
				if (number == end || *number < '1' || *number > '9') return 0;
				while (++number < end)
					if (!isdigit((unsigned char)*number)) return 0;
				values[i] = 1;
			}
			seen[i] = 1;
		}
		status = end;
	}
	for (unsigned int i = 0; i < 6; i++) if (!seen[i]) return 0;
	return (!values[0] && !values[1] && !values[4] && !values[5]) ||
	       (values[2] && values[3]);
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
			!strcmp(name, "fault-b-list1") || !strcmp(name, "fault-b-poc") ? "fault-b2" :
			!strncmp(name, "fault-longterm-", 15) ? "fault-longterm-b2" : name;
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
		else {
			/* Type0 full POC has low6 bits0, but the NAL/control LSB is1. */
			params.top_field_order_cnt = params.bottom_field_order_cnt = 131072;
		}
	}
	if (!strncmp(name, "fault-longterm-", 15)) {
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
		params.dpb[0].flags |= V4L2_H264_DPB_ENTRY_FLAG_LONG_TERM;
		params.dpb[1] = params.dpb[0];
		params.dpb[1].reference_ts = 2000000000ULL;
		params.dpb[1].frame_num = params.dpb[1].pic_num = 1;
		params.dpb[1].top_field_order_cnt = params.dpb[1].bottom_field_order_cnt = 2;
		for (unsigned int i = 0; i < 2; i++) {
			slice.ref_pic_list0[i].fields = slice.ref_pic_list1[i].fields = V4L2_H264_FRAME_REF;
			slice.ref_pic_list0[i].index = i;
			slice.ref_pic_list1[i].index = 1 - i;
		}
		/* Untrusted stateless metadata on two real retained pictures. All
		 * failures must precede DMA, and neither capture plane may change.
		 */
		if (!strcmp(name, "fault-longterm-range"))
			params.dpb[0].frame_num = params.dpb[0].pic_num = 2;
		else if (!strcmp(name, "fault-longterm-picnum"))
			params.dpb[0].pic_num = 1;
		else
			params.dpb[1].frame_num = params.dpb[1].pic_num = 0;
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
	select_capture(stream, &params);
	sync_mapping(&stream->source, DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE);
	memcpy(stream->source.address, nal, bytes);
	sync_mapping(&stream->source, DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE);
	fill_capture(stream);
	struct v4l2_plane source_plane = { .bytesused = bytes, .length = stream->source.bytes };
	struct v4l2_buffer source = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,
		.memory = V4L2_MEMORY_MMAP, .length = 1, .m.planes = &source_plane,
		.flags = V4L2_BUF_FLAG_REQUEST_FD, .request_fd = request, .timestamp.tv_sec = timestamp };
	struct v4l2_plane capture_planes[] = { { .length = stream->capture[0].bytes },
		{ .length = stream->capture[1].bytes } };
	struct v4l2_buffer capture = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
		.memory = V4L2_MEMORY_MMAP, .index = stream->capture_index,
		.length = 2, .m.planes = capture_planes };
	checked_ioctl(stream->video, VIDIOC_QBUF, &capture, "QBUF capture");
	checked_ioctl(stream->video, VIDIOC_QBUF, &source, "QBUF request source");
	checked_ioctl(request, MEDIA_REQUEST_IOC_QUEUE, NULL, "REQUEST_QUEUE");
	int bad = dequeue(stream, V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE, expect_error, timestamp, sequence);
	bad |= dequeue(stream, V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE, expect_error, timestamp, sequence);
	struct pollfd pollfd = { .fd = request, .events = POLLPRI };
	if (poll(&pollfd, 1, 1000) != 1 || !(pollfd.revents & POLLPRI)) {
		fprintf(stderr, "Request did not complete\n"); exit(1);
	}
	/* Persist the cached stop/guard boundary before reading any capture
	 * alias. ERROR metadata or a missing/malformed boundary must never
	 * authorize CPU reads of memory potentially still owned by hardware.
	 */
	char status[4096], status_output[1024];
	FILE *status_file = fopen(status_path, "r");
	if (!status_file || !fgets(status, sizeof(status), status_file)) fail("read cached job status");
	if (fclose(status_file)) fail("close cached job status");
	if (snprintf(status_output, sizeof(status_output), "%s/%s-status.txt", out, name) >= (int)sizeof(status_output)) {
		fprintf(stderr, "Status path too long\n"); exit(1);
	}
	status_file = fopen(status_output, "w");
	if (!status_file || fputs(status, status_file) == EOF || fclose(status_file)) fail("write cached job status");
	checked_ioctl(request, MEDIA_REQUEST_IOC_REINIT, NULL, "REQUEST_REINIT");
	close(request);
	if (bad || !strchr(status, '\n') || !cached_cpu_access_safe(status)) {
		fprintf(stderr, "Completed metadata or cached stop boundary denies CPU access\n"); exit(1);
	}
	if (!strcmp(name, "fault-scaling") || !strcmp(name, "fault-weight") ||
	    !strcmp(name, "fault-refmissing") || !strcmp(name, "fault-refmetadata") ||
	    !strcmp(name, "fault-b-list1") || !strcmp(name, "fault-b-poc") ||
	    !strncmp(name, "fault-longterm-", 15)) {
		capture_untouched(stream);
	}

	if (!expect_error) {
		char path[1024];
		if (snprintf(path, sizeof(path), "%s/%s.bin", out, name) >= (int)sizeof(path)) {
			fprintf(stderr, "Output path too long\n"); exit(1);
		}
		FILE *file = fopen(path, "wb");
		if (!file) fail("output file");
		sync_capture(stream, DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ);
		if (fwrite(plane_data(&stream->capture[0]), 1, width * storage_height, file) != width * storage_height ||
		    fwrite(plane_data(&stream->capture[1]), 1, width * storage_height / 2, file) != width * storage_height / 2 || fclose(file)) fail("write output");
		sync_capture(stream, DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ);
	}
	printf("{\"fixture\":\"%s\",\"expected_error\":%d,\"timestamp\":%u,\"sequence\":%u,\"request_completed\":true}\n",
		name, expect_error, timestamp, sequence);
	fflush(stdout);
}

int main(int argc, char **argv)
{
	struct stream stream;
	int single_grey = argc == 7 && !strcmp(argv[5], "--single") &&
			  !strcmp(argv[6], "grey64");
	buffers_only = argc == 7 && !strcmp(argv[5], "--buffers-only");
	int native_gpu = argc == 8 && !strcmp(argv[5], "--native-gpu");
	if (argc != 5 && argc != 9 && argc != 10 && !single_grey && !buffers_only && !native_gpu) {
		fprintf(stderr, "Usage: %s VIDEO MEDIA OUTPUT_DIRECTORY CACHED_STATUS_PATH [--native-gpu RENDER_NODE HELPER | --buffers-only RENDER_NODE | --single grey64 | FIXTURES WIDTH HEIGHT mmap|export [faults]]\n", argv[0]); return 2;
	}
	status_path = argv[4];
	if (native_gpu) {
		width = 80; height = storage_height = 64;
		test_native_gpu(argv[1], argv[2], argv[6], argv[7], argv[3]);
		return 0;
	}
	if (buffers_only) {
		width = 80;
		height = storage_height = 64;
		test_create_buffers(argv[1], argv[2]);
		test_native_buffers(&stream, argv[1], argv[2], argv[6]);
		return 0;
	}
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
	if (single_grey) {
		open_stream(&stream, argv[1], argv[2]);
		decode(&stream, argv[3], "grey64", grey64_nal, sizeof(grey64_nal), 0, 0, 0, 1, 0);
		close_stream(&stream);
		puts("{\"public_api_test_passed\":true,\"scope\":\"single-grey64\"}");
		return 0;
	}
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
			decode(&stream, argv[3], "fault-longterm-range", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 7, 7);
			decode(&stream, argv[3], "fault-longterm-picnum", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 8, 8);
			decode(&stream, argv[3], "fault-longterm-duplicate", pskip64_nal, sizeof(pskip64_nal), 1, 0, 1, 9, 9);
			decode(&stream, argv[3], "reference-after-reject", pskip64_nal, sizeof(pskip64_nal), 1, 0, 0, 10, 10);
			close_stream(&stream);
		}
	}
	puts("{\"public_api_test_passed\":true}");
	return 0;
}
