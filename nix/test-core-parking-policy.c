// SPDX-License-Identifier: MIT
/* Host checks for the actual policy, parser and admission paths. */
#define _GNU_SOURCE
#include <stdbool.h>
#include <stddef.h>
#include <sys/types.h>
#include <fcntl.h>
#include <unistd.h>
static int parser_open(const char *, int, ...);
static int parser_close(int);
static ssize_t parser_read(int, void *, size_t);
static off_t parser_seek(int, off_t, int);
#define open parser_open
#define close parser_close
#define read parser_read
#define lseek parser_seek
#define main core_parking_daemon_main
#include "core-parking.c"
#undef main
#undef open
#undef close
#undef read
#undef lseek

#include <assert.h>
#include <stdarg.h>

static int parser_fds[2] = {-1, -1};
static unsigned parser_opens[2], parser_closes[2];
static size_t fragment_limit, read_bytes, read_error_after;
static bool interrupt_read, seek_error;

static int parser_open(const char *path, int flags, ...)
{
	int fd = open(path, flags);
	const char *suffix[] = {"/proc/stat", "/proc/loadavg"};

	for (unsigned i = 0; i < 2; i++) {
		size_t n = strlen(suffix[i]), len = strlen(path);

		if (len >= n && !strcmp(path + len - n, suffix[i])) {
			assert(parser_fds[i] == -1);
			parser_opens[i]++;
			parser_fds[i] = fd;
			if (i == 0)
				read_bytes = 0;
		}
	}
	return fd;
}

static int parser_close(int fd)
{
	for (unsigned i = 0; i < 2; i++) {
		if (fd == parser_fds[i]) {
			parser_closes[i]++;
			parser_fds[i] = -1;
		}
	}
	return close(fd);
}

static ssize_t parser_read(int fd, void *buf, size_t size)
{
	ssize_t n;

	if (fd == parser_fds[0]) {
		if (interrupt_read) {
			interrupt_read = false;
			errno = EINTR;
			return -1;
		}
		if (read_error_after && read_bytes >= read_error_after) {
			errno = EIO;
			return -1;
		}
		if (read_error_after && size > read_error_after - read_bytes)
			size = read_error_after - read_bytes;
	}
	if (fragment_limit && size > fragment_limit)
		size = fragment_limit;
	n = read(fd, buf, size);
	if (fd == parser_fds[0] && n > 0)
		read_bytes += (size_t)n;
	return n;
}

static off_t parser_seek(int fd, off_t offset, int whence)
{
	if (fd == parser_fds[0]) {
		read_bytes = 0;
		if (seek_error) {
			seek_error = false;
			errno = ESPIPE;
			return -1;
		}
	}
	return lseek(fd, offset, whence);
}

static const struct policy P = {
	.period_ms = 50, .up_pct = 80, .up_samples = 2,
	.down_pct = 60, .down_samples = 4, .down_hold_ms = 1000,
	.rush_pct = 95, .min_k = 0, .boost_k = 3,
	.boost_hold_ms = 1500, .thermal_k = 3,
};

static int step(struct pstate *s, int load, int cap, int nr, int64_t t, int k,
		enum reason *why)
{
	struct sample x = { .load = load, .cap = cap, .nr = nr };

	return decide(&P, s, &x, t, k, 9, false, why);
}

static void fixture_file(const char *relative, const char *value, bool remove)
{
	char *path;
	FILE *f;

	assert(asprintf(&path, "%s%s", root, relative) >= 0);
	if (remove) {
		assert(unlink(path) == 0);
	} else {
		f = fopen(path, "w");
		assert(f && fputs(value, f) >= 0 && fclose(f) == 0);
	}
	free(path);
}

static void reject_sample(struct sample *x)
{
	struct sample saved = *x;
	unsigned long long b[MAX_CPUS], t[MAX_CPUS];
	bool valid[MAX_CPUS];

	memcpy(b, prev_busy, sizeof(b));
	memcpy(t, prev_total, sizeof(t));
	memcpy(valid, prev_valid, sizeof(valid));
	assert(!read_stat(x));
	assert(!memcmp(x, &saved, sizeof(saved)));
	assert(!memcmp(b, prev_busy, sizeof(b)));
	assert(!memcmp(t, prev_total, sizeof(t)));
	assert(!memcmp(valid, prev_valid, sizeof(valid)));
	assert(stat_fd == -1 && loadavg_fd == -1);
	assert(parser_fds[0] == -1 && parser_fds[1] == -1);
}

