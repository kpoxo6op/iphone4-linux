#!/usr/bin/env python3
"""Public process boundary: unknown position, given fixes, stale bindings and
journal replay. Uses isolated /run, never the phone or the host's real sensors.
These failures are unsafe to inject during a field walk; phone frame checks
own rendering cadence and actual hardware probes own the sensor identities.
"""
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--native',required=True,type=Path);p.add_argument('--sense',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--inside',action='store_true');a=p.parse_args()
root=Path(__file__).resolve().parents[2]
if not a.inside:
 a.out.mkdir(parents=True,exist_ok=False)
 raise SystemExit(subprocess.run(['unshare','--user','--map-root-user','--mount',sys.executable,__file__,'--inside','--native',str(a.native.resolve()),'--sense',str(a.sense.resolve()),'--out',str(a.out.resolve())]).returncode)
subprocess.run(['mount','-t','tmpfs','none','/run'],check=True)
out=a.out;config=out/'config';config.mkdir();scenes=out/'scenes';scenes.mkdir();run=Path('/run/soy');run.mkdir();sense_run=Path('/run/sense');sense_run.mkdir()
(config/'graph.txt').write_text('0 0\n0 0 0 1000 1000 0 0 1000\n');(config/'model.txt').write_text('0 50 1792971000\n');(config/'checkpoints.tsv').write_text('start 0 0 15 Start\nfinish .0089932 0 15 Finish\n');(config/'wifi-known.tsv').write_text('');(config/'wifi-hints.tsv').write_text('')
(scenes/'index').write_text('reader\n');(scenes/'reader.md').write_text('---\nid: reader\nlabel: Field boundary\n---\n# Position\n\n{{sense.position}}\n\n{{sense.position_source}}\n\n{{sense.position_accuracy}}\n\n'+('\n\nA route card must keep its reading position when the live estimate changes.'*20))
service=subprocess.Popen([str(a.sense),str(config),str(sense_run)],stdout=(out/'sense.log').open('w'),stderr=subprocess.STDOUT)
renderer=subprocess.Popen([str(a.native),'--headless','--assets',str(root/'soy/assets'),'--scenes',str(scenes),'--run',str(run),'--scene','reader'],stdout=(out/'renderer.log').open('w'),stderr=subprocess.STDOUT)
def wait(pred,seconds=8):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  assert renderer.poll() is None,'renderer exited'
  try:
   if pred():return
  except (FileNotFoundError,json.JSONDecodeError):pass
  time.sleep(.05)
 raise AssertionError('boundary state did not arrive')
def cmd(dir,text):
 with (dir/'control').open('w') as f:f.write(text+'\n')
def sense():return json.loads((sense_run/'state.json').read_text())
def status():return json.loads((run/'status.json').read_text())
def capture(name):
 f=run/'frame.ppm';f.unlink(missing_ok=True);cmd(run,'capture');wait(lambda:f.exists() and f.stat().st_size==640*960*3+15);data=f.read_bytes();(out/(name+'.ppm')).write_bytes(data);return data
checks={}
try:
 wait(lambda:(run/'control').exists() and sense()['position'] is None);unknown=capture('unknown');checks['no_position_from_planned_graph_origin']=True
 cmd(sense_run,'fix missing');cmd(sense_run,'x'*200+'fix start');time.sleep(1.1);assert sense()['position'] is None;checks['invalid_and_overlong_fix_rejected']=True
 cmd(sense_run,'fix start');wait(lambda:sense()['position'] is not None);assert sense()['heading_deg'] is None
 time.sleep(1.1);given=capture('given');assert given!=unknown;checks['binding_updates_existing_scene']=True
 cmd(run,'scroll 900');wait(lambda:status()['scroll']==900)
 cmd(sense_run,'fix finish');wait(lambda:sense()['position']['lat']>.008);time.sleep(1.1);assert status()['scroll']==900;checks['live_update_preserves_reading_position']=True
 fixes=[json.loads(x) for x in (sense_run/'journal.jsonl').read_text().splitlines() if json.loads(x)['e']=='sense_fix'];assert fixes[0]['predicted_lat'] is None and fixes[1]['predicted_lat']==0;checks['fix_logs_prediction_before_reset']=True
 service.terminate();service.wait(timeout=5);cmd(run,'scroll -9600');wait(lambda:status()['scroll']==0);time.sleep(1.2);stale=capture('stopped');assert stale!=given;checks['stopped_service_does_not_leave_live_position']=True
 sys.path.insert(0,str(root/'soy/tools'));import scene
 class Local:
  def run(self,command):return subprocess.check_output(['sh','-c',command])
 dest=out/'journal';n=scene.journal_pull(Local(),dest);assert n>0;assert scene.journal_pull(Local(),dest)==0;checks['independent_journals_pull_once']=True
 result={'passed':all(checks.values()),'scope':'Native processes in isolated /run; no hardware claim','checks':checks};(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
finally:
 for proc in (renderer,service):
  if proc.poll() is None:proc.terminate();proc.wait(timeout=8)
