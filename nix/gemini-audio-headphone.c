// SPDX-License-Identifier: GPL-2.0-only
/*
 * Fail-closed, one-stage Gemini MT6797/MT6351 headphone diagnostic.
 *
 * Every ALSA control or PCM ioctl has an unbuffered, fsync-attempted BEFORE
 * record and a matching AFTER record. A missing AFTER record means that the
 * preceding syscall did not return; an in-process deadline cannot help when
 * the whole kernel has stalled. The default stage is observation only.
 *
 * This deliberately does not write PCM frames, PREPARE, START, or DRAIN.
 * The most invasive available stage is hw-params: it is followed by HW_FREE
 * when userspace still runs. A control activation similarly restores its
 * original value even when the target write reports an error.
 */
#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sound/asound.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define PCM_DEVICE 0U
#define SAMPLE_RATE 48000U

enum control_kind { CONTROL_BOOLEAN, CONTROL_ENUM };
enum stage {
	STAGE_OBSERVE,
	STAGE_CONTROL_READ,
	STAGE_CONTROL_ACTIVATE,
	STAGE_PCM_OPEN,
	STAGE_PCM_HW_REFINE,
	STAGE_PCM_HW_PARAMS,
};

struct control_spec {
	const char *name;
	enum control_kind kind;
	const char *enum_item;
};

struct saved_control {
	struct snd_ctl_elem_info info;
	struct snd_ctl_elem_value value;
	unsigned int enum_item;
};

struct options {
	unsigned int card;
	unsigned int control;
	enum stage stage;
	bool have_control;
	bool activate;
};

static const struct control_spec controls[] = {
	{ "ADDA_DL_CH1 DL1_CH1", CONTROL_BOOLEAN, NULL },
	{ "ADDA_DL_CH2 DL1_CH2", CONTROL_BOOLEAN, NULL },
	{ "HPL Mux", CONTROL_ENUM, "Audio Playback" },
	{ "HPR Mux", CONTROL_ENUM, "Audio Playback" },
};

static unsigned int sequence;

static void boundary(const char *phase, const char *kind, const char *op,
			 int result, int error)
{
	if (strcmp(phase, "before") == 0)
		fprintf(stderr, "gemini-audio-headphone: seq=%u phase=before kind=%s op=%s\n",
			++sequence, kind, op);
	else
		fprintf(stderr,
			"gemini-audio-headphone: seq=%u phase=after kind=%s op=%s ret=%d errno=%d (%s)\n",
			sequence, kind, op, result, error, strerror(error));
	/* stderr is unbuffered, but also flush the stdio and kernel layers for a
	 * redirected SSH stream. fsync(pipe/socket) normally returns EINVAL. */
	fflush(stderr);
	(void)fsync(STDERR_FILENO);
}

static int traced_ioctl(int fd, unsigned long request, void *argument,
			const char *kind, const char *op)
{
	int ret, saved_errno;

	boundary("before", kind, op, 0, 0);
	errno = 0;
	ret = ioctl(fd, (int)request, argument);
	saved_errno = errno;
	boundary("after", kind, op, ret, saved_errno);
	errno = saved_errno;
	return ret;
}

static int traced_open(const char *path, int flags, const char *kind,
		       const char *op)
{
	int ret, saved_errno;

	boundary("before", kind, op, 0, 0);
	errno = 0;
	ret = open(path, flags);
	saved_errno = errno;
	boundary("after", kind, op, ret, saved_errno);
	errno = saved_errno;
	return ret;
}

static void traced_close(int *fd, const char *kind)
{
	int ret, saved_errno;

	if (*fd < 0)
		return;
	boundary("before", kind, "close", 0, 0);
	errno = 0;
	ret = close(*fd);
	saved_errno = errno;
	boundary("after", kind, "close", ret, saved_errno);
	*fd = -1;
}

static void print_errno(const char *what)
{
	fprintf(stderr, "gemini-audio-headphone: %s: %s\n", what, strerror(errno));
	fflush(stderr);
}