static void test_parser(void)
{
	static const char *const dirs[] = {
		"/proc", "/sys", "/sys/devices", "/sys/devices/system",
		"/sys/devices/system/cpu", "/sys/devices/system/cpu/cpu1",
		"/sys/devices/system/cpu/cpu3", "/sys/devices/system/cpu/cpu8",
		"/sys/devices/system/cpu/cpu31",
	};
	static const int cpus[] = {1, 3, 8, 31};
	static const char aggregate[] = "cpu  0 0 0 0 0 0 0 0 0 0\n";
	static const char good[] = "cpu  0 0 0 0 0 0 0 0 0 0\n"
		"cpu0 40 0 0 160 0 0 0 0 0 0\nintr ";
	struct sample x;
	char *tmp, *path;
	const char *tmpdir = getenv("TMPDIR");

	assert(asprintf(&tmp, "%s/core-parking-parser-XXXXXX",
			tmpdir ? tmpdir : "/tmp") >= 0);
	assert(mkdtemp(tmp));
	root = tmp;
	for (size_t i = 0; i < sizeof(dirs) / sizeof(dirs[0]); i++) {
		assert(asprintf(&path, "%s%s", root, dirs[i]) >= 0);
		assert(mkdir(path, 0700) == 0);
		free(path);
	}
	fixture_file("/proc/stat",
		"cpu  0 0 0 0 0 0 0 0 0 0\n"
		"cpu0 10 0 0 90 0 0 0 0 0 0\n"
		"cpu3 20 0 0 80 0 0 0 0 0 0\n"
		"cpu8 30 0 0 70 0 0 0 0 0 0\n"
		"cpu31 0 0 0 100 0 0 0 0 0 0\nintr 0\nprocs_running 99\n", false);
	fixture_file("/proc/loadavg", "0.00 1.23 4.56 3/20 7\n", false);
	assert(read_stat(&x));
	assert(parser_opens[0] == 1 && parser_opens[1] == 1);
	assert(!parser_closes[0] && !parser_closes[1]);
	assert(fcntl(stat_fd, F_GETFD) & FD_CLOEXEC);
	assert(fcntl(loadavg_fd, F_GETFD) & FD_CLOEXEC);
	assert(x.cap == 4 && x.nr == 2 && x.load == 0);
	assert(x.online_mask == (UINT32_C(1) | (UINT32_C(1) << 3) |
				(UINT32_C(1) << 8) | (UINT32_C(1) << 31)));
	memcpy(order, cpus, sizeof(cpus));
	norder = sizeof(cpus) / sizeof(cpus[0]);
	blocked[8] = true;
	assert(count_online_managed(&x) == 2);
	fixture_file("/proc/stat",
		"cpu  0 0 0 0 0 0 0 0 0 0\n"
		"cpu0 20 0 0 180 0 0 0 0 0 0\n"
		"cpu3 70 0 0 130 0 0 0 0 0 0\n"
		"cpu31 0 0 0 200 0 0 0 0 0 0\nintr 123\n", false);
	fixture_file("/proc/loadavg", "0.00 0.00 0.00 0/1 0\n", false);
	fragment_limit = 2;
	interrupt_read = true;
	assert(read_stat(&x));
	fragment_limit = 0;
	assert(parser_opens[0] == 1 && parser_opens[1] == 1);
	assert(x.cap == 3 && x.nr == 0 && x.load == 60);
	assert(x.online_mask == (UINT32_C(1) | (UINT32_C(1) << 3) |
				(UINT32_C(1) << 31)));
	assert(count_online_managed(&x) == 2);
	fixture_file("/sys/devices/system/cpu/cpu1/online", "1\n", false);
	fixture_file("/sys/devices/system/cpu/cpu3/online", "0\n", false);
	fixture_file("/sys/devices/system/cpu/cpu8/online", "1\n", false);
	fixture_file("/sys/devices/system/cpu/cpu31/online", "0\n", false);
	assert(count_online_managed(NULL) == 1);
	apply(2, R_MIN, &x);
	assert(cpu_online(3) == 1 && cpu_online(31) == 0);
	assert(count_online_managed(NULL) == 2);

	static const char *const invalid[] = {
		"cpu0 1 2 3 4\nintr ", /* missing aggregate */
		"cpu 0 0 0 0\nintr ", /* no online rows */
		"cpu 0 0 0 0\ncpu0 malformed\nintr ",
		"cpu 0 0 0 0\ncpu0 -1 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu0 18446744073709551616 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu0 18446744073709551615 1 0 0\nintr ",
		"cpu 0 0 0 0\ncpu0 1 0 0 1 0 0 0 0 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu0 1 0 0 1\ncpu0 1 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu1 1 0 0 1\ncpu0 1 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu32 1 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu0 1 0 0 1\ncpu 0 0 0 0\nintr ",
		"cpu 0 0 0 0\ncpu0 1 0 0 1", /* truncated row/tag */
		"cpu 0 0 0 0\ncpu0 1 0 0 1\nintr", /* partial tag */
		"cpu 0 0 0 0\ncpu0 1 0 0 1\nprocs_running 1\n",
		"\ncpu 0 0 0 0\ncpu0 1 0 0 1\nintr ",
		"cpu 0 0 0 0\n\ncpu0 1 0 0 1\nintr ",
		"cpu 0 0 0 0\ncpu0 1 0 0 1\n\nintr ",
	};
	for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
		fixture_file("/proc/stat", invalid[i], false);
		reject_sample(&x);
	}
	char long_row[1024];
	memset(long_row, ' ', sizeof(long_row));
	const char *row_start = "cpu 0 0 0 0\ncpu0 1 0 0 1";
	memcpy(long_row, row_start, strlen(row_start));
	memcpy(long_row + 900, "\nintr ", 7);
	fixture_file("/proc/stat", long_row, false);
	reject_sample(&x);
	char *oversize = malloc(20000);
	assert(oversize);
	memset(oversize, ' ', 19999); oversize[19999] = 0;
	fixture_file("/proc/stat", oversize, false);
	reject_sample(&x); free(oversize);
	fixture_file("/proc/stat", good, false);
	static const char *const bad_loadavg[] = {
		"", "0.00 0.00 0.00 1/1 0", /* missing newline */
		"0.00 0.00 0.00 -1/1 0\n", "0.00 0.00 0.00 x/1 0\n",
		"0.0 0.00 0.00 1/1 0\n", "0.00 0.00 0.00 2147483649/1 0\n",
		"0.00 0.00 0.00 1/4294967296 0\n",
		"0.00 0.00 0.00 1/1 4294967296\n",
		"0.00 0.00 0.00 1/1 0 junk\n",
	};
	for (size_t i = 0; i < sizeof(bad_loadavg) / sizeof(bad_loadavg[0]); i++) {
		fixture_file("/proc/loadavg", bad_loadavg[i], false);
		reject_sample(&x);
	}
	fixture_file("/proc/loadavg", "0.00 0.00 0.00 1/1 0\n", false);
	read_error_after = sizeof(aggregate);
	reject_sample(&x);
	read_error_after = 0;
	assert(read_stat(&x));
	seek_error = true;
	reject_sample(&x);
	assert(read_stat(&x)); /* errors retire both descriptors; next call reopens */
	close_stat();
	fixture_file("/proc/stat", NULL, true);
	reject_sample(&x);
	fixture_file("/proc/loadavg", NULL, true);
	for (size_t i = 0; i < sizeof(cpus) / sizeof(cpus[0]); i++) {
		assert(asprintf(&path, "/sys/devices/system/cpu/cpu%d/online", cpus[i]) >= 0);
		fixture_file(path, NULL, true);
		free(path);
	}
	for (size_t i = sizeof(dirs) / sizeof(dirs[0]); i > 0; i--) {
		assert(asprintf(&path, "%s%s", root, dirs[i - 1]) >= 0);
		assert(rmdir(path) == 0);
		free(path);
	}
	assert(rmdir(root) == 0);
	root = "";
	free(tmp);
}

