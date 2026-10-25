/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef N90_CALIBRATION_H
#define N90_CALIBRATION_H
#define CAL_MAX 600
typedef struct { double center[3], matrix[3][3], rms; int valid; } Calibration;
int calibrate(const double samples[][3], int n, double field, Calibration *out);
void calibrated(const Calibration *c, const double raw[3], double out[3]);
int compass_heading(const Calibration *c, const double mag_chip[3], const double accel_chip[3], double field, double declination, double *heading);
#endif
