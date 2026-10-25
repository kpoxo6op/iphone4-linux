/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef N90_POSITION_H
#define N90_POSITION_H
#define PARTICLES 256
typedef struct { double x,y,w; } Particle;
typedef struct { double lat0,lon0,x,y,uncertainty,travel; int valid; Particle p[PARTICLES]; } Position;
int position_graph(const char *path,Position *p);
void position_fix(Position *p,double lat,double lon,double accuracy);
int position_step(Position *p,double heading,double stride);
double position_distance(const Position *p,int target);
void position_latlon(const Position *p,double *lat,double *lon);
#endif
