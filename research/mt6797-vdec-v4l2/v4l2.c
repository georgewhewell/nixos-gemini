// SPDX-License-Identifier: GPL-2.0-only
/* Original Linux Request-API frontend. Initial hardware scope is deliberately
 * restricted by engine.c to the cases exercised by the private diagnostics.
 */
#include <linux/module.h>
#include <linux/pm_runtime.h>
#include <linux/sizes.h>
#include <linux/workqueue.h>
#include <media/media-device.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-fh.h>
#include <media/v4l2-ioctl.h>
#include <media/v4l2-mem2mem.h>
#include <media/videobuf2-vmalloc.h>
#include "engine.h"

#define INPUT_SIZE (SZ_128K - 128)

struct decoder {
	struct device *dev;
	struct mt6797_engine *engine;
	struct media_device media;
	struct v4l2_device v4l2;
	struct video_device video;
	struct v4l2_m2m_dev *m2m;
	struct mutex mutex;
	struct workqueue_struct *queue;
	struct work_struct work;
	struct mt6797_decode_status last_status;
	spinlock_t status_lock;
	int last_result;
	u64 jobs, failures;
};

struct decode_file {
	struct decoder *decoder;
	struct v4l2_fh fh;
	struct v4l2_ctrl_handler controls;
	struct mt6797_decode_context *context;
	struct mt6797_decode_job job;
	struct v4l2_ctrl *sps, *pps, *slice, *decode;
	atomic_t abort;
	u32 sequence;
	u16 width, height;
};

static struct decode_file *file_context(void *priv)
{
	return container_of(priv, struct decode_file, fh);
}

static bool output_queue(enum v4l2_buf_type type)
{
	return type == V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
}

static int query_capability(struct file *file, void *priv, struct v4l2_capability *cap)
{
	strscpy(cap->driver, "mt6797-vdec", sizeof(cap->driver));
	strscpy(cap->card, "MT6797 H.264 Request decoder", sizeof(cap->card));
	/* The ioctl core supplies bus_info and passes NULL as priv on this
	 * kernel. Capability queries require no per-file decoder state.
	 */
	return 0;
}

static int enumerate_format(struct file *file, void *priv, struct v4l2_fmtdesc *format)
{
	if (format->index || (format->type != V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE &&
			      format->type != V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE))
		return -EINVAL;
	format->pixelformat = output_queue(format->type) ? V4L2_PIX_FMT_H264_SLICE : V4L2_PIX_FMT_MM21;
	if (output_queue(format->type))
		format->flags = V4L2_FMT_FLAG_COMPRESSED;
	return 0;
}

static int enumerate_size(struct file *file, void *priv, struct v4l2_frmsizeenum *size)
{
	if (size->index >= 17 * 7 || (size->pixel_format != V4L2_PIX_FMT_H264_SLICE &&
			    size->pixel_format != V4L2_PIX_FMT_MM21))
		return -EINVAL;
	size->type = V4L2_FRMSIZE_TYPE_DISCRETE;
	size->discrete.width = 64 + 16 * (size->index / 7);
	size->discrete.height = 64 + 32 * (size->index % 7);
	return 0;
}

static int fill_format(struct v4l2_format *format, unsigned int width, unsigned int height)
{
	struct v4l2_pix_format_mplane *pix = &format->fmt.pix_mp;
	bool output = output_queue(format->type);
	if (!output && format->type != V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)
		return -EINVAL;
	memset(pix, 0, sizeof(*pix));
	pix->width = width;
	pix->height = height;
	pix->field = V4L2_FIELD_NONE;
	pix->pixelformat = output ? V4L2_PIX_FMT_H264_SLICE : V4L2_PIX_FMT_MM21;
	pix->num_planes = output ? 1 : 2;
	pix->plane_fmt[0].sizeimage = output ? INPUT_SIZE : width * height;
	if (!output) {
		pix->plane_fmt[0].bytesperline = width;
		pix->plane_fmt[1].bytesperline = width;
		pix->plane_fmt[1].sizeimage = width * height / 2;
	}
	return 0;
}

static int get_format(struct file *file, void *priv, struct v4l2_format *format)
{
	struct decode_file *ctx = file_context(file_to_v4l2_fh(file));
	return fill_format(format, ctx->width, ctx->height);
}

