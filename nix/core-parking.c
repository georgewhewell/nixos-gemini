// SPDX-License-Identifier: MIT
/*
 * gemini-core-parking: load-driven CPU parking (hotplug) for MT6797.
 *
 * MT6797 has no per-core power-down idle state; PSCI CPU_OFF via CPU hotplug
 * is the only way to remove power from a core (handoff/m42-spm-idle.md,
 * handoff/atf-custom-20260928.md).  The vendor kernel ran an in-kernel
 * policy for this (MediaTek HPS, mt_hotplug_strategy_*.c).  Upstream Linux
 * does not take in-kernel hotplug governors, so this is the userspace
 * equivalent: it samples /proc/stat, parks cores with hysteresis and brings
 * them back on load, on input and when asked to hold.
 *
 * Model.  The managed CPUs form an ordered list (the "unpark order", e.g.
 * 1,2,3,4,5,6,7,8,9); k is how many of them are online.  Parking removes
 * the last online CPU of that list, unparking adds the first offline one.
 * CPU0 and pinned CPUs are never written.  Load is the sum of per-CPU busy
 * percentages over all online CPUs (managed or not), as in the vendor's
 * hps_ctxt.cur_loads, and "cap" is the number of online CPUs.
 *
 * Decision per sample (see decide()):
 *   rush:  load >= rush_pct*cap and runnable > cap  -> k += runnable - cap
 *   up:    mean(last up_samples loads) > up_pct*cap  -> k += 1
 *   down:  mean(last down_samples loads) < down_pct*(cap-1) continuously for
 *          down_hold_ms -> k -= 1 (and the hold restarts)
 *   floors: k >= min_k; k >= boost_k while an input boost is active
 *   ceiling: k <= thermal_k while the thermal zone is hot
 *   hold file present: k = all; pause file present: no writes at all.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define MAX_CPUS 32
#define MAX_INPUTS 48
#define HIST 32

struct policy {
	int period_ms;
	int up_pct;
	int up_samples;
	int down_pct;
	int down_samples;
	int down_hold_ms;
	int rush_pct;
	int min_k;
	int boost_k;
	int boost_hold_ms;
	int thermal_k;
};

struct sample {
	int load;	/* sum of busy percent over online CPUs */
	int cap;	/* online CPUs */
	int nr;		/* runnable tasks, excluding this daemon */
};

struct pstate {
	int hist[HIST];
	int nhist;
	int hpos;
	int64_t low_since;	/* -1: load is not low */
	int64_t boost_until;
	bool hot;
};

enum reason {
	R_NONE,
	R_RUSH,
	R_UP,
	R_DOWN,
	R_BOOST,
	R_MIN,
	R_THERMAL,
	R_HOLD,
	R_INPUT,
	R_EXIT,
};

static const char *const reason_name[] = {
	[R_NONE] = "none", [R_RUSH] = "rush", [R_UP] = "up",
	[R_DOWN] = "down", [R_BOOST] = "boost", [R_MIN] = "min",
	[R_THERMAL] = "thermal", [R_HOLD] = "hold", [R_INPUT] = "input",
	[R_EXIT] = "exit",
};

static int hist_mean(const struct pstate *s, int n)
{
	int i, sum = 0;

	if (n > s->nhist)
		n = s->nhist;
	if (n <= 0)
		return 0;
	for (i = 0; i < n; i++)
		sum += s->hist[(s->hpos - 1 - i + HIST) % HIST];
	return sum / n;
}

static int policy_floor(const struct policy *p, const struct pstate *s,
			int64_t now)
{
	int floor = p->min_k;

	if (now < s->boost_until && p->boost_k > floor)
		floor = p->boost_k;
	return floor;
}

/*
 * Pure policy step.  k: managed CPUs online now; m: managed CPUs in total.
 * Returns the wanted k.  Parking is limited to one CPU per call.
 */