static int parse_unsigned(const char *text, unsigned int *value)
{
	char *end;
	unsigned long parsed;

	errno = 0;
	parsed = strtoul(text, &end, 10);
	if (errno || *text == '\0' || *end != '\0' || parsed > UINT_MAX)
		return -1;
	*value = (unsigned int)parsed;
	return 0;
}

static int parse_stage(const char *text, enum stage *stage)
{
	if (strcmp(text, "observe") == 0)
		*stage = STAGE_OBSERVE;
	else if (strcmp(text, "control-read") == 0)
		*stage = STAGE_CONTROL_READ;
	else if (strcmp(text, "control-activate") == 0)
		*stage = STAGE_CONTROL_ACTIVATE;
	else if (strcmp(text, "pcm-open") == 0)
		*stage = STAGE_PCM_OPEN;
	else if (strcmp(text, "pcm-hw-refine") == 0)
		*stage = STAGE_PCM_HW_REFINE;
	else if (strcmp(text, "pcm-hw-params") == 0)
		*stage = STAGE_PCM_HW_PARAMS;
	else
		return -1;
	return 0;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [--card N] [--stage observe|control-read|control-activate|pcm-open|pcm-hw-refine|pcm-hw-params] [--control 0..3] [--activate]\n"
		"  default: --stage observe (CARD_INFO and PCM_INFO only)\n"
		"  --activate is mandatory for control-activate and every PCM stage\n"
		"  no stage writes frames, PREPAREs, STARTs, or DRAINs PCM\n",
		argv0);
}

static int parse_options(int argc, char **argv, struct options *options)
{
	int i;

	*options = (struct options){ .stage = STAGE_OBSERVE };
	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--activate") == 0)
			options->activate = true;
		else if (strcmp(argv[i], "--card") == 0 && i + 1 < argc) {
			if (parse_unsigned(argv[++i], &options->card) < 0)
				goto invalid;
		} else if (strcmp(argv[i], "--control") == 0 && i + 1 < argc) {
			if (parse_unsigned(argv[++i], &options->control) < 0)
				goto invalid;
			options->have_control = true;
		} else if (strcmp(argv[i], "--stage") == 0 && i + 1 < argc) {
			if (parse_stage(argv[++i], &options->stage) < 0)
				goto invalid;
		} else
			goto invalid;
	}
	if ((options->stage == STAGE_CONTROL_READ || options->stage == STAGE_CONTROL_ACTIVATE) &&
	    (!options->have_control || options->control >= sizeof(controls) / sizeof(controls[0])))
		goto invalid;
	if ((options->stage == STAGE_CONTROL_ACTIVATE || options->stage >= STAGE_PCM_OPEN) &&
	    !options->activate)
		goto invalid;
	return 0;
invalid:
	usage(argv[0]);
	return -1;
}

static int open_control(unsigned int card, bool writable)
{
	char path[64];

	if (snprintf(path, sizeof(path), "/dev/snd/controlC%u", card) >= (int)sizeof(path))
		return -1;
	return traced_open(path, (writable ? O_RDWR : O_RDONLY) | O_CLOEXEC,
			   "control", "open");
}

static int verify_card(int fd)
{
	struct snd_ctl_card_info info = { 0 };

	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_CARD_INFO, &info, "control", "CARD_INFO") < 0)
		return -1;
	if (strncmp((const char *)info.name, "mt6797-mt6351", sizeof(info.name)) != 0) {
		fprintf(stderr, "gemini-audio-headphone: refusing unexpected ALSA card '%.*s'\n",
			(int)sizeof(info.name), info.name);
		return -1;
	}
	return 0;
}

static int verify_playback_1(int fd)
{
	static const char expected[] = "Playback_1";
	struct snd_pcm_info info = {
		.device = PCM_DEVICE,
		.subdevice = 0,
		.stream = SNDRV_PCM_STREAM_PLAYBACK,
	};

	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_PCM_INFO, &info, "control", "PCM_INFO") < 0)
		return -1;
	if (strncmp((const char *)info.id, expected, sizeof(expected) - 1) != 0 ||
	    (info.id[sizeof(expected) - 1] != '\0' && info.id[sizeof(expected) - 1] != ' ')) {
		fprintf(stderr, "gemini-audio-headphone: PCM C?D0p identity is id='%.*s' name='%.*s' subname='%.*s', not Playback_1\n",
			(int)sizeof(info.id), info.id, (int)sizeof(info.name), info.name,
			(int)sizeof(info.subname), info.subname);
		return -1;
	}
	return 0;
}

