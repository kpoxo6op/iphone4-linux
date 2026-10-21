// SPDX-License-Identifier: GPL-2.0
/*
 * Userspace bring-up probe for the N90 (iPhone 4) Zephyr2 touch controller.
 *
 * Drives SPI1, the GPIO pins and the PMU directly so the protocol can be
 * proven before it moves into a kernel driver. The wiring comes from Apple's
 * N90 device tree (iOS 7.1.2): SPI1 at 0x82100000, reset GPIO 20, chip
 * select GPIO 49, ATN GPIO 21, power from PMU LDO12 (reg 0x16 bit 1).
 * The protocol follows openiBoot plat-s5l8900/multitouch-z2.c.
 *
 * Usage: z2probe <cmd> [args]
 *   regs                 dump SPI1, pins and PMU state
 *   power <0|1>          switch the touch LDO
 *   atn <ms>             print ATN level transitions for <ms>
 *   boot <fw> [cal]      reset, upload firmware (and calibration), start
 *   run <fw> [cal]       boot, then print finger frames until killed
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define SPI1_BASE 0x82100000
#define GPIO_BASE 0xbfa00000

#define SPI_CTRL   0x00
#define SPI_CFG    0x04
#define SPI_STATUS 0x08
#define SPI_PIN    0x0c
#define SPI_TXDATA 0x10
#define SPI_RXDATA 0x20
#define SPI_CLKDIV 0x30
#define SPI_RXCNT  0x34
#define SPI_TXCNT  0x4c

#define PIN_RESET 20
#define PIN_ATN   21
#define PIN_CS    49

#define PMU_ADDR   0x74
#define PMU_LDO_EN 0x16
#define PMU_LDO12  0x02

static volatile uint32_t *spi, *gpio;
static int i2c = -1;
static int verbose;
static uint32_t base_hz = 24000000;
static uint32_t spi_mode = 0x00;	/* CFG bits 5-6: 0 polled, 0x20 irq */

static uint64_t now_us(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000000ull + ts.tv_nsec / 1000;
}

static void udelay(unsigned int us)
{
	uint64_t end = now_us() + us;

	if (us > 2000) {
		usleep(us);
		return;
	}
	while (now_us() < end)
		;
}

static volatile uint32_t *map(off_t base)
{
	static int fd = -1;
	void *p;

	if (fd < 0)
		fd = open("/dev/mem", O_RDWR | O_SYNC);
	if (fd < 0) {
		perror("/dev/mem");
		exit(1);
	}
	p = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED, fd, base);
	if (p == MAP_FAILED) {
		perror("mmap");
		exit(1);
	}
	return p;
}

#define R(o)    (spi[(o) / 4])
#define W(o, v) (spi[(o) / 4] = (v))

static int pin_get(int pin)
{
	return gpio[pin] & 1;
}

static void pin_out(int pin, int val)
{
	/* openiBoot plat-a4: 0x212 drives low, 0x213 drives high */
	gpio[pin] = 0x212 | (val ? 1 : 0);
}

static int pmu_read(int reg)
{
	uint8_t r = reg;

	if (write(i2c, &r, 1) != 1 || read(i2c, &r, 1) != 1)
		return -1;
	return r;
}

static int pmu_write(int reg, int val)
{
	uint8_t b[2] = { reg, val };

	return write(i2c, b, 2) == 2 ? 0 : -1;
}

static void power(int on)
{
	int v = pmu_read(PMU_LDO_EN);

	if (v < 0) {
		fprintf(stderr, "pmu read failed\n");
		exit(1);
	}
	v = on ? (v | PMU_LDO12) : (v & ~PMU_LDO12);
	pmu_write(PMU_LDO_EN, v);
	printf("pmu 0x16 = 0x%02x\n", pmu_read(PMU_LDO_EN));
}

/* --- SPI1, polled ------------------------------------------------------ */

#define TX_LEVEL(s) (((s) >> 6) & 0x1f)
#define RX_LEVEL(s) (((s) >> 11) & 0x1f)
#define FIFO_DEPTH  16

static void spi_setup(uint32_t hz)
{
	uint32_t div = base_hz / hz;

	if (div < 2)
		div = 2;
	if (div > 0x7ff)
		div = 0x7ff;
	W(SPI_CTRL, 0);
	W(SPI_CLKDIV, div);
	/* master + clock enable, CPHA=1, CPOL=1, 8 bit, NCLK source */
	W(SPI_CFG, 0x18 | (1 << 1) | (1 << 2) | spi_mode | (1 << 14));
	W(SPI_PIN, 2);
}