static int try_format(struct file *file, void *priv, struct v4l2_format *format)
{
	struct decode_file *ctx = file_context(file_to_v4l2_fh(file));
	unsigned int width = ctx->width, height = ctx->height;
	if (output_queue(format->type)) {
		width = ALIGN(clamp(format->fmt.pix_mp.width, 64U, 320U), 16U);
		height = ALIGN(clamp(format->fmt.pix_mp.height, 64U, 256U), 32U);
	}
	return fill_format(format, width, height);
}

static int set_format(struct file *file, void *priv, struct v4l2_format *format)
{
	struct decode_file *ctx = file_context(file_to_v4l2_fh(file));
	struct vb2_queue *queue = v4l2_m2m_get_vq(ctx->fh.m2m_ctx, format->type);
	if (!queue)
		return -EINVAL;
	if (vb2_is_busy(queue) ||
	    (output_queue(format->type) && vb2_is_busy(v4l2_m2m_get_dst_vq(ctx->fh.m2m_ctx))))
		return -EBUSY;
	if (try_format(file, priv, format))
		return -EINVAL;
	if (output_queue(format->type)) {
		ctx->width = format->fmt.pix_mp.width;
		ctx->height = format->fmt.pix_mp.height;
		mt6797_decode_context_reset(ctx->context);
	}
	return 0;
}

static int queue_setup(struct vb2_queue *queue, unsigned int *buffers,
		       unsigned int *planes, unsigned int sizes[], struct device *devices[])
{
	bool output = output_queue(queue->type);
	struct decode_file *ctx = vb2_get_drv_priv(queue);
	unsigned int luma_size = ctx->width * ctx->height;
	unsigned int count = output ? 1 : 2;
	unsigned int first = output ? INPUT_SIZE : luma_size;
	if (*planes) {
		if (*planes != count || sizes[0] < first || (!output && sizes[1] < luma_size / 2))
			return -EINVAL;
		return 0;
	}
	*planes = count;
	sizes[0] = first;
	if (!output)
		sizes[1] = luma_size / 2;
	return 0;
}

static int prepare_buffer(struct vb2_buffer *buffer)
{
	bool output = output_queue(buffer->vb2_queue->type);
	struct decode_file *ctx = vb2_get_drv_priv(buffer->vb2_queue);
	unsigned int luma_size = ctx->width * ctx->height;
	struct vb2_v4l2_buffer *vbuf = to_vb2_v4l2_buffer(buffer);
	unsigned int first = output ? INPUT_SIZE : luma_size;
	unsigned int bytes = vb2_get_plane_payload(buffer, 0);
	unsigned int offset = buffer->planes[0].data_offset;
	if (vb2_plane_size(buffer, 0) < first ||
	    (!output && vb2_plane_size(buffer, 1) < luma_size / 2))
		return -EINVAL;
	if (output && (bytes <= offset || bytes - offset > INPUT_SIZE))
		return -EINVAL;
	vbuf->field = V4L2_FIELD_NONE;
	if (!output) {
		vb2_set_plane_payload(buffer, 0, 0);
		vb2_set_plane_payload(buffer, 1, 0);
	}
	return 0;
}

static void queue_buffer(struct vb2_buffer *buffer)
{
	struct decode_file *ctx = vb2_get_drv_priv(buffer->vb2_queue);
	v4l2_m2m_buf_queue(ctx->fh.m2m_ctx, to_vb2_v4l2_buffer(buffer));
}

static int validate_output_buffer(struct vb2_buffer *buffer)
{
	struct vb2_v4l2_buffer *vbuf = to_vb2_v4l2_buffer(buffer);
	/* Request binding needs this hook before the later buf_prepare call. */
	if (vbuf->field != V4L2_FIELD_ANY && vbuf->field != V4L2_FIELD_NONE)
		return -EOPNOTSUPP;
	vbuf->field = V4L2_FIELD_NONE;
	return 0;
}

static void complete_buffer_request(struct vb2_buffer *buffer)
{
	struct decode_file *ctx = vb2_get_drv_priv(buffer->vb2_queue);
	if (buffer->req_obj.req)
		v4l2_ctrl_request_complete(buffer->req_obj.req, &ctx->controls);
}

static int start_stream(struct vb2_queue *queue, unsigned int count)
{
	struct decode_file *ctx = vb2_get_drv_priv(queue);
	atomic_set(&ctx->abort, 0);
	return 0;
}

