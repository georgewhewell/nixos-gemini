// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
/*
 * Bounded, manual Gemini MT6797/MT6351 headphone exercise.
 *
 * This is intentionally not an ALSA replacement.  It uses only the stable
 * ALSA kernel UAPI to verify and temporarily set the four DPCM controls that
 * were hardware-proven on a Gemini by bsg100's 2026-07-19 #267 test:
 *
 *   ADDA_DL_CH1 DL1_CH1 = on
 *   ADDA_DL_CH2 DL1_CH2 = on
 *   HPL Mux = Audio Playback
 *   HPR Mux = Audio Playback
 *
 * It then plays one 750 ms, low-amplitude 440 Hz triangle-wave PCM tone on
 * Playback_1 (PCM device zero), with nonblocking I/O and a monotonic internal
 * deadline.  It restores all four controls exactly as they were before every
 * normal, error, or timeout exit.  There is no speaker routing, GPIO, jack
 * detection, persistent state, or automatic invocation.
 */

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <sound/asound.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define PCM_DEVICE 0
#define SAMPLE_RATE 48000U
#define TONE_HZ 440U
#define TONE_MILLISECONDS 750U
#define TONE_FRAMES ((SAMPLE_RATE * TONE_MILLISECONDS) / 1000U)
#define TONE_CHUNK_FRAMES 240U
#define TONE_AMPLITUDE 6000
/* This covers the 750 ms payload and a bounded drain margin.  It is an
 * internal deadline: it must remain reachable so control restoration is not
 * delegated to a process-killing external timeout. */
#define PCM_DEADLINE_MILLISECONDS 3000U

