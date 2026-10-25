/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef N90_SOLAR_H
#define N90_SOLAR_H
/* Geometric Sun direction from UTC and east-positive WGS84 coordinates.
 * Azimuth is clockwise from true north. No magnetic measurement is used. */
int solar_direction(double utc, double lat, double lon, double *azimuth, double *elevation);
#endif
