#!/usr/bin/env python3
"""Install bounded sense tools and private trip inputs without rebooting."""
import argparse,hashlib,io,json,subprocess,tarfile,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--ssh-config',required=True,type=Path);p.add_argument('--host',default='iphone4-usb');p.add_argument('--config',required=True,type=Path);p.add_argument('--receipt',required=True,type=Path);a=p.parse_args()
root=Path(__file__).resolve().parents[2];out=root/'output/sense';ssh=['ssh','-F',str(a.ssh_config),'-o','BatchMode=yes','-o','ConnectTimeout=10',a.host]
def remote(command,data=None,timeout=30):return subprocess.run(ssh+[command],input=data,capture_output=True,check=True,timeout=timeout).stdout
files={n:out/n for n in ('n90-sense','n90-wmm','WMM.COF')};files['n90-i2c2.ko']=out/'module/n90-i2c2.ko'
for n in ('model.txt','graph.txt','checkpoints.tsv','wifi-known.tsv','wifi-hints.tsv','wmm.json','manifest.json'):files[n]=a.config/n
for name,path in files.items():
 if not path.is_file() or path.is_symlink():raise SystemExit('Missing regular input: '+name)
blob=io.BytesIO();hashes={}
with tarfile.open(fileobj=blob,mode='w') as tar:
 for name,path in files.items():
  data=path.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o700 if name in ('n90-sense','n90-wmm') else 0o600;tar.addfile(info,io.BytesIO(data))
# A known oops blocks a new load, regardless of model confidence.
remote('t=$(cat /proc/sys/kernel/tainted); test $((t & 128)) -eq 0 || exit 1; echo 0 > /proc/sys/kernel/panic_on_oops')
remote('mkdir -p /opt/n90-sense /run/sense /run/keep; chmod 700 /opt/n90-sense /run/sense; echo $(( $(date +%s) + 180 )) > /run/keep/hold-sense; '
       'p=; read -r p < /run/keep/sense.pid 2>/dev/null; if [ -n "$p" ] && [ "$(cat /proc/$p/comm 2>/dev/null)" = n90-sense ]; then kill "$p"; i=0; while kill -0 "$p" 2>/dev/null; do i=$((i+1)); test "$i" -lt 50 || exit 1; sleep .1; done; fi; '
       'tar -xf - -C /opt/n90-sense',blob.getvalue(),timeout=60)
checks='\n'.join(f'{value}  {name}' for name,value in hashes.items())+'\n'
remote('cd /opt/n90-sense && sha256sum -c -',checks.encode())
remote('''if [ ! -e /dev/i2c-2 ]; then
 echo $(( $(date +%s) + 86400 )) > /run/keep/hold-oops
 insmod /opt/n90-sense/n90-i2c2.ko || exit 1
fi
t=$(cat /proc/sys/kernel/tainted); test $((t & 128)) -eq 0 || exit 1
rm -f /run/sense/state.json
nohup /opt/n90-sense/n90-sense /opt/n90-sense /run/sense >/run/sense/service.log 2>&1 </dev/null &
echo $! > /run/keep/sense.pid
''')
deadline=time.monotonic()+30
while True:
 try:
  state=json.loads(remote('p=$(cat /run/keep/sense.pid); kill -0 "$p" && cat /run/sense/state.json'))
  break
 except (subprocess.CalledProcessError,json.JSONDecodeError):
  if time.monotonic()>=deadline:raise
  time.sleep(.5)
remote('rm -f /run/keep/hold-sense')
a.receipt.parent.mkdir(parents=True,exist_ok=True);a.receipt.write_text(json.dumps({'time':time.time(),'artifacts':hashes,'running':True,'state':state},indent=2)+'\n');print('Sense running; private receipt saved.')