static int find_control(int fd, const char *name, struct snd_ctl_elem_id *id)
{
	struct snd_ctl_elem_list list = { 0 };
	struct snd_ctl_elem_id *ids;
	unsigned int i;
	int ret = -1;

	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list, "control", "ELEM_LIST(count)") < 0 ||
	    list.count == 0)
		return -1;
	ids = calloc(list.count, sizeof(*ids));
	if (!ids)
		return -1;
	list.space = list.count;
	list.pids = ids;
	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list, "control", "ELEM_LIST(entries)") < 0)
		goto out;
	for (i = 0; i < list.used; i++) {
		if (strncmp((const char *)ids[i].name, name, sizeof(ids[i].name)) == 0) {
			*id = ids[i];
			ret = 0;
			break;
		}
	}
out:
	free(ids);
	return ret;
}

static int prepare_control(int fd, const struct control_spec *spec,
			   struct saved_control *saved)
{
	unsigned int i;

	if (find_control(fd, spec->name, &saved->info.id) < 0)
		return -1;
	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &saved->info, "control", "ELEM_INFO") < 0 ||
	    !(saved->info.access & SNDRV_CTL_ELEM_ACCESS_WRITE) ||
	    saved->info.count == 0 || saved->info.count > 128)
		return -1;
	if (spec->kind == CONTROL_BOOLEAN) {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_BOOLEAN)
			return -1;
	} else {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_ENUMERATED ||
		    saved->info.value.enumerated.items == 0 || saved->info.value.enumerated.items > 128)
			return -1;
		for (i = 0; i < saved->info.value.enumerated.items; i++) {
			saved->info.value.enumerated.item = i;
			if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &saved->info,
					 "control", "ELEM_INFO(enum-item)") < 0)
				return -1;
			if (strncmp(saved->info.value.enumerated.name, spec->enum_item,
				    sizeof(saved->info.value.enumerated.name)) == 0) {
				saved->enum_item = i;
				break;
			}
		}
		if (i == saved->info.value.enumerated.items)
			return -1;
	}
	saved->value.id = saved->info.id;
	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &saved->value, "control", "ELEM_READ(saved)") < 0)
		return -1;
	return 0;
}

static int control_write(int fd, const struct control_spec *spec,
			 const struct saved_control *saved, bool target)
{
	struct snd_ctl_elem_value value = { .id = saved->info.id };
	unsigned int i;

	if (!target)
		value = saved->value;
	else for (i = 0; i < saved->info.count; i++) {
		if (spec->kind == CONTROL_BOOLEAN)
			value.value.integer.value[i] = 1;
		else
			value.value.enumerated.item[i] = saved->enum_item;
	}
	return traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &value, "control",
			    target ? "ELEM_WRITE(target)" : "ELEM_WRITE(restore)");
}

static void params_any(struct snd_pcm_hw_params *params)
{
	unsigned int i;

	memset(params, 0, sizeof(*params));
	for (i = 0; i < sizeof(params->masks) / sizeof(params->masks[0]); i++)
		memset(params->masks[i].bits, 0xff, sizeof(params->masks[i].bits));
	for (i = 0; i < sizeof(params->intervals) / sizeof(params->intervals[0]); i++)
		params->intervals[i].max = UINT_MAX;
	params->rmask = UINT_MAX;
}

static void params_set_mask(struct snd_pcm_hw_params *params, unsigned int param,
			    unsigned int value)
{
	struct snd_mask *mask = &params->masks[param - SNDRV_PCM_HW_PARAM_FIRST_MASK];

	memset(mask, 0, sizeof(*mask));
	mask->bits[value / 32] = 1U << (value % 32);
	params->rmask |= 1U << param;
}

