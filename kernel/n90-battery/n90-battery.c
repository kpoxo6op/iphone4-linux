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
 * 15 vbus. VBAT is 2500 mV + counts x 2000/4096: two readings on 21 and 22
 * October matched iBoot's own boot-time record in 0x8e:0x8d within 14 mV.
 * The other scales are not known yet; `probe` prints raw values.
 *
 * Charging: register 0x08 bit 5 means the charge timer ran out and bit 3
 * that charging ended; ich (channel 1) reads 0 then. AppleD1815PMUPowerSource
 * restarts the charger by writing 0x2e & 0x08 to 0x2e and then the old value
 * (iOS 7.1.2 kernelcache 0x8098cfb0), five minutes after a timeout or when
 * the battery is below 95 %. On 22 October the timer had expired, the phone
 * drained on USB, and that write brought ich from 0 to about 1275 counts.
 *
 * The USB input current limit is register 0x2b: bits 0-4 a code, bit 7 set
 * when software chose it. AppleD1815PMUPowerSource writes code | 0x80 and
 * maps codes to milliamps as in limit_ma() (iOS 7.1.2 kernelcache,
 * 0x8098bc80 and 0x8098ddfe). Code 5, 100 mA, is the unconfigured USB value.
 *
 * Usage: n90-battery <cmd>
 *   probe            print the supply registers and every ADC channel
 *   usb-limit <mA>   raise or lower the USB input current limit, backing
 *                    off if VBUS sags by more than a tenth
 *   meter [mA]       the phone's draw on USB, from the limit at which the
 *                    charger stops charging, or from the charge current at
 *                    one limit, for comparisons (stop serve first)
 *   serve [dir]      publish readings every 10 s as power_supply-style
 *                    files under dir (default /run/power_supply)
 *   poweroff         switch the phone off through the PMU
 *   clock [save|load] the PMU's real-time clock: show it, store its offset
 *                    from the system time, or set the system time from it
 *   mark oops|reboot record that keep is restarting the phone after an oops,
 *                    or that someone is restarting it on purpose
 *   lastrun          at boot: report once how and when the phone last stopped
 *
 * Last stop: serve writes a heartbeat to PMU bytes 0x89-0x8c every minute
 * (state, the seconds counter in minutes, the battery voltage), which the PMU
 * keeps while the phone is off. A planned stop replaces the state: low
 * battery, an oops restart, a restart on purpose, or poweroff. At the next boot lastrun turns the
 * record into a "last_stop" journal event; a heartbeat state still there
 * means the phone stopped without warning (crash, watchdog reset, a battery
 * that gave out first, or a hard reset), last seen at that minute.
 *
 * serve restarts the charger the same way, publishes the voltage and the
 * charge state, and publishes a percentage estimated from the voltage only
 * on battery: while charging the voltage reads high. When a cable comes in
 * it raises the USB limit to 500 mA, as usb-limit does: the PMU starts again
 * at 100 mA, less than the phone uses, so it drained on a charger.
 *
 * Low battery: three readings in a row (30 s) under 3.45 V, about 2 % left,
 * on battery or on a USB source that is not charging it, switch the phone
 * off before the battery browns it out. serve notes it in Soy's journal and
 * waits 20 s so the laptop can copy the logs if it can reach the phone.
 * Power then starts the phone into DFU mode. On USB below 3.6 V without
 * charging, serve first asks for 500 mA again and restarts the charger.
 *
 * poweroff is openiBoot's pmu_poweroff() for the A4: mask the wake events
 * in 0x0c-0x11, drive the PMU GPIO outputs low, set 0x12 (OOCSHDWN).
 *
 * Clock: 0x4c-0x4f count seconds, little-endian, and keep counting while the
 * phone is off (measured +20 in 20.04 s on 22 October; 151,000 s then, so
 * it counts from some reset rather than 1970). No time offset turned up in
 * the PMU, so `clock save` keeps ours, epoch minus counter, in general-
 * purpose bytes 0x84-0x87 with 0x5a in 0x88. openiBoot names the iBoot use
 * of 0x80-0x83 and 0x8f, and iBoot records the boot voltage in 0x8d-0x8e.
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define PMU_ADDR        0x74
#define PMU_EVENT       0x02
#define PMU_SUPPLY      0x07
#define PMU_CHARGE      0x08
#define PMU_USB_LIMIT   0x2b
#define PMU_CHARGER     0x2e
#define CHARGE_TIMEOUT  0x20
#define CHARGE_END      0x08
#define PMU_ADC_MUX     0x30
#define PMU_ADC_LOW     0x31
#define PMU_SUPPLY_USB  0x08
#define PMU_SUPPLY_FW   0x10
#define ADC_DONE        0x20
#define ADC_START       0x10
#define ADC_VBAT        4
#define ADC_ICH         1
#define ADC_VBUS        15
#define PMU_WAKE_MASKS  0x0c
#define PMU_GPIO_FIRST  0x50
#define PMU_GPIO_LAST   0x5a
#define PMU_SHUTDOWN    0x12
#define LOW_MV          3450
#define PMU_RTC         0x4c
#define PMU_RTC_OFFSET  0x84
#define PMU_RTC_MAGIC   0x88
#define RTC_MAGIC       0x5a
#define PMU_LAST        0x89	/* state; 0x8a-0x8b minutes; 0x8c mV */
#define LAST_REPORTED   0xa0
#define LAST_RUNNING    0xa1
#define LAST_BATTERY    0xa2
#define LAST_OOPS       0xa3
#define LAST_OFF        0xa4
#define LAST_REBOOT     0xa5

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

