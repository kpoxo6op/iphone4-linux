// SPDX-License-Identifier: GPL-2.0
/*
 * Bring-up probe for the A4 SDIO host (SDHCI at 0x80000000) and the BCM4329.
 * Sends CMD5 by hand so power, clock and reset ordering can be varied
 * without the kernel driver. Unload sdhci-s5l8930 first.
 *
 * Usage: sdio-probe [div] [reset_ms] [after_ms]
 */
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static volatile uint8_t *h;
static volatile uint32_t *gpio, *pmgr;

#define R32(o) (*(volatile uint32_t *)(h + (o)))
#define R16(o) (*(volatile uint16_t *)(h + (o)))
#define R8(o)  (*(volatile uint8_t *)(h + (o)))

static void ms(int n) { usleep(n * 1000); }

static void *map(int fd, off_t base)
{
	void *p = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, base);

	if (p == MAP_FAILED) {
		perror("mmap");
		exit(1);
	}
	return p;
}

static int cmd(int idx, uint32_t arg, int resp, uint32_t *out)
{
	R16(0x30) = 0xffff;
	R16(0x32) = 0xffff;
	for (int i = 0; i < 1000 && (R32(0x24) & 1); i++)
		usleep(100);
	R32(0x08) = arg;
	R32(0x0c) = (uint32_t)((idx << 8) | resp) << 16;
	for (int i = 0; i < 2000; i++) {
		uint16_t s = R16(0x30);

		if (s & 0x8000) {
			uint16_t e = R16(0x32);

			R16(0x30) = 0xffff;
			R16(0x32) = 0xffff;
			R8(0x2f) = 2;	/* reset CMD line */
			for (int j = 0; j < 100 && (R8(0x2f) & 2); j++)
				usleep(100);
			return -e;
		}
		if (s & 1) {
			*out = R32(0x10);
			R16(0x30) = 1;
			return 0;
		}
		usleep(50);
	}
	return -0x10000;
}

int main(int argc, char **argv)
{
	int div = argc > 1 ? atoi(argv[1]) : 60;
	int reset_ms = argc > 2 ? atoi(argv[2]) : 12;
	int after_ms = argc > 3 ? atoi(argv[3]) : 150;
	int fd = open("/dev/mem", O_RDWR | O_SYNC);
	uint32_t r;

	h = map(fd, 0x80000000);
	gpio = map(fd, 0xbfa00000);
	pmgr = map(fd, 0xbf101000);
	pmgr[(0x10 + 0x24 * 4) / 4] |= 0xf;	/* SDIO clock gate */
	ms(1);
	printf("caps %08x state %08x\n", R32(0x40), R32(0x24));
	R8(0x2f) = 1;
	for (int i = 0; i < 100 && (R8(0x2f) & 1); i++)
		ms(1);
	R8(0x29) = getenv("SDIO_PWR") ? strtoul(getenv("SDIO_PWR"), NULL, 0) : 0x0f;
	if (getenv("SDIO_V18"))
		R16(0x3e) |= 8;		/* 1.8 V signalling enable */
	R16(0x2c) = ((div & 0xff) << 8) | (((div >> 8) & 3) << 6) | 1;
	for (int i = 0; i < 100 && !(R16(0x2c) & 2); i++)
		ms(1);
	R16(0x2c) |= 4;			/* SD clock on */
	R8(0x2e) = 0x0e;
	R16(0x34) = 0xffff;		/* status enables */
	R16(0x36) = 0xffff;
	printf("clock %04x power %02x host %02x host2 %04x\n", R16(0x2c), R8(0x29),
	       R8(0x28), R16(0x3e));

	gpio[6] = 0x212;		/* WL_REG_ON low */
	ms(reset_ms);
	gpio[6] = 0x213;
	ms(after_ms);

	for (int t = 0; t < 5; t++) {
		int e = cmd(5, 0, 0x02, &r);

		printf("CMD5 try %d: %s %08x (err %04x) state %08x\n", t,
		       e ? "fail" : "ok", e ? 0 : r, e < 0 ? -e : 0, R32(0x24));
		if (!e)
			break;
		ms(50);
	}
	int e = cmd(0, 0, 0x00, &r);
	printf("CMD0: %d\n", e);
	e = cmd(52, 0x00000c00, 0x1a, &r);	/* read CCCR 0x06 */
	printf("CMD52: %d %08x\n", e, e ? 0 : r);
	return 0;
}
