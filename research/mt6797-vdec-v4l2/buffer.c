// SPDX-License-Identifier: GPL-2.0-only
/* Native compound capture surfaces. dma_buf owns the allocation; independent
 * plane views, VMAs and the decoder DPB/job own references to that dma_buf.
 */
#include <linux/dma-buf.h>
#include <linux/dma-fence.h>
#include <linux/dma-mapping.h>
#include <linux/dma-resv.h>
#include <linux/highmem.h>
#include <linux/iosys-map.h>
#include <linux/jiffies.h>
#include <linux/list.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/overflow.h>
#include <linux/refcount.h>
#include <linux/scatterlist.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <media/videobuf2-memops.h>
#include "buffer.h"

#define SURFACE_LIMIT 17U
#define DEPENDENCY_TIMEOUT msecs_to_jiffies(1000)

/* One allocator owner serializes CPU phases; reservation locks precede it. */
static DEFINE_MUTEX(capture_lock);

struct capture_surface {
	struct device *dev;
	struct sg_table *sgt;
	u8 *cpu;
	dma_addr_t dma;
	size_t bytes;
	struct list_head mappings;
	unsigned int cpu_accesses;
	bool busy, device_owned, poisoned;
};

struct capture_view {
	struct dma_buf *buffer;
	refcount_t users;
	struct vb2_vmarea_handler handler;
	int cache_error;
};

struct capture_mapping {
	struct sg_table sgt;
	struct device *dev;
	enum dma_data_direction direction;
	struct list_head list;
};

struct capture_fence {
	struct dma_fence base;
	spinlock_t lock;
};

struct mt6797_surface_job {
	struct dma_fence *output_fence, *reference_fence;
	struct dma_buf *buffers[SURFACE_LIMIT];
	bool write[SURFACE_LIMIT];
	unsigned int count;
	bool cpu_locked;
};

size_t mt6797_picture_bytes(size_t luma)
{
	size_t bytes;

	if (check_mul_overflow(luma, (size_t)7, &bytes) ||
	    check_add_overflow(bytes / 4, (size_t)SZ_64K - 1, &bytes))
		return 0;
	bytes = round_down(bytes, SZ_64K);
	if (check_add_overflow(bytes, (size_t)SZ_128K, &bytes))
		return 0;
	return bytes;
}

int mt6797_capture_size(size_t luma, size_t first, size_t second, size_t *bytes)
{
	size_t picture = mt6797_picture_bytes(luma);
	size_t chroma_end, allocation;

	if (!luma || !picture || check_add_overflow(luma, luma / 2, &chroma_end) ||
	    first < luma || second < chroma_end)
		return -EINVAL;
	allocation = max(max(picture, first), second);
	/* The entire object, including padding requested by CREATE_BUFS, must
	 * fit the decoder's DMA aperture. This bound also makes PAGE_ALIGN safe.
	 */
	if (allocation > (size_t)DMA_BIT_MASK(28) + 1)
		return -EINVAL;
	*bytes = PAGE_ALIGN(allocation);
	return 0;
}

static void surface_to_cpu(struct capture_surface *surface)
{
	struct capture_mapping *mapping;

	if (!surface->device_owned)
		return;
	dma_sync_sgtable_for_cpu(surface->dev, surface->sgt, DMA_BIDIRECTIONAL);
	list_for_each_entry(mapping, &surface->mappings, list)
		dma_sync_sgtable_for_cpu(mapping->dev, &mapping->sgt, mapping->direction);
	invalidate_kernel_vmap_range(surface->cpu, surface->bytes);
	surface->device_owned = false;
}

static void surface_to_device(struct capture_surface *surface)
{
	struct capture_mapping *mapping;

	if (surface->device_owned)
		return;
	flush_kernel_vmap_range(surface->cpu, surface->bytes);
	dma_sync_sgtable_for_device(surface->dev, surface->sgt, DMA_BIDIRECTIONAL);
	list_for_each_entry(mapping, &surface->mappings, list)
		dma_sync_sgtable_for_device(mapping->dev, &mapping->sgt, mapping->direction);
	surface->device_owned = true;
}