static int spi_xfer(const uint8_t *tx, uint8_t *rx, int len)
{
	int txi = 0, rxi = 0;
	uint64_t deadline = now_us() + 200000 + len * 200;
	uint32_t st;

	/*
	 * The A4 block only shifts while CTRL.RUN is set: words written to an
	 * idle block are dropped. Enable it, reset both FIFOs, then feed it.
	 */
	W(SPI_CTRL, 1);
	W(SPI_CTRL, 1 | (1 << 2) | (1 << 3));
	W(SPI_STATUS, R(SPI_STATUS));
	W(SPI_TXCNT, len);
	W(SPI_RXCNT, rx ? len : 0);
	W(SPI_CTRL, 1);

	while (rx ? rxi < len : 1) {
		st = R(SPI_STATUS);
		int room = FIFO_DEPTH - TX_LEVEL(st);

		/* never let unread RX words exceed the FIFO */
		if (rx && room > FIFO_DEPTH - (txi - rxi) - RX_LEVEL(st))
			room = FIFO_DEPTH - (txi - rxi) - RX_LEVEL(st);

		while (room-- > 0 && txi < len)
			W(SPI_TXDATA, tx ? tx[txi++] : (txi++, 0));
		if (rx) {
			int n = RX_LEVEL(st);

			while (n-- > 0 && rxi < len)
				rx[rxi++] = R(SPI_RXDATA);
		} else if (txi >= len && TX_LEVEL(st) == 0) {
			break;
		}
		if (now_us() > deadline) {
			fprintf(stderr, "spi timeout tx %d/%d rx %d/%d status 0x%08x\n",
				txi, len, rxi, len, st);
			W(SPI_CTRL, 0);
			return -1;
		}
	}
	/* let the last word leave the shifter */
	deadline = now_us() + 20000;
	while (!(R(SPI_STATUS) & 0x400002) && now_us() < deadline && !rx)
		;
	W(SPI_STATUS, R(SPI_STATUS));
	if (getenv("Z2_SPI_OFF"))
		W(SPI_CTRL, 0);
	return len;
}

struct speed { uint32_t hz; unsigned int tx_delay, rx_delay; };
static const struct speed normal = { 83000, 5000, 10000 };
static const struct speed fast = { 4500000, 0, 10000 };

static uint64_t last_xfer;
static int fw_running;

static int raw_txrx(const struct speed *s, const uint8_t *tx, uint8_t *rx, int len);

static int mt_txrx(const struct speed *s, const uint8_t *tx, uint8_t *rx, int len)
{
	/* AppleMultitouchN1SPI: wake the firmware after 100 ms of silence */
	if (fw_running && now_us() - last_xfer > 100000) {
		uint8_t w[16] = { 0xee }, wr[16];

		w[14] = 0xee;
		raw_txrx(&normal, w, wr, 16);
		udelay(2000);
	}
	return raw_txrx(s, tx, rx, len);
}

static int raw_txrx(const struct speed *s, const uint8_t *tx, uint8_t *rx, int len)
{
	int ret;

	spi_setup(s->hz);
	pin_out(PIN_CS, 0);
	udelay(rx ? s->rx_delay : s->tx_delay);
	ret = spi_xfer(tx, rx, len);
	pin_out(PIN_CS, 1);
	last_xfer = now_us();
	if (verbose > 1 && rx) {
		printf("  tx");
		for (int i = 0; i < len && i < 16; i++)
			printf(" %02x", tx[i]);
		printf("\n  rx");
		for (int i = 0; i < len && i < 16; i++)
			printf(" %02x", rx[i]);
		printf("\n");
	}
	return ret;
}

/* --- ATN --------------------------------------------------------------- */

/* ATN is active low (asserted = 0); learned from the level probe. */
static int atn_active_level;

static int wait_atn(unsigned int timeout_us)
{
	uint64_t end = now_us() + timeout_us;

	while (pin_get(PIN_ATN) != atn_active_level)
		if (now_us() > end)
			return 0;
	return 1;
}

