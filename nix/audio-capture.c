// SPDX-License-Identifier: GPL-2.0-only
/*
 * Fail-closed Gemini MT6797/MT6351 capture diagnostic.
 *
 * The default is observation only.  --stage capture additionally requires
 * --activate, snapshots every mixer value before the first write, restores
 * every attempted control in reverse order, and verifies the restoration.
 * Capture_1 is found with PCM_NEXT_DEVICE/PCM_INFO; no PCM number is assumed.
 * PCM data stays in memory and the nonblocking read loop has a hard deadline.
 */
#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <sound/asound.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define SAMPLE_RATE 48000U
#define CHANNELS 2U
#define PERIOD_FRAMES 960U
#define BUFFER_FRAMES 3840U
#define CAPTURE_FRAMES (SAMPLE_RATE * 3U / 4U)
#define DEADLINE_MS 3000L

enum control_kind { CONTROL_BOOLEAN, CONTROL_ENUM, CONTROL_INTEGER };
enum stage { STAGE_OBSERVE, STAGE_CONTROL_READ, STAGE_CAPTURE };

struct control_spec {
	const char *name;
	enum control_kind kind;
	const char *enum_item;
	long integer_value;
};

struct saved_control {
	struct snd_ctl_elem_info info;
	struct snd_ctl_elem_value value;
	unsigned int enum_item;
};

struct options {
	unsigned int card;
	enum stage stage;
	bool activate;
};

static const struct control_spec controls[] = {
	{ "UL1_CH1 ADDA_UL_CH1", CONTROL_BOOLEAN, NULL, 1 },
	{ "UL1_CH2 ADDA_UL_CH2", CONTROL_BOOLEAN, NULL, 1 },
	{ "AIF Out Mux", CONTROL_ENUM, "Normal Path", 0 },
	{ "ADC L Mux", CONTROL_ENUM, "Left Preamplifier", 0 },
	{ "ADC R Mux", CONTROL_ENUM, "Right Preamplifier", 0 },
	{ "PGA L Mux", CONTROL_ENUM, "AIN0", 0 },
	{ "PGA R Mux", CONTROL_ENUM, "AIN0", 0 },
	{ "PGA Volume", CONTROL_INTEGER, NULL, 1 }, /* 6 dB, both channels */
};

static unsigned int sequence;
static volatile sig_atomic_t deadline_expired;

static void deadline_handler(int signal_number)
{
	(void)signal_number;
	deadline_expired = 1;
}

static void boundary(const char *phase, const char *kind, const char *op,
			 int result, int error)
{
	if (strcmp(phase, "before") == 0)
		fprintf(stderr, "gemini-audio-capture: seq=%u before %s/%s\n",
			++sequence, kind, op);
	else
		fprintf(stderr,
			"gemini-audio-capture: seq=%u after ret=%d errno=%d\n",
			sequence, result, error);
	fflush(stderr);
	(void)fsync(STDERR_FILENO);
}

static int traced_ioctl(int fd, unsigned long request, void *argument,
			const char *kind, const char *op)
{
	int ret, saved_errno;

	boundary("before", kind, op, 0, 0);
	errno = 0;
	/* musl's ioctl request is int; preserve the ALSA UAPI's low 32 bits. */
	ret = ioctl(fd, (int)(uint32_t)request, argument);
	saved_errno = errno;
	boundary("after", kind, op, ret, saved_errno);
	errno = saved_errno;
	return ret;
}

static int traced_open(const char *path, int flags, const char *kind)
{
	int ret, saved_errno;

	boundary("before", kind, "open", 0, 0);
	errno = 0;
	ret = open(path, flags);
	saved_errno = errno;
	boundary("after", kind, "open", ret, saved_errno);
	errno = saved_errno;
	return ret;
}

static int traced_close(int *fd, const char *kind)
{
	int ret, saved_errno;

	if (*fd < 0)
		return 0;
	boundary("before", kind, "close", 0, 0);
	errno = 0;
	ret = close(*fd);
	saved_errno = errno;
	boundary("after", kind, "close", ret, saved_errno);
	*fd = -1;
	errno = saved_errno;
	return ret;
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

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [--card N] [--stage observe|control-read|capture] [--activate]\n"
		"  default: observe (CARD_INFO and dynamic Capture_1 PCM_INFO only)\n"
		"  capture requires --activate; it records no audio outside memory\n",
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
		} else if (strcmp(argv[i], "--stage") == 0 && i + 1 < argc) {
			const char *stage = argv[++i];

			if (strcmp(stage, "observe") == 0)
				options->stage = STAGE_OBSERVE;
			else if (strcmp(stage, "control-read") == 0)
				options->stage = STAGE_CONTROL_READ;
			else if (strcmp(stage, "capture") == 0)
				options->stage = STAGE_CAPTURE;
			else
				goto invalid;
		} else
			goto invalid;
	}
	if (options->stage == STAGE_CAPTURE && !options->activate)
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
	return traced_open(path, (writable ? O_RDWR : O_RDONLY) | O_CLOEXEC, "control");
}

