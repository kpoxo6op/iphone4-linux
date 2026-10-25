// SPDX-License-Identifier: GPL-3.0-or-later
/* Bounded N90 UART4 observation. Register facts: openiBoot plat-a4,
 * revision 0e6178b235068c29a3289131049467e8ae90124e; GPL-3.0-or-later.
 * No clock, pin, interrupt, UART configuration or transmit writes.
 * Reading URXH consumes a received byte. Raw data belongs in private storage.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static volatile sig_atomic_t stop;
static void quit(int sig){(void)sig;stop=1;}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
int main(int argc,char **argv){
 if(argc!=3){fprintf(stderr,"usage: uart-listen SECONDS PRIVATE-OUTPUT\n");return 2;}
 char *end;long seconds=strtol(argv[1],&end,10);if(*end||seconds<1||seconds>60)return 2;
 umask(077);int fd=open("/dev/mem",O_RDONLY|O_SYNC|O_CLOEXEC);if(fd<0){perror("/dev/mem");return 1;}
 volatile uint32_t *pm=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0xbf101000);
 if(pm==MAP_FAILED){perror("PMGR mapping");return 1;}
 uint32_t gate=pm[0xe0/4];if((gate&0xff)!=0xff){fprintf(stderr,"UART4 gate not enabled: %08x; no UART read\n",gate);return 1;}
 volatile uint32_t *uart=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0x82900000);
 if(uart==MAP_FAILED){perror("UART mapping");return 1;}
 FILE *out=fopen(argv[2],"wb");if(!out){perror("output");return 1;}
 signal(SIGTERM,quit);signal(SIGINT,quit);signal(SIGHUP,quit);
 double begin=now(),deadline=begin+seconds;unsigned bytes=0,errors=0,full=0,max_queued=0;
 fprintf(stderr,"UART4 before ULCON=%08x UCON=%08x UFCON=%08x UMCON=%08x UBAUD=%08x\n",uart[0],uart[1],uart[2],uart[3],uart[10]);
 while(!stop&&now()<deadline&&bytes<1024*1024){
  uint32_t status=uart[6];unsigned n=(status&0x100)?16:(status&15);
  if(n>max_queued)max_queued=n;
  if(status&0x100)full++;
  if(n){for(unsigned i=0;i<n;i++){errors|=uart[5];uint8_t b=*((volatile uint8_t*)uart+0x24);if(fputc(b,out)==EOF){stop=1;break;}bytes++;}}
  else usleep(1000);
 }
 fclose(out);fprintf(stderr,"{\"seconds\":%.3f,\"received_bytes\":%u,\"error_bits\":%u,\"fifo_full_observations\":%u,\"maximum_queued\":%u,\"register_writes\":0}\n",now()-begin,bytes,errors,full,max_queued);
 munmap((void*)uart,4096);munmap((void*)pm,4096);close(fd);return 0;
}
