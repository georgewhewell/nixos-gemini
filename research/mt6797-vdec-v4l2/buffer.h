/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MT6797_VDEC_BUFFER_H
#define MT6797_VDEC_BUFFER_H

#include <linux/dma-buf.h>
#include <media/videobuf2-core.h>

struct mt6797_surface_job;

/* One object contains MM21 Y/C, retained motion data and a guarded tail. */
struct mt6797_picture {
	struct dma_buf *buffer;
	u8 *cpu;
	dma_addr_t dma;
	size_t bytes;
};

size_t mt6797_picture_bytes(size_t luma);
int mt6797_picture_from_vb2(struct vb2_buffer *vb, struct mt6797_picture *picture);
int mt6797_capture_prepare(struct vb2_buffer *vb);
int mt6797_capture_finish_error(struct vb2_buffer *vb);
void mt6797_picture_get(struct mt6797_picture *dst, const struct mt6797_picture *src);
void mt6797_picture_put(struct mt6797_picture *picture);
bool mt6797_picture_poisoned(const struct mt6797_picture *picture);

/* Dependencies and exclusive ownership fences cover the compound objects,
 * including CPU snapshots/cache/guards around the codec's reference reads.
 * The job holds independent references, never a vb2/file pointer.
 */
struct mt6797_surface_job *mt6797_surface_job_begin(struct mt6797_picture *pictures,
						 unsigned int count,
						 unsigned int output);
void mt6797_surface_job_to_device(struct mt6797_surface_job *job);
void mt6797_surface_job_to_cpu(struct mt6797_surface_job *job);
void mt6797_surface_job_finish(struct mt6797_surface_job *job, int error,
			      int reference_error);
void mt6797_surface_job_poison(struct mt6797_surface_job *job);

extern const struct vb2_mem_ops mt6797_capture_memops;

#endif
