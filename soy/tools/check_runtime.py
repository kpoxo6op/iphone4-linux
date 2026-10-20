#!/usr/bin/env python3
"""Exercise the real renderer's public FIFO and pixels in a disposable bundle.

Contract: remote navigation/reload cannot lose the last valid scene or spawn a
second display writer. This catches parser/state regressions independently of
QEMU SSH tests. It does not simulate or certify the phone's touch hardware.
"""
import argparse,json,os,shutil,subprocess as sp,time,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--binary',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
root=Path(__file__).resolve().parents[1];out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
shutil.copytree(root/'scenes',out/'scenes');run=out/'run';run.mkdir()
args=[str(a.binary.resolve()),'--assets',str(root/'assets'),'--scenes',str(out/'scenes'),'--run',str(run),'--headless']
checks={};proc=None

def wait(pred,seconds=4):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  if proc.poll() is not None:raise RuntimeError('Renderer exited unexpectedly')
  try:
   status=json.loads((run/'status.json').read_text())
   if pred(status):return status
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.03)
 raise RuntimeError('Expected state did not arrive')

def command(text):
 with (run/'control').open('w') as f:f.write(text+'\n')

def pixels():
 path=run/'frame.ppm'
 if path.exists():path.unlink()
 command('capture')
 deadline=time.monotonic()+3
 while time.monotonic()<deadline:
  if path.exists() and path.stat().st_size==640*960*3+15:return hashlib.sha256(path.read_bytes()).hexdigest()
  time.sleep(.02)
 raise RuntimeError('No complete captured frame')

try:
 with (out/'runtime.log').open('w') as log:
  proc=sp.Popen(args,stdout=log,stderr=sp.STDOUT)
  wait(lambda s:s['scene']=='battery')
  duplicate=sp.run(args,capture_output=True,timeout=3)
  checks['single_writer']=duplicate.returncode!=0 and b'already running' in duplicate.stderr
  for expected in ('network','reader'):
   command('touch down 550 450\ntouch move 100 450\ntouch up 100 450')
   wait(lambda s:s['scene']==expected);time.sleep(.25)
  checks['horizontal_gesture_reaches_reader']=True
  # A release-only slide can pass navigation tests while still feeling broken.
  # Observe actual pixels before release, then prove cancellation restores them.
  before=pixels()
  command('touch down 500 450\ntouch move 440 450')
  time.sleep(.06)
  checks['drag_updates_before_release']=pixels()!=before
  command('touch up 440 450');time.sleep(.25)
  checks['short_drag_cancels']=wait(lambda s:s['scene']=='reader')['scroll']==0 and pixels()==before
  # Broad control regions must work without precision tapping a tiny mark.
  command('touch down 200 900\ntouch up 200 900')
  wait(lambda s:s['scene']=='network');time.sleep(.25)
  command('touch down 440 900\ntouch up 440 900')
  wait(lambda s:s['scene']=='reader');time.sleep(.25)
  checks['page_control_navigation']=True
  before=pixels();command('touch down 300 700\ntouch move 300 300\ntouch up 300 300')
  state=wait(lambda s:s['scroll']>0);time.sleep(.08)
  after=pixels();checks['vertical_gesture_scrolls_pixels']=before!=after
  scroll=state['scroll'];command('next');wait(lambda s:s['scene']=='files');time.sleep(.25)
  command('prev');wait(lambda s:s['scene']=='reader' and s['scroll']==scroll);time.sleep(.25)
  checks['reading_position_retained']=True
  (out/'scenes/hello.md').write_text('---\nid: hello\nlabel: HELLO\naccent: cyan\n---\n# Привет, мир.\n\n**A new scene** without a new binary.\n')
  index=(out/'scenes/index').read_text();(out/'scenes/index').write_text(index+'hello\n');command('reload');wait(lambda s:s['count']==6)
  command('goto hello');wait(lambda s:s['scene']=='hello');time.sleep(.25);before=pixels()
  checks['hot_add_scene']=True
  (out/'scenes/hello.md').write_text('broken bundle\n');command('reload');time.sleep(.15)
  state=wait(lambda s:s['scene']=='hello' and s['count']==6);after=pixels()
  checks['bad_reload_keeps_previous_pixels']=before==after
  (out/'scenes/index').write_text(index);command('reload');wait(lambda s:s['count']==5 and s['scene']=='battery')
  checks['remove_active_scene_recovers']=True
  command('quit');proc.wait(timeout=3);checks['clean_shutdown']=proc.returncode==0
finally:
 if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=3)
 result={'passed':bool(checks) and all(checks.values()),'checks':checks,'binary_sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'scope':'Host process boundary; synthetic gesture controls, NOT physical touch'}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
raise SystemExit(0 if result['passed'] else 1)