static int verify_card(int fd)
{
	struct snd_ctl_card_info info = { 0 };

	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_CARD_INFO, &info, "control", "CARD_INFO") < 0)
		return -1;
	if (strncmp((const char *)info.name, "mt6797-mt6351", sizeof(info.name)) != 0) {
		fprintf(stderr, "gemini-audio-capture: refusing unexpected ALSA card '%.*s'\n",
			(int)sizeof(info.name), info.name);
		return -1;
	}
	return 0;
}

static bool pcm_id_is(const unsigned char *id, size_t size, const char *expected)
{
	size_t length = strlen(expected);

	return length < size && memcmp(id, expected, length) == 0 &&
		(id[length] == '\0' || id[length] == ' ');
}

static int find_capture_1(int fd, unsigned int *device)
{
	int candidate = -1;
	unsigned int attempts;

	for (attempts = 0; attempts < 32; attempts++) {
		struct snd_pcm_info info = { .subdevice = 0,
			.stream = SNDRV_PCM_STREAM_CAPTURE };

		if (traced_ioctl(fd, SNDRV_CTL_IOCTL_PCM_NEXT_DEVICE, &candidate,
				 "control", "PCM_NEXT_DEVICE") < 0)
			return -1;
		if (candidate < 0)
			break;
		info.device = (unsigned int)candidate;
		if (traced_ioctl(fd, SNDRV_CTL_IOCTL_PCM_INFO, &info,
				 "control", "PCM_INFO(capture)") < 0) {
			if (errno == ENOENT)
				continue;
			return -1;
		}
		fprintf(stderr,
			"gemini-audio-capture: candidate device=%d id='%.*s' name='%.*s'\n",
			candidate, (int)sizeof(info.id), info.id,
			(int)sizeof(info.name), info.name);
		if (pcm_id_is(info.id, sizeof(info.id), "Capture_1")) {
			*device = (unsigned int)candidate;
			fprintf(stderr,
				"gemini-audio-capture: selected device=%u id=Capture_1 stream=capture\n",
				*device);
			return 0;
		}
	}
	fprintf(stderr, "gemini-audio-capture: Capture_1 was not found\n");
	errno = ENOENT;
	return -1;
}

static int find_control(int fd, const char *name, struct snd_ctl_elem_id *id)
{
	struct snd_ctl_elem_list list = { 0 };
	struct snd_ctl_elem_id *ids;
	unsigned int i;
	int ret = -1;

	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list,
			 "control", "ELEM_LIST(count)") < 0 ||
	    list.count == 0 || list.count > 4096)
		return -1;
	ids = calloc(list.count, sizeof(*ids));
	if (!ids)
		return -1;
	list.space = list.count;
	list.pids = ids;
	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list,
			 "control", "ELEM_LIST(entries)") < 0)
		goto out;
	if (list.used > list.space)
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
	if (ret < 0)
		fprintf(stderr, "gemini-audio-capture: missing control '%s'\n", name);
	return ret;
}

static int prepare_control(int fd, const struct control_spec *spec,
			   struct saved_control *saved)
{
	unsigned int i;

	if (find_control(fd, spec->name, &saved->info.id) < 0)
		return -1;
	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &saved->info,
			 "control", "ELEM_INFO") < 0 ||
	    !(saved->info.access & SNDRV_CTL_ELEM_ACCESS_READ) ||
	    !(saved->info.access & SNDRV_CTL_ELEM_ACCESS_WRITE) ||
	    saved->info.count == 0 || saved->info.count > 128)
		return -1;
	if (spec->kind == CONTROL_BOOLEAN) {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_BOOLEAN)
			return -1;
	} else if (spec->kind == CONTROL_INTEGER) {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_INTEGER ||
		    spec->integer_value < saved->info.value.integer.min ||
		    spec->integer_value > saved->info.value.integer.max)
			return -1;
	} else {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_ENUMERATED ||
		    saved->info.value.enumerated.items == 0 ||
		    saved->info.value.enumerated.items > 128)
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
	return traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &saved->value,
			    "control", "ELEM_READ(saved)");
}