static struct sg_table *capture_map(struct dma_buf_attachment *attachment,
				  enum dma_data_direction direction)
{
	struct capture_surface *surface = attachment->dmabuf->priv;
	struct scatterlist *source, *target;
	struct capture_mapping *mapping;
	struct sg_table *sgt;
	unsigned int i;
	int ret;

	/* The pinned native direct and IOMMU DMA owners both mark a bounced
	 * SG list. With no architecture DMA ops, generic SG mapping chooses
	 * only those owners; other routes cannot prove this export contract.
	 */
	if (!IS_ENABLED(CONFIG_NEED_SG_DMA_FLAGS) || IS_ENABLED(CONFIG_ARCH_HAS_DMA_OPS))
		return ERR_PTR(-EOPNOTSUPP);
	mutex_lock(&capture_lock);
	if (surface->poisoned) {
		ret = -EIO;
		goto unlock;
	}
	if (surface->cpu_accesses) {
		ret = -EBUSY;
		goto unlock;
	}
	mapping = kzalloc(sizeof(*mapping), GFP_KERNEL);
	if (!mapping) {
		ret = -ENOMEM;
		goto unlock;
	}
	sgt = &mapping->sgt;
	ret = sg_alloc_table(sgt, surface->sgt->orig_nents, GFP_KERNEL);
	if (ret)
		goto free;

	source = surface->sgt->sgl;
	target = sgt->sgl;
	for (i = 0; i < sgt->orig_nents; i++) {
		sg_set_page(target, sg_page(source), source->length, source->offset);
		source = sg_next(source);
		target = sg_next(target);
	}
	/* A producer's CPU initialization/guard phase holds this lock. Flush
	 * an idle CPU-owned object once before adding another device mapping;
	 * nested aliases must not invalidate dirty CPU-owned contents again.
	 */
	surface_to_device(surface);
	ret = dma_map_sgtable(attachment->dev, sgt, direction, DMA_ATTR_SKIP_CPU_SYNC);
	if (ret)
		goto free_table;
	for_each_sgtable_sg(sgt, target, i)
		if (sg_dma_is_swiotlb(target)) {
			/* Independently bounced device mappings cannot share the
			 * same producer/reference pages without ambiguous copyback.
			 */
			ret = -EOPNOTSUPP;
			goto unmap;
		}
	mapping->dev = attachment->dev;
	mapping->direction = direction;
	list_add_tail(&mapping->list, &surface->mappings);
	mutex_unlock(&capture_lock);
	return sgt;

unmap:
	dma_unmap_sgtable(attachment->dev, sgt, direction, DMA_ATTR_SKIP_CPU_SYNC);
free_table:
	sg_free_table(sgt);
free:
	kfree(mapping);
unlock:
	mutex_unlock(&capture_lock);
	return ERR_PTR(ret);
}

static void capture_unmap(struct dma_buf_attachment *attachment,
			  struct sg_table *sgt, enum dma_data_direction direction)
{
	struct capture_mapping *mapping = container_of(sgt, struct capture_mapping, sgt);

	mutex_lock(&capture_lock);
	list_del(&mapping->list);
	/* Cache ownership was already handled by the shared owner, including
	 * CPU access through any alias. Removing an IOVA must not change it.
	 */
	dma_unmap_sgtable(attachment->dev, sgt, direction, DMA_ATTR_SKIP_CPU_SYNC);
	sg_free_table(sgt);
	kfree(mapping);
	mutex_unlock(&capture_lock);
}

static void capture_release(struct dma_buf *buffer)
{
	struct capture_surface *surface = buffer->priv;

	/* A poisoned job retains its own dma_buf reference until reboot. */
	if (WARN_ON(surface->busy || surface->poisoned))
		return;
	WARN_ON(!list_empty(&surface->mappings));
	dma_vunmap_noncontiguous(surface->dev, surface->cpu);
	dma_free_noncontiguous(surface->dev, surface->bytes, surface->sgt,
			       DMA_BIDIRECTIONAL);
	put_device(surface->dev);
	kfree(surface);
}

