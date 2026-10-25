/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef N90_SENSORS_H
#define N90_SENSORS_H
#include <stdint.h>
typedef struct { int mag, accel, mag_ok, accel_ok; uint8_t asa[3]; } Sensors;
int sensors_open(Sensors *s, const char *mag_bus, const char *accel_bus);
int sensor_mag(Sensors *s, double out[3], int selftest);
int sensor_accel_selftest(Sensors *s, double delta[3]);
int sensor_accel(Sensors *s, double out[3]);
void sensors_close(Sensors *s);
#endif
