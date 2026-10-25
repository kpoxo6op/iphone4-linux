// SPDX-License-Identifier: GPL-2.0-only
/* Bootstrap particle filter on public pedestrian segments. The reference
 * origin only defines coordinates; it never initializes a position fix. */
#include "position.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#define MAX_EDGES 80000
#define MAX_LINKS 400000
#define HASH 16384
#define CELL 50.0
typedef struct {double x1,y1,x2,y2,d[4];} Edge;
typedef struct {int x,y,edge,next;} Link;
static Edge edges[MAX_EDGES];static Link links[MAX_LINKS];static int heads[HASH],ne,nl;
static unsigned hash(int x,int y){return ((uint32_t)x*73856093u^(uint32_t)y*19349663u)&(HASH-1);}
static double random01(void){return (rand()+.5)/(RAND_MAX+1.0);}
static double normal(void){return sqrt(-2*log(random01()))*cos(2*M_PI*random01());}
int position_graph(const char *path,Position *p)
{
 FILE *f=fopen(path,"r");if(!f)return -1;
 *p=(Position){0};for(int i=0;i<HASH;i++)heads[i]=-1;
 if(fscanf(f,"%lf %lf",&p->lat0,&p->lon0)!=2||!isfinite(p->lat0)||fabs(p->lat0)>85||!isfinite(p->lon0)||fabs(p->lon0)>180){fclose(f);return -1;}
 Edge e;ne=nl=0;
 while(fscanf(f,"%lf %lf %lf %lf %lf %lf %lf %lf",&e.x1,&e.y1,&e.x2,&e.y2,&e.d[0],&e.d[1],&e.d[2],&e.d[3])==8){
  if(ne==MAX_EDGES||!isfinite(e.x1)||!isfinite(e.y1)||!isfinite(e.x2)||!isfinite(e.y2)||fabs(e.x1)>200000||fabs(e.y1)>200000||fabs(e.x2)>200000||fabs(e.y2)>200000){fclose(f);return -1;}
  int x1=floor(fmin(e.x1,e.x2)/CELL),x2=floor(fmax(e.x1,e.x2)/CELL),y1=floor(fmin(e.y1,e.y2)/CELL),y2=floor(fmax(e.y1,e.y2)/CELL);
  if((x2-x1+1)*(y2-y1+1)>10000){fclose(f);return -1;}
  for(int x=x1;x<=x2;x++)for(int y=y1;y<=y2;y++){
   if(nl==MAX_LINKS){fclose(f);return -1;}unsigned h=hash(x,y);links[nl]=(Link){x,y,ne,heads[h]};heads[h]=nl++;
  }
  edges[ne++]=e;
 }
 fclose(f);return ne>0?0:-1;
}
static double nearest(double x,double y,double *ox,double *oy)
{
 double best=1e9;int cx=floor(x/CELL),cy=floor(y/CELL);
 for(int xx=cx-1;xx<=cx+1;xx++)for(int yy=cy-1;yy<=cy+1;yy++)for(int l=heads[hash(xx,yy)];l>=0;l=links[l].next){
  if(links[l].x!=xx||links[l].y!=yy)continue;
  Edge e=edges[links[l].edge];
  double dx=e.x2-e.x1,dy=e.y2-e.y1,den=dx*dx+dy*dy;if(den<.001)continue;
  double t=fmax(0,fmin(1,((x-e.x1)*dx+(y-e.y1)*dy)/den));double a=e.x1+t*dx,b=e.y1+t*dy,d=hypot(x-a,y-b);
  if(d<best){best=d;*ox=a;*oy=b;}
 }
 return best;
}
void position_fix(Position *p,double lat,double lon,double accuracy)
{
 if(!isfinite(lat)||!isfinite(lon)||fabs(lat)>85||fabs(lon)>180||!isfinite(accuracy)||accuracy<5||accuracy>1000)return;
 p->x=(lon-p->lon0)*111195.08*cos(p->lat0*M_PI/180);p->y=(lat-p->lat0)*111195.08;
 p->valid=1;p->travel=0;p->uncertainty=fmax(accuracy,10);
 for(int i=0;i<PARTICLES;i++){
  double x=p->x+normal()*accuracy*.4,y=p->y+normal()*accuracy*.4,a=x,b=y;
  if(nearest(x,y,&a,&b)<accuracy+15){x=a;y=b;}
  p->p[i]=(Particle){x,y,1.0/PARTICLES};
 }
}
int position_step(Position *p,double heading,double stride)
{
 if(!p->valid||!isfinite(heading)||!isfinite(stride)||stride<.2||stride>2)return -1;
 Particle next[PARTICLES];double total=0;
 for(int i=0;i<PARTICLES;i++){
  double h=(heading+normal()*15)*M_PI/180,d=fmax(.25,stride+normal()*.12);
  double x=p->p[i].x+sin(h)*d,y=p->p[i].y+cos(h)*d,a=x,b=y,dist=nearest(x,y,&a,&b);
  /* Do not jump across parallel roads: each constraint is local. */
  double w=dist<8?exp(-dist*dist/8):0;
  next[i]=(Particle){a,b,w};total+=w;
 }
 p->travel+=stride;p->uncertainty+=.15*stride;
 if(total<.0001){p->valid=0;return -1;}
 double start=random01()/PARTICLES,cumulative=next[0].w/total;int j=0;
 p->x=p->y=0;
 for(int i=0;i<PARTICLES;i++){
  double u=start+(double)i/PARTICLES;
  while(u>cumulative&&j<PARTICLES-1)cumulative+=next[++j].w/total;
  p->p[i]=(Particle){next[j].x,next[j].y,1.0/PARTICLES};p->x+=next[j].x/PARTICLES;p->y+=next[j].y/PARTICLES;
 }
 double variance=0;for(int i=0;i<PARTICLES;i++)variance+=pow(p->p[i].x-p->x,2)+pow(p->p[i].y-p->y,2);
 p->uncertainty=fmax(p->uncertainty,2.45*sqrt(variance/PARTICLES));return 0;
}
void position_latlon(const Position *p,double *lat,double *lon)
{*lat=p->lat0+p->y/111195.08;*lon=p->lon0+p->x/(111195.08*cos(p->lat0*M_PI/180));}

double position_distance(const Position *p,int target)
{
 if(!p->valid||target<0||target>1)return -1;
 double best=1e9,result=-1;int cx=floor(p->x/CELL),cy=floor(p->y/CELL);
 for(int xx=cx-1;xx<=cx+1;xx++)for(int yy=cy-1;yy<=cy+1;yy++)for(int l=heads[hash(xx,yy)];l>=0;l=links[l].next){
  if(links[l].x!=xx||links[l].y!=yy)continue;
  Edge e=edges[links[l].edge];double dx=e.x2-e.x1,dy=e.y2-e.y1,den=dx*dx+dy*dy;if(den<.001)continue;
  double t=fmax(0,fmin(1,((p->x-e.x1)*dx+(p->y-e.y1)*dy)/den));double d=hypot(p->x-e.x1-t*dx,p->y-e.y1-t*dy);
  if(d<best){best=d;double len=sqrt(den),a=e.d[target*2],b=e.d[target*2+1];result=fmin(a<0?1e9:a+t*len,b<0?1e9:b+(1-t)*len)+d;}
 }
 return best>80||result>10000?-1:result;
}
