// SPDX-License-Identifier: GPL-2.0
/*
 * Battery and charger readings for the N90 (iPhone 4) from the Dialog D1815
 * PMU at I2C address 0x74, through /dev/i2c-0.
 *
 * Register contract from openiBoot plat-a4/pmu.c: power supply in 0x07
 * (0x08 USB, 0x10 FireWire); ADC mux 0x30 (channel | 0x10 starts a
 * conversion; channel 3 first needs 0x20 and 80 ms), done flag 0x20 in 0x02,
 * 12-bit result in 0x31 (low nibble) and 0x32 (high byte). The channel names
 * come from AppleD1815PMU's sensor table in the iOS 7.1.2 kernelcache:
 * 0 vcc_main, 1 ich, 2 tbat, 4 vbat, 5 ibat, 7 adc_in7, 11-14 tdev1-4,
 * 15 vbus. The scale of each channel is not known yet: `probe` prints raw
 * values so they can be matched against a meter or the gas gauge.
 *
 * Usage: n90-battery <cmd>
 *   probe            print the supply register and every ADC channel
 *   serve [dir]      publish readings every 10 s as power_supply-style
 *                    files under dir (default /run/power_supply)
 *
 * serve needs N90_VBAT_UV_PER_COUNT (microvolts per count, from probe) and
 * optionally N90_VBAT_OFFSET_UV, and N90_ICH_CHARGING_COUNTS for the charge
 * current above which the battery counts as charging. Without them it
 * publishes the supply and raw counts only, never an invented voltage,
 * percentage or charge state.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define PMU_ADDR        0x74
#define PMU_EVENT       0x02
#define PMU_SUPPLY      0x07
#define PMU_ADC_MUX     0x30
#define PMU_ADC_LOW     0x31
#define PMU_SUPPLY_USB  0x08
#define PMU_SUPPLY_FW   0x10
#define ADC_DONE        0x20
#define ADC_START       0x10
#define ADC_VBAT        4
#define ADC_ICH         1

static int i2c = -1;

/* One combined write-then-read transfer, so other PMU users (the backlight
 * driver, n90-touch) cannot move the register pointer in between. */
static int pmu_read_n(int reg, uint8_t *out, int n)
{
	uint8_t r = reg;
	struct i2c_msg msgs[2] = {
		{ .addr = PMU_ADDR, .flags = 0, .len = 1, .buf = &r },
		{ .addr = PMU_ADDR, .flags = I2C_M_RD, .len = n, .buf = out },
	};
	struct i2c_rdwr_ioctl_data data = { .msgs = msgs, .nmsgs = 2 };

	return ioctl(i2c, I2C_RDWR, &data) == 2 ? 0 : -1;
}

static int pmu_read(int reg)
{
	uint8_t v;

	return pmu_read_n(reg, &v, 1) ? -1 : v;
}

static int pmu_write(int reg, int val)
{
	uint8_t b[2] = { reg, val };
	struct i2c_msg msg = { .addr = PMU_ADDR, .flags = 0, .len = 2, .buf = b };
	struct i2c_rdwr_ioctl_data data = { .msgs = &msg, .nmsgs = 1 };

	return ioctl(i2c, I2C_RDWR, &data) == 1 ? 0 : -1;
}

static void msleep(int ms)
{
	struct timespec t = { ms / 1000, (ms % 1000) * 1000000L };

	nanosleep(&t, NULL);
}

/* openiBoot query_adc(), returning the 12-bit count or -1. */
static int adc(int channel)
{
	uint8_t v[2];
	int mux = channel & 0xf, i, ok = 0;

	pmu_read(PMU_EVENT);
	if (channel == 3) {
		pmu_write(PMU_ADC_MUX, mux | 0x20);
		msleep(80);
		mux |= 0x20;
	}
	if (pmu_write(PMU_ADC_MUX, mux | ADC_START))
		return -1;
	for (i = 0; i < 50 && !ok; i++) {
		int event;

		msleep(1);
		event = pmu_read(PMU_EVENT);
		ok = event >= 0 && (event & ADC_DONE);
	}
	if (!ok || pmu_read_n(PMU_ADC_LOW, v, 2)) {
		pmu_write(PMU_ADC_MUX, 0);
		return -1;
	}
	pmu_write(PMU_ADC_MUX, 0);
	return (v[1] << 4) | (v[0] & 0xf);
}

