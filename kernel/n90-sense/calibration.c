// SPDX-License-Identifier: GPL-2.0-only
/* A full 3-D ellipsoid fit estimates hard-iron offset and a symmetric
 * soft-iron correction. Reject poor coverage, degeneracy and field anomalies.
 * A good fit is not an independent heading-accuracy measurement. */
#include "calibration.h"
#include <math.h>
#include <string.h>
static int solve(double a[9][10],int n,double *x)
{
 for(int k=0;k<n;k++){
  int p=k;for(int i=k+1;i<n;i++)if(fabs(a[i][k])>fabs(a[p][k]))p=i;
  if(fabs(a[p][k])<1e-9)return -1;
  for(int j=k;j<=n;j++){double t=a[k][j];a[k][j]=a[p][j];a[p][j]=t;}
  double d=a[k][k];for(int j=k;j<=n;j++)a[k][j]/=d;
  for(int i=0;i<n;i++)if(i!=k){d=a[i][k];for(int j=k;j<=n;j++)a[i][j]-=d*a[k][j];}
 }
 for(int i=0;i<n;i++)x[i]=a[i][n];
 return 0;
}
void calibrated(const Calibration *c,const double raw[3],double out[3])
{for(int i=0;i<3;i++){out[i]=0;for(int j=0;j<3;j++)out[i]+=c->matrix[i][j]*(raw[j]-c->center[j]);}}
int calibrate(const double s[][3],int n,double field,Calibration *out)
{
 if(n<120||n>CAL_MAX||field<20||field>80)return -1;
 double eq[9][10]={{0}},v[9],b[9];
 for(int k=0;k<n;k++){
  double x=s[k][0]/100,y=s[k][1]/100,z=s[k][2]/100;
  double row[9]={x*x,y*y,z*z,2*x*y,2*x*z,2*y*z,x,y,z};
  for(int i=0;i<9;i++){eq[i][9]+=row[i];for(int j=0;j<9;j++)eq[i][j]+=row[i]*row[j];}
 }
 if(solve(eq,9,b))return -1;
 double a[3][3]={{b[0],b[3],b[4]},{b[3],b[1],b[5]},{b[4],b[5],b[2]}};
 memset(eq,0,sizeof eq);
 for(int i=0;i<3;i++){for(int j=0;j<3;j++)eq[i][j]=a[i][j];eq[i][3]=-.5*b[i+6];}
 if(solve(eq,3,v))return -1;
 Calibration c={0};double den=1;
 for(int i=0;i<3;i++){c.center[i]=100*v[i];for(int j=0;j<3;j++)den+=v[i]*a[i][j]*v[j];}
 if(den<=0)return -1;
 double q[3][3],rot[3][3]={{1,0,0},{0,1,0},{0,0,1}};
 for(int i=0;i<3;i++)for(int j=0;j<3;j++)q[i][j]=a[i][j]/den;
 for(int it=0;it<30;it++){
  int p=0,r=1;for(int i=0;i<3;i++)for(int j=i+1;j<3;j++)if(fabs(q[i][j])>fabs(q[p][r])){p=i;r=j;}
  if(fabs(q[p][r])<1e-10)break;
  double angle=.5*atan2(2*q[p][r],q[r][r]-q[p][p]),co=cos(angle),si=sin(angle);
  /* R rotates columns p/r; Q <- R^T Q R. */
  for(int i=0;i<3;i++){double x=q[i][p],y=q[i][r];q[i][p]=co*x-si*y;q[i][r]=si*x+co*y;}
  for(int j=0;j<3;j++){double x=q[p][j],y=q[r][j];q[p][j]=co*x-si*y;q[r][j]=si*x+co*y;}
  for(int i=0;i<3;i++){double x=rot[i][p],y=rot[i][r];rot[i][p]=co*x-si*y;rot[i][r]=si*x+co*y;}
 }
 for(int k=0;k<3;k++){
  if(q[k][k]<=0)return -1;
  double scale=sqrt(q[k][k])*field/100;
  if(scale<.4||scale>2.5)return -1;
  for(int i=0;i<3;i++)for(int j=0;j<3;j++)c.matrix[i][j]+=rot[i][k]*scale*rot[j][k];
 }
 int octants=0;double residual=0;
 for(int k=0;k<n;k++){
  double x[3];calibrated(&c,s[k],x);double norm=sqrt(x[0]*x[0]+x[1]*x[1]+x[2]*x[2]);
  residual+=(norm-field)*(norm-field);octants|=1<<((x[0]>0)+2*(x[1]>0)+4*(x[2]>0));
 }
 c.rms=sqrt(residual/n);
 if(octants!=255||c.rms>field*.08)return -1;
 c.valid=1;*out=c;return 0;
}
static double dot(const double a[3],const double b[3]){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
static void cross(const double a[3],const double b[3],double o[3]){o[0]=a[1]*b[2]-a[2]*b[1];o[1]=a[2]*b[0]-a[0]*b[2];o[2]=a[0]*b[1]-a[1]*b[0];}
int compass_heading(const Calibration *c,const double mag[3],const double accel[3],double field,double decl,double *heading)
{
 if(!c->valid)return -1;
 double adjusted[3];calibrated(c,mag,adjusted);
 double norm=sqrt(dot(adjusted,adjusted));if(norm<field*.8||norm>field*1.2)return -1;
 /* N90 iOS device-tree orientation matrices, signed 8-bit entries. */
 double north[3]={-adjusted[1],-adjusted[0],-adjusted[2]};
 double down[3]={accel[1],-accel[0],-accel[2]};
 double g=sqrt(dot(down,down));if(g<.8||g>1.25)return -1;
 for(int i=0;i<3;i++)down[i]/=g;
 double forward[3]={0,1,0},vertical=dot(north,down),tilt=dot(forward,down);
 for(int i=0;i<3;i++){north[i]-=vertical*down[i];forward[i]-=tilt*down[i];}
 if(dot(forward,forward)<.12||dot(north,north)<36)return -1;
 double perpendicular[3];cross(north,forward,perpendicular);
 *heading=fmod(atan2(dot(perpendicular,down),dot(north,forward))*180/M_PI+decl+360,360);
 return 0;
}