enum control_kind {
	CONTROL_BOOLEAN,
	CONTROL_ENUM,
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

static const struct control_spec controls[] = {
	{ "ADDA_DL_CH1 DL1_CH1", CONTROL_BOOLEAN, NULL },
	{ "ADDA_DL_CH2 DL1_CH2", CONTROL_BOOLEAN, NULL },
	{ "HPL Mux", CONTROL_ENUM, "Audio Playback" },
	{ "HPR Mux", CONTROL_ENUM, "Audio Playback" },
};

static void print_errno(const char *what)
{
	fprintf(stderr, "gemini-audio-headphone: %s: %s\n", what,
		strerror(errno));
}

/* musl declares ioctl's request argument as int even on aarch64, whereas the
 * ALSA UAPI request macros are unsigned-long constants.  Preserve their low
 * 32 bits explicitly; that is the kernel ioctl ABI and avoids relying on a
 * compiler-specific implicit narrowing conversion. */
static int alsa_ioctl(int fd, unsigned long request, const void *argument)
{
	return ioctl(fd, (int)request, (void *)argument);
}

static int open_control(unsigned int card)
{
	char path[64];
	int fd;

	if (snprintf(path, sizeof(path), "/dev/snd/controlC%u", card) >=
	    (int)sizeof(path))
		return -1;

	fd = open(path, O_RDWR | O_CLOEXEC);
	if (fd < 0)
		print_errno(path);
	return fd;
}

static int verify_card(int fd)
{
	struct snd_ctl_card_info card_info = { 0 };

	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_CARD_INFO, &card_info) < 0) {
		print_errno("SNDRV_CTL_IOCTL_CARD_INFO");
		return -1;
	}

	if (strncmp((const char *)card_info.name, "mt6797-mt6351",
		    sizeof(card_info.name)) != 0) {
		fprintf(stderr,
			"gemini-audio-headphone: refusing unexpected ALSA card '%.*s'\n",
			(int)sizeof(card_info.name), card_info.name);
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

	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list) < 0) {
		print_errno("SNDRV_CTL_IOCTL_ELEM_LIST(count)");
		return -1;
	}
	if (list.count == 0) {
		fprintf(stderr, "gemini-audio-headphone: card has no controls\n");
		return -1;
	}

	ids = calloc(list.count, sizeof(*ids));
	if (!ids) {
		fprintf(stderr, "gemini-audio-headphone: control allocation failed\n");
		return -1;
	}

	list.space = list.count;
	list.pids = ids;
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_LIST, &list) < 0) {
		print_errno("SNDRV_CTL_IOCTL_ELEM_LIST(entries)");
		goto out;
	}

	for (i = 0; i < list.used; i++) {
		if (strncmp((const char *)ids[i].name, name,
			    sizeof(ids[i].name)) == 0) {
			*id = ids[i];
			ret = 0;
			break;
		}
	}
	if (ret < 0)
		fprintf(stderr, "gemini-audio-headphone: required control '%s' absent\n",
			name);
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
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &saved->info) < 0) {
		print_errno(spec->name);
		return -1;
	}
	if (!(saved->info.access & SNDRV_CTL_ELEM_ACCESS_WRITE)) {
		fprintf(stderr, "gemini-audio-headphone: control '%s' is not writable\n",
			spec->name);
		return -1;
	}
	if (saved->info.count == 0 || saved->info.count > 128) {
		fprintf(stderr, "gemini-audio-headphone: invalid value count for '%s'\n",
			spec->name);
		return -1;
	}

	if (spec->kind == CONTROL_BOOLEAN) {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_BOOLEAN) {
			fprintf(stderr, "gemini-audio-headphone: '%s' is not boolean\n",
				spec->name);
			return -1;
		}
	} else {
		if (saved->info.type != SNDRV_CTL_ELEM_TYPE_ENUMERATED ||
		    saved->info.value.enumerated.items == 0 ||
		    saved->info.value.enumerated.items > 128) {
			fprintf(stderr, "gemini-audio-headphone: '%s' is not a usable enum\n",
				spec->name);
			return -1;
		}
		for (i = 0; i < saved->info.value.enumerated.items; i++) {
			saved->info.value.enumerated.item = i;
			if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_INFO, &saved->info) < 0) {
				print_errno(spec->name);
				return -1;
			}
			if (strncmp(saved->info.value.enumerated.name, spec->enum_item,
				    sizeof(saved->info.value.enumerated.name)) == 0) {
				saved->enum_item = i;
				break;
			}
		}
		if (i == saved->info.value.enumerated.items) {
			fprintf(stderr,
				"gemini-audio-headphone: '%s' lacks enum item '%s'\n",
				spec->name, spec->enum_item);
			return -1;
		}
	}

	memset(&saved->value, 0, sizeof(saved->value));
	saved->value.id = saved->info.id;
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &saved->value) < 0) {
		print_errno(spec->name);
		return -1;
	}
	return 0;
}

static int verify_control(int fd, const struct control_spec *spec,
			  const struct saved_control *saved, bool target)
{
	struct snd_ctl_elem_value value = { 0 };
	unsigned int i;

	value.id = saved->info.id;
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &value) < 0) {
		print_errno(spec->name);
		return -1;
	}
	for (i = 0; i < saved->info.count; i++) {
		if (spec->kind == CONTROL_BOOLEAN) {
			if (!!value.value.integer.value[i] != target)
				return -1;
		} else if (value.value.enumerated.item[i] !=
				   (target ? saved->enum_item :
				    saved->value.value.enumerated.item[i])) {
			return -1;
		}
	}
	return 0;
}

static int verify_restored_control(int fd, const struct control_spec *spec,
				   const struct saved_control *saved)
{
	struct snd_ctl_elem_value value = { 0 };
	unsigned int i;

	value.id = saved->info.id;
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &value) < 0) {
		print_errno(spec->name);
		return -1;
	}
	for (i = 0; i < saved->info.count; i++) {
		if (spec->kind == CONTROL_BOOLEAN) {
			if (value.value.integer.value[i] !=
			    saved->value.value.integer.value[i])
				return -1;
		} else if (value.value.enumerated.item[i] !=
			   saved->value.value.enumerated.item[i]) {
			return -1;
		}
	}
	return 0;
}