static long capture_wait_owner(struct dma_buf *buffer, unsigned long deadline)
{
	struct capture_surface *surface = buffer->priv;
	long remaining = deadline - jiffies;
	long waited;

	if (READ_ONCE(surface->poisoned))
		return -EIO;
	if (remaining <= 0)
		return -ETIMEDOUT;
	waited = dma_resv_wait_timeout(buffer->resv, DMA_RESV_USAGE_READ,
				       true, remaining);
	if (READ_ONCE(surface->poisoned))
		return -EIO;
	return waited > 0 ? 0 : waited ? waited : -ETIMEDOUT;
}

/* Reservation publication and the cache handoff share one lock interval.
 * Success returns with both locks held; no dependency wait holds capture_lock.
 */
static int capture_lock_owner(struct dma_buf *buffer)
{
	struct capture_surface *surface = buffer->priv;
	unsigned long deadline = jiffies + DEPENDENCY_TIMEOUT;
	int ret;

	if (READ_ONCE(surface->poisoned))
		return -EIO;
	ret = dma_resv_lock_interruptible(buffer->resv, NULL);
	if (ret)
		return ret;
	ret = capture_wait_owner(buffer, deadline);
	if (ret)
		goto unlock;
	mutex_lock(&capture_lock);
	if (surface->poisoned)
		ret = -EIO;
	else if (surface->busy)
		ret = -EBUSY;
	if (!ret)
		return 0;
	mutex_unlock(&capture_lock);
unlock:
	dma_resv_unlock(buffer->resv);
	return ret;
}

static void capture_unlock_owner(struct dma_buf *buffer)
{
	mutex_unlock(&capture_lock);
	dma_resv_unlock(buffer->resv);
}

static int capture_begin_cpu(struct dma_buf *buffer, enum dma_data_direction direction)
{
	struct capture_surface *surface = buffer->priv;
	int ret;

	/* CPU/device ownership is exclusive, including CPU reads of references.
	 * The core waits after this callback, so retire dependencies first.
	 */
	ret = capture_lock_owner(buffer);
	if (ret)
		return ret;
	surface_to_cpu(surface);
	surface->cpu_accesses++;
	capture_unlock_owner(buffer);
	return 0;
}

static int capture_end_cpu(struct dma_buf *buffer, enum dma_data_direction direction)
{
	struct capture_surface *surface = buffer->priv;
	int ret;

	/* Serialize the final cache handoff with new reservation publication. */
	ret = dma_resv_lock_interruptible(buffer->resv, NULL);
	if (ret)
		return ret;
	mutex_lock(&capture_lock);
	if (surface->poisoned)
		ret = -EIO;
	else if (!surface->cpu_accesses)
		ret = -EINVAL;
	else if (!--surface->cpu_accesses)
		surface_to_device(surface);
	capture_unlock_owner(buffer);
	return ret;
}

static int capture_vmap(struct dma_buf *buffer, struct iosys_map *map)
{
	struct capture_surface *surface = buffer->priv;

	if (READ_ONCE(surface->poisoned))
		return -EIO;
	iosys_map_set_vaddr(map, surface->cpu);
	return 0;
}

static int capture_mmap(struct dma_buf *buffer, struct vm_area_struct *vma)
{
	struct capture_surface *surface = buffer->priv;

	if (READ_ONCE(surface->poisoned))
		return -EIO;
	return dma_mmap_noncontiguous(surface->dev, vma, surface->bytes, surface->sgt);
}

static const struct dma_buf_ops capture_dmabuf_ops = {
	.map_dma_buf = capture_map,
	.unmap_dma_buf = capture_unmap,
	.release = capture_release,
	.begin_cpu_access = capture_begin_cpu,
	.end_cpu_access = capture_end_cpu,
	.vmap = capture_vmap,
	.mmap = capture_mmap,
};

static struct dma_buf *allocate_surface(struct device *dev, size_t bytes)
{
	struct capture_surface *surface;
	struct dma_buf *buffer;
	DEFINE_DMA_BUF_EXPORT_INFO(info);
	int ret = -ENOMEM;

