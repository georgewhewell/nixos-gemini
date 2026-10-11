// SPDX-License-Identifier: MIT
/* Host checks for the actual policy, parser and admission paths. */
#define _GNU_SOURCE
#include <stdio.h>
static FILE *parser_fopen(const char *, const char *);
static int parser_fclose(FILE *);
#define fopen parser_fopen
#define fclose parser_fclose
#define main core_parking_daemon_main
#include "core-parking.c"
#undef main
#undef fopen
#undef fclose

#include <assert.h>

static FILE *parser_stream;
static int parser_opens, parser_closes;
enum { NORMAL_FILE, READ_ERROR, SEEK_ERROR };
static int next_stream;
static size_t cookie_position;
static int cookie_kind;

static ssize_t cookie_read(void *cookie, char *buf, size_t size)
{
	static const char data[] = "cpu0 40 0 0 160 0 0 0 0 0 0\nprocs_running 1\n";
	size_t n = sizeof(data) - 1 - cookie_position;
	(void)cookie;
	if (!n && cookie_kind == READ_ERROR) {
		errno = EIO;
		return -1;
	}
	if (n > size)
		n = size;
	memcpy(buf, data + cookie_position, n);
	cookie_position += n;
	return (ssize_t)n;
}

static int cookie_seek(void *cookie, off64_t *offset, int whence)
{
	(void)cookie;
	(void)offset;
	(void)whence;
	errno = ESPIPE;
	return -1;
}

static FILE *parser_fopen(const char *path, const char *mode)
{
	FILE *f;
	if (strlen(path) < 10 || strcmp(path + strlen(path) - 10, "/proc/stat"))
		return fopen(path, mode);
	parser_opens++;
	if (next_stream) {
		cookie_position = 0;
		cookie_kind = next_stream;
		next_stream = NORMAL_FILE;
		f = fopencookie(NULL, "r", (cookie_io_functions_t){
			.read = cookie_read, .seek = cookie_seek});
	} else {
		f = fopen(path, mode);
	}
	parser_stream = f;
	return f;
}

static int parser_fclose(FILE *f)
{
	if (f == parser_stream) {
		parser_closes++;
		parser_stream = NULL;
	}
	return fclose(f);
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

static void test_parser(void)
{
	static const char *const dirs[] = {
		"/proc", "/sys", "/sys/devices", "/sys/devices/system",
		"/sys/devices/system/cpu", "/sys/devices/system/cpu/cpu1",
		"/sys/devices/system/cpu/cpu3", "/sys/devices/system/cpu/cpu8",
		"/sys/devices/system/cpu/cpu31",
	};
	static const int cpus[] = {1, 3, 8, 31};
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
		"cpu31 0 0 0 100 0 0 0 0 0 0\n"
		"cpu32 100 0 0 0 0 0 0 0 0 0\n"
		"cpu2 malformed\nprocs_running 3\n", false);
	assert(read_stat(&x));
	assert(parser_opens == 1 && parser_closes == 0 && parser_stream);
	assert(fcntl(fileno(parser_stream), F_GETFD) & FD_CLOEXEC);
	assert(x.cap == 4 && x.nr == 2 && x.load == 0);
	assert(x.online_mask == (UINT32_C(1) | (UINT32_C(1) << 3) |
				(UINT32_C(1) << 8) | (UINT32_C(1) << 31)));
	memcpy(order, cpus, sizeof(cpus));
	norder = sizeof(cpus) / sizeof(cpus[0]);
	blocked[8] = true;
	/* CPU0 is unmanaged; blocked CPU8 still contributes to sample cap. */
	assert(count_online_managed(&x) == 2);
	fixture_file("/proc/stat",
		"cpu0 20 0 0 180 0 0 0 0 0 0\n"
		"cpu3 70 0 0 130 0 0 0 0 0 0\n"
		"cpu31 0 0 0 200 0 0 0 0 0 0\n"
		"procs_running 0\n", false);
	assert(read_stat(&x));
	/* Rewind the same FILE and consume the rewritten counters, not EOF. */
	assert(parser_opens == 1 && parser_closes == 0);
	assert(x.cap == 3 && x.nr == 0 && x.load == 60);
	assert(x.online_mask == (UINT32_C(1) | (UINT32_C(1) << 3) |
				(UINT32_C(1) << 31)));
	assert(count_online_managed(&x) == 2);
	fixture_file("/sys/devices/system/cpu/cpu1/online", "1\n", false);
	fixture_file("/sys/devices/system/cpu/cpu3/online", "0\n", false);
	fixture_file("/sys/devices/system/cpu/cpu8/online", "1\n", false);
	fixture_file("/sys/devices/system/cpu/cpu31/online", "0\n", false);
	/* Admission must reread current state even when the sample says k=2. */
	assert(count_online_managed(NULL) == 1);
	apply(2, R_MIN, &x);
	assert(cpu_online(3) == 1 && cpu_online(31) == 0);
	assert(count_online_managed(NULL) == 2);
	assert(count_online_managed(&x) == 2);
	fixture_file("/proc/stat", "cpu2 malformed\nprocs_running 1\n", false);
	assert(!read_stat(&x) && x.cap == 0 && x.online_mask == 0);
	assert(!parser_stream && parser_closes == 1);
	fixture_file("/proc/stat", NULL, true);
	x = (struct sample){ .cap = 7, .online_mask = UINT32_C(1) << 31 };
	assert(!read_stat(&x) && x.cap == 7 &&
	       x.online_mask == (UINT32_C(1) << 31));
	/* A partial read error must discard the stream and its partial sample. */
	next_stream = READ_ERROR;
	assert(!read_stat(&x) && x.cap == 7 &&
	       x.online_mask == (UINT32_C(1) << 31));
	assert(!parser_stream && parser_closes == 2);
	fixture_file("/proc/stat", "cpu0 40 0 0 160 0 0 0 0 0 0\n", false);
	assert(read_stat(&x) && x.cap == 1 && parser_stream);
	fixture_file("/proc/stat", "cpu2 malformed\n", false);
	assert(!read_stat(&x) && !parser_stream && parser_closes == 3);
	/* Failed seek retires a previously readable FILE; the next call reopens. */
	next_stream = SEEK_ERROR;
	assert(read_stat(&x) && x.cap == 1 && parser_stream);
	x = (struct sample){ .cap = 7, .online_mask = UINT32_C(1) << 31 };
	assert(!read_stat(&x) && x.cap == 7 &&
	       x.online_mask == (UINT32_C(1) << 31));
	assert(!parser_stream && parser_closes == 4);
	fixture_file("/proc/stat", "cpu0 40 0 0 160 0 0 0 0 0 0\n", false);
	assert(read_stat(&x) && x.cap == 1 && parser_stream);
	fixture_file("/proc/stat", "cpu2 malformed\n", false);
	assert(!read_stat(&x) && !parser_stream && parser_closes == 5);
	fixture_file("/proc/stat", NULL, true);
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