static void probe(void)
{
	int supply = pmu_read(PMU_SUPPLY), c, n;

	printf("supply 0x07 = 0x%02x (%s)\n", supply,
	       supply < 0 ? "read failed" :
	       supply & PMU_SUPPLY_USB ? "USB" :
	       supply & PMU_SUPPLY_FW ? "FireWire" : "battery");
	printf("gpmem 0x80-0x8f:");
	for (c = 0x80; c <= 0x8f; c++)
		printf(" %02x", pmu_read(c) & 0xff);
	printf("\n");
	for (n = 0; n < 3; n++) {
		printf("adc pass %d:", n);
		for (c = 0; c < 16; c++)
			printf(" %d=%d", c, adc(c));
		printf("\n");
		fflush(stdout);
		msleep(500);
	}
}

static void put(const char *dir, const char *name, const char *fmt, long value)
{
	char path[256], tmp[256], text[64];
	int fd, n;

	snprintf(path, sizeof path, "%s/%s", dir, name);
	snprintf(tmp, sizeof tmp, "%s/.%s", dir, name);
	n = snprintf(text, sizeof text, fmt, value);
	fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0)
		return;
	if (write(fd, text, n) == n)
		rename(tmp, path);
	close(fd);
}

/* Typical Li-ion open-circuit voltage, mV for 0, 10, ... 100 %. Under load
 * or while charging the reading is off, so the result is an estimate. */
static const int ocv[11] = { 3300, 3610, 3690, 3740, 3770, 3800,
			     3840, 3890, 3960, 4050, 4170 };

static int percent(long mv)
{
	int i;

	if (mv <= ocv[0])
		return 0;
	for (i = 1; i < 11; i++)
		if (mv < ocv[i])
			return (i - 1) * 10 + (mv - ocv[i - 1]) * 10 / (ocv[i] - ocv[i - 1]);
	return 100;
}

static void serve(const char *root)
{
	char battery[200], usb[200];
	const char *scale = getenv("N90_VBAT_UV_PER_COUNT");
	const char *offset = getenv("N90_VBAT_OFFSET_UV");
	const char *charging = getenv("N90_ICH_CHARGING_COUNTS");
	long uv_per_count = scale ? atol(scale) : 0;
	long offset_uv = offset ? atol(offset) : 0;
	long ich_min = charging ? atol(charging) : -1;

	snprintf(battery, sizeof battery, "%s/battery", root);
	snprintf(usb, sizeof usb, "%s/usb", root);
	mkdir(root, 0755);
	mkdir(battery, 0755);
	mkdir(usb, 0755);
	put(battery, "type", "Battery\n", 0);
	put(usb, "type", "USB\n", 0);
	for (;;) {
		int supply = pmu_read(PMU_SUPPLY), vbat = adc(ADC_VBAT);
		int ich = adc(ADC_ICH), online = supply >= 0 && (supply & PMU_SUPPLY_USB);

		put(usb, "online", "%ld\n", online);
		put(battery, "vbat_counts", "%ld\n", vbat);
		put(battery, "ich_counts", "%ld\n", ich);
		if (uv_per_count && vbat > 0) {
			long uv = offset_uv + vbat * uv_per_count;

			put(battery, "voltage_now", "%ld\n", uv);
			put(battery, "capacity", "%ld\n", percent(uv / 1000));
			put(battery, "capacity_source", "voltage\n", 0);
		}
		put(battery, "status", supply < 0 ? "Unknown\n" :
		    !online ? "Discharging\n" :
		    ich_min < 0 || ich < 0 ? "Unknown\n" :
		    ich > ich_min ? "Charging\n" : "Not charging\n", 0);
		sleep(10);
	}
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: n90-battery probe | serve [dir]\n");
		return 2;
	}
	i2c = open("/dev/i2c-0", O_RDWR);
	if (i2c < 0 || ioctl(i2c, I2C_SLAVE_FORCE, PMU_ADDR) < 0) {
		perror("i2c");
		return 1;
	}
	if (!strcmp(argv[1], "probe"))
		probe();
	else if (!strcmp(argv[1], "serve"))
		serve(argc > 2 ? argv[2] : "/run/power_supply");
	else
		return 2;
	return 0;
}
