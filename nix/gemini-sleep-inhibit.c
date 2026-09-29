// SPDX-License-Identifier: MIT
/*
 * gemini-sleep-inhibit - shape the Gemini PDA lid/sleep policy with
 * systemd-logind block inhibitors.
 *
 * logind owns the policy (HandleLidSwitch=, sleep.conf).  This daemon only
 * holds or releases inhibitors, so that "systemd-inhibit --list" always
 * shows why the device is not sleeping:
 *
 *   handle-lid-switch  while the lid is open, and for --lid-grace seconds
 *                      after it closes.  Once released, logind's lid recheck
 *                      carries out HandleLidSwitch= for the closed lid.
 *   sleep              while the USB device controller (--udc) is attached
 *                      to a host.  The MTU3 gadget refuses system sleep with
 *                      -EBUSY while connected, and it is the recovery link.
 *                      Requires LidSwitchIgnoreInhibited=no for the lid.
 *   sleep              until --accepted-file holds --accepted-content, i.e.
 *                      until the unattended-recovery watchdog lease has been
 *                      accepted.  A sleep before acceptance would make the
 *                      boot-time lease expire on resume.
 *
 * Inhibitors that cannot be taken (logind not reachable yet) are retried
 * every second; the daemon never exits on its own.
 */

#define _GNU_SOURCE

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <limits.h>
#include <linux/input.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/ioctl.h>
#include <sys/timerfd.h>
#include <time.h>
#include <unistd.h>

#include <systemd/sd-bus.h>

#define WHO "gemini-sleep-inhibit"

#define BITS_PER_LONG (sizeof(unsigned long) * CHAR_BIT)
#define NLONGS(n) (((n) + BITS_PER_LONG - 1) / BITS_PER_LONG)

static bool test_bit(unsigned int bit, const unsigned long *array)
{
	return (array[bit / BITS_PER_LONG] >> (bit % BITS_PER_LONG)) & 1UL;
}

struct inhibitor {
	const char *what;
	const char *why;
	bool wanted;
	int fd;
};

enum { INH_LID, INH_USB, INH_LEASE, INH_COUNT };

static struct inhibitor inhibitors[INH_COUNT] = {
	[INH_LID] = { "handle-lid-switch", NULL, false, -1 },
	[INH_USB] = { "sleep", "USB host attached to the recovery gadget", false, -1 },
	[INH_LEASE] = { "sleep", "unattended-recovery lease not yet accepted", false, -1 },
};

static char lid_why[128];

static int take_inhibitor(struct inhibitor *inh)
{
	sd_bus_error error = SD_BUS_ERROR_NULL;
	sd_bus_message *reply = NULL;
	sd_bus *bus = NULL;
	int fd, r;

	r = sd_bus_open_system(&bus);
	if (r < 0) {
		fprintf(stderr, "<4>cannot connect to the system bus: %s\n", strerror(-r));
		return r;
	}

	r = sd_bus_call_method(bus, "org.freedesktop.login1", "/org/freedesktop/login1",
			       "org.freedesktop.login1.Manager", "Inhibit", &error, &reply,
			       "ssss", inh->what, WHO, inh->why, "block");
	if (r < 0) {
		fprintf(stderr, "<4>Inhibit(%s) failed: %s\n", inh->what,
			error.message ? error.message : strerror(-r));
		goto out;
	}

	r = sd_bus_message_read(reply, "h", &fd);
	if (r < 0)
		goto out;

	/* The message owns fd; keep a private copy. */
	r = fcntl(fd, F_DUPFD_CLOEXEC, 3);
	if (r < 0)
		r = -errno;
out:
	sd_bus_error_free(&error);
	sd_bus_message_unref(reply);
	sd_bus_flush_close_unref(bus);
	return r;
}

/* Returns false if a wanted inhibitor could not be taken. */
static bool reconcile(void)
{
	bool complete = true;

	for (size_t i = 0; i < INH_COUNT; i++) {
		struct inhibitor *inh = &inhibitors[i];

		if (inh->wanted && inh->fd < 0) {
			int fd = take_inhibitor(inh);

			if (fd < 0) {
				complete = false;
				continue;
			}
			inh->fd = fd;
			fprintf(stderr, "<6>holding %s inhibitor: %s\n", inh->what, inh->why);
		} else if (!inh->wanted && inh->fd >= 0) {
			close(inh->fd);
			inh->fd = -1;
			fprintf(stderr, "<6>released %s inhibitor: %s\n", inh->what, inh->why);
		}
	}

	return complete;
}