	surface = kzalloc(sizeof(*surface), GFP_KERNEL);
	if (!surface)
		return ERR_PTR(-ENOMEM);
	surface->dev = get_device(dev);
	surface->bytes = bytes;
	INIT_LIST_HEAD(&surface->mappings);
	surface->sgt = dma_alloc_noncontiguous(dev, bytes, DMA_BIDIRECTIONAL,
					     GFP_KERNEL, DMA_ATTR_ALLOC_SINGLE_PAGES);
	if (!surface->sgt)
		goto free;
	surface->dma = sg_dma_address(surface->sgt->sgl);
	if (surface->sgt->nents != 1 || !IS_ALIGNED(surface->dma, 2048) ||
	    sg_dma_len(surface->sgt->sgl) < bytes ||
	    surface->dma > DMA_BIT_MASK(28) - (bytes - 1)) {
		ret = -ERANGE;
		goto free_dma;
	}
	surface->cpu = dma_vmap_noncontiguous(dev, bytes, surface->sgt);
	if (!surface->cpu)
		goto free_dma;
	/* No uninitialized kernel pages may reach mmap or an attachment. */
	memset(surface->cpu, 0, bytes);
	surface_to_device(surface);
	surface_to_cpu(surface);
	info.ops = &capture_dmabuf_ops;
	info.size = bytes;
	info.flags = O_RDWR;
	info.priv = surface;
	buffer = dma_buf_export(&info);
	if (!IS_ERR(buffer))
		return buffer;
	ret = PTR_ERR(buffer);
	dma_vunmap_noncontiguous(dev, surface->cpu);
free_dma:
	dma_free_noncontiguous(dev, bytes, surface->sgt, DMA_BIDIRECTIONAL);
free:
	put_device(surface->dev);
	kfree(surface);
	return ERR_PTR(ret);
}

static void capture_view_put(void *private)
{
	struct capture_view *view = private;

	if (refcount_dec_and_test(&view->users)) {
		dma_buf_put(view->buffer);
		kfree(view);
	}
}

static void *capture_alloc(struct vb2_buffer *vb, struct device *dev, unsigned long size)
{
	struct capture_view *view, *first = vb->planes[0].mem_priv;
	struct dma_buf *buffer;
	size_t bytes;
	int ret;

	if (vb->num_planes != 2)
		return ERR_PTR(-EINVAL);
	/* Both original lengths are populated before the first alloc callback.
	 * Its size argument is rounded for this view, not the compound object.
	 */
	ret = mt6797_capture_size(mt6797_capture_luma(vb), vb->planes[0].length,
				 vb->planes[1].length, &bytes);
	if (ret)
		return ERR_PTR(ret);
	if (size != PAGE_ALIGN((size_t)vb->planes[first ? 1 : 0].length))
		return ERR_PTR(-EINVAL);
	view = kzalloc(sizeof(*view), GFP_KERNEL);
	if (!view)
		return ERR_PTR(-ENOMEM);
	/* vb2-core allocates planes in order. The second view shares the first
	 * object's base; its chroma offset is metadata, not a second mapping.
	 */
	if (first) {
		buffer = first->buffer;
		if (buffer->size != bytes) {
			kfree(view);
			return ERR_PTR(-EINVAL);
		}
		get_dma_buf(buffer);
	} else {
		buffer = allocate_surface(dev, bytes);
		if (IS_ERR(buffer)) {
			kfree(view);
			return buffer;
		}
	}
	view->buffer = buffer;
	refcount_set(&view->users, 1);
	view->handler.refcount = &view->users;
	view->handler.put = capture_view_put;
	view->handler.arg = view;
	return view;
}

static unsigned int capture_num_users(void *private)
{
	struct capture_view *view = private;

	/* Sibling views and engine references do not map this plane. Exported
	 * files independently pin the object and survive vb2 buffer orphaning.
	 */
	return refcount_read(&view->users);
}

static void *capture_vaddr(struct vb2_buffer *vb, void *private)
{
	struct capture_view *view = private;
	struct capture_surface *surface = view->buffer->priv;

	return READ_ONCE(surface->poisoned) ? NULL : surface->cpu;
}

