// SPDX-License-Identifier: GPL-2.0-only
/* Meeus solar equations, following NOAA/GML's public-domain calculator:
 * https://gml.noaa.gov/grad/solcalc/azel.html
 * This small implementation computes a geometric direction, not a position
 * fix or a guarantee about a visible shadow. Atmospheric refraction is omitted.
 */
#include "solar.h"
#include <math.h>
static double rad(double d){return d*0.017453292519943295;}
static double deg(double r){return r*57.29577951308232;}
static double wrap(double x,double period){x=fmod(x,period);return x<0?x+period:x;}
int solar_direction(double utc,double lat,double lon,double *az,double *el)
{
 if(!isfinite(utc)||utc<-2177452800.0||utc>=4102444800.0||!isfinite(lat)||fabs(lat)>85||!isfinite(lon)||fabs(lon)>180)return -1;
 double t=(utc/86400.0+2440587.5-2451545.0)/36525.0;
 double l=rad(wrap(280.46646+t*(36000.76983+.0003032*t),360));
 double m=rad(357.52911+t*(35999.05029-.0001537*t));
 double e=.016708634-t*(.000042037+.0000001267*t);
 double center=sin(m)*(1.914602-t*(.004817+.000014*t))+sin(2*m)*(.019993-.000101*t)+sin(3*m)*.000289;
 double omega=rad(125.04-1934.136*t);
 double apparent=l+rad(center-.00569-.00478*sin(omega));
 double obliq=rad(23+(26+(21.448-t*(46.815+t*(.00059-t*.001813)))/60)/60+.00256*cos(omega));
 double decl=asin(sin(obliq)*sin(apparent));
 double y=tan(obliq/2);y*=y;
 double eq=4*deg(y*sin(2*l)-2*e*sin(m)+4*e*y*sin(m)*cos(2*l)-.5*y*y*sin(4*l)-1.25*e*e*sin(2*m));
 double hour=rad(wrap(wrap(utc,86400)/60+eq+4*lon,1440)/4-180),phi=rad(lat);
 double sine=sin(phi)*sin(decl)+cos(phi)*cos(decl)*cos(hour);
 *el=deg(asin(fmax(-1,fmin(1,sine))));
 *az=wrap(deg(atan2(sin(hour),cos(hour)*sin(phi)-tan(decl)*cos(phi)))+180,360);
 return 0;
}
