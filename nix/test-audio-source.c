/* Synthetic stereo capture source for host-only ALSA route tests. */
#include <alsa/asoundlib.h>
#include <alsa/pcm_external.h>
#include <stdint.h>
#include <stdlib.h>

struct sample_source {
	snd_pcm_extplug_t pcm;
	uint64_t frame;
};

static snd_pcm_sframes_t source_transfer(snd_pcm_extplug_t *pcm,
		const snd_pcm_channel_area_t *dst, snd_pcm_uframes_t offset,
		const snd_pcm_channel_area_t *src, snd_pcm_uframes_t src_offset,
		snd_pcm_uframes_t frames)
{
	struct sample_source *source = pcm->private_data;
	snd_pcm_uframes_t frame;
	unsigned int channel;

	(void)src;
	(void)src_offset;
	for (frame = 0; frame < frames; frame++) {
		uint64_t index = source->frame + frame;
		int value[2] = { (int)(index * 37 % 6001) - 3000,
				12000 - (int)(index * 11 % 4001) };

		for (channel = 0; channel < 2; channel++) {
			unsigned char *out = (unsigned char *)dst[channel].addr +
				(dst[channel].first + (offset + frame) * dst[channel].step) / 8;
			uint16_t sample = (uint16_t)value[channel];

			out[0] = sample & 255;
			out[1] = sample >> 8;
		}
	}
	source->frame += frames;
	return frames;
}

static int source_init(snd_pcm_extplug_t *pcm)
{
	struct sample_source *source = pcm->private_data;

	source->frame = 0;
	return 0;
}

static int source_close(snd_pcm_extplug_t *pcm)
{
	free(pcm->private_data);
	return 0;
}

static const snd_pcm_extplug_callback_t callbacks = {
	.transfer = source_transfer,
	.init = source_init,
	.close = source_close,
};

SND_PCM_PLUGIN_DEFINE_FUNC(gemini_test_source)
{
	struct sample_source *source;
	snd_config_t *slave;
	int ret;

	if (stream != SND_PCM_STREAM_CAPTURE || snd_config_search(conf, "slave", &slave) < 0)
		return -EINVAL;
	source = calloc(1, sizeof(*source));
	if (!source)
		return -ENOMEM;
	source->pcm.version = SND_PCM_EXTPLUG_VERSION;
	source->pcm.name = "Gemini synthetic stereo source";
	source->pcm.callback = &callbacks;
	source->pcm.private_data = source;
	ret = snd_pcm_extplug_create(&source->pcm, name, root, slave, stream, mode);
	if (ret < 0) {
		free(source);
		return ret;
	}
	ret = snd_pcm_extplug_set_param(&source->pcm, SND_PCM_EXTPLUG_HW_CHANNELS, 2);
	if (!ret)
		ret = snd_pcm_extplug_set_slave_param(&source->pcm, SND_PCM_EXTPLUG_HW_CHANNELS, 2);
	if (!ret)
		ret = snd_pcm_extplug_set_param(&source->pcm, SND_PCM_EXTPLUG_HW_FORMAT, SND_PCM_FORMAT_S16_LE);
	if (!ret)
		ret = snd_pcm_extplug_set_slave_param(&source->pcm, SND_PCM_EXTPLUG_HW_FORMAT, SND_PCM_FORMAT_S16_LE);
	if (ret < 0) {
		snd_pcm_extplug_delete(&source->pcm);
		return ret;
	}
	*pcmp = source->pcm.pcm;
	return 0;
}
SND_PCM_PLUGIN_SYMBOL(gemini_test_source);