static int capture_view_mmap(void *private, struct vm_area_struct *vma)
{
	struct capture_view *view = private;
	int ret;

	/* Each plane cookie maps its requested prefix of the same object.
	 * vb2 bounds the VMA by that plane's page-rounded QUERYBUF length.
	 */
	vma->vm_pgoff = 0;
	ret = capture_mmap(view->buffer, vma);
	if (ret)
		return ret;
	vma->vm_ops = &vb2_common_vm_ops;
	vma->vm_private_data = &view->handler;
	vma->vm_ops->open(vma);
	return 0;
}

static struct dma_buf *capture_get_dmabuf(struct vb2_buffer *vb, void *private,
					unsigned long flags)
{
	struct capture_view *view = private;
	struct capture_surface *surface = view->buffer->priv;

	/* The central file has one fixed access mode. Never silently upgrade
	 * a requested read-only/write-only descriptor to read/write access.
	 */
	if (READ_ONCE(surface->poisoned))
		return ERR_PTR(-EIO);
	if (flags != O_RDWR)
		return ERR_PTR(-EINVAL);
	get_dma_buf(view->buffer);
	return view->buffer;
}

static int capture_queue_transition(struct capture_view *view, bool cpu)
{
	struct capture_surface *surface = view->buffer->priv;
	int ret;

	ret = capture_lock_owner(view->buffer);
	if (ret)
		return ret;
	if (surface->cpu_accesses)
		ret = -EBUSY;
	else if (cpu)
		surface_to_cpu(surface);
	else
		surface_to_device(surface);
	capture_unlock_owner(view->buffer);
	return ret;
}

static void capture_prepare_view(void *private)
{
	struct capture_view *view = private;

	view->cache_error = capture_queue_transition(view, false);
}

static void capture_finish_view(void *private)
{
	struct capture_view *view = private;

	view->cache_error = capture_queue_transition(view, true);
}

int mt6797_capture_prepare(struct vb2_buffer *vb)
{
	struct capture_view *first = vb->planes[0].mem_priv;
	struct capture_view *second = vb->planes[1].mem_priv;
	int ret;

	if (vb->num_planes != 2 || !first || !second || first->buffer != second->buffer)
		return -EINVAL;
	ret = capture_queue_transition(first, false);
	if (!ret) {
		first->cache_error = 0;
		second->cache_error = 0;
	}
	return ret;
}

int mt6797_capture_finish_error(struct vb2_buffer *vb)
{
	struct capture_view *first = vb->planes[0].mem_priv;
	struct capture_view *second = vb->planes[1].mem_priv;

	return first->cache_error ? first->cache_error : second->cache_error;
}

const struct vb2_mem_ops mt6797_capture_memops = {
	.alloc = capture_alloc,
	.put = capture_view_put,
	.num_users = capture_num_users,
	.vaddr = capture_vaddr,
	.mmap = capture_view_mmap,
	.get_dmabuf = capture_get_dmabuf,
	.prepare = capture_prepare_view,
	.finish = capture_finish_view,
};

int mt6797_picture_from_vb2(struct vb2_buffer *vb, size_t luma,
			  struct mt6797_picture *picture)
{
	struct capture_view *first = vb->planes[0].mem_priv;
	struct capture_view *second = vb->planes[1].mem_priv;
	struct capture_surface *surface;
	size_t bytes;
	int ret;

	if (vb->num_planes != 2 || !first || !second || first->buffer != second->buffer)
		return -EINVAL;
	ret = mt6797_capture_size(luma, vb->planes[0].length, vb->planes[1].length, &bytes);
	if (ret)
		return ret;
	if (first->cache_error || second->cache_error)
		return first->cache_error ? first->cache_error : second->cache_error;
	surface = first->buffer->priv;
	if (surface->bytes != bytes)
		return -EINVAL;
	if (READ_ONCE(surface->poisoned))
		return -EIO;
	*picture = (struct mt6797_picture) {
		.buffer = first->buffer, .cpu = surface->cpu,
		.dma = surface->dma, .bytes = mt6797_picture_bytes(luma),
	};
	return 0;
}

void mt6797_picture_get(struct mt6797_picture *dst, const struct mt6797_picture *src)
{
	*dst = *src;
	get_dma_buf(dst->buffer);
}