static int decide(const struct policy *p, struct pstate *s,
		  const struct sample *x, int64_t now, int k, int m, bool hold,
		  enum reason *why)
{
	int cap = x->cap > 0 ? x->cap : 1;
	int want = k;
	int floor, ceiling;

	s->hist[s->hpos] = x->load;
	s->hpos = (s->hpos + 1) % HIST;
	if (s->nhist < HIST)
		s->nhist++;
	*why = R_NONE;

	if (hold) {
		*why = R_HOLD;
		s->low_since = -1;
		return m;
	}

	if (x->load >= p->rush_pct * cap && x->nr > cap) {
		want = k + (x->nr - cap);
		*why = R_RUSH;
		s->low_since = -1;
	} else if (s->nhist >= p->up_samples &&
		   hist_mean(s, p->up_samples) > p->up_pct * cap) {
		want = k + 1;
		*why = R_UP;
		s->low_since = -1;
	} else if (cap > 1 && x->nr < cap &&
		   x->load < p->down_pct * (cap - 1) &&
		   s->nhist >= p->down_samples &&
		   hist_mean(s, p->down_samples) < p->down_pct * (cap - 1)) {
		if (s->low_since < 0)
			s->low_since = now;
		if (now - s->low_since >= p->down_hold_ms) {
			want = k - 1;
			*why = R_DOWN;
			s->low_since = now;
		}
	} else {
		s->low_since = -1;
	}

	floor = policy_floor(p, s, now);
	if (want < floor) {
		if (k < floor)
			*why = now < s->boost_until && p->boost_k > p->min_k ?
				R_BOOST : R_MIN;
		else
			*why = R_NONE;
		want = floor;
	}
	ceiling = s->hot ? p->thermal_k : m;
	if (want > ceiling) {
		want = ceiling;
		if (k > ceiling)
			*why = R_THERMAL;
	}
	if (want > m)
		want = m;
	if (want < 0)
		want = 0;
	if (want < k - 1)
		want = k - 1;
	return want;
}

#ifndef CORE_PARKING_NO_MAIN

static const char *root = "";
static bool dry_run;
static bool restore_on_exit = true;
static volatile sig_atomic_t stop_requested;

static int order[MAX_CPUS];	/* unpark order */
static int norder;
static bool pinned[MAX_CPUS];
static int requires_cpu[MAX_CPUS];	/* must be online before this one */
static bool blocked[MAX_CPUS];	/* permanent failure */
static int64_t backoff_until[MAX_CPUS];

static unsigned long long prev_busy[MAX_CPUS], prev_total[MAX_CPUS];
static bool prev_valid[MAX_CPUS];

static char thermal_path[512];
static long thermal_hot = 95000, thermal_clear = 90000;

static int64_t now_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int64_t now_us(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}

static void path_of(char *buf, size_t len, const char *fmt, int arg)
{
	char tail[256];

	snprintf(tail, sizeof(tail), fmt, arg);
	snprintf(buf, len, "%s%s", root, tail);
}

