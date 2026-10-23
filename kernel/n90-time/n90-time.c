// SPDX-License-Identifier: GPL-2.0
/*
 * n90-time: keep the phone's clock right, with or without a network.
 *
 * The phone has no NTP client and no kernel RTC. Its clocks are the system
 * clock, set by the laptop's boot pass, and the PMU's seconds counter, which
 * runs while the phone is off; n90-battery keeps that counter's offset from
 * real time in PMU bytes 0x84-0x88 (kernel/n90-battery/README.md#clock).
 *
 *   n90-time sync [SERVER...]  ask NTP servers (SNTP, RFC 4330) once, set the
 *                              clock, store the PMU offset again
 *   n90-time serve             what keep runs: set the clock from the PMU if it
 *                              is unset, then sync every 15 min while a server
 *                              answers, and learn how fast the system clock
 *                              runs so it stays right offline
 *   n90-time freq PPM          apply a frequency correction learned earlier
 *
 * State for Soy and the laptop in /run/time: source (ntp, pmu or laptop),
 * synced (epoch of the last good sync), offset_ms, freq_ppm, server.
 * Built against musl, whose resolver needs no NSS modules.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <math.h>
#include <netdb.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/timex.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define NTP_EPOCH 2208988800UL	/* 1900 to 1970 */
#define PLAUSIBLE 1767225600L	/* 2026-01-01: anything earlier is unset */
#define DIR "/run/time"

static const char *servers[] = { "nz.pool.ntp.org", "time.cloudflare.com",
				 "pool.ntp.org", NULL };