static void stop_stream(struct vb2_queue *queue)
{
	struct decode_file *ctx = vb2_get_drv_priv(queue);
	struct vb2_v4l2_buffer *buffer;
	/* The mem2mem core drains the running job before calling this callback.
	 * Its worker always proves DMA stop before returning a successful buffer.
	 */
	if (output_queue(queue->type)) {
		while ((buffer = v4l2_m2m_src_buf_remove(ctx->fh.m2m_ctx))) {
			complete_buffer_request(&buffer->vb2_buf);
			v4l2_m2m_buf_done(buffer, VB2_BUF_STATE_ERROR);
		}
	} else {
		while ((buffer = v4l2_m2m_dst_buf_remove(ctx->fh.m2m_ctx)))
			v4l2_m2m_buf_done(buffer, VB2_BUF_STATE_ERROR);
	}
	mt6797_decode_context_reset(ctx->context);
}

static const struct vb2_ops buffer_ops = {
	.queue_setup = queue_setup,
	.buf_prepare = prepare_buffer,
	.buf_out_validate = validate_output_buffer,
	.buf_queue = queue_buffer,
	.buf_request_complete = complete_buffer_request,
	.start_streaming = start_stream,
	.stop_streaming = stop_stream,
};

static int initialize_queues(void *priv, struct vb2_queue *source, struct vb2_queue *capture)
{
	struct decode_file *ctx = priv;
	struct vb2_queue *queues[] = { source, capture };
	unsigned int i;
	int ret;
	for (i = 0; i < ARRAY_SIZE(queues); i++) {
		struct vb2_queue *queue = queues[i];
		queue->type = i ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
		queue->io_modes = VB2_MMAP;
		queue->drv_priv = ctx;
		queue->ops = &buffer_ops;
		queue->mem_ops = &vb2_vmalloc_memops;
		queue->buf_struct_size = sizeof(struct v4l2_m2m_buffer);
		queue->timestamp_flags = V4L2_BUF_FLAG_TIMESTAMP_COPY;
		queue->lock = &ctx->decoder->mutex;
		queue->dev = ctx->decoder->dev;
		queue->max_num_buffers = 32;
		queue->supports_requests = !i;
		queue->requires_requests = !i;
		ret = vb2_queue_init(queue);
		if (ret)
			return ret;
	}
	return 0;
}

static void decode_work(struct work_struct *work)
{
	struct decoder *decoder = container_of(work, struct decoder, work);
	struct decode_file *ctx = v4l2_m2m_get_curr_priv(decoder->m2m);
	struct vb2_v4l2_buffer *source = v4l2_m2m_next_src_buf(ctx->fh.m2m_ctx);
	struct vb2_v4l2_buffer *capture = v4l2_m2m_next_dst_buf(ctx->fh.m2m_ctx);
	struct media_request *request = source->vb2_buf.req_obj.req;
	const u8 *pixels = NULL;
	struct mt6797_decode_status status = { 0 };
	unsigned long flags;
	int ret;

	ret = request ? v4l2_ctrl_request_setup(request, &ctx->controls) : -EINVAL;
	if (!ret) {
		/* Snapshot control payloads under the handler lock. Later control
		 * updates cannot alter an in-flight hardware job.
		 */
		mutex_lock(ctx->controls.lock);
		ctx->job.sps = *ctx->sps->p_cur.p_h264_sps;
		ctx->job.pps = *ctx->pps->p_cur.p_h264_pps;
		ctx->job.slice = *ctx->slice->p_cur.p_h264_slice_params;
		ctx->job.decode = *ctx->decode->p_cur.p_h264_decode_params;
		ctx->job.width = ctx->width;
		ctx->job.height = ctx->height;
		mutex_unlock(ctx->controls.lock);
		ctx->job.nal = vb2_plane_vaddr(&source->vb2_buf, 0);
		if (!ctx->job.nal)
			ret = -EFAULT;
		else {
			ctx->job.nal += source->vb2_buf.planes[0].data_offset;
			ctx->job.bytes = vb2_get_plane_payload(&source->vb2_buf, 0) - source->vb2_buf.planes[0].data_offset;
			ctx->job.timestamp = source->vb2_buf.timestamp;
			ret = atomic_read(&ctx->abort) ? -ECANCELED :
				mt6797_engine_decode(ctx->context, &ctx->job, &pixels, &status);
		}
	}
	if (atomic_read(&ctx->abort))
		ret = -ECANCELED;
	if (!ret) {
		unsigned int luma_size = ctx->width * ctx->height;
		memcpy(vb2_plane_vaddr(&capture->vb2_buf, 0), pixels, luma_size);
		memcpy(vb2_plane_vaddr(&capture->vb2_buf, 1), pixels + luma_size, luma_size / 2);
		vb2_set_plane_payload(&capture->vb2_buf, 0, luma_size);
		vb2_set_plane_payload(&capture->vb2_buf, 1, luma_size / 2);
	}
	spin_lock_irqsave(&decoder->status_lock, flags);
	decoder->last_status = status;
	decoder->last_result = ret;
	decoder->jobs++;
	if (ret)
		decoder->failures++;
	spin_unlock_irqrestore(&decoder->status_lock, flags);
	v4l2_m2m_buf_copy_metadata(source, capture);
	capture->sequence = ctx->sequence++;
	if (request)
		v4l2_ctrl_request_complete(request, &ctx->controls);
	v4l2_m2m_buf_done_and_job_finish(decoder->m2m, ctx->fh.m2m_ctx,
				       ret ? VB2_BUF_STATE_ERROR : VB2_BUF_STATE_DONE);
}

