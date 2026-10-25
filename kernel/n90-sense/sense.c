// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include "sensors.h"
#include "calibration.h"
#include "position.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#define CHECKPOINTS 32
typedef struct {char id[40],label[80];double lat,lon,accuracy;} Checkpoint;
static Checkpoint points[CHECKPOINTS];static int npoints;
static char root[512]="/run/sense",config[512]="/opt/n90-sense";
static volatile sig_atomic_t stop;
static Position position;static Calibration calibration;static Sensors sensors;
static double field,declination,pickup,fix_time,position_time,heading=NAN,heading_time,last_step,stride=.75;
static double acc[3],mag[3],samples[CAL_MAX][3],cal_started,cal_until;
static int nsamples,steps,walking=1,cal_failed,stationary_peaks,target_override=-1;
static char fix_name[80]="Unavailable",source[64]="unavailable";
static FILE *journal;
static double mono(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static double epoch(void){struct timespec t;clock_gettime(CLOCK_REALTIME,&t);return t.tv_sec+t.tv_nsec/1e9;}
static void shutdown_handler(int sig){(void)sig;stop=1;}
static void filename(char *out,size_t size,const char *base,const char *name){snprintf(out,size,"%s/%s",base,name);}
static void record(const char *format,...)
{
 if(!journal)return;
 fprintf(journal,"{\"t\":%.3f,",epoch());va_list ap;va_start(ap,format);vfprintf(journal,format,ap);va_end(ap);fputs("}\n",journal);fflush(journal);
 /* Twelve hours of one-second snapshots fits; never silently rotate field
  * evidence off an offline phone. Stop logging with an explicit state at 32MiB. */
 if(ftell(journal)>32*1024*1024){fclose(journal);journal=NULL;}
}
static void publish(const char *name,const char *format,...)
{
 char path[600],tmp[620];filename(path,sizeof path,root,name);snprintf(tmp,sizeof tmp,"%s.new",path);
 FILE *f=fopen(tmp,"w");if(!f)return;va_list ap;va_start(ap,format);vfprintf(f,format,ap);va_end(ap);fputs("\n",f);fclose(f);rename(tmp,path);
}
static int safe_id(const char *s){if(!*s||strlen(s)>39)return 0;for(;*s;s++)if(!isalnum((unsigned char)*s)&&*s!='-'&&*s!='_')return 0;return 1;}
static void clean_label(char *s){for(;*s;s++)if((unsigned char)*s<32||*s=='"'||*s=='\\')*s=' ';}
static void save_calibration(void)
{
 char path[600];filename(path,sizeof path,root,"calibration.dat");FILE *f=fopen(path,"w");if(!f)return;
 fprintf(f,"%.9g %.9g %.9g %.9g\n",calibration.center[0],calibration.center[1],calibration.center[2],calibration.rms);
 for(int i=0;i<3;i++)fprintf(f,"%.9g %.9g %.9g\n",calibration.matrix[i][0],calibration.matrix[i][1],calibration.matrix[i][2]);
 fclose(f);
}
static void load_calibration(void)
{
 char path[600];filename(path,sizeof path,root,"calibration.dat");FILE *f=fopen(path,"r");if(!f)return;
 Calibration c={0};int n=fscanf(f,"%lf %lf %lf %lf",&c.center[0],&c.center[1],&c.center[2],&c.rms);
 for(int i=0;i<3;i++)n+=fscanf(f,"%lf %lf %lf",&c.matrix[i][0],&c.matrix[i][1],&c.matrix[i][2]);
 fclose(f);
 int valid=n==13&&isfinite(c.rms)&&c.rms>=0&&c.rms<field*.08;
 for(int i=0;i<3;i++){
  valid&=isfinite(c.center[i])&&fabs(c.center[i])<1200;
  for(int j=0;j<3;j++)valid&=isfinite(c.matrix[i][j])&&fabs(c.matrix[i][j])<3;
  valid&=c.matrix[i][i]>.2;
 }
 if(valid){c.valid=1;calibration=c;}
}
static void given_fix(const Checkpoint *point,const char *kind)
{
 if(!isfinite(point->lat)||fabs(point->lat)>85||!isfinite(point->lon)||fabs(point->lon)>180||!isfinite(point->accuracy)||point->accuracy<5||point->accuracy>1000)return;
 double lat=0,lon=0;position_latlon(&position,&lat,&lon);
 if(position.valid)record("\"e\":\"sense_fix\",\"id\":\"%s\",\"source\":\"%s\",\"lat\":%.7f,\"lon\":%.7f,\"accuracy_m\":%.1f,\"predicted_lat\":%.7f,\"predicted_lon\":%.7f,\"predicted_accuracy_m\":%.1f,\"anchor_age_s\":%.1f",point->id,kind,point->lat,point->lon,point->accuracy,lat,lon,position.uncertainty,epoch()-fix_time);
 else record("\"e\":\"sense_fix\",\"id\":\"%s\",\"source\":\"%s\",\"lat\":%.7f,\"lon\":%.7f,\"accuracy_m\":%.1f,\"predicted_lat\":null,\"predicted_lon\":null",point->id,kind,point->lat,point->lon,point->accuracy);
 position_fix(&position,point->lat,point->lon,point->accuracy);fix_time=position_time=epoch();snprintf(fix_name,sizeof fix_name,"%s",point->label);snprintf(source,sizeof source,"%s",kind);stationary_peaks=0;
}
static void command(char *line)
{
 if(!strcmp(line,"calibrate")){cal_started=mono();cal_until=cal_started+40;nsamples=0;cal_failed=0;heading=NAN;record("\"e\":\"sense_calibration_start\"");}
 else if(!strcmp(line,"target shop"))target_override=0;
 else if(!strcmp(line,"target bus"))target_override=1;
 else if(!strcmp(line,"cancel")){cal_until=0;record("\"e\":\"sense_calibration_cancel\"");}
 else if(!strcmp(line,"mode walk")){walking=1;record("\"e\":\"sense_mode\",\"mode\":\"walk\"");}
 else if(!strcmp(line,"mode bus")){walking=0;record("\"e\":\"sense_mode\",\"mode\":\"bus\"");}
 else if(!strncmp(line,"fix ",4)&&safe_id(line+4))for(int i=0;i<npoints;i++)if(!strcmp(line+4,points[i].id)){walking=1;given_fix(&points[i],"given landmark");break;}
}
static void normalize_name(const char *in,char *out,size_t n)
{
 size_t used=0;for(;*in&&used+1<n;in++)if(isalnum((unsigned char)*in))out[used++]=tolower((unsigned char)*in);out[used]=0;
}
static void wifi_hint(const char *ssid)
{
 char seen[160];normalize_name(ssid,seen,sizeof seen);char path[600];filename(path,sizeof path,config,"wifi-hints.tsv");FILE *f=fopen(path,"r");if(!f)return;
 char line[256];while(fgets(line,sizeof line,f)){
  char id[40],name[160],key[160];if(sscanf(line,"%39s\t%159[^\n]",id,name)!=2)continue;
  normalize_name(name,key,sizeof key);
  if(strlen(key)>=6&&strstr(seen,key)){
   clean_label(name);publish("wifi_hint","Cached name match: %.65s; not a position fix",name);
   record("\"e\":\"sense_wifi_hint\",\"poi\":\"%s\",\"name\":\"%s\",\"age\":\"unknown\",\"position_fix\":false",id,name);break;
  }
 }fclose(f);
}
static void wifi(void)
{
 /* n90-wifi uses nl80211 directly; this phone has no supplicant. Read the
  * kernel's cached BSS entries with their real age, without forcing a scan. */
 char line[512],path[600];int seen=0,fresh=0;
 publish("wifi_hint","No matched landmark in cached sightings");
 FILE *f=popen("/usr/sbin/n90-wifi sightings 2>/dev/null","r");
 if(!f){publish("wifi","Unavailable");return;}
 while(fgets(line,sizeof line,f)){
  char mac[40],ssid[160];int freq,signal,age,associated;
  if(sscanf(line,"%39s\t%d\t%d\t%d\t%d\t%159[^\n]",mac,&freq,&signal,&age,&associated,ssid)!=6)continue;
  clean_label(ssid);seen++;if(age>=0&&age<=120000){fresh++;wifi_hint(ssid);}
  record("\"e\":\"sense_wifi\",\"bssid\":\"%s\",\"ssid\":\"%s\",\"signal_dbm\":%d,\"age_ms\":%d,\"associated\":%s",mac,ssid,signal,age,associated?"true":"false");
  if(!associated)continue;
  filename(path,sizeof path,config,"wifi-known.tsv");FILE *known=fopen(path,"r");if(!known)continue;
  char entry[256];while(fgets(entry,sizeof entry,known)){
   Checkpoint p={0};char expected[40];
   if(sscanf(entry,"%39s %lf %lf %lf %39s %79[^\n]",expected,&p.lat,&p.lon,&p.accuracy,p.id,p.label)==6&&safe_id(p.id)&&!strcasecmp(expected,mac)){
    clean_label(p.label);if(strcmp(source,"known Wi-Fi")||epoch()-fix_time>120)given_fix(&p,"known Wi-Fi");
   }
  }fclose(known);
 }
 int rc=pclose(f);if(rc)publish("wifi","Unavailable");else publish("wifi","%d cached sightings; %d under two minutes old",seen,fresh);
}
static void status(void)
{
 double now=epoch(),age=fix_time?now-fix_time:0;int good_heading=isfinite(heading)&&now-heading_time<2&&!cal_until;
 char heading_json[32]="null";if(good_heading)snprintf(heading_json,sizeof heading_json,"%.2f",heading);
 publish("heading",good_heading?"%.0f° true · calibrated estimate":"Unavailable · calibration or field check needed",heading);
 publish("steps","%d detected steps",steps);
 publish("position_source","%s",source);
 publish("position_name","%s",fix_name);
 publish("position_age",position.valid?"%.0f s since last fix":"Unavailable",age);
 publish("position_accuracy",position.valid?"±%.0f m model estimate":"Unavailable",position.uncertainty+fmax(0,now-position_time)*1.5);
 if(cal_until)publish("calibration","Figure eight: %.0f s left, away from metal",fmax(0,cal_until-mono()));
 else publish("calibration","%s",cal_failed?"Calibration rejected; try away from metal":calibration.valid?"Calibration fitted; compare a known bearing":"Not calibrated");
 int target=target_override>=0?target_override:(now>pickup);
 double metres=position_distance(&position,target);
 publish("target","%s",target?"Bus home":"Shop");
 if(metres>=0){
  int minutes=(int)ceil(metres/72);publish("distance","%.0f m mapped walk estimate",metres);publish("eta","About %d min plus crossings",minutes);
  if(!target){time_t leave=(time_t)(pickup-300-minutes*60);struct tm t;localtime_r(&leave,&t);publish("leave_by","%02d:%02d to reach shop five minutes early",t.tm_hour,t.tm_min);}
  else publish("leave_by","Use dated departures on Getting home");
 }else{publish("distance","Unavailable here; use route card");publish("eta","Unavailable");publish("leave_by","Use route card");}
 publish("mode","%s",walking?"Walking estimate":"On bus; last fix only");
 char position_json[512]="null",heading_age[32]="null";
 if(good_heading)snprintf(heading_age,sizeof heading_age,"%.3f",now-heading_time);
 if(position.valid){
  double lat,lon;position_latlon(&position,&lat,&lon);
  publish("position","%.5f, %.5f",lat,lon);
  snprintf(position_json,sizeof position_json,"{\"lat\":%.7f,\"lon\":%.7f,\"source\":\"%s\",\"fix_age_s\":%.1f,\"estimate_age_s\":%.1f,\"accuracy_m\":%.1f}",lat,lon,source,age,now-position_time,position.uncertainty+fmax(0,now-position_time)*1.5);
  record("\"e\":\"sense_position\",\"lat\":%.7f,\"lon\":%.7f,\"source\":\"%s\",\"fix_age_s\":%.1f,\"accuracy_m\":%.1f,\"steps\":%d",lat,lon,source,age,position.uncertainty,steps);
 }else publish("position","Unavailable · choose I'm here");
 publish("state.json","{\"schema\":1,\"time\":%.3f,\"position\":%s,\"source\":\"%s\",\"mode\":\"%s\",\"heading_deg\":%s,\"heading_age_s\":%s,\"heading_source\":\"AK8975 + LIS331 + WMM2025\",\"heading_accuracy_deg\":null,\"steps\":%d,\"journal_recording\":%s}",now,position_json,position.valid?source:"unavailable",walking?"walk":"bus",heading_json,heading_age,steps,journal?"true":"false");
 if(good_heading)record("\"e\":\"sense_heading\",\"heading_deg\":%.3f,\"mag_uT\":[%.3f,%.3f,%.3f],\"accel_g\":[%.4f,%.4f,%.4f]",heading,mag[0],mag[1],mag[2],acc[0],acc[1],acc[2]);
 publish("updated","%.3f",now);
}
int main(int argc,char **argv)
{
 if(argc>1)snprintf(config,sizeof config,"%s",argv[1]);
 if(argc>2)snprintf(root,sizeof root,"%s",argv[2]);
 umask(077);mkdir(root,0700);char path[600];filename(path,sizeof path,root,"lock");int lock=open(path,O_CREAT|O_RDWR,0600);if(lock<0||flock(lock,LOCK_EX|LOCK_NB))return 1;
 filename(path,sizeof path,config,"model.txt");FILE *f=fopen(path,"r");if(!f||fscanf(f,"%lf %lf %lf",&declination,&field,&pickup)!=3)return 1;fclose(f);
 if(!isfinite(field)||field<20||field>80||!isfinite(declination)||fabs(declination)>180)return 1;
 filename(path,sizeof path,config,"graph.txt");if(position_graph(path,&position))return 1;
 filename(path,sizeof path,config,"checkpoints.tsv");f=fopen(path,"r");if(!f)return 1;char line[512];
 while(npoints<CHECKPOINTS&&fgets(line,sizeof line,f)){Checkpoint p={0};if(sscanf(line,"%39s %lf %lf %lf %79[^\n]",p.id,&p.lat,&p.lon,&p.accuracy,p.label)==5&&safe_id(p.id)&&isfinite(p.lat)&&fabs(p.lat)<85&&isfinite(p.lon)&&fabs(p.lon)<180&&p.accuracy>=5&&p.accuracy<=1000){clean_label(p.label);points[npoints++]=p;}}fclose(f);
 filename(path,sizeof path,root,"checkpoints");f=fopen(path,"w");if(f){for(int i=0;i<npoints;i++)fprintf(f,"%s\t%s\n",points[i].id,points[i].label);fclose(f);}
 filename(path,sizeof path,root,"journal.jsonl");journal=fopen(path,"ae");
 filename(path,sizeof path,root,"control");if(mkfifo(path,0600)&&errno!=EEXIST)return 1;int ctl=open(path,O_RDWR|O_NONBLOCK);if(ctl<0)return 1;
 signal(SIGTERM,shutdown_handler);signal(SIGINT,shutdown_handler);signal(SIGHUP,shutdown_handler);
 sensors_open(&sensors,"/dev/i2c-0","/dev/i2c-2");load_calibration();srand((unsigned)time(NULL));
 record("\"e\":\"sense_start\",\"mag_selftest\":%s,\"accel_id\":%s,\"calibrated\":%s",sensors.mag_ok?"true":"false",sensors.accel_ok?"true":"false",calibration.valid?"true":"false");
 double gravity=1,next_mag=0,next_status=0,next_wifi=0,accel_time=-10,tilt[3]={0};int armed=0,overflow=0;size_t used=0;char commands[128];
 while(!stop){
  double now=mono();if(!sensor_accel(&sensors,acc)){
   if(accel_time<0)memcpy(tilt,acc,sizeof tilt);
   else for(int k=0;k<3;k++)tilt[k]+=.05*(acc[k]-tilt[k]);
   accel_time=now;
   double norm=sqrt(acc[0]*acc[0]+acc[1]*acc[1]+acc[2]*acc[2]);gravity+=.015*(norm-gravity);double high=norm-gravity;
   if(high<-.07)armed=1;
   if(armed&&high>.12&&now-last_step>.30){
    armed=0;if(now-last_step<1.6)stationary_peaks++;else stationary_peaks=1;last_step=now;
    if(stationary_peaks>=3&&walking&&!cal_until){steps++;int hgood=isfinite(heading)&&epoch()-heading_time<1.5;
     if(hgood&&position.valid&&!position_step(&position,heading,stride)){position_time=epoch();snprintf(source,sizeof source,"steps + calibrated compass");}
     char htext[32]="null";if(hgood)snprintf(htext,sizeof htext,"%.2f",heading);
     record("\"e\":\"sense_step\",\"steps\":%d,\"heading_deg\":%s,\"heading_valid\":%s,\"stride_m\":%.2f,\"accel_g\":[%.4f,%.4f,%.4f]",steps,htext,hgood?"true":"false",stride,acc[0],acc[1],acc[2]);
    }
   }
  }
  if(now>=next_mag){next_mag=now+.125;if(!sensor_mag(&sensors,mag,0)){
   if(cal_until&&nsamples<CAL_MAX){memcpy(samples[nsamples++],mag,sizeof mag);record("\"e\":\"sense_calibration_sample\",\"mag_uT\":[%.4f,%.4f,%.4f]",mag[0],mag[1],mag[2]);}
   if(now-accel_time<.2&&!compass_heading(&calibration,mag,tilt,field,declination,&heading))heading_time=epoch();else heading=NAN;
  }else heading=NAN;}
  if(cal_until&&now>=cal_until){cal_until=0;Calibration c={0};if(!calibrate(samples,nsamples,field,&c)){calibration=c;save_calibration();cal_failed=0;}else cal_failed=1;record("\"e\":\"sense_calibration_result\",\"samples\":%d,\"passed\":%s,\"rms_uT\":%.3f",nsamples,cal_failed?"false":"true",c.rms);}
  if(now>=next_status){status();next_status=now+1;}
  if(now>=next_wifi){wifi();next_wifi=now+60;}
  struct pollfd pfd={ctl,POLLIN,0};poll(&pfd,1,15);
  if(pfd.revents&POLLIN){char b[256];ssize_t n=read(ctl,b,sizeof b);for(ssize_t i=0;i<n;i++){if(b[i]=='\n'){commands[used]=0;if(!overflow)command(commands);used=0;overflow=0;}else if(!overflow&&used<sizeof commands-1)commands[used++]=b[i];else overflow=1;}}
 }
 sensors_close(&sensors);record("\"e\":\"sense_stop\"");if(journal)fclose(journal);publish("updated","0");close(ctl);close(lock);return 0;
}