static void atn_trace(int ms)
{
	uint64_t start = now_us(), end = start + ms * 1000ull;
	int last = pin_get(PIN_ATN);

	printf("atn start %d\n", last);
	while (now_us() < end) {
		int v = pin_get(PIN_ATN);

		if (v != last) {
			printf("atn %d at %llu us\n", v,
			       (unsigned long long)(now_us() - start));
			last = v;
		}
	}
}

/* --- Zephyr2 bootloader ------------------------------------------------ */

static uint16_t hbpp_ack(unsigned int timeout_us)
{
	uint8_t tx[2] = { 0x1a, 0xa1 }, rx[2];

	if (!wait_atn(timeout_us))
		return 0xffff;
	mt_txrx(&normal, tx, rx, 2);
	return rx[0] << 8 | rx[1];
}

static uint32_t hbpp_long_ack(void)
{
	uint8_t tx[8] = { 0x1a, 0xa1, 0x18, 0xe1, 0x18, 0xe1, 0x18, 0xe1 }, rx[8];

	if (!wait_atn(100000))
		return 0xffffffff;
	mt_txrx(&normal, tx, rx, 8);
	return (rx[2] << 8) | rx[3] | (rx[4] << 24) | (rx[5] << 16);
}

static int make_data_packet(uint8_t *out, uint32_t addr, const uint8_t *data, int len)
{
	uint32_t sum = 0;
	int i;

	out[0] = 0x30;
	out[1] = 0x01;
	out[2] = ((len >> 2) >> 10) & 0xff;
	out[3] = (len >> 2) & 0xff;
	out[4] = (addr >> 8) & 0xff;
	out[5] = addr & 0xff;
	out[6] = (addr >> 24) & 0xff;
	out[7] = (addr >> 16) & 0xff;
	for (i = 2; i < 8; i++)
		sum += out[i];
	out[8] = (sum >> 8) & 0xff;
	out[9] = sum & 0xff;
	for (i = 0; i < len; i += 4) {
		out[10 + i + 0] = data[i + 1];
		out[10 + i + 1] = data[i + 0];
		out[10 + i + 2] = data[i + 3];
		out[10 + i + 3] = data[i + 2];
	}
	sum = 0;
	for (i = 10; i < len + 10; i++)
		sum += out[i];
	out[len + 10] = (sum >> 8) & 0xff;
	out[len + 11] = sum & 0xff;
	out[len + 12] = (sum >> 24) & 0xff;
	out[len + 13] = (sum >> 16) & 0xff;
	return len + 14;
}

static int upload_blob(uint32_t addr, const uint8_t *data, int len, const char *what)
{
	uint8_t pkt[0x400 + 16];
	uint8_t chunk[0x3f0];

	while (len > 0) {
		int n = len > 0x3f0 ? 0x3f0 : len;
		int try;

		memset(chunk, 0, sizeof(chunk));
		memcpy(chunk, data, n);
		n = (n + 3) & ~3;
		pkt[0] = 0x18;
		pkt[1] = 0xe1;
		make_data_packet(pkt + 2, addr, chunk, n);
		for (try = 0; try < 5; try++) {
			mt_txrx(&fast, pkt, NULL, n + 16);
			uint16_t a = hbpp_ack(100000);

			if (a == 0x4bc1)
				break;
			printf("%s ack 0x%04x\n", what, a);
		}
		if (try == 5)
			return -1;
		addr += n;
		data += n;
		len -= n;
	}
	return 0;
}

static uint32_t read_reg(uint32_t addr)
{
	uint8_t tx[8], rx[8];
	uint32_t sum = 0;

	tx[0] = 0x1c;
	tx[1] = 0x73;
	tx[2] = (addr >> 8) & 0xff;
	tx[3] = addr & 0xff;
	tx[4] = (addr >> 24) & 0xff;
	tx[5] = (addr >> 16) & 0xff;
	for (int i = 2; i < 6; i++)
		sum += tx[i];
	tx[6] = (sum >> 8) & 0xff;
	tx[7] = sum & 0xff;
	mt_txrx(&normal, tx, rx, 8);
	return hbpp_long_ack();
}