static void target_value(const struct control_spec *spec,
			 const struct saved_control *saved,
			 struct snd_ctl_elem_value *value)
{
	unsigned int i;

	memset(value, 0, sizeof(*value));
	value->id = saved->info.id;
	for (i = 0; i < saved->info.count; i++) {
		if (spec->kind == CONTROL_BOOLEAN)
			value->value.integer.value[i] = 1;
		else if (spec->kind == CONTROL_INTEGER)
			value->value.integer.value[i] = spec->integer_value;
		else
			value->value.enumerated.item[i] = saved->enum_item;
	}
}

static int control_write(int fd, const struct control_spec *spec,
			 const struct saved_control *saved, bool target)
{
	struct snd_ctl_elem_value value;

	if (target)
		target_value(spec, saved, &value);
	else
		value = saved->value;
	fprintf(stderr, "gemini-audio-capture: control='%s' action=%s\n",
		spec->name, target ? "target" : "restore");
	return traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &value,
			    "control", target ? "ELEM_WRITE(target)" : "ELEM_WRITE(restore)");
}

static int verify_control(int fd, const struct control_spec *spec,
			  const struct saved_control *saved, bool target)
{
	struct snd_ctl_elem_value value = { .id = saved->info.id };
	struct snd_ctl_elem_value expected = saved->value;
	unsigned int i;

	if (target)
		target_value(spec, saved, &expected);
	if (traced_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &value,
			 "control", target ? "ELEM_READ(verify-target)" :
			 "ELEM_READ(verify-restore)") < 0)
		return -1;
	for (i = 0; i < saved->info.count; i++) {
		if (spec->kind == CONTROL_ENUM) {
			if (value.value.enumerated.item[i] != expected.value.enumerated.item[i])
				return -1;
		} else if (value.value.integer.value[i] != expected.value.integer.value[i])
			return -1;
	}
	return 0;
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
	struct snd_interval *interval =
		&params->intervals[param - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];

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
	params_set_interval(params, SNDRV_PCM_HW_PARAM_SAMPLE_BITS, 16);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_FRAME_BITS, 32);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_CHANNELS, CHANNELS);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_RATE, SAMPLE_RATE);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, PERIOD_FRAMES);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_PERIODS, 4);
	params_set_interval(params, SNDRV_PCM_HW_PARAM_BUFFER_SIZE, BUFFER_FRAMES);
}

static int configure_capture(int fd)
{
	struct snd_pcm_hw_params params;
	struct snd_pcm_sw_params sw = { 0 };
	const unsigned int intervals[][2] = {
		{ SNDRV_PCM_HW_PARAM_RATE, SAMPLE_RATE },
		{ SNDRV_PCM_HW_PARAM_CHANNELS, CHANNELS },
		{ SNDRV_PCM_HW_PARAM_SAMPLE_BITS, 16 },
		{ SNDRV_PCM_HW_PARAM_FRAME_BITS, 32 },
		{ SNDRV_PCM_HW_PARAM_PERIOD_SIZE, PERIOD_FRAMES },
		{ SNDRV_PCM_HW_PARAM_BUFFER_SIZE, BUFFER_FRAMES },
	};
	unsigned int i;

	requested_params(&params);
	if (traced_ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, &params,
			 "pcm", "HW_PARAMS") < 0)
		return -1;
	for (i = 0; i < sizeof(intervals) / sizeof(intervals[0]); i++) {
		const struct snd_interval *value = &params.intervals[
			intervals[i][0] - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
		if (value->min != intervals[i][1] || value->max != intervals[i][1]) {
			errno = EINVAL;
			return -1;
		}
	}
	sw.tstamp_mode = SNDRV_PCM_TSTAMP_NONE;
	sw.period_step = 1;
	sw.avail_min = PERIOD_FRAMES;
	/* START is explicit; do not start a second stream implicitly on READI. */
	sw.boundary = BUFFER_FRAMES;
	while (sw.boundary <= (LONG_MAX - BUFFER_FRAMES) / 2)
		sw.boundary *= 2;
	sw.start_threshold = sw.boundary;
	sw.stop_threshold = BUFFER_FRAMES;
	if (traced_ioctl(fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sw,
			 "pcm", "SW_PARAMS") < 0)
		return -1;
	return traced_ioctl(fd, SNDRV_PCM_IOCTL_PREPARE, NULL, "pcm", "PREPARE");
}

