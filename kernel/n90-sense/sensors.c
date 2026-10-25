// SPDX-License-Identifier: GPL-2.0-only
/* AKM MS1187-E-02 pp. 12-15, 24-28; ST LIS331DLH Doc ID 15094 Rev 3.
 * AK8975 single conversion, ASA adjustment, self-test and overflow check.
 * LIS331DLH normal 50 Hz, +/-2 g, block-data update, 12-bit left-justified.
 * Device addresses and mounting come from the N90 device tree, not probing
 * writes to unknown addresses. All I2C transactions use the kernel adapter.
 */
#include "sensors.h"
#include <errno.h>
#include <math.h>
#include <fcntl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>
#include <stddef.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int read_regs(int fd, int addr, uint8_t reg, uint8_t *out, int n)
{
 struct i2c_msg m[2]={{.addr=addr,.len=1,.buf=&reg},{.addr=addr,.flags=I2C_M_RD,.len=n,.buf=out}};
 struct i2c_rdwr_ioctl_data rd={m,2};
 return ioctl(fd,I2C_RDWR,&rd)==2 ? 0 : -1;
}
static int write_reg(int fd,int addr,uint8_t reg,uint8_t val)
{
 uint8_t b[]={reg,val};struct i2c_msg m={.addr=addr,.len=2,.buf=b};
 struct i2c_rdwr_ioctl_data rd={&m,1};return ioctl(fd,I2C_RDWR,&rd)==1 ? 0 : -1;
}
static int mode(Sensors *s,int value)
{
 if(write_reg(s->mag,0x0d,0x0a,0))return -1;
 usleep(200);return value ? write_reg(s->mag,0x0d,0x0a,value) : 0;
}
int sensor_mag(Sensors *s,double out[3],int selftest)
{
 uint8_t st,b[7];int result=-1;
 if(!s->mag_ok)return -1;
 if(mode(s,0))return -1;
 if(selftest && write_reg(s->mag,0x0d,0x0c,0x40))goto done;
 if(mode(s,selftest?8:1))goto done;
 for(int i=0;i<30;i++){
  usleep(1000);
  if(read_regs(s->mag,0x0d,0x02,&st,1))goto done;
  if(st&1){
   /* Reading through ST2 is required to finish the transaction. */
   if(read_regs(s->mag,0x0d,0x03,b,7) || (b[6]&0x0c))goto done;
   for(int k=0;k<3;k++){
    int16_t raw=(int16_t)((uint16_t)b[k*2]|((uint16_t)b[k*2+1]<<8));
    if(raw < -4096 || raw > 4095)goto done;
    out[k]=raw*(s->asa[k]+128)/256.0*(selftest?1.0:0.3);
   }
   result=0;break;
  }
 }
 done:
 if(selftest)write_reg(s->mag,0x0d,0x0c,0);
 mode(s,0);return result;
}
int sensor_accel(Sensors *s,double out[3])
{
 uint8_t b[6],st;
 if(!s->accel_ok || read_regs(s->accel,0x19,0x27,&st,1) || !(st&8))return -1;
 if(read_regs(s->accel,0x19,0xa8,b,6))return -1;
 for(int k=0;k<3;k++)out[k]=((int16_t)((uint16_t)b[k*2]|((uint16_t)b[k*2+1]<<8))>>4)*0.001;
 return 0;
}
int sensor_accel_selftest(Sensors *s,double delta[3])
{
 /* ST Doc ID 15094 Rev 3: +/-2g, 12-bit, X/Y 120..550 and Z
  * 140..750 LSB. Read an average before and after enabling ST. */
 if(!s->accel_ok)return -1;
 double avg[2][3]={{0}},v[3];int result=-1;
 for(int phase=0;phase<2;phase++){
  if(write_reg(s->accel,0x19,0x23,phase?0x82:0x80))goto done;
  usleep(100000);int got=0;
  for(int i=0;i<40&&got<16;i++){
   usleep(25000);if(sensor_accel(s,v))continue;
   for(int k=0;k<3;k++)avg[phase][k]+=v[k];
   got++;
  }
  if(got!=16)goto done;
 }
 result=0;
 for(int k=0;k<3;k++){
  delta[k]=(avg[1][k]-avg[0][k])*1000/16;
  if(fabs(delta[k])<(k==2?140:120)||fabs(delta[k])>(k==2?750:550))result=-1;
 }
 done:
 if(write_reg(s->accel,0x19,0x23,0x80))result=-1;
 usleep(100000);return result;
}
int sensors_open(Sensors *s,const char *mag_bus,const char *accel_bus)
{
 *s=(Sensors){.mag=-1,.accel=-1};uint8_t id;double test[3];
 s->mag=open(mag_bus,O_RDWR|O_CLOEXEC);
 if(s->mag>=0 && !read_regs(s->mag,0x0d,0,&id,1) && id==0x48 && !mode(s,15)){
  usleep(1000);
  if(!read_regs(s->mag,0x0d,0x10,s->asa,3)){
   s->mag_ok=1;
   for(int k=0;k<3;k++)if(s->asa[k]==0 || s->asa[k]==255)s->mag_ok=0;
  }
  mode(s,0);
  if(s->mag_ok && (sensor_mag(s,test,1) || test[0]<-100 || test[0]>100 || test[1]<-100 || test[1]>100 || test[2]<-1000 || test[2]>-300))s->mag_ok=0;
 }
 s->accel=open(accel_bus,O_RDWR|O_CLOEXEC);
 if(s->accel>=0 && !read_regs(s->accel,0x19,0x0f,&id,1) && id==0x32){
  if(!write_reg(s->accel,0x19,0x23,0x80) && !write_reg(s->accel,0x19,0x20,0x27)){s->accel_ok=1;usleep(40000);}
 }
 return s->mag_ok || s->accel_ok ? 0 : -1;
}
void sensors_close(Sensors *s)
{
 if(s->mag>=0){if(s->mag_ok){write_reg(s->mag,0x0d,0x0c,0);mode(s,0);}close(s->mag);}
 if(s->accel>=0){if(s->accel_ok)write_reg(s->accel,0x19,0x20,7);close(s->accel);}
}