static int write_reg(uint32_t addr, uint32_t value, uint32_t mask)
{
	uint8_t tx[16], rx[16];
	uint32_t sum = 0;

	tx[0] = 0x1e;
	tx[1] = 0x33;
	tx[2] = (addr >> 8) & 0xff;
	tx[3] = addr & 0xff;
	tx[4] = (addr >> 24) & 0xff;
	tx[5] = (addr >> 16) & 0xff;
	tx[6] = (mask >> 8) & 0xff;
	tx[7] = mask & 0xff;
	tx[8] = (mask >> 24) & 0xff;
	tx[9] = (mask >> 16) & 0xff;
	tx[10] = (value >> 8) & 0xff;
	tx[11] = value & 0xff;
	tx[12] = (value >> 24) & 0xff;
	tx[13] = (value >> 16) & 0xff;
	for (int i = 2; i < 14; i++)
		sum += tx[i];
	tx[14] = (sum >> 8) & 0xff;
	tx[15] = sum & 0xff;
	mt_txrx(&normal, tx, rx, 16);
	return hbpp_ack(100000) == 0x4ad1;
}

static void put_sum16(uint8_t *b, int n)
{
	uint32_t sum = 0;

	for (int i = 0; i < n; i++)
		sum += b[i];
	b[n] = sum & 0xff;
	b[n + 1] = (sum >> 8) & 0xff;
}

static int sum16_ok(const uint8_t *b, int n)
{
	uint32_t sum = 0;

	for (int i = 0; i < n; i++)
		sum += b[i];
	return (b[n] | b[n + 1] << 8) == (sum & 0xffff);
}

static int interface_version, max_packet = 1000;

static int get_interface_version(void)
{
	uint8_t tx[16] = { 0xe2 }, rx[16];

	put_sum16(tx, 14);
	mt_txrx(&normal, tx, rx, 16);
	for (int t = 0; t < 4; t++) {
		mt_txrx(&normal, tx, rx, 16);
		if (rx[0] == 0xe2 && sum16_ok(rx, 14)) {
			interface_version = rx[2];
			max_packet = rx[4] << 8 | rx[3];
			printf("interface version %d, max packet %d\n",
			       interface_version, max_packet);
			return 0;
		}
		udelay(3000);
	}
	return -1;
}

static int get_report(int id, uint8_t *buf, int *outlen)
{
	uint8_t tx[0x200], rx[0x200];
	int len = -1;

	for (int t = 0; t < 4 && len < 0; t++) {
		memset(tx, 0, 16);
		tx[0] = 0xe3;
		tx[1] = id;
		put_sum16(tx, 14);
		mt_txrx(&normal, tx, rx, 16);
		udelay(25);
		mt_txrx(&normal, tx, rx, 16);
		if (rx[0] == 0xe3 && sum16_ok(rx, 14) && !rx[2])
			len = rx[4] << 8 | rx[3];
	}
	if (len < 0 || len > 0x1f0)
		return -1;

	for (int t = 0; t < 4; t++) {
		uint32_t sum = 0;

		memset(tx, 0, sizeof(tx));
		tx[0] = len < 12 ? 0xe6 : 0xe7;
		tx[1] = id;
		tx[3] = len & 0xff;
		tx[4] = len >> 8;
		for (int i = 0; i < 5; i++)
			sum += tx[i];
		tx[14] = sum & 0xff;
		tx[15] = sum >> 8;
		mt_txrx(&normal, tx, rx, 16);
		udelay(25);
		tx[2] = 1;
		if (len < 12) {
			mt_txrx(&normal, tx, rx, 16);
			if (!sum16_ok(rx, 14))
				continue;
		} else {
			tx[14] = tx[15] = 0;
			tx[3 + len] = sum & 0xff;
			tx[4 + len] = sum >> 8;
			mt_txrx(&normal, tx, rx, len + 5);
			if (!sum16_ok(rx, len + 3))
				continue;
		}
		memcpy(buf, rx + 3, len);
		*outlen = len;
		return 0;
	}
	return -1;
}

static int flip_nop, cur_nop = 1;
static int sensor_w = 1, sensor_h = 1;

static uint8_t *load(const char *path, int *len)
{
	FILE *f = fopen(path, "rb");
	uint8_t *buf;

	if (!f) {
		perror(path);
		exit(1);
	}
	fseek(f, 0, SEEK_END);
	*len = ftell(f);
	rewind(f);
	buf = malloc(*len + 4);
	if (fread(buf, 1, *len, f) != (size_t)*len) {
		perror(path);
		exit(1);
	}
	fclose(f);
	return buf;
}

