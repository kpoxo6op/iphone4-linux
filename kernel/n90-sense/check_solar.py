#!/usr/bin/env python3
"""Compare the production solar direction with twelve NOAA calculator outputs.

Contract: UTC/east-longitude conversion and north-clockwise azimuth agree with
an outside calculator across hemispheres, seasons and the date line. Wrong
longitude signs or a timezone offset can reverse a field bearing. The existing
calibration vectors own magnetic orientation, not celestial time/coordinates.
"""
import ctypes,datetime,json,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='n90-solar-') as d:
 lib=Path(d)/'solar.so';subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(root/'solar.c'),'-lm','-o',str(lib)],check=True)
 f=ctypes.CDLL(str(lib)).solar_direction;f.argtypes=[ctypes.c_double]*3+[ctypes.POINTER(ctypes.c_double)]*2;f.restype=ctypes.c_int
 errors=[]
 for case in json.loads((root/'solar-reference.json').read_text())['cases']:
  az=ctypes.c_double();el=ctypes.c_double();t=datetime.datetime.fromisoformat(case['utc'].replace('Z','+00:00')).timestamp()
  assert f(t,case['lat'],case['lon'],ctypes.byref(az),ctypes.byref(el))==0
  err=abs((az.value-float(case['azimuth'])+180)%360-180);assert err<.011,(case,az.value,err);errors.append(err)
  # NOAA's elevation includes refraction; our geometric value is intentionally lower.
  assert abs(el.value-float(case['elevation_refracted']))<.07,(case,el.value)
 print(json.dumps({'scope':'Native calculation against NOAA published calculator; not field heading accuracy','cases':len(errors),'maximum_azimuth_difference_deg':max(errors),'passed':True}))