static void run_job(void *priv)
{
	struct decode_file *ctx = priv;
	queue_work(ctx->decoder->queue, &ctx->decoder->work);
}

static void abort_job(void *priv)
{
	struct decode_file *ctx = priv;
	/* The bounded worker still owns DMA until stop/reset acknowledgement. */
	atomic_set(&ctx->abort, 1);
}

static const struct v4l2_m2m_ops job_ops = {
	.device_run = run_job,
	.job_abort = abort_job,
};

static int open_decoder(struct file *file)
{
	struct decoder *decoder = video_drvdata(file);
	struct decode_file *ctx;
	struct v4l2_ctrl_config config = { 0 };
	int ret;

	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->decoder = decoder;
	ctx->width = ctx->height = 64;
	mutex_lock(&decoder->mutex);
	ctx->context = mt6797_decode_context_create(decoder->engine);
	if (IS_ERR(ctx->context)) {
		ret = PTR_ERR(ctx->context);
		goto free;
	}
	v4l2_fh_init(&ctx->fh, &decoder->video);
	v4l2_ctrl_handler_init(&ctx->controls, 7);
	config.id = V4L2_CID_STATELESS_H264_SPS;
	ctx->sps = v4l2_ctrl_new_custom(&ctx->controls, &config, NULL);
	config.id = V4L2_CID_STATELESS_H264_PPS;
	ctx->pps = v4l2_ctrl_new_custom(&ctx->controls, &config, NULL);
	config.id = V4L2_CID_STATELESS_H264_SLICE_PARAMS;
	ctx->slice = v4l2_ctrl_new_custom(&ctx->controls, &config, NULL);
	config.id = V4L2_CID_STATELESS_H264_DECODE_PARAMS;
	ctx->decode = v4l2_ctrl_new_custom(&ctx->controls, &config, NULL);
	config.id = V4L2_CID_STATELESS_H264_SCALING_MATRIX;
	v4l2_ctrl_new_custom(&ctx->controls, &config, NULL);
	v4l2_ctrl_new_std_menu(&ctx->controls, NULL, V4L2_CID_STATELESS_H264_DECODE_MODE,
			       V4L2_STATELESS_H264_DECODE_MODE_SLICE_BASED, 0,
			       V4L2_STATELESS_H264_DECODE_MODE_SLICE_BASED);
	v4l2_ctrl_new_std_menu(&ctx->controls, NULL, V4L2_CID_STATELESS_H264_START_CODE,
			       V4L2_STATELESS_H264_START_CODE_NONE, 0,
			       V4L2_STATELESS_H264_START_CODE_NONE);
	ret = ctx->controls.error;
	if (ret)
		goto controls;
	ctx->fh.ctrl_handler = &ctx->controls;
	ctx->fh.m2m_ctx = v4l2_m2m_ctx_init(decoder->m2m, ctx, initialize_queues);
	if (IS_ERR(ctx->fh.m2m_ctx)) {
		ret = PTR_ERR(ctx->fh.m2m_ctx);
		goto controls;
	}
	file->private_data = &ctx->fh;
	v4l2_fh_add(&ctx->fh, file);
	mutex_unlock(&decoder->mutex);
	return 0;
controls:
	v4l2_ctrl_handler_free(&ctx->controls);
	v4l2_fh_exit(&ctx->fh);
	mt6797_decode_context_destroy(ctx->context);
free:
	mutex_unlock(&decoder->mutex);
	kfree(ctx);
	return ret;
}