static int boot(const char *fw_path, const char *cal_path)
{
	int fw_len, i;
	uint8_t *fw = load(fw_path, &fw_len);
	uint8_t rep[0x200];
	int rlen;

	power(1);
	udelay(15000);
	for (i = 0; i < 4; i++) {
		pin_out(PIN_RESET, 0);
		udelay(200000);
		/*
		 * AppleMultitouchZ2SPI::resetDevice(): "ensuring S_CLK is high"
		 * with a dummy HBPP transfer before reset is released.
		 */
		if (!getenv("Z2_NO_REQ_WAKEUP")) {
			/* AppleMultitouchN1SPI power-on: REQ_WAKEUP, then 10 ms */
			uint8_t q[2] = { 0x19, 0xc1 }, qr[2];

			raw_txrx(&normal, q, qr, 2);
			udelay(10000);
		}
		{
			uint8_t d[16] = { 0x1a, 0xa1 }, dr[16];

			for (int k = 2; k < 16; k += 2)
				d[k] = 0x18, d[k + 1] = 0xe1;
			raw_txrx(&normal, d, dr, 16);
		}
		/* iOS N90 personality: reset-deassert-high-z, 15 ms delay */
		gpio[PIN_RESET] = 0x210;
		udelay(15000);
		/* drain acks until the bootloader goes quiet */
		while (hbpp_ack(1000) != 0xffff)
			;
		mt_txrx(&fast, fw, NULL, fw_len);
		uint16_t a = hbpp_ack(200000);

		printf("firmware upload %d: ack 0x%04x\n", i, a);
		if (a == 0x4bc1)
			break;
	}
	if (i == 4)
		return -1;

	if (cal_path) {
		int cal_len;
		uint8_t *cal = load(cal_path, &cal_len);

		if (upload_blob(0x400200, cal, cal_len, "cal"))
			return -1;
		printf("calibration %d bytes loaded\n", cal_len);
	}

	/*
	 * MTSPIBootloader_N1::performCalibSeq() from the iOS 7.1.2 N90
	 * AppleMultitouchSPI kext, with its default register addresses.
	 */
	uint32_t ver = read_reg(0x10008ffc);

	printf("n1 version 0x%08x\n", ver);
	if (getenv("Z2_PEEK")) {
		char *e = getenv("Z2_PEEK");

		while (*e) {
			uint32_t a = strtoul(e, &e, 0);

			printf("peek 0x%08x = 0x%08x\n", a, read_reg(a));
			while (*e == ',')
				e++;
		}
	}
	if (!getenv("Z2_NO_N1REGS"))
	printf("n1 regs: %d %d %d %d\n",
	       write_reg(0x1000300c, 0x16e4, 0xffffffff),
	       write_reg(0x1000305c, 0x20, 0xffffffff),
	       write_reg(0x10003058, 6, 0xffffffff),
	       write_reg(0x10003000, ver == 0x434d11a0 ? 2 : 3, 0xffffffff));
	printf("SPI_APU_EN 0x%08x\n", read_reg(0x10003800));

	uint8_t tx[12] = { 0x1f, 0x01 }, rx[12];

	if (!getenv("Z2_NO_CALSEQ"))
		mt_txrx(&normal, tx, rx, 2);
	udelay(65000);
	{
		uint8_t at[2] = { 0x1a, 0xa1 }, ar[2];

		printf("atn after calibrate %d\n", pin_get(PIN_ATN));
		raw_txrx(&normal, at, ar, 2);
		printf("calibration ack (no wait) 0x%02x%02x\n", ar[0], ar[1]);
	}

	uint8_t ex[12] = { 0x1d, 0x53, 0x18, 0x00, 0x10, 0x00, 0x00, 0x01, 0x00, 0x00 };
	uint32_t sum = 0;

	for (i = 2; i < 10; i++)
		sum += ex[i];
	ex[10] = (sum >> 8) & 0xff;
	ex[11] = sum & 0xff;
	mt_txrx(&normal, ex, rx, 12);
	printf("execute rx %02x %02x %02x %02x\n", rx[0], rx[1], rx[2], rx[3]);
	udelay(40000);
	if (getenv("Z2_PEEK2")) {
		char *e = getenv("Z2_PEEK2");
		int keep = fw_running;

		fw_running = 0;
		while (*e) {
			uint32_t a = strtoul(e, &e, 0);

			printf("post-exec peek 0x%08x = 0x%08x\n", a, read_reg(a));
			while (*e == ',')
				e++;
		}
		fw_running = keep;
	}
	if (getenv("Z2_TRACE_AFTER_EXEC"))
		atn_trace(atoi(getenv("Z2_TRACE_AFTER_EXEC")));
	udelay(1000);

	fw_running = 1;
	if (getenv("Z2_TB"))
		return 0;
	if (get_interface_version())
		return -1;
	if (!get_report(0xd1, rep, &rlen))
		printf("family id 0x%x\n", rep[0]);
	if (!get_report(0xd3, rep, &rlen)) {
		int bcd = rep[3] << 8 | rep[4];

		printf("sensor rows %d cols %d bcd 0x%x endian %d\n",
		       rep[1], rep[2], bcd, rep[0]);
		flip_nop = bcd > 0x23;
	}
	if (!get_report(0xd9, rep, &rlen)) {
		uint32_t w, h;

		memcpy(&w, rep, 4);
		memcpy(&h, rep + 4, 4);
		printf("sensor dimensions raw %u x %u (%d bytes)\n", w, h, rlen);
		sensor_w = w;
		sensor_h = h;
	}
	return 0;
}

