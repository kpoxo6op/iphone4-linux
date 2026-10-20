#define _GNU_SOURCE
#include <arm_neon.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <time.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <linux/fb.h>
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
int main(void){int fd=open("/dev/fb0",O_RDWR);struct fb_fix_screeninfo f;if(fd<0||ioctl(fd,FBIOGET_FSCREENINFO,&f))return 1;size_t n=f.smem_len;unsigned char *m=mmap(NULL,n,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0),*b=aligned_alloc(64,(n+63)&~63);if(m==MAP_FAILED||!b||n%64)return 2;memcpy(b,m,n);for(int mode=0;mode<4;mode++){double best=1e9,total=0;for(int r=0;r<3;r++){double t=now();switch(mode){case 0:{volatile uint32_t *d=(volatile uint32_t*)m;uint32_t*s=(uint32_t*)b;for(size_t i=0;i<n/4;i++)d[i]=s[i];break;}case 1:memcpy(m,b,n);break;case 2:for(size_t i=0;i<n;i+=64){uint8x16x4_t v=vld1q_u8_x4(b+i);vst1q_u8_x4(m+i,v);}break;case 3:if(pwrite(fd,b,n,0)!=(ssize_t)n)return 3;break;}t=(now()-t)*1000;if(t<best)best=t;total+=t;}printf("mode=%d best_ms=%.3f avg_ms=%.3f\n",mode,best,total/3);fflush(stdout);}free(b);munmap(m,n);close(fd);}