int main(void)
{
	struct pstate s = { .low_since = -1 };
	enum reason why;
	int64_t t = 0;
	int k, i;

	test_parser();

	/* Idle, 10 CPUs online: nothing before the hold, then one per hold. */
	k = 9;
	for (i = 0; i < 23; i++, t += 50)  /* 3 warm-up samples */
		assert(step(&s, 20, 10, 0, t, k, &why) == k && why == R_NONE);
	assert(step(&s, 20, 10, 0, t, k, &why) == 8 && why == R_DOWN);
	k = 8;
	t += 50;
	assert(step(&s, 20, 9, 0, t, k, &why) == 8);	/* hold restarted */
	for (; k > 0; ) {
		t += 1000;
		assert(step(&s, 20, k + 1, 0, t, k, &why) == k - 1 && why == R_DOWN);
		k--;
	}
	/* k == 0: CPU0 alone, cap 1: never below 0. */
	t += 2000;
	assert(step(&s, 5, 1, 0, t, 0, &why) == 0);

	/* Rush: one saturated sample with 4 runnable on 1 CPU -> +3 at once. */
	assert(step(&s, 100, 1, 4, t += 50, 0, &why) == 3 && why == R_RUSH);

	/* Up: mean of 2 samples above 80% per CPU -> +1, not before. */
	s = (struct pstate){ .low_since = -1 };
	assert(step(&s, 170, 2, 1, t += 50, 1, &why) == 1);	/* 1 sample */
	assert(step(&s, 170, 2, 1, t += 50, 1, &why) == 2 && why == R_UP);

	/* Hysteresis: 150% on 3 CPUs is neither up (>240) nor down (<120). */
	s = (struct pstate){ .low_since = -1 };
	for (i = 0; i < 100; i++)
		assert(step(&s, 150, 3, 1, t += 50, 2, &why) == 2);

	/* A spike resets the down hold. */
	s = (struct pstate){ .low_since = -1 };
	for (i = 0; i < 10; i++)
		assert(step(&s, 10, 3, 0, t += 50, 2, &why) == 2);
	for (i = 0; i < 4; i++)
		step(&s, 400, 3, 0, t += 50, 2, &why);
	for (i = 0; i < 20; i++)
		assert(step(&s, 10, 3, 0, t += 50, 2, &why) == 2);
	assert(s.low_since >= 0);

	/* The hold and low mean must not hide new runnable/load demand.
	 * Measured hotplug downs removed CPU1 with cap=2/nr=4, or with
	 * current load=120, followed by immediate rush unpark. Neither fits
	 * the prospective one-core capacity even when the old mean is low.
	 */
	for (int demand = 0; demand < 2; demand++) {
		s = (struct pstate){ .low_since = -1 };
		t = 0;
		for (i = 0; i < 23; i++, t += 50)
			assert(step(&s, 10, 2, 0, t, 1, &why) == 1);
		assert(step(&s, demand ? 53 : 120, 2, demand ? 4 : 1,
			    t, 1, &why) == 1 && why == R_NONE);
		assert(s.low_since < 0);
		/* Return to quiet load starts a fresh hold, not immediate park. */
		for (i = 0; i < 20; i++)
			assert(step(&s, 10, 2, 0, t += 50, 1, &why) == 1);
		assert(step(&s, 10, 2, 0, t += 50, 1, &why) == 0 &&
		       why == R_DOWN);
	}

	/* Input boost floor, then decay after the hold. */
	s = (struct pstate){ .low_since = -1 };
	s.boost_until = t + 1500;
	assert(step(&s, 0, 1, 0, t += 50, 0, &why) == 3 && why == R_BOOST);
	for (i = 0; i < 20; i++)
		assert(step(&s, 0, 4, 0, t += 50, 3, &why) == 3);
	t += 1500;
	assert(step(&s, 0, 4, 0, t, 3, &why) == 2 && why == R_DOWN);

	/* Thermal cap: park one per step down to thermal_k, block unpark. */
	s = (struct pstate){ .low_since = -1, .hot = true };
	assert(step(&s, 900, 10, 12, t += 50, 9, &why) == 8 && why == R_THERMAL);
	assert(step(&s, 300, 4, 12, t += 50, 3, &why) == 3);

	/* Hold: everything. */
	s = (struct pstate){ .low_since = -1 };
	{
		struct sample x = { .load = 0, .cap = 1, .nr = 0 };

		assert(decide(&P, &s, &x, t, 0, 9, true, &why) == 9 && why == R_HOLD);
	}
	puts("core-parking-policy: pass");
	return 0;
}