/* AppleD1815PMUPowerSource's code-to-milliamp table for register 0x2b. */
static int limit_ma(int code)
{
	if (code <= 15)
		return 50 + 10 * code;
	if (code <= 23)
		return 50 * code - 550;
	if (code <= 25)
		return 200 * code - 4100;
	return code <= 31 ? 200 * code - 4200 : -1;
}

static int limit_code(int ma)
{
	int code, best = 0;

	for (code = 0; code <= 31; code++)
		if (limit_ma(code) <= ma)
			best = code;
	return best;
}

static int usb_limit(int ma)
{
	int before = pmu_read(PMU_USB_LIMIT), vbus = adc(ADC_VBUS), after, sag;

	if (before < 0 || vbus <= 0) {
		fprintf(stderr, "cannot read the limit or VBUS\n");
		return 1;
	}
	if (!(pmu_read(PMU_SUPPLY) & PMU_SUPPLY_USB)) {
		fprintf(stderr, "no USB power\n");
		return 1;
	}
	pmu_write(PMU_USB_LIMIT, limit_code(ma) | 0x80);
	sleep(1);
	after = adc(ADC_VBUS);
	sag = after > 0 && after * 10 < vbus * 9;
	if (sag)
		pmu_write(PMU_USB_LIMIT, before);
	printf("usb limit 0x%02x (%d mA) -> 0x%02x (%d mA), vbus %d -> %d counts%s\n",
	       before, limit_ma(before & 0x1f), pmu_read(PMU_USB_LIMIT),
	       limit_ma(pmu_read(PMU_USB_LIMIT) & 0x1f), vbus, after,
	       sag ? ", sagged: restored" : "");
	return sag;
}