static int release_decoder(struct file *file)
{
	struct decode_file *ctx = file_context(file->private_data);
	struct decoder *decoder = ctx->decoder;
	mutex_lock(&decoder->mutex);
	v4l2_m2m_ctx_release(ctx->fh.m2m_ctx);
	v4l2_fh_del(&ctx->fh, file);
	v4l2_fh_exit(&ctx->fh);
	v4l2_ctrl_handler_free(&ctx->controls);
	mt6797_decode_context_destroy(ctx->context);
	mutex_unlock(&decoder->mutex);
	kfree(ctx);
	return 0;
}

static const struct v4l2_file_operations file_ops = {
	.owner = THIS_MODULE,
	.open = open_decoder,
	.release = release_decoder,
	.unlocked_ioctl = video_ioctl2,
	.poll = v4l2_m2m_fop_poll,
	.mmap = v4l2_m2m_fop_mmap,
};

static const struct v4l2_ioctl_ops ioctls = {
	.vidioc_querycap = query_capability,
	.vidioc_enum_fmt_vid_out = enumerate_format,
	.vidioc_enum_fmt_vid_cap = enumerate_format,
	.vidioc_enum_framesizes = enumerate_size,
	.vidioc_g_fmt_vid_out_mplane = get_format,
	.vidioc_g_fmt_vid_cap_mplane = get_format,
	.vidioc_try_fmt_vid_out_mplane = try_format,
	.vidioc_try_fmt_vid_cap_mplane = try_format,
	.vidioc_s_fmt_vid_out_mplane = set_format,
	.vidioc_s_fmt_vid_cap_mplane = set_format,
	.vidioc_reqbufs = v4l2_m2m_ioctl_reqbufs,
	.vidioc_create_bufs = v4l2_m2m_ioctl_create_bufs,
	.vidioc_querybuf = v4l2_m2m_ioctl_querybuf,
	.vidioc_expbuf = v4l2_m2m_ioctl_expbuf,
	.vidioc_qbuf = v4l2_m2m_ioctl_qbuf,
	.vidioc_dqbuf = v4l2_m2m_ioctl_dqbuf,
	.vidioc_prepare_buf = v4l2_m2m_ioctl_prepare_buf,
	.vidioc_streamon = v4l2_m2m_ioctl_streamon,
	.vidioc_streamoff = v4l2_m2m_ioctl_streamoff,
};

static const struct media_device_ops request_ops = {
	.req_validate = vb2_request_validate,
	.req_queue = v4l2_m2m_request_queue,
};

static int runtime_resume(struct device *dev)
{
	return mt6797_engine_resume(((struct decoder *)dev_get_drvdata(dev))->engine);
}

static int runtime_suspend(struct device *dev)
{
	return mt6797_engine_suspend(((struct decoder *)dev_get_drvdata(dev))->engine);
}

static int system_suspend(struct device *dev)
{
	struct decoder *decoder = dev_get_drvdata(dev);
	int ret;
	v4l2_m2m_suspend(decoder->m2m);
	flush_workqueue(decoder->queue);
	ret = pm_runtime_force_suspend(dev);
	if (ret)
		v4l2_m2m_resume(decoder->m2m);
	return ret;
}

static int system_resume(struct device *dev)
{
	struct decoder *decoder = dev_get_drvdata(dev);
	int ret = pm_runtime_force_resume(dev);
	if (!ret)
		v4l2_m2m_resume(decoder->m2m);
	return ret;
}

static const struct dev_pm_ops power_ops = {
	SET_RUNTIME_PM_OPS(runtime_suspend, runtime_resume, NULL)
	SET_SYSTEM_SLEEP_PM_OPS(system_suspend, system_resume)
};

/* Cached observations only: sysfs never powers the block or reads live MMIO. */
static ssize_t last_job_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct decoder *decoder = dev_get_drvdata(dev);
	struct mt6797_decode_status status;
	unsigned long flags;
	u64 jobs, failures;
	int result;
	spin_lock_irqsave(&decoder->status_lock, flags);
	status = decoder->last_status;
	jobs = decoder->jobs;
	failures = decoder->failures;
	result = decoder->last_result;
	spin_unlock_irqrestore(&decoder->status_lock, flags);
	return sysfs_emit(buf, "jobs=%llu failures=%llu result=%d fetched=%u submitted=%u state=%#x error=%#x message=%#x irq=%#x break=%d reset=%d quiesced=%u guards=%u\n",
		jobs, failures, result, status.fetched, status.submitted, status.state, status.error,
		status.message, status.irq, status.break_result, status.reset_result,
		status.quiesced, status.guards_unchanged);
}
static DEVICE_ATTR_RO(last_job);
static struct attribute *decoder_attrs[] = { &dev_attr_last_job.attr, NULL };
ATTRIBUTE_GROUPS(decoder);

