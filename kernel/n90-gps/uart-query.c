// SPDX-License-Identifier: GPL-3.0-or-later
/* N90 bounded UART4 query transport. Register facts: openiBoot A4,
 * 0e6178b235068c29a3289131049467e8ae90124e. Caller supplies reviewed protocol
 * bytes privately; no firmware is embedded. Does not change clocks/pins/baud.
 */
#define _GNU_SOURCE
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
 if(argc!=4){fprintf(stderr,"usage: uart-query SECONDS PRIVATE-TX PRIVATE-RX\n");return 2;}
 char *end;long seconds=strtol(argv[1],&end,10);if(*end||seconds<1||seconds>60)return 2;
 umask(077);uint8_t tx[257];FILE *in=fopen(argv[2],"rb");if(!in){perror("TX");return 1;}
 size_t count=fread(tx,1,sizeof tx,in);int bad=ferror(in);fclose(in);
 if(bad||!count||count>256){fprintf(stderr,"TX must contain 1..256 reviewed bytes\n");return 2;}
 int fd=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);if(fd<0){perror("/dev/mem");return 1;}
 volatile uint32_t *pm=mmap(NULL,4096,PROT_READ,MAP_SHARED,fd,0xbf101000);
 if(pm==MAP_FAILED){perror("PMGR mapping");return 1;}
 if((pm[0xe0/4]&0xff)!=0xff){fprintf(stderr,"UART4 gate is not enabled\n");return 1;}
 volatile uint32_t *u=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0x82900000);
 if(u==MAP_FAILED){perror("UART mapping");return 1;}
 if(u[0]!=3||(u[1]!=0x405&&u[1]!=0x425)||u[2]!=1||(u[3]!=0x10&&u[3]!=1)||u[10]!=12||u[11]!=0){fprintf(stderr,"UART4 is not the reviewed 115200 8N1 polling configuration\n");return 1;}
 FILE *out=fopen(argv[3],"wb");if(!out){perror("RX");return 1;}
 signal(SIGTERM,quit);signal(SIGINT,quit);signal(SIGHUP,quit);
 unsigned sent=0,received=0,errors=0,full=0;double begin=now(),deadline=begin+seconds;int failed=0;
 while(!stop&&now()<deadline&&received<1024*1024){
  uint32_t status=u[6];unsigned n=(status&0x100)?16:(status&15);
  if(status&0x100)full++;
  for(unsigned i=0;i<n;i++){
   errors|=u[5];uint8_t b=*((volatile uint8_t*)u+0x24);
   if(fputc(b,out)==EOF){failed=stop=1;break;}received++;
  }
  if(sent<count&&!(status&0x200)) *((volatile uint8_t*)u+0x20)=tx[sent++];
  else usleep(1000);
 }
 int drained=(u[4]&4)!=0;uint32_t fifo=u[6],modem=u[7];
 /* Do not leave queued commands to transmit after this bounded experiment. */
 if(!drained){u[2]=5;u[2]=1;failed=1;}
 if(fclose(out))failed=1;
 fprintf(stderr,"{\"seconds\":%.3f,\"tx_requested\":%zu,\"tx_enqueued\":%u,\"tx_drained\":%s,\"received_bytes\":%u,\"error_bits\":%u,\"fifo_full_observations\":%u,\"fifo_at_end\":%u,\"modem_status\":%u,\"tx_fifo_reset\":%s}\n",now()-begin,count,sent,drained?"true":"false",received,errors,full,fifo,modem,drained?"false":"true");
 munmap((void*)u,4096);munmap((void*)pm,4096);close(fd);return failed||sent!=count?1:0;
}
