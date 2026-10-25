// SPDX-License-Identifier: GPL-2.0-only
#include "sensors.h"
#include <math.h>
#include <stdio.h>
#include <unistd.h>
int main(void)
{
 Sensors s;sensors_open(&s,"/dev/i2c-0","/dev/i2c-2");
 printf("{\"magnetometer_selftest_pass\":%s,\"asa\":[%u,%u,%u],\"accelerometer_identity_pass\":%s}\n",s.mag_ok?"true":"false",s.asa[0],s.asa[1],s.asa[2],s.accel_ok?"true":"false");
 double delta[3]={0};int ast=sensor_accel_selftest(&s,delta);
 printf("{\"accelerometer_selftest_pass\":%s,\"delta_LSB\":[%.2f,%.2f,%.2f]}\n",ast?"false":"true",delta[0],delta[1],delta[2]);
 for(int i=0;i<5;i++){
  double v[3];if(!sensor_mag(&s,v,0))printf("{\"mag_uT_chip\":[%.3f,%.3f,%.3f],\"norm_uT\":%.3f}\n",v[0],v[1],v[2],sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2]));
  if(!sensor_accel(&s,v))printf("{\"accel_g_chip\":[%.3f,%.3f,%.3f],\"norm_g\":%.3f}\n",v[0],v[1],v[2],sqrt(v[0]*v[0]+v[1]*v[1]+v[2]*v[2]));
  usleep(200000);
 }
 int ok=s.mag_ok;sensors_close(&s);return ok?0:1;
}