static int read_status(int fd, struct snd_pcm_status *status)
{
	memset(status, 0, sizeof(*status));
	if (traced_ioctl(fd, SNDRV_PCM_IOCTL_STATUS, status, "pcm", "STATUS") < 0)
		return -1;
	fprintf(stderr, "gemini-audio-capture: state=%d delay=%ld appl=%lu hw=%lu\n",
		(int)status->state, (long)status->delay,
		(unsigned long)status->appl_ptr, (unsigned long)status->hw_ptr);
	return 0;
}

static int open_capture(unsigned int card, unsigned int device)
{
	char path[64];

	if (snprintf(path, sizeof(path), "/dev/snd/pcmC%uD%uc", card, device) >=
	    (int)sizeof(path))
		return -1;
	return traced_open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC, "pcm");
}

static long remaining_ms(const struct timespec *deadline)
{
	struct timespec now;
	long milliseconds;

	if (clock_gettime(CLOCK_MONOTONIC, &now) < 0)
		return -1;
	milliseconds = (deadline->tv_sec - now.tv_sec) * 1000L +
		(deadline->tv_nsec - now.tv_nsec) / 1000000L;
	return milliseconds > 0 ? milliseconds : 0;
}

static int capture_frames(int fd, uint64_t *nonzero_samples, uint32_t *peak)
{
	int16_t samples[PERIOD_FRAMES * CHANNELS];
	struct timespec deadline;
	unsigned int captured = 0;

	if (clock_gettime(CLOCK_MONOTONIC, &deadline) < 0)
		return -1;
	deadline.tv_nsec += (DEADLINE_MS % 1000L) * 1000000L;
	deadline.tv_sec += DEADLINE_MS / 1000L + deadline.tv_nsec / 1000000000L;
	deadline.tv_nsec %= 1000000000L;
	while (captured < CAPTURE_FRAMES && !deadline_expired) {
		struct pollfd pollfd = { .fd = fd, .events = POLLIN };
		struct snd_xferi transfer = {
			.buf = samples,
			.frames = PERIOD_FRAMES,
		};
		long wait = remaining_ms(&deadline);
		unsigned int i, frames;
		int ret;

		if (wait <= 0) {
			errno = ETIMEDOUT;
			break;
		}
		ret = poll(&pollfd, 1, wait > INT_MAX ? INT_MAX : (int)wait);
		if (ret < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (ret == 0) {
			errno = ETIMEDOUT;
			break;
		}
		if ((pollfd.revents & (POLLERR | POLLHUP | POLLNVAL)) ||
		    !(pollfd.revents & POLLIN)) {
			errno = EIO;
			return -1;
		}
		transfer.frames = CAPTURE_FRAMES - captured;
		if (transfer.frames > PERIOD_FRAMES)
			transfer.frames = PERIOD_FRAMES;
		if (traced_ioctl(fd, SNDRV_PCM_IOCTL_READI_FRAMES, &transfer,
				 "pcm", "READI_FRAMES") < 0) {
			if (errno == EAGAIN || errno == EINTR)
				continue;
			return -1;
		}
		if (transfer.result <= 0 ||
		    (snd_pcm_uframes_t)transfer.result > transfer.frames) {
			errno = EIO;
			return -1;
		}
		frames = (unsigned int)transfer.result;
		for (i = 0; i < frames * CHANNELS; i++) {
			uint32_t magnitude;

			if (samples[i] == 0)
				continue;
			(*nonzero_samples)++;
			magnitude = (uint32_t)(samples[i] < 0 ? -(int)samples[i] : samples[i]);
			if (magnitude > *peak)
				*peak = magnitude;
		}
		captured += frames;
	}
	fprintf(stderr,
		"gemini-audio-capture: captured_frames=%u requested_frames=%u nonzero_samples=%llu peak_abs=%u\n",
		captured, CAPTURE_FRAMES, (unsigned long long)*nonzero_samples, *peak);
	if (captured != CAPTURE_FRAMES) {
		if (!errno)
			errno = ETIMEDOUT;
		return -1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct options options;
	struct saved_control saved[sizeof(controls) / sizeof(controls[0])] = { 0 };
	struct snd_pcm_status pcm_status;
	struct sigaction action = { .sa_handler = deadline_handler };
	uint64_t nonzero_samples = 0;
	uint32_t peak = 0;
	unsigned int device = 0, prepared_controls = 0, attempted_controls = 0;
	int ctl_fd = -1, pcm_fd = -1;
	int status = EXIT_FAILURE;
	bool start_attempted = false, restore_ok = true;

	setvbuf(stderr, NULL, _IONBF, 0);
	if (parse_options(argc, argv, &options) < 0)
		return EXIT_FAILURE;
	fprintf(stderr,
		"gemini-audio-capture: stage selected; missing after means a non-returning syscall\n");
	ctl_fd = open_control(options.card, options.stage == STAGE_CAPTURE);
	if (ctl_fd < 0 || verify_card(ctl_fd) < 0 || find_capture_1(ctl_fd, &device) < 0)
		goto out;
	if (options.stage == STAGE_OBSERVE) {
		status = EXIT_SUCCESS;
		goto out;
	}
	for (prepared_controls = 0;
	     prepared_controls < sizeof(controls) / sizeof(controls[0]);
	     prepared_controls++) {
		if (prepare_control(ctl_fd, &controls[prepared_controls],
				    &saved[prepared_controls]) < 0)
			goto out;
	}
	if (options.stage == STAGE_CONTROL_READ) {
		status = EXIT_SUCCESS;
		goto out;
	}
	if (sigemptyset(&action.sa_mask) < 0 ||
	    sigaction(SIGALRM, &action, NULL) < 0 ||
	    sigaction(SIGINT, &action, NULL) < 0 ||
	    sigaction(SIGTERM, &action, NULL) < 0)
		goto out;
	deadline_expired = 0;
	for (attempted_controls = 0;
	     attempted_controls < sizeof(controls) / sizeof(controls[0]);) {
		unsigned int index;

		if (deadline_expired) {
			errno = EINTR;
			goto restore;
		}
		index = attempted_controls++;
		if (control_write(ctl_fd, &controls[index], &saved[index], true) < 0)
			goto restore;
		if (verify_control(ctl_fd, &controls[index], &saved[index], true) < 0)
			goto restore;
		if (deadline_expired) {
			errno = EINTR;
			goto restore;
		}
	}
	pcm_fd = open_capture(options.card, device);
	if (pcm_fd < 0)
		goto restore;
	if (configure_capture(pcm_fd) < 0)
		goto restore;
	if (read_status(pcm_fd, &pcm_status) < 0 ||
	    pcm_status.state != SNDRV_PCM_STATE_PREPARED || pcm_status.appl_ptr != 0)
		goto restore;
	alarm(4);
	start_attempted = true;
	if (traced_ioctl(pcm_fd, SNDRV_PCM_IOCTL_START, NULL, "pcm", "START") < 0)
		goto restore;
	if (capture_frames(pcm_fd, &nonzero_samples, &peak) < 0)
		goto restore;
	if (read_status(pcm_fd, &pcm_status) < 0 ||
	    pcm_status.state != SNDRV_PCM_STATE_RUNNING ||
	    pcm_status.appl_ptr != CAPTURE_FRAMES)
		goto restore;
	status = EXIT_SUCCESS;
restore:
	alarm(0);
	if (start_attempted) {
		if (traced_ioctl(pcm_fd, SNDRV_PCM_IOCTL_DROP, NULL,
				 "pcm", "DROP(cleanup)") < 0 ||
		    read_status(pcm_fd, &pcm_status) < 0 ||
		    pcm_status.state != SNDRV_PCM_STATE_SETUP)
			status = EXIT_FAILURE;
	}
	/* Close releases HW_PARAMS even when a setup or START ioctl failed. */
	if (traced_close(&pcm_fd, "pcm") < 0)
		status = EXIT_FAILURE;
	while (attempted_controls > 0) {
		unsigned int index = --attempted_controls;

		if (control_write(ctl_fd, &controls[index], &saved[index], false) < 0)
			restore_ok = false;
	}
	for (attempted_controls = 0; attempted_controls < prepared_controls;
	     attempted_controls++) {
		if (verify_control(ctl_fd, &controls[attempted_controls],
				   &saved[attempted_controls], false) < 0) {
			fprintf(stderr, "gemini-audio-capture: restore mismatch control='%s'\n",
				controls[attempted_controls].name);
			restore_ok = false;
		}
	}
	if (restore_ok && prepared_controls == sizeof(controls) / sizeof(controls[0]))
		fprintf(stderr, "gemini-audio-capture: restore_verified controls=%u\n",
			prepared_controls);
	else
		status = EXIT_FAILURE;
out:
	if (traced_close(&pcm_fd, "pcm") < 0)
		status = EXIT_FAILURE;
	if (traced_close(&ctl_fd, "control") < 0)
		status = EXIT_FAILURE;
	if (status == EXIT_SUCCESS && options.stage == STAGE_CAPTURE)
		fprintf(stderr, "gemini-audio-capture: result=stream-and-route-restoration-passed\n");
	return status;
}
