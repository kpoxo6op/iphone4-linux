// SPDX-License-Identifier: GPL-2.0
/*
 * Userspace keeper for the A4 watchdog, until the kernel driver is in the DTB.
 *
 * The timer block at 0xbf102000 has a watchdog at +0x20: CUR_TIME counts at
 * 24 MHz, the SoC resets when it reaches BITE_TIME while CTRL bit 2 is set,
 * and writing 0 to CUR_TIME restarts the count. Linux's s5l8930 reboot uses
 * the same registers. A frozen kernel stops this process, the count reaches
 * the bite, and the phone resets into DFU, where the boot watcher brings it
 * back.
 *
 * SIGTERM (a deploy replacing the binary, or init stopping everything for a
 * reboot) leaves a final 30 s count instead of disarming. A reboot normally
 * resets the SoC long before that; on 22 October one hung in
 * device_shutdown() on a lock a crashed driver probe still held, and with
 * the watchdog disarmed nothing could reset the phone. A new kicker re-arms
 * with the full timeout. SIGUSR1 disarms it, for work that needs no watchdog.
 *
 * Usage: n90-wdt [timeout_s] [kick_s]
 */
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

#define TIMER_BASE 0xbf102000
#define WD_CUR  (0x20 / 4)
#define WD_BITE (0x24 / 4)
#define WD_CTRL (0x2c / 4)
#define RESET_EN 4

#define FINAL_S 30

static volatile uint32_t *regs;
static volatile sig_atomic_t stopping, disarm;

static void on_signal(int s)
{
	disarm = s == SIGUSR1;
	stopping = 1;
}

int main(int argc, char **argv)
{
	unsigned timeout = argc > 1 ? atoi(argv[1]) : 60;
	unsigned kick = argc > 2 ? atoi(argv[2]) : 10;
	int fd = open("/dev/mem", O_RDWR | O_SYNC);
	struct sched_param sp = { .sched_priority = 50 };

	if (timeout < 5 || timeout > 170 || kick == 0 || kick >= timeout) {
		fprintf(stderr, "timeout 5..170 s, kick below timeout\n");
		return 2;
	}
	if (fd < 0) {
		perror("/dev/mem");
		return 1;
	}
	regs = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, TIMER_BASE);
	if (regs == MAP_FAILED) {
		perror("mmap");
		return 1;
	}
	signal(SIGTERM, on_signal);
	signal(SIGINT, on_signal);
	signal(SIGUSR1, on_signal);
	if (sched_setscheduler(0, SCHED_FIFO, &sp))
		perror("SCHED_FIFO");
	regs[WD_CTRL] = 0;
	regs[WD_BITE] = timeout * 24000000u;
	regs[WD_CUR] = 0;
	regs[WD_CTRL] = RESET_EN;
	fprintf(stderr, "watchdog armed: %u s, kicked every %u s\n", timeout, kick);
	while (!stopping) {
		regs[WD_CUR] = 0;
		sleep(kick);
	}
	if (disarm) {
		regs[WD_CTRL] = 0;
		fprintf(stderr, "watchdog disarmed\n");
		return 0;
	}
	regs[WD_CTRL] = 0;
	regs[WD_BITE] = FINAL_S * 24000000u;
	regs[WD_CUR] = 0;
	regs[WD_CTRL] = RESET_EN;
	fprintf(stderr, "watchdog left armed: reset in %d s unless a new kicker starts\n",
		FINAL_S);
	return 0;
}