static int read_frame(void)
{
	uint8_t tx[0x200], rx[0x200];
	int len;

	memset(tx, 0, 16);
	tx[0] = flip_nop ? 0xeb : 0xea;
	tx[1] = cur_nop;
	put_sum16(tx, 14);
	mt_txrx(&normal, tx, rx, 16);
	if (!sum16_ok(rx, 14))
		return -1;
	len = rx[1] | rx[2] << 8;
	if (len) {
		len += 5;
		if (len > 0x200)
			len = 0x200;
		memset(tx, 0, len);
		tx[0] = flip_nop ? 0xeb : 0xea;
		tx[1] = cur_nop;
		tx[2] = 1;
		uint32_t sum = 0;

		for (int i = 0; i < 14; i++)
			sum += tx[i];
		tx[len - 2] = sum & 0xff;
		tx[len - 1] = sum >> 8;
		mt_txrx(&normal, tx, rx, len);
		int plen = rx[2] | rx[3] << 8;

		if (plen > 2 && rx[5 + 18] > 0) {
			const uint8_t *h = rx + 5;
			int nf = h[18], flen = h[19];
			const uint8_t *f = h + h[2];

			printf("frame %3d fingers %d:", h[1], nf);
			for (int i = 0; i < nf; i++, f += flen) {
				int16_t x = f[4] | f[5] << 8, y = f[6] | f[7] << 8;

				printf(" [id %d ev %d x %d y %d]", f[0], f[1], x, y);
			}
			printf("\n");
			fflush(stdout);
		}
	}
	if (flip_nop)
		cur_nop = cur_nop == 1 ? 2 : 1;
	return 0;
}

/* Touch Bar style read (mainline apple_z2.c): 0xEB length, then payload. */
static int tb_parity;

static int tb_read(int dump)
{
	uint8_t tx[0x1000], rx[0x1000];
	int len;

	memset(tx, 0, 16);
	tx[0] = 0xeb;
	tx[1] = tb_parity + 1;
	tx[14] = (0xeb + tx[1]) & 0xff;
	tx[15] = (0xeb + tx[1]) >> 8;
	tb_parity = !tb_parity;
	mt_txrx(&normal, tx, rx, 16);
	len = ((rx[1] | rx[2] << 8) + 8) & ~3;
	if (dump) {
		printf("len hdr:");
		for (int i = 0; i < 16; i++)
			printf(" %02x", rx[i]);
		printf("\n");
	}
	if (len <= 8 || len > 0x1000)
		return -1;
	memset(tx, 0, len);
	mt_txrx(&normal, tx, rx, len);
	printf("pkt %d:", len);
	for (int i = 0; i < len && i < (dump ? 96 : 48); i++)
		printf(" %02x", rx[i]);
	printf("\n");
	fflush(stdout);
	return 0;
}

static void regs(void)
{
	printf("spi1 ctrl %08x cfg %08x status %08x pin %08x clkdiv %08x\n",
	       R(SPI_CTRL), R(SPI_CFG), R(SPI_STATUS), R(SPI_PIN), R(SPI_CLKDIV));
	printf("pins reset %03x atn %03x cs %03x\n",
	       gpio[PIN_RESET], gpio[PIN_ATN], gpio[PIN_CS]);
	printf("pmu 0x16 %02x 0x50 %02x\n", pmu_read(0x16), pmu_read(0x50));
}