static int set_control(int fd, const struct control_spec *spec,
		       const struct saved_control *saved)
{
	struct snd_ctl_elem_value value = { 0 };
	unsigned int i;

	value.id = saved->info.id;
	for (i = 0; i < saved->info.count; i++) {
		if (spec->kind == CONTROL_BOOLEAN)
			value.value.integer.value[i] = 1;
		else
			value.value.enumerated.item[i] = saved->enum_item;
	}
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &value) < 0) {
		print_errno(spec->name);
		return -1;
	}
	if (verify_control(fd, spec, saved, true) < 0) {
		fprintf(stderr, "gemini-audio-headphone: '%s' did not take target value\n",
			spec->name);
		return -1;
	}
	return 0;
}

static int restore_control(int fd, const struct control_spec *spec,
			   const struct saved_control *saved)
{
	if (alsa_ioctl(fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &saved->value) < 0) {
		print_errno(spec->name);
		return -1;
	}
	if (verify_restored_control(fd, spec, saved) < 0) {
		fprintf(stderr, "gemini-audio-headphone: '%s' did not restore\n",
			spec->name);
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
	for (i = 0; i < sizeof(params->intervals) / sizeof(params->intervals[0]); i++) {
		params->intervals[i].min = 0;
		params->intervals[i].max = UINT_MAX;
	}
	params->rmask = UINT_MAX;
}

static void params_set_mask(struct snd_pcm_hw_params *params,
			    unsigned int param, unsigned int value)
{
	struct snd_mask *mask = &params->masks[param - SNDRV_PCM_HW_PARAM_FIRST_MASK];

	memset(mask, 0, sizeof(*mask));
	mask->bits[value / 32] = 1U << (value % 32);
	params->rmask |= 1U << param;
}

static void params_set_interval(struct snd_pcm_hw_params *params,
				unsigned int param, unsigned int value)
{
	struct snd_interval *interval =
		&params->intervals[param - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];

	memset(interval, 0, sizeof(*interval));
	interval->min = value;
	interval->max = value;
	interval->integer = 1;
	params->rmask |= 1U << param;
}

static int verify_playback_1(int ctl_fd)
{
	struct snd_pcm_info info = {
		.device = PCM_DEVICE,
		.subdevice = 0,
		.stream = SNDRV_PCM_STREAM_PLAYBACK,
	};

	if (alsa_ioctl(ctl_fd, SNDRV_CTL_IOCTL_PCM_INFO, &info) < 0) {
		print_errno("SNDRV_CTL_IOCTL_PCM_INFO(Playback_1)");
		return -1;
	}
	if (strncmp((const char *)info.name, "Playback_1", sizeof(info.name)) != 0) {
		fprintf(stderr,
			"gemini-audio-headphone: PCM C?D0p is '%.*s', not Playback_1\n",
			(int)sizeof(info.name), info.name);
		return -1;
	}
	return 0;
}

static int open_playback(unsigned int card)
{
	char path[64];
	int fd;

	if (snprintf(path, sizeof(path), "/dev/snd/pcmC%uD%up", card,
		     PCM_DEVICE) >= (int)sizeof(path))
		return -1;
	/* PCM ioctls observe this flag: WRITEI and DRAIN return EAGAIN instead of
	 * sleeping forever behind a wedged AFE. */
	fd = open(path, O_WRONLY | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		print_errno(path);
	return fd;
}

static int configure_playback(int pcm_fd, unsigned int *period_frames,
			      unsigned int *buffer_frames)
{
	struct snd_pcm_hw_params hw;
	struct snd_pcm_sw_params sw = { 0 };

	params_any(&hw);
	params_set_mask(&hw, SNDRV_PCM_HW_PARAM_ACCESS,
			SNDRV_PCM_ACCESS_RW_INTERLEAVED);
	params_set_mask(&hw, SNDRV_PCM_HW_PARAM_FORMAT, SNDRV_PCM_FORMAT_S16_LE);
	params_set_mask(&hw, SNDRV_PCM_HW_PARAM_SUBFORMAT, SNDRV_PCM_SUBFORMAT_STD);
	params_set_interval(&hw, SNDRV_PCM_HW_PARAM_CHANNELS, 2);
	params_set_interval(&hw, SNDRV_PCM_HW_PARAM_RATE, SAMPLE_RATE);
	/* Let the driver select its supported period and buffer geometry.  The
	 * transfer loop below is deliberately independent of that geometry, so a
	 * normal PCM constraint change cannot turn this bounded smoke test into a
	 * false-negative hardware failure. */

	if (alsa_ioctl(pcm_fd, SNDRV_PCM_IOCTL_HW_PARAMS, &hw) < 0) {
		print_errno("SNDRV_PCM_IOCTL_HW_PARAMS");
		return -1;
	}
	*period_frames = hw.intervals[SNDRV_PCM_HW_PARAM_PERIOD_SIZE -
				     SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min;
	*buffer_frames = hw.intervals[SNDRV_PCM_HW_PARAM_BUFFER_SIZE -
				     SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min;
	if (*period_frames == 0 || *buffer_frames < *period_frames) {
		fprintf(stderr, "gemini-audio-headphone: invalid negotiated PCM geometry\n");
		return -1;
	}
	if (*buffer_frames > UINT_MAX / 4U) {
		fprintf(stderr, "gemini-audio-headphone: PCM buffer geometry is too large\n");
		return -1;
	}

	sw.period_step = 1;
	sw.avail_min = *period_frames;
	sw.start_threshold = 1;
	sw.stop_threshold = *buffer_frames;
	/* ALSA requires a boundary greater than the hardware buffer.  Keeping it
	 * close also prevents this one-shot writer from accumulating a huge frame
	 * counter if a buggy driver reports a very large default boundary. */
	sw.boundary = *buffer_frames * 4U;
	if (alsa_ioctl(pcm_fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sw) < 0) {
		print_errno("SNDRV_PCM_IOCTL_SW_PARAMS");
		return -1;
	}
	if (alsa_ioctl(pcm_fd, SNDRV_PCM_IOCTL_PREPARE, NULL) < 0) {
		print_errno("SNDRV_PCM_IOCTL_PREPARE");
		return -1;
	}
	return 0;
}

static void fill_tone(int16_t *frames, unsigned int count, uint32_t *phase)
{
	const uint32_t phase_step = (uint32_t)(((uint64_t)TONE_HZ << 32) / SAMPLE_RATE);
	unsigned int i;

	for (i = 0; i < count; i++) {
		uint16_t position = (uint16_t)(*phase >> 16);
		int32_t triangle = position < 32768U ? position : 65535 - position;
		int16_t sample;

		triangle = triangle * 2 - 32767;
		sample = (int16_t)((triangle * TONE_AMPLITUDE) / 32767);
		frames[2 * i] = sample;
		frames[2 * i + 1] = sample;
		*phase += phase_step;
	}
}

static int make_pcm_deadline(struct timespec *deadline)
{
	if (clock_gettime(CLOCK_MONOTONIC, deadline) < 0) {
		print_errno("clock_gettime(CLOCK_MONOTONIC)");
		return -1;
	}
	deadline->tv_sec += PCM_DEADLINE_MILLISECONDS / 1000U;
	deadline->tv_nsec +=
		(long)(PCM_DEADLINE_MILLISECONDS % 1000U) * 1000000L;
	if (deadline->tv_nsec >= 1000000000L) {
		deadline->tv_sec++;
		deadline->tv_nsec -= 1000000000L;
	}
	return 0;
}

static int timeout_until_deadline(const struct timespec *deadline,
				  int *timeout_milliseconds)
{
	struct timespec now;
	uint64_t remaining_nanoseconds;
	uint64_t milliseconds;

	if (clock_gettime(CLOCK_MONOTONIC, &now) < 0) {
		print_errno("clock_gettime(CLOCK_MONOTONIC)");
		return -1;
	}
	if (now.tv_sec > deadline->tv_sec ||
	    (now.tv_sec == deadline->tv_sec && now.tv_nsec >= deadline->tv_nsec)) {
		errno = ETIMEDOUT;
		return -1;
	}
	remaining_nanoseconds =
		(uint64_t)(deadline->tv_sec - now.tv_sec) * 1000000000ULL;
	if (deadline->tv_nsec >= now.tv_nsec)
		remaining_nanoseconds += (uint64_t)(deadline->tv_nsec - now.tv_nsec);
	else
		remaining_nanoseconds -= (uint64_t)(now.tv_nsec - deadline->tv_nsec);
	milliseconds = (remaining_nanoseconds + 999999ULL) / 1000000ULL;
	*timeout_milliseconds = milliseconds > (uint64_t)INT_MAX ? INT_MAX :
		(int)milliseconds;
	return 0;
}

static int wait_for_playback(int pcm_fd, const struct timespec *deadline)
{
	struct pollfd pfd = {
		.fd = pcm_fd,
		.events = POLLOUT,
	};
	int timeout_milliseconds;
	int ret;

	for (;;) {
		if (timeout_until_deadline(deadline, &timeout_milliseconds) < 0) {
			if (errno == ETIMEDOUT)
				fprintf(stderr, "gemini-audio-headphone: PCM deadline expired\n");
			else
				print_errno("PCM deadline");
			return -1;
		}
		pfd.revents = 0;
		ret = poll(&pfd, 1, timeout_milliseconds);
		if (ret < 0) {
			if (errno == EINTR)
				continue;
			print_errno("poll(PCM playback)");
			return -1;
		}
		if (ret == 0) {
			errno = ETIMEDOUT;
			fprintf(stderr, "gemini-audio-headphone: PCM deadline expired\n");
			return -1;
		}
		if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) {
			errno = EIO;
			print_errno("poll(PCM playback state)");
			return -1;
		}
		if (pfd.revents & POLLOUT)
			return 0;
	}
}

static int drain_playback(int pcm_fd, const struct timespec *deadline)
{
	for (;;) {
		if (timeout_until_deadline(deadline, &(int){ 0 }) < 0) {
			if (errno == ETIMEDOUT)
				fprintf(stderr, "gemini-audio-headphone: PCM deadline expired\n");
			else
				print_errno("PCM deadline");
			return -1;
		}
		if (alsa_ioctl(pcm_fd, SNDRV_PCM_IOCTL_DRAIN, NULL) == 0)
			return 0;
		if (errno == EINTR)
			continue;
		if (errno == EAGAIN) {
			if (wait_for_playback(pcm_fd, deadline) < 0)
				return -1;
			continue;
		}
		print_errno("SNDRV_PCM_IOCTL_DRAIN");
		return -1;
	}
}

static int play_tone(int pcm_fd)
{
	int16_t frames[TONE_CHUNK_FRAMES * 2];
	struct timespec deadline;
	unsigned int remaining = TONE_FRAMES;
	uint32_t phase = 0;

	if (make_pcm_deadline(&deadline) < 0)
		return -1;
	while (remaining > 0) {
		unsigned int count = remaining < TONE_CHUNK_FRAMES ? remaining : TONE_CHUNK_FRAMES;
		unsigned int written = 0;

		fill_tone(frames, count, &phase);
		while (written < count) {
			struct snd_xferi xfer = {
				.buf = &frames[2 * written],
				.frames = count - written,
			};

			if (timeout_until_deadline(&deadline, &(int){ 0 }) < 0) {
				if (errno == ETIMEDOUT)
					fprintf(stderr, "gemini-audio-headphone: PCM deadline expired\n");
				else
					print_errno("PCM deadline");
				return -1;
			}
			if (alsa_ioctl(pcm_fd, SNDRV_PCM_IOCTL_WRITEI_FRAMES, &xfer) < 0) {
				if (errno == EINTR)
					continue;
				if (errno == EAGAIN) {
					if (wait_for_playback(pcm_fd, &deadline) < 0)
						return -1;
					continue;
				}
				print_errno("SNDRV_PCM_IOCTL_WRITEI_FRAMES");
				return -1;
			}
			if (xfer.result <= 0 || (unsigned int)xfer.result > count - written) {
				fprintf(stderr, "gemini-audio-headphone: invalid PCM write result %ld\n",
					(long)xfer.result);
				return -1;
			}
			written += (unsigned int)xfer.result;
			remaining -= (unsigned int)xfer.result;
		}
	}
	return drain_playback(pcm_fd, &deadline);
}

static int parse_card(int argc, char **argv, unsigned int *card)
{
	char *end;
	unsigned long parsed;

	if (argc == 1) {
		*card = 0;
		return 0;
	}
	if (argc != 3 || strcmp(argv[1], "--card") != 0) {
		fprintf(stderr, "usage: %s [--card N]\n", argv[0]);
		return -1;
	}
	errno = 0;
	parsed = strtoul(argv[2], &end, 10);
	if (errno || *argv[2] == '\0' || *end != '\0' || parsed > UINT_MAX) {
		fprintf(stderr, "gemini-audio-headphone: invalid card number '%s'\n",
			argv[2]);
		return -1;
	}
	*card = (unsigned int)parsed;
	return 0;
}

int main(int argc, char **argv)
{
	struct saved_control saved[sizeof(controls) / sizeof(controls[0])];
	unsigned int card;
	unsigned int period_frames;
	unsigned int buffer_frames;
	unsigned int prepared = 0;
	unsigned int applied = 0;
	int ctl_fd = -1;
	int pcm_fd = -1;
	int status = EXIT_FAILURE;
	int restore_status = 0;

	if (parse_card(argc, argv, &card) < 0)
		return EXIT_FAILURE;
	ctl_fd = open_control(card);
	if (ctl_fd < 0)
		goto out;
	if (verify_card(ctl_fd) < 0 || verify_playback_1(ctl_fd) < 0)
		goto out;

	for (prepared = 0; prepared < sizeof(controls) / sizeof(controls[0]); prepared++) {
		if (prepare_control(ctl_fd, &controls[prepared], &saved[prepared]) < 0)
			goto out;
	}
	for (applied = 0; applied < sizeof(controls) / sizeof(controls[0]); applied++) {
		/* Restore even if the write itself reports an error: it may have
		 * reached hardware before the driver returned its failure. */
		if (set_control(ctl_fd, &controls[applied], &saved[applied]) < 0) {
			applied++;
			goto restore;
		}
	}

	pcm_fd = open_playback(card);
	if (pcm_fd < 0 || configure_playback(pcm_fd, &period_frames, &buffer_frames) < 0)
		goto restore;
	if (play_tone(pcm_fd) < 0)
		goto restore;
	fprintf(stderr,
		"gemini-audio-headphone: completed %u ms 440 Hz headphone tone "
		"(period=%u buffer=%u frames)\n",
		TONE_MILLISECONDS, period_frames, buffer_frames);
	status = EXIT_SUCCESS;

restore:
	if (pcm_fd >= 0) {
		close(pcm_fd);
		pcm_fd = -1;
	}
	while (applied > 0) {
		applied--;
		if (restore_control(ctl_fd, &controls[applied], &saved[applied]) < 0)
			restore_status = -1;
	}
	if (restore_status < 0)
		status = EXIT_FAILURE;
out:
	if (pcm_fd >= 0)
		close(pcm_fd);
	if (ctl_fd >= 0)
		close(ctl_fd);
	return status;
}