void mt6797_picture_put(struct mt6797_picture *picture)
{
	if (picture->buffer)
		dma_buf_put(picture->buffer);
	memset(picture, 0, sizeof(*picture));
}

bool mt6797_picture_poisoned(const struct mt6797_picture *picture)
{
	struct capture_surface *surface = picture->buffer->priv;

	return READ_ONCE(surface->poisoned);
}

static const char *capture_fence_driver(struct dma_fence *fence)
{
	return "mt6797-vdec";
}

static const char *capture_fence_timeline(struct dma_fence *fence)
{
	return "capture";
}

static void capture_fence_release(struct dma_fence *fence)
{
	kfree(container_of(fence, struct capture_fence, base));
	module_put(THIS_MODULE);
}

static const struct dma_fence_ops capture_fence_ops = {
	.get_driver_name = capture_fence_driver,
	.get_timeline_name = capture_fence_timeline,
	.release = capture_fence_release,
};

static struct dma_fence *allocate_fence(void)
{
	struct capture_fence *fence = kzalloc(sizeof(*fence), GFP_KERNEL);

	if (!fence)
		return NULL;
	__module_get(THIS_MODULE);
	spin_lock_init(&fence->lock);
	dma_fence_init(&fence->base, &capture_fence_ops, &fence->lock,
		       dma_fence_context_alloc(1), 1);
	return &fence->base;
}

static void unlock_surfaces(struct mt6797_surface_job *job, unsigned int locked)
{
	while (locked)
		dma_resv_unlock(job->buffers[--locked]->resv);
}

static int lock_surfaces(struct mt6797_surface_job *job, struct ww_acquire_ctx *ctx)
{
	unsigned int i, blocked, slow = job->count;
	int ret;

retry:
	for (i = 0; i < job->count; i++) {
		if (i == slow)
			continue;
		ret = dma_resv_lock_interruptible(job->buffers[i]->resv, ctx);
		if (!ret)
			continue;
		blocked = i;
		while (i)
			if (--i != slow)
				dma_resv_unlock(job->buffers[i]->resv);
		if (slow < job->count)
			dma_resv_unlock(job->buffers[slow]->resv);
		if (ret != -EDEADLK)
			return ret;
		slow = blocked;
		ret = dma_resv_lock_slow_interruptible(job->buffers[slow]->resv, ctx);
		if (ret)
			return ret;
		goto retry;
	}
	ww_acquire_done(ctx);
	return 0;
}

static void release_job(struct mt6797_surface_job *job)
{
	unsigned int i;

	for (i = 0; i < job->count; i++)
		dma_buf_put(job->buffers[i]);
	dma_fence_put(job->output_fence);
	dma_fence_put(job->reference_fence);
	kfree(job);
}