int main(int argc, char **argv)
{
	if (argc < 2)
		return 2;
	if (getenv("Z2_VERBOSE"))
		verbose = atoi(getenv("Z2_VERBOSE"));
	if (getenv("Z2_BASE_HZ"))
		base_hz = atoi(getenv("Z2_BASE_HZ"));
	if (getenv("Z2_SPI_MODE"))
		spi_mode = strtoul(getenv("Z2_SPI_MODE"), NULL, 0);
	if (getenv("Z2_ATN_ACTIVE"))
		atn_active_level = atoi(getenv("Z2_ATN_ACTIVE"));
	spi = map(SPI1_BASE);
	gpio = map(GPIO_BASE);
	i2c = open("/dev/i2c-0", O_RDWR);
	if (i2c < 0 || ioctl(i2c, I2C_SLAVE_FORCE, PMU_ADDR) < 0) {
		perror("i2c");
		return 1;
	}

	if (!strcmp(argv[1], "regs")) {
		regs();
	} else if (!strcmp(argv[1], "power") && argc > 2) {
		power(atoi(argv[2]));
	} else if (!strcmp(argv[1], "reset")) {
		pin_out(PIN_CS, 1);
		pin_out(PIN_RESET, 0);
		udelay(200000);
		pin_out(PIN_RESET, 1);
		atn_trace(argc > 2 ? atoi(argv[2]) : 500);
	} else if (!strcmp(argv[1], "atn")) {
		atn_trace(argc > 2 ? atoi(argv[2]) : 1000);
	} else if (!strcmp(argv[1], "ack")) {
		printf("ack 0x%04x\n", hbpp_ack(100000));
	} else if (!strcmp(argv[1], "xfer")) {
		/* xfer <hz> <hex bytes...>: raw transfer, prints rx */
		uint8_t tx[64], rx[64];
		int n = 0;
		struct speed s = { atoi(argv[2]), 0, 0 };

		for (int i = 3; i < argc && n < 64; i++)
			tx[n++] = strtoul(argv[i], NULL, 16);
		uint64_t t0 = now_us();

		mt_txrx(&s, tx, rx, n);
		printf("%llu us:", (unsigned long long)(now_us() - t0));
		for (int i = 0; i < n; i++)
			printf(" %02x", rx[i]);
		printf("\n");
	} else if (!strcmp(argv[1], "dbg")) {
		/* dbg <ctrl-reset> <txcnt> <rxcnt>: watch status during a 4 byte run */
		uint32_t seen[64];
		int ns = 0;

		spi_setup(argc > 5 ? atoi(argv[5]) : 83000);
		W(SPI_CTRL, strtoul(argv[2], NULL, 0));
		W(SPI_TXCNT, strtoul(argv[3], NULL, 0));
		W(SPI_RXCNT, strtoul(argv[4], NULL, 0));
		int nw = argc > 6 ? atoi(argv[6]) : 4;

		for (int i = 0; i < nw; i++)
			W(SPI_TXDATA, 0x1a + i);
		printf("before run status %08x\n", R(SPI_STATUS));
		W(SPI_CTRL, 1);
		uint64_t t0 = now_us(), end = t0 + 30000;
		uint32_t last = ~0u, when[64];

		while (now_us() < end && ns < 64) {
			uint32_t s = R(SPI_STATUS);

			if (s != last)
				when[ns] = now_us() - t0, seen[ns++] = s, last = s;
		}
		for (int i = 0; i < ns; i++)
			printf("%6u us status %08x\n", when[i], seen[i]);
		for (int i = 0; i < 6; i++)
			printf("rx %08x status %08x\n", R(SPI_RXDATA), R(SPI_STATUS));
		for (int o = 0; o < 0x60; o += 4)
			printf("%02x:%08x%c", o, spi[o / 4], (o % 32) == 28 ? '\n' : ' ');
		printf("\n");
		W(SPI_CTRL, 0);
	} else if (!strcmp(argv[1], "boot") && argc > 2) {
		pin_out(PIN_CS, 1);
		return boot(argv[2], argc > 3 ? argv[3] : NULL) ? 1 : 0;
	} else if (!strcmp(argv[1], "tb") && argc > 2) {
		int n = argc > 3 ? atoi(argv[3]) : 20;

		setenv("Z2_TB", "1", 1);
		pin_out(PIN_CS, 1);
		if (boot(argv[2], NULL))
			return 1;
		while (n-- > 0) {
			if (wait_atn(3000000))
				tb_read(1);
			else
				printf("no atn\n");
		}
	} else if (!strcmp(argv[1], "poke") && argc > 2) {
		/* poke <fw> <hex bytes...>: boot (TB mode), then send one 16 byte cmd */
		uint8_t tx[16] = { 0 }, rx[16];
		int n = 0;

		setenv("Z2_TB", "1", 1);
		pin_out(PIN_CS, 1);
		if (boot(argv[2], getenv("Z2_CAL")))
			return 1;
		usleep(atoi(getenv("Z2_WAIT") ? getenv("Z2_WAIT") : "100") * 1000);
		printf("atn %d\n", pin_get(PIN_ATN));
		for (int i = 3; i < argc && n < 14; i++)
			tx[n++] = strtoul(argv[i], NULL, 16);
		put_sum16(tx, 14);
		for (int k = 0; k < 4; k++) {
			if (getenv("Z2_POKE_WAKE")) {
				uint8_t w[16] = { 0 }, wr[16];

				for (int i = 0; i < 14 && getenv("Z2_POKE_WAKE")[2 * i]; i++)
					sscanf(getenv("Z2_POKE_WAKE") + 2 * i, "%2hhx", &w[i]);
				put_sum16(w, 14);
				raw_txrx(&normal, w, wr, 16);
				printf("wk");
				for (int i = 0; i < 16; i++)
					printf(" %02x", wr[i]);
				printf("\n");
				udelay(2000);
			}
			raw_txrx(&normal, tx, rx, 16);
			printf("rx");
			for (int i = 0; i < 16; i++)
				printf(" %02x", rx[i]);
			printf("  atn %d\n", pin_get(PIN_ATN));
		}
	} else if (!strcmp(argv[1], "seq") && argc > 3) {
		/*
		 * seq <fw> <step>...: boot, then run steps. A step is hex bytes
		 * ("19c1"), "w<ms>" to wait, or hex ending in "+" for a 16 byte
		 * frame with the 16 bit sum in bytes 14-15.
		 */
		setenv("Z2_TB", "1", 1);
		pin_out(PIN_CS, 1);
		if (boot(argv[2], getenv("Z2_CAL")))
			return 1;
		for (int a = 3; a < argc; a++) {
			uint8_t tx[64] = { 0 }, rx[64];
			int n = 0, sum = 0;
			const char *p = argv[a];

			if (p[0] == 'W') {
				/* W<addr>=<val>: HBPP register write, all bits */
				uint32_t ad = strtoul(p + 1, (char **)&p, 0);
				uint32_t v = strtoul(p + 1, NULL, 0);

				printf("write 0x%08x = 0x%08x -> %d\n", ad, v,
				       write_reg(ad, v, 0xffffffff));
				continue;
			}
			if (p[0] == 'R') {
				uint32_t ad = strtoul(p + 1, NULL, 0);

				printf("read 0x%08x = 0x%08x\n", ad, read_reg(ad));
				continue;
			}
			if (p[0] == 'w') {
				usleep(atoi(p + 1) * 1000);
				continue;
			}
			while (p[0] && p[1] && p[0] != '+' && n < 64) {
				sscanf(p, "%2hhx", &tx[n++]);
				p += 2;
			}
			if (*p == '+') {
				put_sum16(tx, 14);
				n = 16;
				sum = 1;
			}
			raw_txrx(&normal, tx, rx, n);
			printf("%s%s ->", argv[a], sum ? "" : "");
			for (int i = 0; i < n; i++)
				printf(" %02x", rx[i]);
			printf("  atn %d\n", pin_get(PIN_ATN));
		}
	} else if (!strcmp(argv[1], "run") && argc > 2) {
		pin_out(PIN_CS, 1);
		if (boot(argv[2], argc > 3 ? argv[3] : NULL))
			return 1;
		for (;;) {
			if (wait_atn(1000000))
				read_frame();
		}
	} else {
		return 2;
	}
	return 0;
}