static int cpu_online(int cpu)
{
	char path[512], c = '1';
	int fd;

	path_of(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/online", cpu);
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return cpu == 0 ? 1 : -1;
	if (read(fd, &c, 1) != 1)
		c = '1';
	close(fd);
	return c == '1';
}

/* Returns 0 or -errno; logs the transition and its latency. */
static int cpu_set(int cpu, int on, enum reason why, const struct sample *x,
		   int k)
{
	char path[512];
	int64_t t0, t1;
	int fd, ret = 0;
	ssize_t n;

	if (cpu == 0 || pinned[cpu])
		return -EPERM;
	path_of(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/online", cpu);
	t0 = now_us();
	if (!dry_run) {
		fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
		if (fd < 0) {
			ret = -errno;
		} else {
			do {
				n = write(fd, on ? "1" : "0", 1);
			} while (n < 0 && errno == EINTR);
			if (n != 1)
				ret = n < 0 ? -errno : -EIO;
			if (close(fd) && !ret)
				ret = -errno;
		}
	}
	t1 = now_us();
	printf("cpu%d %s reason=%s load=%d cap=%d nr=%d k=%d took_us=%lld%s%s%s\n",
	       cpu, on ? "online" : "offline", reason_name[why],
	       x ? x->load : -1, x ? x->cap : -1, x ? x->nr : -1, k,
	       (long long)(t1 - t0), dry_run ? " dry-run" : "",
	       ret ? " error=" : "", ret ? strerror(-ret) : "");
	if (ret) {
		switch (-ret) {
		case EPERM:
		case EOPNOTSUPP:
		case EINVAL:
		case ENOENT:
		case EACCES:
		case EROFS:
			blocked[cpu] = true;
			printf("cpu%d not manageable (%s); leaving it %s\n",
			       cpu, strerror(-ret), on ? "offline" : "online");
			break;
		default:
			backoff_until[cpu] = now_ms() + 5000;
			break;
		}
	}
	if (!ret)
		prev_valid[cpu] = false;
	return ret;
}

static bool usable(int cpu, int64_t now)
{
	return !blocked[cpu] && !pinned[cpu] && now >= backoff_until[cpu];
}

static int count_online_managed(void)
{
	int i, k = 0;

	for (i = 0; i < norder; i++)
		if (!blocked[order[i]] && cpu_online(order[i]) == 1)
			k++;
	return k;
}

static int managed_total(void)
{
	int i, m = 0;

	for (i = 0; i < norder; i++)
		if (!blocked[order[i]])
			m++;
	return m;
}

/* Online the first offline managed CPU in unpark order. */
static bool unpark_one(enum reason why, const struct sample *x, int k)
{
	int64_t now = now_ms();
	int i, cpu, dep;

	for (i = 0; i < norder; i++) {
		cpu = order[i];
		if (cpu_online(cpu) != 0 || !usable(cpu, now))
			continue;
		dep = requires_cpu[cpu];
		if (dep >= 0 && cpu_online(dep) == 0) {
			if (!usable(dep, now) || cpu_set(dep, 1, why, x, k))
				continue;
		}
		if (!cpu_set(cpu, 1, why, x, k))
			return true;
	}
	return false;
}

/* Offline the last online managed CPU in unpark order. */
static bool park_one(enum reason why, const struct sample *x, int k)
{
	int64_t now = now_ms();
	int i, cpu;

	for (i = norder - 1; i >= 0; i--) {
		cpu = order[i];
		if (cpu_online(cpu) != 1 || !usable(cpu, now))
			continue;
		if (!cpu_set(cpu, 0, why, x, k))
			return true;
	}
	return false;
}

static void apply(int want, enum reason why, const struct sample *x)
{
	int k = count_online_managed();
	int guard = MAX_CPUS * 2;

	while (k < want && guard--) {
		if (!unpark_one(why, x, k))
			break;
		k = count_online_managed();
	}
	if (k > want && park_one(why, x, k))
		k = count_online_managed();
}

static bool read_stat(struct sample *x)
{
	char path[512], line[512];
	FILE *f;
	int load = 0, cap = 0, nr = 0;

	snprintf(path, sizeof(path), "%s/proc/stat", root);
	f = fopen(path, "re");
	if (!f)
		return false;
	while (fgets(line, sizeof(line), f)) {
		unsigned long long v[10] = {0};
		unsigned long long busy, total, db, dt;
		int cpu, i;

		if (!strncmp(line, "procs_running ", 14)) {
			nr = atoi(line + 14) - 1;
			continue;
		}
		if (strncmp(line, "cpu", 3) || line[3] < '0' || line[3] > '9')
			continue;
		if (sscanf(line + 3, "%d %llu %llu %llu %llu %llu %llu %llu %llu %llu %llu",
			   &cpu, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6],
			   &v[7], &v[8], &v[9]) < 5)
			continue;
		if (cpu < 0 || cpu >= MAX_CPUS)
			continue;
		cap++;
		total = 0;
		for (i = 0; i < 8; i++)	/* guest time is already in user */
			total += v[i];
		busy = total - v[3] - v[4];
		if (prev_valid[cpu] && total > prev_total[cpu]) {
			db = busy >= prev_busy[cpu] ? busy - prev_busy[cpu] : 0;
			dt = total - prev_total[cpu];
			load += (int)(db * 100 / dt);
		}
		prev_busy[cpu] = busy;
		prev_total[cpu] = total;
		prev_valid[cpu] = true;
	}
	fclose(f);
	x->load = load;
	x->cap = cap;
	x->nr = nr < 0 ? 0 : nr;
	return cap > 0;
}

static bool file_exists(const char *name)
{
	char path[512];

	snprintf(path, sizeof(path), "%s/run/gemini-core-parking/%s", root, name);
	return access(path, F_OK) == 0;
}

static long read_temp(void)
{
	char buf[32];
	ssize_t n;
	int fd;

	if (!thermal_path[0])
		return -1;
	fd = open(thermal_path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n <= 0)
		return -1;
	buf[n] = 0;
	return strtol(buf, NULL, 10);
}

static void find_thermal(const char *type)
{
	char path[512], buf[64];
	struct dirent *de;
	DIR *d;

	snprintf(path, sizeof(path), "%s/sys/class/thermal", root);
	d = opendir(path);
	if (!d)
		return;
	while ((de = readdir(d))) {
		FILE *f;

		if (strncmp(de->d_name, "thermal_zone", 12))
			continue;
		snprintf(path, sizeof(path), "%s/sys/class/thermal/%s/type",
			 root, de->d_name);
		f = fopen(path, "re");
		if (!f)
			continue;
		if (fgets(buf, sizeof(buf), f)) {
			buf[strcspn(buf, "\n")] = 0;
			if (!strcmp(buf, type))
				snprintf(thermal_path, sizeof(thermal_path),
					 "%s/sys/class/thermal/%s/temp", root,
					 de->d_name);
		}
		fclose(f);
		if (thermal_path[0])
			break;
	}
	closedir(d);
}

/* Input devices: any key, touch, pointer or motion event boosts. */
static int input_fd[MAX_INPUTS];
static char input_name[MAX_INPUTS][64];
static int ninput;

static void open_input(const char *name)
{
	char path[512];
	int i, fd;

	if (strncmp(name, "event", 5) || strlen(name) >= sizeof(input_name[0]) ||
	    ninput >= MAX_INPUTS)
		return;
	for (i = 0; i < ninput; i++)
		if (!strcmp(input_name[i], name))
			return;
	snprintf(path, sizeof(path), "%s/dev/input/%s", root, name);
	fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		return;
	input_fd[ninput] = fd;
	memcpy(input_name[ninput], name, strlen(name) + 1);
	ninput++;
	printf("input %s watched\n", name);
}

static void drop_input(int i)
{
	close(input_fd[i]);
	printf("input %s gone\n", input_name[i]);
	ninput--;
	input_fd[i] = input_fd[ninput];
	memcpy(input_name[i], input_name[ninput], sizeof(input_name[0]));
}

static void scan_input(void)
{
	char path[512];
	struct dirent *de;
	DIR *d;

	snprintf(path, sizeof(path), "%s/dev/input", root);
	d = opendir(path);
	if (!d)
		return;
	while ((de = readdir(d)))
		open_input(de->d_name);
	closedir(d);
}

/* Returns true if a boosting event was read. */
static bool drain_input(int i, bool *gone)
{
	struct input_event ev[32];
	bool boost = false;
	ssize_t n;
	size_t j;

	*gone = false;
	for (;;) {
		n = read(input_fd[i], ev, sizeof(ev));
		if (n < 0) {
			if (errno == EINTR)
				continue;
			if (errno != EAGAIN)
				*gone = true;
			break;
		}
		if (n == 0)
			break;
		for (j = 0; j < (size_t)n / sizeof(ev[0]); j++)
			if (ev[j].type == EV_KEY || ev[j].type == EV_ABS ||
			    ev[j].type == EV_REL)
				boost = true;
		if ((size_t)n < sizeof(ev))
			break;
	}
	return boost;
}

static bool parse_list(const char *arg, int *out, int *n)
{
	char *copy = strdup(arg), *tok, *save = NULL;
	bool ok = true;

	*n = 0;
	for (tok = strtok_r(copy, ",", &save); tok;
	     tok = strtok_r(NULL, ",", &save)) {
		int v = atoi(tok);

		if (v <= 0 || v >= MAX_CPUS || *n >= MAX_CPUS) {
			ok = false;
			break;
		}
		out[(*n)++] = v;
	}
	free(copy);
	return ok;
}

static void on_signal(int sig)
{
	(void)sig;
	stop_requested = 1;
}

static void usage(void)
{
	fputs("usage: gemini-core-parking [options]\n"
	      "  --order 1,2,...       managed CPUs in unpark order (default 1..9)\n"
	      "  --pinned 8,9          never write these CPUs\n"
	      "  --requires 8:4        online CPU 4 before CPU 8 (repeatable)\n"
	      "  --period-ms N         sampling period (50)\n"
	      "  --up-pct N            unpark above N%% per online CPU (80)\n"
	      "  --up-samples N        over the mean of N samples (2)\n"
	      "  --rush-pct N          rush when one sample >= N%% and runnable > online (95)\n"
	      "  --down-pct N          park when load fits in one CPU fewer at N%% (60)\n"
	      "  --down-samples N      over the mean of N samples (4)\n"
	      "  --down-hold-ms N      ... held for N ms; one CPU per hold (1000)\n"
	      "  --min N               managed CPUs always online (0)\n"
	      "  --boost N             managed CPUs online after input (3)\n"
	      "  --boost-hold-ms N     boost duration after the last event (1500)\n"
	      "  --thermal-type T      thermal zone type (soc-thermal)\n"
	      "  --thermal-hot mC      cap at --thermal-max from this temperature (95000)\n"
	      "  --thermal-clear mC    release the cap below this (90000)\n"
	      "  --thermal-max N       managed CPUs allowed online when hot (3)\n"
	      "  --start-delay-ms N    no parking during the first N ms (0)\n"
	      "  --root DIR            prefix for /sys, /proc, /dev, /run (tests)\n"
	      "  --no-input            do not watch /dev/input\n"
	      "  --no-restore          do not online everything on exit\n"
	      "  --dry-run             log decisions, write nothing\n"
	      "Files: /run/gemini-core-parking/hold (all online, no parking),\n"
	      "       /run/gemini-core-parking/pause (no writes at all).\n",
	      stderr);
}

int main(int argc, char **argv)
{
	struct policy p = {
		.period_ms = 50, .up_pct = 80, .up_samples = 2,
		.down_pct = 60, .down_samples = 4, .down_hold_ms = 1000,
		.rush_pct = 95, .min_k = 0, .boost_k = 3,
		.boost_hold_ms = 1500, .thermal_k = 3,
	};
	struct pstate s = { .low_since = -1 };
	const char *thermal_type = "soc-thermal";
	bool watch_input = true;
	int start_delay_ms = 0;
	int64_t start, next_tick, next_thermal = 0;
	struct sample last = {0};
	int inotify_fd = -1;
	int i, c;

	static const struct option opts[] = {
		{"order", required_argument, 0, 'o'},
		{"pinned", required_argument, 0, 'P'},
		{"requires", required_argument, 0, 'R'},
		{"period-ms", required_argument, 0, 1},
		{"up-pct", required_argument, 0, 2},
		{"up-samples", required_argument, 0, 3},
		{"rush-pct", required_argument, 0, 4},
		{"down-pct", required_argument, 0, 5},
		{"down-samples", required_argument, 0, 6},
		{"down-hold-ms", required_argument, 0, 7},
		{"min", required_argument, 0, 8},
		{"boost", required_argument, 0, 9},
		{"boost-hold-ms", required_argument, 0, 10},
		{"thermal-type", required_argument, 0, 11},
		{"thermal-hot", required_argument, 0, 12},
		{"thermal-clear", required_argument, 0, 13},
		{"thermal-max", required_argument, 0, 14},
		{"start-delay-ms", required_argument, 0, 15},
		{"root", required_argument, 0, 16},
		{"no-input", no_argument, 0, 17},
		{"no-restore", no_argument, 0, 18},
		{"dry-run", no_argument, 0, 19},
		{"help", no_argument, 0, 'h'},
		{0, 0, 0, 0},
	};

	setvbuf(stdout, NULL, _IOLBF, 0);
	for (i = 0; i < MAX_CPUS; i++)
		requires_cpu[i] = -1;
	for (i = 0; i < 9; i++)
		order[i] = i + 1;
	norder = 9;

	while ((c = getopt_long(argc, argv, "h", opts, NULL)) != -1) {
		int list[MAX_CPUS], n, a, b;

		switch (c) {
		case 'o':
			if (!parse_list(optarg, order, &norder) || !norder)
				goto bad;
			break;
		case 'P':
			if (!parse_list(optarg, list, &n))
				goto bad;
			for (i = 0; i < n; i++)
				pinned[list[i]] = true;
			break;
		case 'R':
			if (sscanf(optarg, "%d:%d", &a, &b) != 2 || a <= 0 ||
			    a >= MAX_CPUS || b < 0 || b >= MAX_CPUS || a == b)
				goto bad;
			requires_cpu[a] = b;
			break;
		case 1: p.period_ms = atoi(optarg); break;
		case 2: p.up_pct = atoi(optarg); break;
		case 3: p.up_samples = atoi(optarg); break;
		case 4: p.rush_pct = atoi(optarg); break;
		case 5: p.down_pct = atoi(optarg); break;
		case 6: p.down_samples = atoi(optarg); break;
		case 7: p.down_hold_ms = atoi(optarg); break;
		case 8: p.min_k = atoi(optarg); break;
		case 9: p.boost_k = atoi(optarg); break;
		case 10: p.boost_hold_ms = atoi(optarg); break;
		case 11: thermal_type = optarg; break;
		case 12: thermal_hot = atol(optarg); break;
		case 13: thermal_clear = atol(optarg); break;
		case 14: p.thermal_k = atoi(optarg); break;
		case 15: start_delay_ms = atoi(optarg); break;
		case 16: root = optarg; break;
		case 17: watch_input = false; break;
		case 18: restore_on_exit = false; break;
		case 19: dry_run = true; break;
		case 'h': usage(); return 0;
		default: goto bad;
		}
	}
	if (optind != argc || p.period_ms < 5 || p.up_samples < 1 ||
	    p.up_samples > HIST || p.down_samples < 1 ||
	    p.down_samples > HIST || p.min_k < 0 || p.boost_k < 0 ||
	    p.thermal_k < 0 || thermal_clear > thermal_hot)
		goto bad;

	/* Drop pinned CPUs from the managed list; they only count as load. */
	for (i = 0, c = 0; i < norder; i++)
		if (!pinned[order[i]])
			order[c++] = order[i];
	norder = c;

	find_thermal(thermal_type);
	printf("gemini-core-parking: order=");
	for (i = 0; i < norder; i++)
		printf("%s%d", i ? "," : "", order[i]);
	printf(" period=%dms up=%d%%x%d rush=%d%% down=%d%%x%d/%dms min=%d boost=%d/%dms thermal=%s@%ld/%ld->%d%s\n",
	       p.period_ms, p.up_pct, p.up_samples, p.rush_pct, p.down_pct,
	       p.down_samples, p.down_hold_ms, p.min_k, p.boost_k,
	       p.boost_hold_ms, thermal_path[0] ? thermal_path : "none",
	       thermal_hot, thermal_clear, p.thermal_k,
	       dry_run ? " dry-run" : "");

	signal(SIGTERM, on_signal);
	signal(SIGINT, on_signal);
	signal(SIGPIPE, SIG_IGN);

	if (watch_input) {
		char path[512];

		snprintf(path, sizeof(path), "%s/dev/input", root);
		inotify_fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
		if (inotify_fd >= 0 &&
		    inotify_add_watch(inotify_fd, path, IN_CREATE | IN_ATTRIB) < 0) {
			close(inotify_fd);
			inotify_fd = -1;
		}
		scan_input();
	}

	read_stat(&last);	/* prime the per-CPU counters */
	start = now_ms();
	next_tick = start + p.period_ms;

	while (!stop_requested) {
		struct pollfd pfd[MAX_INPUTS + 1];
		int64_t now = now_ms();
		int timeout = next_tick > now ? (int)(next_tick - now) : 0;
		bool input_boost = false;
		int n = 0;

		for (i = 0; i < ninput; i++) {
			pfd[n].fd = input_fd[i];
			pfd[n++].events = POLLIN;
		}
		if (inotify_fd >= 0) {
			pfd[n].fd = inotify_fd;
			pfd[n++].events = POLLIN;
		}
		if (poll(pfd, n, timeout) < 0 && errno != EINTR)
			break;
		if (stop_requested)
			break;

		for (i = ninput - 1; i >= 0; i--) {
			bool gone;

			if (!(pfd[i].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL)))
				continue;
			if (drain_input(i, &gone))
				input_boost = true;
			if (gone || (pfd[i].revents & (POLLERR | POLLHUP | POLLNVAL)))
				drop_input(i);
		}
		if (inotify_fd >= 0 && (pfd[n - 1].revents & POLLIN)) {
			char buf[4096];

			while (read(inotify_fd, buf, sizeof(buf)) > 0)
				;
			scan_input();
		}

		now = now_ms();
		if (input_boost) {
			s.boost_until = now + p.boost_hold_ms;
			if (!file_exists("pause")) {
				int k = count_online_managed();
				int want = policy_floor(&p, &s, now);

				if (s.hot && want > p.thermal_k)
					want = p.thermal_k;
				if (k < want)
					apply(want, R_INPUT, &last);
			}
		}
		if (now < next_tick)
			continue;
		next_tick += p.period_ms;
		if (next_tick <= now)
			next_tick = now + p.period_ms;

		if (thermal_path[0] && now >= next_thermal) {
			long t = read_temp();

			next_thermal = now + 1000;
			if (t >= 0) {
				if (!s.hot && t >= thermal_hot) {
					s.hot = true;
					printf("thermal hot temp=%ld\n", t);
				} else if (s.hot && t <= thermal_clear) {
					s.hot = false;
					printf("thermal clear temp=%ld\n", t);
				}
			}
		}

		if (!read_stat(&last))
			continue;
		if (file_exists("pause"))
			continue;
		{
			bool hold = file_exists("hold");
			int k = count_online_managed();
			enum reason why;
			int want = decide(&p, &s, &last, now, k, managed_total(),
					  hold, &why);

			if (!hold && want < k && now - start < start_delay_ms)
				want = k;
			if (want != k)
				apply(want, why, &last);
		}
	}

	if (restore_on_exit && !file_exists("pause")) {
		printf("exit: onlining all managed CPUs\n");
		apply(norder, R_EXIT, NULL);
	}
	return 0;
bad:
	usage();
	return 2;
}

#endif /* CORE_PARKING_NO_MAIN */
