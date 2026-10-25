#!/usr/bin/env python3
"""Build small sensor tools and the pinned, public-domain NOAA WMM2025 caller."""
import argparse,hashlib,json,os,shutil,subprocess,urllib.request,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--cc',default='cc');p.add_argument('--static',action='store_true');p.add_argument('--kernel-src',type=Path);p.add_argument('--kernel-build',type=Path);p.add_argument('--kernel-cross');a=p.parse_args()
root=Path(__file__).resolve().parents[2];src=root/'kernel/n90-sense';out=root/'output/sense';out.mkdir(parents=True,exist_ok=True)
cc=[a.cc,'-O2','-Wall','-Wextra','-Wformat=2']+(['-static'] if a.static else [])
def build(name,files,extra=[]):subprocess.run([*cc,*[str(src/f) for f in files],*extra,'-lm','-o',str(out/name)],check=True)
build('n90-sense',['sense.c','sensors.c','calibration.c','position.c']);build('n90-sense-probe',['probe.c','sensors.c'])
url='https://www.ngdc.noaa.gov/geomag/WMM/data/WMM2025/wmm2025_Linux.zip';sha='e3a0fb9c9275f72574200456da20c3e7408dd7fa54e48abf3c4a0681b1ed3c2b';cache=root/'.cache/navigator/wmm2025';cache.mkdir(parents=True,exist_ok=True);archive=cache/'wmm2025_Linux.zip'
if not archive.exists():
 with urllib.request.urlopen(url,timeout=60) as response,archive.with_suffix('.download').open('wb') as f:shutil.copyfileobj(response,f)
 archive.with_suffix('.download').rename(archive)
if hashlib.sha256(archive.read_bytes()).hexdigest()!=sha:raise SystemExit('WMM archive hash mismatch')
folder=cache/'wmm2025_Linux'
if not folder.exists():
 with zipfile.ZipFile(archive) as z:
  for item in z.infolist():
   if '..' in Path(item.filename).parts or Path(item.filename).is_absolute():raise SystemExit('Unsafe upstream archive')
  z.extractall(cache)
upstream=folder/'src';build('n90-wmm',['wmm.c'],['-ffunction-sections','-fdata-sections','-I',str(upstream),str(upstream/'GeomagnetismLibrary.c'),'-Wl,--gc-sections'])
subprocess.run(['cc','-O2','-ffunction-sections','-fdata-sections','-I',str(upstream),str(src/'wmm.c'),str(upstream/'GeomagnetismLibrary.c'),'-Wl,--gc-sections','-lm','-o',str(out/'wmm-native')],check=True)
shutil.copyfile(folder/'data/WMM.COF',out/'WMM.COF')
if a.kernel_src or a.kernel_build or a.kernel_cross:
 if not all((a.kernel_src,a.kernel_build,a.kernel_cross)):p.error('Module requires all three kernel arguments')
 mod=out/'module';mod.mkdir(exist_ok=True);shutil.copyfile(src/'n90-i2c2.c',mod/'n90-i2c2.c');(mod/'Makefile').write_text('obj-m += n90-i2c2.o\n')
 subprocess.run(['make','-C',str(a.kernel_src.resolve()),'O='+str(a.kernel_build.resolve()),'ARCH=arm','CROSS_COMPILE='+a.kernel_cross,'M='+str(mod),'-j2','modules'],check=True)
receipt={'wmm_source':url,'wmm_sha256':sha,'wmm_license':'Public domain, United States Government work (NOAA/NCEI); no use restrictions','compiler':subprocess.check_output([a.cc,'--version'],text=True).splitlines()[0],'artifacts':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in [out/'n90-sense',out/'n90-sense-probe',out/'n90-wmm',out/'WMM.COF']}}
(out/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(out)
