// SPDX-License-Identifier: GPL-2.0-only
/* Thin, noninteractive caller of NOAA's public-domain WMM implementation.
 * Input lines: decimal year, WGS84 ellipsoid height (km), latitude, longitude.
 * The latitude/longitude are not echoed; the caller owns their private source.
 */
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "GeomagnetismHeader.h"
int main(int argc,char **argv)
{
 if(argc!=2){fprintf(stderr,"usage: n90-wmm WMM.COF < private-coordinates\n");return 2;}
 MAGtype_MagneticModel *models[1]={0};
 if(!MAG_robustReadMagModels(argv[1],&models,1) || !models[0])return 1;
 MAGtype_MagneticModel *model=models[0];
 MAGtype_MagneticModel *timed=MAG_AllocateModelMemory((model->nMax+1)*(model->nMax+2)/2);
 MAGtype_Ellipsoid ellipsoid;MAGtype_Geoid geoid;
 MAG_SetDefaults(&ellipsoid,&geoid);
 double year,height,lat,lon;
 while(scanf("%lf %lf %lf %lf",&year,&height,&lat,&lon)==4){
  if(!isfinite(year)||!isfinite(height)||!isfinite(lat)||!isfinite(lon)||year<model->epoch||year>=model->epoch+5||fabs(lat)>90||fabs(lon)>360||height< -1||height>850){fprintf(stderr,"Outside WMM model validity\n");return 1;}
  MAGtype_CoordGeodetic coord={0};coord.phi=lat;coord.lambda=lon;coord.HeightAboveEllipsoid=height;
  MAGtype_CoordSpherical spherical;MAGtype_Date date={0};date.DecimalYear=year;
  MAGtype_GeoMagneticElements field={0},error={0};
  MAG_GeodeticToSpherical(ellipsoid,coord,&spherical);
  MAG_TimelyModifyMagneticModel(date,model,timed);
  MAG_Geomag(ellipsoid,spherical,coord,timed,&field);
  MAG_WMMErrorCalc(field.H,&error);
  printf("{\"model\":\"WMM2025\",\"declination_deg\":%.6f,\"inclination_deg\":%.6f,\"field_uT\":%.6f,\"horizontal_uT\":%.6f,\"declination_model_error_deg\":%.6f,\"compass_region_usable\":%s}\n",field.Decl,field.Incl,field.F/1000,field.H/1000,error.Decl,field.H>6000?"true":"false");
 }
 MAG_FreeMagneticModelMemory(timed);MAG_FreeMagneticModelMemory(model);return 0;
}