struct mt6797_surface_job *mt6797_surface_job_begin(struct mt6797_picture *pictures,
						 unsigned int count,
						 unsigned int output)
{
	struct mt6797_surface_job *job;
	struct ww_acquire_ctx acquire;
	unsigned long deadline = jiffies + DEPENDENCY_TIMEOUT;
	unsigned int i, j, claimed = 0;
	int ret;

	if (count > SURFACE_LIMIT || output >= count || !pictures[output].buffer)
		return ERR_PTR(-EINVAL);
	job = kzalloc(sizeof(*job), GFP_KERNEL);
	if (!job)
		return ERR_PTR(-ENOMEM);
	for (i = 0; i < count; i++) {
		if (!pictures[i].buffer)
			continue;
		for (j = 0; j < job->count; j++)
			if (job->buffers[j] == pictures[i].buffer)
				break;
		if (j == job->count) {
			get_dma_buf(pictures[i].buffer);
			job->buffers[job->count++] = pictures[i].buffer;
		}
		job->write[j] |= i == output;
	}
	job->output_fence = allocate_fence();
	job->reference_fence = allocate_fence();
	if (!job->output_fence || !job->reference_fence) {
		ret = -ENOMEM;
		goto release;
	}
	ww_acquire_init(&acquire, &reservation_ww_class);
	ret = lock_surfaces(job, &acquire);
	if (ret)
		goto fini;
	for (i = 0; i < job->count; i++) {
		long remaining = deadline - jiffies;
		long waited;

		if (remaining <= 0) {
			ret = -ETIMEDOUT;
			goto unclaim;
		}
		/* This preparation also reads guarded reference memory through
		 * the CPU vmap. Retire readers before changing cache ownership.
		 */
		waited = dma_resv_wait_timeout(job->buffers[i]->resv, DMA_RESV_USAGE_READ,
					      true, remaining);
		if (waited <= 0) {
			ret = waited ? waited : -ETIMEDOUT;
			goto unclaim;
		}
		ret = dma_resv_reserve_fences(job->buffers[i]->resv, 1);
		if (ret)
			goto unclaim;
	}
	/* No dependency wait occurs while the owner lock is held. Keep it
	 * throughout the worker's CPU initialization/snapshot phase.
	 */
	mutex_lock(&capture_lock);
	job->cpu_locked = true;
	for (i = 0; i < job->count; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		if (surface->poisoned || surface->busy || surface->cpu_accesses) {
			ret = surface->poisoned ? -EIO : -EBUSY;
			goto unclaim;
		}
		surface->busy = true;
		claimed++;
	}
	/* Every dependency and reservation succeeded before publishing any
	 * fence. Native cache maintenance below does not wait on our own fence.
	 */
	for (i = 0; i < job->count; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		dma_resv_add_fence(job->buffers[i]->resv, job->write[i] ?
				   job->output_fence : job->reference_fence,
				   DMA_RESV_USAGE_WRITE);
		surface_to_cpu(surface);
	}
	unlock_surfaces(job, job->count);
	ww_acquire_fini(&acquire);
	return job;

unclaim:
	for (i = 0; i < claimed; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		surface->busy = false;
	}
	if (job->cpu_locked)
		mutex_unlock(&capture_lock);
	unlock_surfaces(job, job->count);
fini:
	ww_acquire_fini(&acquire);
release:
	release_job(job);
	return ERR_PTR(ret);
}

void mt6797_surface_job_to_device(struct mt6797_surface_job *job)
{
	unsigned int i;

	if (WARN_ON(!job->cpu_locked))
		return;
	for (i = 0; i < job->count; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		surface_to_device(surface);
	}
	job->cpu_locked = false;
	mutex_unlock(&capture_lock);
}

void mt6797_surface_job_to_cpu(struct mt6797_surface_job *job)
{
	unsigned int i;

	if (job->cpu_locked)
		return;
	mutex_lock(&capture_lock);
	for (i = 0; i < job->count; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		if (surface->device_owned)
			surface_to_cpu(surface);
	}
	job->cpu_locked = true;
}

void mt6797_surface_job_finish(struct mt6797_surface_job *job, int error,
			      int reference_error)
{
	unsigned int i;

	mt6797_surface_job_to_cpu(job);
	for (i = 0; i < job->count; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		/* Complete CPU diagnostics and give every mapped consumer the
		 * same device-domain contents before releasing reservation fences.
		 */
		surface_to_device(surface);
		surface->busy = false;
	}
	job->cpu_locked = false;
	mutex_unlock(&capture_lock);
	if (error < 0)
		dma_fence_set_error(job->output_fence, error);
	if (reference_error < 0)
		dma_fence_set_error(job->reference_fence, reference_error);
	dma_fence_signal(job->output_fence);
	dma_fence_signal(job->reference_fence);
	release_job(job);
}

void mt6797_surface_job_poison(struct mt6797_surface_job *job)
{
	unsigned int i;

	if (!job->cpu_locked)
		mutex_lock(&capture_lock);
	for (i = 0; i < job->count; i++) {
		struct capture_surface *surface = job->buffers[i]->priv;

		surface->poisoned = true;
	}
	job->cpu_locked = false;
	mutex_unlock(&capture_lock);
	/* The independent engine context retains this job, its mappings and
	 * dma_buf references. Its fence stays unsignalled until reboot.
	 */
}

MODULE_IMPORT_NS("DMA_BUF");