static int probe_decoder(struct platform_device *pdev)
{
	struct decoder *decoder;
	int ret;
	decoder = devm_kzalloc(&pdev->dev, sizeof(*decoder), GFP_KERNEL);
	if (!decoder)
		return -ENOMEM;
	decoder->dev = &pdev->dev;
	mutex_init(&decoder->mutex);
	spin_lock_init(&decoder->status_lock);
	platform_set_drvdata(pdev, decoder);
	decoder->engine = mt6797_engine_create(pdev);
	if (IS_ERR(decoder->engine))
		return dev_err_probe(&pdev->dev, PTR_ERR(decoder->engine), "decoder resource admission failed\n");
	decoder->queue = alloc_ordered_workqueue("mt6797-vdec", WQ_MEM_RECLAIM);
	if (!decoder->queue) {
		ret = -ENOMEM;
		goto engine;
	}
	INIT_WORK(&decoder->work, decode_work);
	media_device_init(&decoder->media);
	decoder->media.dev = &pdev->dev;
	decoder->media.ops = &request_ops;
	strscpy(decoder->media.model, "MT6797 H.264 Request decoder", sizeof(decoder->media.model));
	decoder->v4l2.mdev = &decoder->media;
	ret = v4l2_device_register(&pdev->dev, &decoder->v4l2);
	if (ret)
		goto media;
	decoder->m2m = v4l2_m2m_init(&job_ops);
	if (IS_ERR(decoder->m2m)) {
		ret = PTR_ERR(decoder->m2m);
		goto v4l2;
	}
	strscpy(decoder->video.name, "mt6797-vdec", sizeof(decoder->video.name));
	decoder->video.fops = &file_ops;
	decoder->video.ioctl_ops = &ioctls;
	decoder->video.release = video_device_release_empty;
	decoder->video.lock = &decoder->mutex;
	decoder->video.v4l2_dev = &decoder->v4l2;
	decoder->video.vfl_dir = VFL_DIR_M2M;
	decoder->video.device_caps = V4L2_CAP_VIDEO_M2M_MPLANE | V4L2_CAP_STREAMING;
	video_set_drvdata(&decoder->video, decoder);
	ret = video_register_device(&decoder->video, VFL_TYPE_VIDEO, -1);
	if (ret)
		goto m2m;
	ret = v4l2_m2m_register_media_controller(decoder->m2m, &decoder->video,
						 MEDIA_ENT_F_PROC_VIDEO_DECODER);
	if (ret)
		goto video;
	ret = media_device_register(&decoder->media);
	if (!ret)
		return 0;
	v4l2_m2m_unregister_media_controller(decoder->m2m);
video:
	video_unregister_device(&decoder->video);
m2m:
	v4l2_m2m_release(decoder->m2m);
v4l2:
	v4l2_device_unregister(&decoder->v4l2);
media:
	media_device_cleanup(&decoder->media);
	destroy_workqueue(decoder->queue);
engine:
	mt6797_engine_destroy(decoder->engine);
	return ret;
}

static void remove_decoder(struct platform_device *pdev)
{
	struct decoder *decoder = platform_get_drvdata(pdev);
	video_unregister_device(&decoder->video);
	flush_workqueue(decoder->queue);
	media_device_unregister(&decoder->media);
	v4l2_m2m_unregister_media_controller(decoder->m2m);
	v4l2_m2m_release(decoder->m2m);
	v4l2_device_unregister(&decoder->v4l2);
	media_device_cleanup(&decoder->media);
	destroy_workqueue(decoder->queue);
	mt6797_engine_destroy(decoder->engine);
}

static const struct of_device_id decoder_match[] = {
	{ .compatible = "mediatek,mt6797-vcodec-dec" }, { }
};
MODULE_DEVICE_TABLE(of, decoder_match);

static struct platform_driver decoder_driver = {
	.probe = probe_decoder,
	.remove = remove_decoder,
	.driver = {
		.name = "mt6797-vdec",
		.dev_groups = decoder_groups,
		.of_match_table = decoder_match,
		.pm = &power_ops,
		.suppress_bind_attrs = true,
	},
};
module_platform_driver(decoder_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Original MT6797 H.264 V4L2 Request decoder");