static double now_real(void)
{
	struct timespec t;

	clock_gettime(CLOCK_REALTIME, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static double now_mono(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static void put(const char *name, const char *fmt, ...)
{
	char path[64], tmp[64];
	va_list ap;
	FILE *f;

	snprintf(path, sizeof path, DIR "/%s", name);
	snprintf(tmp, sizeof tmp, DIR "/.%s", name);
	f = fopen(tmp, "w");
	if (!f)
		return;
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	if (fclose(f) == 0)
		rename(tmp, path);
}

static void say(const char *fmt, ...)
{
	FILE *f = fopen(DIR "/time.log", "a");
	char stamp[32];
	time_t t = time(NULL);
	va_list ap;

	if (!f)
		return;
	strftime(stamp, sizeof stamp, "%F %T", localtime(&t));
	fprintf(f, "%s ", stamp);
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	fputc('\n', f);
	fclose(f);
}

static void journal(const char *source, double offset)
{
	FILE *f = fopen("/run/soy/journal.jsonl", "a");

	if (f) {
		fprintf(f, "{\"t\":%ld,\"e\":\"time\",\"source\":\"%s\",\"offset_ms\":%.0f}\n",
			(long)time(NULL), source, offset * 1000);
		fclose(f);
	}
}

static int run(char *const argv[])
{
	pid_t pid = fork();
	int status;

	if (pid == 0) {
		execv(argv[0], argv);
		_exit(127);
	}
	if (pid < 0 || waitpid(pid, &status, 0) < 0)
		return -1;
	return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

static int pmu_clock(const char *what)
{
	char *argv[] = { "/usr/sbin/n90-battery", "clock", (char *)what, NULL };

	return run(argv);
}

static double from_ntp(const unsigned char *p)
{
	uint32_t s = (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
	uint32_t f = (uint32_t)p[4] << 24 | p[5] << 16 | p[6] << 8 | p[7];

	return (double)s - NTP_EPOCH + f / 4294967296.0;
}

static void to_ntp(unsigned char *p, double t)
{
	uint32_t s = (uint32_t)(t + NTP_EPOCH);
	uint32_t f = (uint32_t)((t - floor(t)) * 4294967296.0);

	p[0] = s >> 24; p[1] = s >> 16; p[2] = s >> 8; p[3] = s;
	p[4] = f >> 24; p[5] = f >> 16; p[6] = f >> 8; p[7] = f;
}

/* One exchange with one address. Returns 0 with the clock offset and the
 * round trip, the server's time minus ours. */
static int query(const struct sockaddr *addr, socklen_t len, double *offset, double *delay)
{
	unsigned char req[48] = { 0x23 }, res[48];	/* LI 0, version 4, client */
	int fd = socket(addr->sa_family, SOCK_DGRAM | SOCK_CLOEXEC, 0);
	struct pollfd p = { fd, POLLIN, 0 };
	double t1, t2, t3, t4;
	ssize_t n;

	if (fd < 0)
		return -1;
	t1 = now_real();
	to_ntp(req + 40, t1);
	if (sendto(fd, req, sizeof req, 0, addr, len) != sizeof req ||
	    poll(&p, 1, 2000) != 1 || (n = recv(fd, res, sizeof res, 0)) != sizeof res) {
		close(fd);
		return -1;
	}
	t4 = now_real();
	close(fd);
	/* A server answer, not a kiss of death, and to this request. */
	if ((res[0] & 7) != 4 || res[1] == 0 || res[1] > 15 ||
	    memcmp(res + 24, req + 40, 8))
		return -1;
	t2 = from_ntp(res + 32);
	t3 = from_ntp(res + 40);
	*offset = ((t2 - t1) + (t3 - t4)) / 2;
	*delay = (t4 - t1) - (t3 - t2);
	return *delay >= 0 && *delay < 1.5 ? 0 : -1;
}

/* The best of a few answers from the given servers: the shortest round trip. */
static int measure(const char *const *names, double *offset, char *used, size_t usedlen)
{
	double best = 9, o, d;
	int got = 0;

	for (; *names; names++) {
		struct addrinfo hints = { .ai_socktype = SOCK_DGRAM }, *list, *a;
		int tried = 0;

		if (getaddrinfo(*names, "123", &hints, &list))
			continue;
		for (a = list; a && tried < 2; a = a->ai_next, tried++)
			for (int i = 0; i < 2; i++)
				if (!query(a->ai_addr, a->ai_addrlen, &o, &d) && d < best) {
					best = d;
					*offset = o;
					snprintf(used, usedlen, "%s", *names);
					got = 1;
				}
		freeaddrinfo(list);
		if (got)
			break;
	}
	return got ? 0 : -1;
}

static int set_freq(double ppm)
{
	struct timex t = { .modes = ADJ_FREQUENCY, .freq = (long)(ppm * 65536) };

	if (ppm < -500 || ppm > 500 || adjtimex(&t) < 0)
		return -1;
	put("freq_ppm", "%.2f\n", ppm);
	return 0;
}

static double get_freq(void)
{
	struct timex t = { 0 };

	adjtimex(&t);
	return t.freq / 65536.0;
}

/* Slew only what the kernel slews within a sync interval (it moves at most
 * 500 ppm, 50 ms in 100 s); step anything larger, such as the up to one
 * second the laptop's whole-second `date -s` leaves at boot. */
static void step(double offset)
{
	if (fabs(offset) > 0.05) {
		double t = now_real() + offset;
		struct timeval tv = { (time_t)t, (suseconds_t)((t - floor(t)) * 1e6) };

		settimeofday(&tv, NULL);
	} else {
		struct timeval tv = { (time_t)trunc(offset),
				      (suseconds_t)((offset - trunc(offset)) * 1e6) };

		adjtime(&tv, NULL);
	}
}

/* Learning: the corrections made over an hour or more are the system
 * clock's own error at its current frequency; fold them into the frequency
 * so the clock keeps time between syncs and offline. */
static double anchor = -1, corrected;
static int first = 1;

/* How far the PMU's clock has wandered since the offset was last stored:
 * its counter has one-second steps, so this is coarse. */
static void pmu_check(void)
{
	FILE *p = popen("/usr/sbin/n90-battery clock", "r");
	char line[160];
	long off;
	char *at;

	if (!p)
		return;
	if (fgets(line, sizeof line, p) && (at = strstr(line, "system ")) &&
	    sscanf(at, "system %ld s", &off) == 1) {
		put("pmu_offset_s", "%ld\n", off);
		if (off)
			say("PMU clock %+ld s from network time", -off);
	}
	pclose(p);
}

static int sync_once(const char *const *names)
{
	char used[64] = "";
	double offset, mono = now_mono();

	if (measure(names, &offset, used, sizeof used))
		return -1;
	if (fabs(offset) > 2) {
		anchor = -1;	/* a step, not drift: start learning again */
	} else if (anchor < 0) {
		anchor = mono;	/* errors from here on are the clock's drift */
		corrected = 0;
	} else {
		corrected += offset;
		if (mono - anchor >= 3600) {
			double ppm = get_freq() + corrected / (mono - anchor) * 1e6;

			if (!set_freq(ppm))
				say("system clock off by %.0f ms over %.0f s: frequency now %+.2f ppm",
				    corrected * 1000, mono - anchor, ppm);
			anchor = mono;
			corrected = 0;
		}
	}
	step(offset);
	put("source", "ntp\n");
	put("synced", "%ld\n", (long)time(NULL));
	put("offset_ms", "%.1f\n", offset * 1000);
	put("server", "%s\n", used);
	if (fabs(offset) > 0.05)
		say("%s: off by %.1f ms, corrected", used, offset * 1000);
	if (first || fabs(offset) > 0.5)
		journal("ntp", offset);
	first = 0;
	pmu_check();
	pmu_clock("save");
	return 0;
}

static void serve(void)
{
	int wait = 60;

	if (time(NULL) < PLAUSIBLE) {
		if (!pmu_clock("load")) {
			put("source", "pmu\n");
			say("clock unset: set from the PMU");
			journal("pmu", 0);
		}
	} else if (access(DIR "/source", F_OK)) {
		put("source", "laptop\n");
	}
	say("serving");
	for (;;) {
		if (!sync_once(servers)) {
			wait = 900;
		} else {
			wait = wait < 900 ? wait * 2 : 900;
		}
		sleep(wait);
	}
}

int main(int argc, char **argv)
{
	mkdir(DIR, 0755);
	if (argc > 1 && !strcmp(argv[1], "serve")) {
		serve();
	} else if (argc > 1 && !strcmp(argv[1], "sync")) {
		const char *const *names = argc > 2 ? (const char *const *)argv + 2 : servers;
		int rc = sync_once(names);

		printf(rc ? "no NTP server answered\n" : "synced\n");
		return rc ? 1 : 0;
	} else if (argc > 2 && !strcmp(argv[1], "freq")) {
		return set_freq(atof(argv[2])) ? 1 : 0;
	} else {
		fprintf(stderr, "usage: n90-time sync [SERVER...] | serve | freq PPM\n");
		return 2;
	}
	return 0;
}