static void arm_timer(int tfd, time_t seconds)
{
	struct itimerspec its = { .it_value = { .tv_sec = seconds } };

	if (timerfd_settime(tfd, 0, &its, NULL) < 0)
		fprintf(stderr, "<3>timerfd_settime: %m\n");
}

/* --- lid ---------------------------------------------------------------- */

static int lid_open_device(char *name, size_t size)
{
	unsigned long evbits[NLONGS(EV_CNT)];
	unsigned long swbits[NLONGS(SW_CNT)];
	struct dirent *de;
	DIR *dir;
	int found = -1;

	dir = opendir("/dev/input");
	if (!dir)
		return -1;

	while (found < 0 && (de = readdir(dir))) {
		char path[PATH_MAX];
		int fd;

		if (strncmp(de->d_name, "event", 5) != 0)
			continue;
		snprintf(path, sizeof(path), "/dev/input/%s", de->d_name);
		fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
		if (fd < 0)
			continue;

		memset(evbits, 0, sizeof(evbits));
		memset(swbits, 0, sizeof(swbits));
		if (ioctl(fd, EVIOCGBIT(0, sizeof(evbits)), evbits) >= 0 &&
		    test_bit(EV_SW, evbits) &&
		    ioctl(fd, EVIOCGBIT(EV_SW, sizeof(swbits)), swbits) >= 0 &&
		    test_bit(SW_LID, swbits)) {
			if (ioctl(fd, EVIOCGNAME(size), name) < 0)
				snprintf(name, size, "%s", path);
			found = fd;
		} else {
			close(fd);
		}
	}

	closedir(dir);
	return found;
}

static int lid_query(int fd)
{
	unsigned long swstate[NLONGS(SW_CNT)];

	memset(swstate, 0, sizeof(swstate));
	if (ioctl(fd, EVIOCGSW(sizeof(swstate)), swstate) < 0)
		return -errno;

	return test_bit(SW_LID, swstate);
}

struct lid {
	int fd;
	int timer;
	long grace;
	bool closed;
	bool grace_pending;
};

static void lid_update(struct lid *lid, bool closed)
{
	if (closed == lid->closed)
		return;

	lid->closed = closed;
	if (closed) {
		lid->grace_pending = true;
		arm_timer(lid->timer, lid->grace);
		fprintf(stderr, "<6>lid closed; lid action allowed in %ld s\n", lid->grace);
	} else {
		lid->grace_pending = false;
		arm_timer(lid->timer, 0);
		fprintf(stderr, "<6>lid opened\n");
	}
}

/* Returns false if the device went away. */
static bool lid_dispatch(struct lid *lid)
{
	struct input_event ev[32];

	for (;;) {
		ssize_t n = read(lid->fd, ev, sizeof(ev));

		if (n < 0) {
			if (errno == EINTR)
				continue;
			if (errno == EAGAIN)
				return true;
			fprintf(stderr, "<3>lid device read failed: %m\n");
			return false;
		}
		if (n == 0)
			return false;

		for (size_t i = 0; i < (size_t)n / sizeof(ev[0]); i++) {
			if (ev[i].type == EV_SW && ev[i].code == SW_LID) {
				lid_update(lid, ev[i].value != 0);
			} else if (ev[i].type == EV_SYN && ev[i].code == SYN_DROPPED) {
				int state = lid_query(lid->fd);

				if (state >= 0)
					lid_update(lid, state);
			}
		}
	}
}

/* --- USB device controller ---------------------------------------------- */

static int udc_open_state(const char *udc, char *name, size_t size)
{
	char path[PATH_MAX];
	struct dirent *de;
	DIR *dir;

	if (udc) {
		snprintf(name, size, "%s", udc);
	} else {
		/* Exactly one UDC, or none is watched. */
		int count = 0;

		dir = opendir("/sys/class/udc");
		if (!dir)
			return -1;
		while ((de = readdir(dir))) {
			if (de->d_name[0] == '.')
				continue;
			snprintf(name, size, "%s", de->d_name);
			count++;
		}
		closedir(dir);
		if (count != 1)
			return -1;
	}

	snprintf(path, sizeof(path), "/sys/class/udc/%s/state", name);
	return open(path, O_RDONLY | O_CLOEXEC);
}

