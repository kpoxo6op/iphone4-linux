#!/usr/bin/env python3
"""Independent known-field rotations protect sign, orientation and soft-iron correction.
Physical probes cannot supply a known rotated field while the owner is asleep.
This reference check never establishes a field accuracy result. Requires NumPy.
"""
import ctypes as C,json,math,subprocess,os
from pathlib import Path
import numpy as np
os.chdir(Path(__file__).resolve().parents[2]);Path("output/sense").mkdir(parents=True,exist_ok=True)
subprocess.run(['cc','-O2','-shared','-fPIC','kernel/n90-sense/calibration.c','-lm','-o','output/sense/libcal.so'],check=True)
class Cal(C.Structure):_fields_=[('center',C.c_double*3),('matrix',(C.c_double*3)*3),('rms',C.c_double),('valid',C.c_int)]
l=C.CDLL(str(Path('output/sense/libcal.so').resolve()));l.calibrate.argtypes=[C.c_void_p,C.c_int,C.c_double,C.POINTER(Cal)];l.compass_heading.argtypes=[C.POINTER(Cal),C.c_void_p,C.c_void_p,C.c_double,C.c_double,C.POINTER(C.c_double)]
rng=np.random.default_rng(405);unit=rng.normal(size=(400,3));unit/=np.linalg.norm(unit,axis=1)[:,None]
soft=np.array([[1.2,.08,-.03],[.08,.85,.05],[-.03,.05,1.05]]);offset=np.array([12.,-8.,6.]);raw=np.ascontiguousarray(unit*50@soft+offset);c=Cal();assert l.calibrate(raw.ctypes.data,400,50,C.byref(c))==0
error=np.linalg.norm((raw-np.array(c.center))@np.array(c.matrix)-unit*50,axis=1);assert max(error)<1e-5
# Independent rotation: world x east, y north, z up. Heading rotates handset
# clockwise about world vertical; tilt rolls about handset's forward axis.
worst=0
for heading in range(0,360,15):
 for roll in (-35,0,35):
  h,r=np.radians([heading,roll]);yaw=np.array([[np.cos(h),np.sin(h),0],[-np.sin(h),np.cos(h),0],[0,0,1]]);tilt=np.array([[np.cos(r),0,np.sin(r)],[0,1,0],[-np.sin(r),0,np.cos(r)]]);body_to_world=yaw@tilt
  body_mag=body_to_world.T@np.array([0,30,-40.]);body_down=body_to_world.T@np.array([0,0,-1.])
  chip_mag=np.array([-body_mag[1],-body_mag[0],-body_mag[2]])@soft+offset;chip_acc=np.array([-body_down[1],body_down[0],-body_down[2]])
  got=C.c_double();assert l.compass_heading(C.byref(c),chip_mag.ctypes.data,chip_acc.ctypes.data,50,0,C.byref(got))==0
  err=abs((got.value-heading+180)%360-180);worst=max(worst,err)
assert worst<.001,worst
flat=np.ascontiguousarray(np.column_stack((np.cos(np.arange(400)),np.sin(np.arange(400)),np.zeros(400)))*50);bad=Cal();assert l.calibrate(flat.ctypes.data,400,50,C.byref(bad))!=0
interference=np.ascontiguousarray(chip_mag*4);got=C.c_double();assert l.compass_heading(C.byref(c),interference.ctypes.data,chip_acc.ctypes.data,50,0,C.byref(got))!=0
result={'scope':'Host mathematical reference; not physical calibration or heading accuracy','ellipsoid_vector_max_error_uT':float(max(error)),'72_orientation_cases_max_error_deg':worst,'flat_calibration_rejected':True,'magnetic_interference_rejected':True};Path('output/sense/calibration-check.json').write_text(json.dumps(result,indent=2));print(result)