static void probe(void)
{
	int supply = pmu_read(PMU_SUPPLY), c, n, limit = pmu_read(PMU_USB_LIMIT);

	printf("supply 0x07 = 0x%02x (%s)\n", supply,
	       supply < 0 ? "read failed" :
	       supply & PMU_SUPPLY_USB ? "USB" :
	       supply & PMU_SUPPLY_FW ? "FireWire" : "battery");
	printf("usb limit 0x2b = 0x%02x (%d mA)\n", limit, limit_ma(limit & 0x1f));
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

static long vbat_mv(int counts)
{
	return 2500 + counts * 2000L / 4096;
}

/* What AppleD1815PMUPowerSource does after a charge timeout or end of charge
 * with the battery below 95 %: clear the charger configuration but bit 3 and
 * write it back, which starts a new charge cycle. */
static int restart_charger(void)
{
	int v = pmu_read(PMU_CHARGER);

	if (v < 0 || pmu_write(PMU_CHARGER, v & 0x08))
		return -1;
	usleep(100000);
	return pmu_write(PMU_CHARGER, v);
}

/* How much the phone draws, without an ammeter. While the charger charges
 * at its USB input limit, the battery gets the limit less what the phone
 * uses, about 4.7 ich counts per mA (README, "Power draw"). Lower the limit a
 * step at a time until charging stops: the draw is the last limit that still
 * charged, less the current that went to the battery there. The limit goes
 * back afterwards, also on SIGINT, SIGTERM or SIGHUP. serve must not run
 * meanwhile: both use the PMU's ADC. */
static int meter_limit = -1;

static void meter_restore(int sig)
{
	if (meter_limit >= 0)
		pmu_write(PMU_USB_LIMIT, meter_limit);
	if (sig)
		_exit(1);
}

static int ich_average(int n)
{
	int i, v, sum = 0, got = 0;

	for (i = 0; i < n; i++) {
		v = adc(ADC_ICH);
		if (v >= 0) {
			sum += v;
			got++;
		}
		msleep(100);
	}
	return got ? sum / got : -1;
}

static int meter(int at)
{
	int code, ich = -1, last = -1, last_ich = 0, charge = pmu_read(PMU_CHARGE);

	if (!(pmu_read(PMU_SUPPLY) & PMU_SUPPLY_USB)) {
		fprintf(stderr, "no USB power\n");
		return 1;
	}
	meter_limit = pmu_read(PMU_USB_LIMIT);
	if (meter_limit < 0)
		return 1;
	signal(SIGINT, meter_restore);
	signal(SIGTERM, meter_restore);
	signal(SIGHUP, meter_restore);
	/* A charge that ended or timed out reads 0 at any limit. */
	if (charge >= 0 && (charge & (CHARGE_TIMEOUT | CHARGE_END)))
		restart_charger();
	/* One fixed limit, averaged longer: for comparing two states. */
	if (at > 0) {
		code = limit_code(at);
		pmu_write(PMU_USB_LIMIT, code | 0x80);
		sleep(3);
		ich = ich_average(50);
		meter_restore(0);
		printf("limit %d mA: ich %d, draw %d mA\n", limit_ma(code), ich,
		       limit_ma(code) - ich * 10 / 47);
		return ich < 40;
	}
	for (code = limit_code(500); code >= 0; code--) {
		pmu_write(PMU_USB_LIMIT, code | 0x80);
		sleep(3);
		ich = ich_average(10);
		printf("limit %d mA: ich %d\n", limit_ma(code), ich);
		fflush(stdout);
		if (ich < 40)
			break;
		last = code;
		last_ich = ich;
	}
	meter_restore(0);
	if (last < 0 || code < 0) {
		fprintf(stderr, "no step where charging stopped\n");
		return 1;
	}
	printf("draw %d mA (charging stopped between %d and %d mA)\n",
	       limit_ma(last) - last_ich * 10 / 47, limit_ma(code), limit_ma(last));
	return 0;
}

/* openiBoot plat-a4/pmu.c pmu_write_oocshdwn(1). Does not return. */
static void poweroff(void)
{
	static const uint8_t masks[] = { PMU_WAKE_MASKS, 0xc0, 0xff, 0xbf, 0xff, 0xae, 0xff };
	struct i2c_msg msg = { .addr = PMU_ADDR, .flags = 0, .len = sizeof masks,
			       .buf = (uint8_t *)masks };
	struct i2c_rdwr_ioctl_data data = { .msgs = &msg, .nmsgs = 1 };
	int reg;

	sync();
	pmu_read(0x01);
	ioctl(i2c, I2C_RDWR, &data);
	for (reg = PMU_GPIO_FIRST; reg <= PMU_GPIO_LAST; reg++) {
		int v = pmu_read(reg);

		/* Outputs (mode 3 and up) that are driven high. */
		if (v >= 0 && (v & 0xe0) > 0x5f && (v & 0x02))
			pmu_write(reg, v & 0xfd);
	}
	pmu_write(PMU_SHUTDOWN, 1);
	for (;;)
		sleep(1);
}

static long rtc_seconds(void)
{
	uint8_t b[4];

	if (pmu_read_n(PMU_RTC, b, 4))
		return -1;
	return b[0] | b[1] << 8 | b[2] << 16 | (long)b[3] << 24;
}

static long rtc_offset(void)
{
	uint8_t b[4];

	if (pmu_read(PMU_RTC_MAGIC) != RTC_MAGIC || pmu_read_n(PMU_RTC_OFFSET, b, 4))
		return -1;
	return b[0] | b[1] << 8 | b[2] << 16 | (long)b[3] << 24;
}

static int clock_cmd(const char *what)
{
	long counter = rtc_seconds(), offset = rtc_offset(), now = time(NULL);
	char text[64];
	time_t t;
	int i;

	if (counter < 0) {
		fprintf(stderr, "cannot read the PMU clock\n");
		return 1;
	}
	if (!strcmp(what, "save")) {
		if (now < 1700000000) {
			fprintf(stderr, "the system time is not set\n");
			return 1;
		}
		offset = now - counter;
		for (i = 0; i < 4; i++)
			pmu_write(PMU_RTC_OFFSET + i, (offset >> (8 * i)) & 0xff);
		pmu_write(PMU_RTC_MAGIC, RTC_MAGIC);
		if (rtc_offset() != offset) {
			fprintf(stderr, "the offset did not stick\n");
			return 1;
		}
	} else if (!strcmp(what, "load")) {
		struct timeval tv = { .tv_sec = counter + offset };

		if (offset < 0) {
			fprintf(stderr, "no saved offset\n");
			return 1;
		}
		if (settimeofday(&tv, NULL)) {
			perror("settimeofday");
			return 1;
		}
		now = tv.tv_sec;
	}
	printf("pmu counter %ld s", counter);
	if (offset >= 0) {
		t = counter + offset;
		strftime(text, sizeof text, "%Y-%m-%d %H:%M:%S UTC", gmtime(&t));
		printf(", clock %s, system %+ld s", text, now - (long)t);
	} else {
		printf(", no saved offset");
	}
	printf("\n");
	return 0;
}

/* Where the phone was last, in bytes the PMU keeps while it is off, next to
 * its seconds counter: the state, the counter in minutes (low 16 bits) and
 * the battery voltage. The state goes last, so a torn write still reads as
 * the previous record. */
static void mark(int state, long mv)
{
	long counter = rtc_seconds();
	int minutes = counter >= 0 ? (int)(counter / 60) & 0xffff : 0;
	long v = mv > 3000 ? (mv - 3000) / 10 : 0;

	pmu_write(PMU_LAST + 1, minutes & 0xff);
	pmu_write(PMU_LAST + 2, minutes >> 8);
	pmu_write(PMU_LAST + 3, v > 255 ? 255 : v);
	pmu_write(PMU_LAST, state);
}

/* At boot: say once, in Soy's journal, how and when the phone last stopped. */
static int lastrun(void)
{
	uint8_t b[4];
	long counter = rtc_seconds(), now = time(NULL), at, mv;
	const char *why;
	char text[64];
	time_t t;
	FILE *f;

	if (counter < 0 || pmu_read_n(PMU_LAST, b, 4)) {
		fprintf(stderr, "cannot read the PMU\n");
		return 1;
	}
	switch (b[0]) {
	case LAST_RUNNING:
		why = "unexpected";
		break;
	case LAST_BATTERY:
		why = "battery";
		break;
	case LAST_OOPS:
		why = "oops";
		break;
	case LAST_OFF:
		why = "off";
		break;
	case LAST_REBOOT:
		why = "reboot";
		break;
	default:
		printf("no record of the last stop\n");
		return 0;
	}
	at = now - 60L * (((int)(counter / 60) - (b[1] | b[2] << 8)) & 0xffff);
	mv = b[3] ? 3000 + b[3] * 10L : -1;
	t = at;
	strftime(text, sizeof text, "%Y-%m-%d %H:%M UTC", gmtime(&t));
	printf("last stop: %s, last seen %s, %ld mV\n", why, text, mv);
	f = fopen("/run/soy/journal.jsonl", "a");
	if (f) {
		fprintf(f, "{\"t\":%ld,\"e\":\"last_stop\",\"why\":\"%s\",\"at\":%ld,\"mv\":%ld}\n",
			now, why, at, mv);
		fclose(f);
	}
	pmu_write(PMU_LAST, LAST_REPORTED);
	return 0;
}

static void note_shutdown(long mv)
{
	FILE *f = fopen("/run/soy/journal.jsonl", "a");

	if (f) {
		fprintf(f, "{\"t\":%ld,\"e\":\"shutdown\",\"why\":\"battery\",\"mv\":%ld}\n",
			(long)time(NULL), mv);
		fclose(f);
	}
	fprintf(stderr, "battery at %ld mV: switching off in 20 s\n", mv);
}

static void serve(const char *root)
{
	char battery[200], usb[200], path[256];
	time_t stopped = 0, restarted = 0, marked = 0, rescued = 0;
	int low = 0, raised = 0;

	snprintf(battery, sizeof battery, "%s/battery", root);
	snprintf(usb, sizeof usb, "%s/usb", root);
	mkdir(root, 0755);
	mkdir(battery, 0755);
	mkdir(usb, 0755);
	put(battery, "type", "Battery\n", 0);
	put(usb, "type", "USB\n", 0);
	snprintf(path, sizeof path, "%s/capacity_source", battery);
	unlink(path);
	for (;;) {
		int supply = pmu_read(PMU_SUPPLY), charge = pmu_read(PMU_CHARGE);
		int vbat = adc(ADC_VBAT), ich = adc(ADC_ICH);
		int online = supply >= 0 && (supply & PMU_SUPPLY_USB);
		int charging = online && ich > 50;
		time_t now = time(NULL);
		long mv = vbat > 0 ? vbat_mv(vbat) : -1;

		/* Once per plug-in: a source that sags at 500 mA keeps what it had. */
		if (!online) {
			raised = 0;
		} else if (!raised) {
			int limit = pmu_read(PMU_USB_LIMIT);

			if (limit >= 0 && limit_ma(limit & 0x1f) < 500) {
				usb_limit(500);
				fflush(stdout);
			}
			raised = 1;
		}
		if (online && charge >= 0 && (charge & (CHARGE_TIMEOUT | CHARGE_END)) &&
		    mv > 0 && mv < 4100) {
			if (!stopped)
				stopped = now;
			/* iOS waits five minutes after a timeout before restarting. */
			if ((!(charge & CHARGE_TIMEOUT) || now - stopped >= 300) &&
			    now - restarted >= 300 && !restart_charger()) {
				fprintf(stderr, "charger restarted (0x08 = 0x%02x, %ld mV)\n",
					charge, mv);
				restarted = now;
				stopped = 0;
			}
		} else {
			stopped = 0;
		}
		put(usb, "online", "%ld\n", online);
		put(battery, "vbat_counts", "%ld\n", vbat);
		put(battery, "ich_counts", "%ld\n", ich);
		put(battery, "charge_flags", "0x%02lx\n", charge);
		if (mv > 0)
			put(battery, "voltage_now", "%ld\n", mv * 1000);
		snprintf(path, sizeof path, "%s/capacity", battery);
		if (mv > 0 && !online) {
			put(battery, "capacity", "%ld\n", percent(mv));
			put(battery, "capacity_source", "voltage\n", 0);
		} else {
			unlink(path);
		}
		put(battery, "status", supply < 0 ? "Unknown\n" :
		    !online ? "Discharging\n" :
		    charging ? "Charging\n" :
		    charge >= 0 && (charge & CHARGE_END) && mv >= 4100 ? "Full\n" :
		    "Not charging\n", 0);
		if (mv > 0 && now - marked >= 60) {
			mark(LAST_RUNNING, mv);
			marked = now;
		}
		/* Plugged in but still draining: a source that gives less than
		 * the phone uses, or a limit left lowered, ran the battery flat
		 * overnight on 22-23 October while this only acted on battery.
		 * Below 3.6 V ask again for 500 mA and restart the charger, at
		 * most every five minutes; the shutdown below now covers USB too. */
		if (online && !charging && mv > 0 && mv < 3600 && now - rescued >= 300) {
			fprintf(stderr, "on USB but not charging at %ld mV: asking for 500 mA\n", mv);
			usb_limit(500);
			restart_charger();
			fflush(stdout);
			rescued = now;
		}
		low = supply >= 0 && (!online || !charging) && mv > 0 && mv < LOW_MV ?
			low + 1 : 0;
		if (low >= 3) {
			note_shutdown(mv);
			sleep(20);
			supply = pmu_read(PMU_SUPPLY);
			if (!(supply & PMU_SUPPLY_USB) || adc(ADC_ICH) <= 50) {
				mark(LAST_BATTERY, mv);
				poweroff();
			}
			low = 0;
		}
		sleep(10);
	}
}

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: n90-battery probe | usb-limit <mA> | meter [mA] | serve [dir] | "
			"poweroff | clock [save|load] | mark oops|reboot | lastrun\n");
		return 2;
	}
	i2c = open("/dev/i2c-0", O_RDWR);
	if (i2c < 0 || ioctl(i2c, I2C_SLAVE_FORCE, PMU_ADDR) < 0) {
		perror("i2c");
		return 1;
	}
	if (!strcmp(argv[1], "probe"))
		probe();
	else if (!strcmp(argv[1], "usb-limit") && argc > 2)
		return usb_limit(atoi(argv[2]));
	else if (!strcmp(argv[1], "adc") && argc > 2) {
		int ch = atoi(argv[2]), n = argc > 3 ? atoi(argv[3]) : 1, i, v, sum = 0, got = 0;
		int lo = 4096, hi = -4096, sign = argc > 4 && !strcmp(argv[4], "signed");

		for (i = 0; i < n; i++) {
			v = adc(ch);
			if (v >= 0 && sign && v >= 2048)
				v -= 4096;
			if (v > -4096) {
				sum += v;
				got++;
				lo = v < lo ? v : lo;
				hi = v > hi ? v : hi;
			}
			msleep(20);
		}
		printf("adc %d: mean %d, min %d, max %d, %d readings\n", ch, got ? sum / got : -1,
		       lo, hi, got);
	} else if (!strcmp(argv[1], "meter"))
		return meter(argc > 2 ? atoi(argv[2]) : 0);
	else if (!strcmp(argv[1], "serve"))
		serve(argc > 2 ? argv[2] : "/run/power_supply");
	else if (!strcmp(argv[1], "poweroff")) {
		int vbat = adc(ADC_VBAT);

		mark(LAST_OFF, vbat > 0 ? vbat_mv(vbat) : -1);
		poweroff();
	} else if (!strcmp(argv[1], "clock"))
		return clock_cmd(argc > 2 ? argv[2] : "");
	else if (!strcmp(argv[1], "mark") && argc > 2 &&
		 (!strcmp(argv[2], "oops") || !strcmp(argv[2], "reboot"))) {
		int vbat = adc(ADC_VBAT);

		mark(strcmp(argv[2], "oops") ? LAST_REBOOT : LAST_OOPS,
		     vbat > 0 ? vbat_mv(vbat) : -1);
	} else if (!strcmp(argv[1], "lastrun"))
		return lastrun();
	else
		return 2;
	return 0;
}