/* Returns 1 if a host is attached, 0 if not, <0 if unreadable. */
static int udc_attached(int fd)
{
	char state[64];
	ssize_t n = pread(fd, state, sizeof(state) - 1, 0);

	if (n <= 0)
		return -1;
	state[n] = '\0';
	state[strcspn(state, "\n")] = '\0';

	/* include/linux/usb/ch9.h usb_state_string(): "not attached" is the
	 * only state in which no host is driving the bus. */
	return strcmp(state, "not attached") != 0;
}

/* --- recovery lease -------------------------------------------------------- */

static bool lease_accepted(const char *file, const char *content)
{
	char buf[256];
	size_t len = strlen(content);
	ssize_t n;
	int fd;

	fd = open(file, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return false;
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n < 0)
		return false;
	buf[n] = '\0';
	buf[strcspn(buf, "\n")] = '\0';

	return strlen(buf) == len && memcmp(buf, content, len) == 0;
}

/* --- main ------------------------------------------------------------------ */

static void usage(FILE *out)
{
	fprintf(out,
		"usage: " WHO " [--lid-grace SECONDS] [--udc NAME]\n"
		"       [--accepted-file PATH --accepted-content STRING]\n");
}

int main(int argc, char **argv)
{
	static const struct option options[] = {
		{ "lid-grace", required_argument, NULL, 'g' },
		{ "udc", required_argument, NULL, 'u' },
		{ "accepted-file", required_argument, NULL, 'f' },
		{ "accepted-content", required_argument, NULL, 'c' },
		{ "help", no_argument, NULL, 'h' },
		{}
	};
	const char *udc_arg = NULL, *accepted_file = NULL, *accepted_content = NULL;
	struct lid lid = { .fd = -1, .timer = -1, .grace = 900 };
	char lid_name[PATH_MAX] = "", udc_name[NAME_MAX + 1] = "";
	int udc_fd = -1, lease_fd = -1, retry_fd;
	int opt;

	while ((opt = getopt_long(argc, argv, "h", options, NULL)) != -1) {
		switch (opt) {
		case 'g': {
			char *end;

			errno = 0;
			lid.grace = strtol(optarg, &end, 10);
			if (errno || *end || lid.grace < 0 || lid.grace > 7 * 24 * 3600) {
				fprintf(stderr, "invalid --lid-grace: %s\n", optarg);
				return EXIT_FAILURE;
			}
			break;
		}
		case 'u':
			udc_arg = optarg;
			break;
		case 'f':
			accepted_file = optarg;
			break;
		case 'c':
			accepted_content = optarg;
			break;
		case 'h':
			usage(stdout);
			return EXIT_SUCCESS;
		default:
			usage(stderr);
			return EXIT_FAILURE;
		}
	}
	if (optind != argc || !accepted_file != !accepted_content) {
		usage(stderr);
		return EXIT_FAILURE;
	}

	retry_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
	if (retry_fd < 0) {
		fprintf(stderr, "<3>timerfd_create: %m\n");
		return EXIT_FAILURE;
	}

	/* Lid: CLOCK_BOOTTIME, so time spent asleep counts towards the grace. */
	lid.fd = lid_open_device(lid_name, sizeof(lid_name));
	if (lid.fd >= 0) {
		int state = lid_query(lid.fd);

		lid.timer = timerfd_create(CLOCK_BOOTTIME, TFD_NONBLOCK | TFD_CLOEXEC);
		if (lid.timer < 0 || state < 0) {
			fprintf(stderr, "<3>cannot track the lid: %m\n");
			return EXIT_FAILURE;
		}
		snprintf(lid_why, sizeof(lid_why),
			 "lid open, or closed for less than %ld s", lid.grace);
		inhibitors[INH_LID].why = lid_why;
		lid.closed = false;
		lid_update(&lid, state);
		fprintf(stderr, "<6>lid switch: %s (%s)\n", lid_name,
			state ? "closed" : "open");
	} else {
		fprintf(stderr, "<5>no SW_LID input device; lid grace disabled\n");
	}

	udc_fd = udc_open_state(udc_arg, udc_name, sizeof(udc_name));
	if (udc_fd >= 0) {
		int attached = udc_attached(udc_fd);

		inhibitors[INH_USB].wanted = attached > 0;
		fprintf(stderr, "<6>USB device controller: %s (%s)\n", udc_name,
			attached > 0 ? "host attached" : "no host");
	} else {
		fprintf(stderr, "<5>no USB device controller state; USB host check disabled\n");
	}

	if (accepted_file) {
		char dir[PATH_MAX];
		char *slash;

		snprintf(dir, sizeof(dir), "%s", accepted_file);
		slash = strrchr(dir, '/');
		if (!slash || slash == dir) {
			fprintf(stderr, "<3>--accepted-file must be an absolute path below /\n");
			return EXIT_FAILURE;
		}
		*slash = '\0';

		/* Watch before the first check so an acceptance cannot be missed. */
		lease_fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
		if (lease_fd < 0 ||
		    inotify_add_watch(lease_fd, dir, IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE) < 0) {
			fprintf(stderr, "<3>cannot watch %s: %m\n", dir);
			return EXIT_FAILURE;
		}
		if (lease_accepted(accepted_file, accepted_content)) {
			close(lease_fd);
			lease_fd = -1;
		} else {
			inhibitors[INH_LEASE].wanted = true;
		}
	}

	for (;;) {
		struct pollfd pfd[5];
		int npfd = 0;
		int ilid = -1, itimer = -1, iudc = -1, ilease = -1, iretry;

		inhibitors[INH_LID].wanted = lid.fd >= 0 && (!lid.closed || lid.grace_pending);
		if (!reconcile())
			arm_timer(retry_fd, 1);

		if (lid.fd >= 0) {
			ilid = npfd;
			pfd[npfd++] = (struct pollfd){ .fd = lid.fd, .events = POLLIN };
			itimer = npfd;
			pfd[npfd++] = (struct pollfd){ .fd = lid.timer, .events = POLLIN };
		}
		if (udc_fd >= 0) {
			iudc = npfd;
			pfd[npfd++] = (struct pollfd){ .fd = udc_fd, .events = POLLPRI | POLLERR };
		}
		if (lease_fd >= 0) {
			ilease = npfd;
			pfd[npfd++] = (struct pollfd){ .fd = lease_fd, .events = POLLIN };
		}
		iretry = npfd;
		pfd[npfd++] = (struct pollfd){ .fd = retry_fd, .events = POLLIN };

		if (poll(pfd, npfd, -1) < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "<3>poll: %m\n");
			return EXIT_FAILURE;
		}

		if (ilid >= 0 && pfd[ilid].revents) {
			if (!lid_dispatch(&lid)) {
				fprintf(stderr, "<4>lid switch gone; lid grace disabled\n");
				close(lid.fd);
				close(lid.timer);
				lid.fd = lid.timer = -1;
				itimer = -1;
			}
		}
		if (itimer >= 0 && pfd[itimer].revents) {
			uint64_t expirations;

			if (read(lid.timer, &expirations, sizeof(expirations)) > 0 && lid.closed) {
				lid.grace_pending = false;
				fprintf(stderr, "<6>lid closed for %ld s; releasing the lid switch\n",
					lid.grace);
			}
		}
		if (iudc >= 0 && pfd[iudc].revents) {
			int attached = udc_attached(udc_fd);

			if (attached >= 0 && inhibitors[INH_USB].wanted != (attached > 0)) {
				inhibitors[INH_USB].wanted = attached > 0;
				fprintf(stderr, "<6>USB host %s\n", attached ? "attached" : "detached");
			}
		}
		if (ilease >= 0 && pfd[ilease].revents) {
			char events[4096];

			while (read(lease_fd, events, sizeof(events)) > 0)
				;
			if (lease_accepted(accepted_file, accepted_content)) {
				fprintf(stderr, "<6>unattended-recovery lease accepted\n");
				inhibitors[INH_LEASE].wanted = false;
				close(lease_fd);
				lease_fd = -1;
			}
		}
		if (pfd[iretry].revents) {
			uint64_t expirations;

			(void)!read(retry_fd, &expirations, sizeof(expirations));
		}
	}
}