static void params_set_interval(struct snd_pcm_hw_params *params, unsigned int param,
				unsigned int value)
{
	struct snd_interval *interval = &params->intervals[param - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];

	memset(interval, 0, sizeof(*interval));
	interval->min = value;
	interval->max = value;
	interval->integer = 1;
	params->rmask |= 1U << param;
}

static void requested_params(struct snd_pcm_hw_params *params)
{
	params_any(params);
	params_set_mask(params, SNDRV_PCM_HW_PARAM_ACCESS, SNDRV_PCM_ACCESS_RW_INTERLEAVED);
	params_set_mask(params, SNDRV_PCM_HW_PARAM_FORMAT, SNDRV_PCM_FORMAT_S16_LE);
	params_set_mask(params, SNDRV_PCM_HW_PARAM_SUBFORMAT, SNDRV_PCM_SUBFORMAT_STD);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_CHANNELS, 2);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_RATE, SAMPLE_RATE);
}

static int open_playback(unsigned int card)
{
	char path[64];

	if (snprintf(path, sizeof(path), "/dev/snd/pcmC%uD%up", card, PCM_DEVICE) >= (int)sizeof(path))
		return -1;
	return traced_open(path, O_WRONLY | O_NONBLOCK | O_CLOEXEC, "pcm", "open");
}

int main(int argc, char **argv)
{
	struct options options;
	struct saved_control saved = { 0 };
	struct snd_pcm_hw_params params;
	int ctl_fd = -1, pcm_fd = -1;
	int status = EXIT_FAILURE;
	bool target_attempted = false, hw_params_done = false;

	setvbuf(stderr, NULL, _IONBF, 0);
	if (parse_options(argc, argv, &options) < 0)
		return EXIT_FAILURE;
	fprintf(stderr, "gemini-audio-headphone: stage selected; a missing after record identifies a non-returning syscall, not a timeout\n");
	ctl_fd = open_control(options.card, options.stage == STAGE_CONTROL_ACTIVATE);
	if (ctl_fd < 0) {
		print_errno("open control");
		goto out;
	}
	if (verify_card(ctl_fd) < 0 || verify_playback_1(ctl_fd) < 0)
		goto out;
	if (options.stage == STAGE_OBSERVE) {
		status = EXIT_SUCCESS;
		goto out;
	}
	if (options.stage == STAGE_CONTROL_READ || options.stage == STAGE_CONTROL_ACTIVATE) {
		if (prepare_control(ctl_fd, &controls[options.control], &saved) < 0)
			goto out;
		if (options.stage == STAGE_CONTROL_READ) {
			status = EXIT_SUCCESS;
			goto out;
		}
		target_attempted = true;
		if (control_write(ctl_fd, &controls[options.control], &saved, true) < 0)
			goto restore_control;
		status = EXIT_SUCCESS;
		goto restore_control;
	}
	pcm_fd = open_playback(options.card);
	if (pcm_fd < 0) {
		print_errno("open PCM");
		goto out;
	}
	if (options.stage == STAGE_PCM_OPEN) {
		status = EXIT_SUCCESS;
		goto out;
	}
	requested_params(&params);
	if (options.stage == STAGE_PCM_HW_REFINE) {
		if (traced_ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_REFINE, &params, "pcm", "HW_REFINE") == 0)
			status = EXIT_SUCCESS;
		goto out;
	}
	if (traced_ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_PARAMS, &params, "pcm", "HW_PARAMS") < 0)
		goto out;
	hw_params_done = true;
	status = EXIT_SUCCESS;
out:
	if (hw_params_done && traced_ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_FREE, NULL, "pcm", "HW_FREE(cleanup)") < 0)
		status = EXIT_FAILURE;
	traced_close(&pcm_fd, "pcm");
restore_control:
	if (target_attempted && control_write(ctl_fd, &controls[options.control], &saved, false) < 0)
		status = EXIT_FAILURE;
	traced_close(&ctl_fd, "control");
	return status;
}
