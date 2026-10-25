#!/usr/bin/env python3
"""Build an offline private trip pack from a request and cached OSM/GTFS.

The AI supplies a private profile with the given home and selected places;
this tool computes routes and dated schedules. It never infers current position.
Example: --request 'Town tomorrow 9:30, back by 13:00'.
"""
import argparse,datetime,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).parent/'nav'))
from graph import Graph,distance
from gtfs import Feed,seconds,clock
from pack import compose


def request_config(config,text,today=None):
    if not text: return config
    match=re.fullmatch(r'\s*(.+?)\s+(tomorrow|today|\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*,\s*back by\s+(\d{1,2}(?::\d{2})?)\s*',text,re.I)
    if not match: raise ValueError("Use 'Place tomorrow 9:30, back by 13:00'; AI resolves other wording into the private config")
    place,day,arrive,back=match.groups(); c=json.loads(json.dumps(config))
    today=today or datetime.datetime.now(ZoneInfo('Pacific/Auckland')).date()
    date=today+datetime.timedelta(days=day.lower()=='tomorrow') if day.lower() in ('today','tomorrow') else datetime.date.fromisoformat(day)
    candidates=[config['destination']]+config.get('alternatives',[])+config.get('places',[])
    matches=[d for d in candidates if place.casefold() in [d['tags'].get('name','').casefold(),*[a.casefold() for a in d.get('aliases',[])]]]
    if len(matches)!=1: raise ValueError('Place needs one explicit OSM selection in the private profile; no guessed destination')
    bh,bm=(back.split(':')+['00'])[:2]; bh=int(bh)
    if ':' not in back and bh<int(arrive.split(':')[0]) and bh<12: bh+=12
    c.update(destination=matches[0],date=str(date),arrive_by=arrive,back_by=f'{bh:02d}:{int(bm):02d}')
    changed=any(c[k]!=config[k] for k in ('date','arrive_by','back_by')) or c['destination']['id']!=config['destination']['id']
    if changed:
        c.pop('notes',None); c['walks']=[]
        c['pickup']=clock(seconds(arrive+':00')+3600)
        c['pickup_source']='assumed one hour after arrival; confirm with destination'
    return c


def plan(graph,config,feed):
    home=(config['home']['latitude'],config['home']['longitude']); dest=config['destination']['point']
    deadline=seconds(config['arrive_by']+':00')-600
    low=max(0,deadline-4*3600); high=deadline
    earliest=feed.journey(graph,home,dest,low)
    if earliest['arrive']>deadline: raise ValueError('No checked journey arriving ten minutes before appointment')
    # Arrive-by routing through the monotonic earliest-arrival boundary.
    while high-low>60:
        mid=(high+low)//2
        try: j=feed.journey(graph,home,dest,mid)
        except ValueError: high=mid; continue
        if j['arrive']<=deadline: low=mid
        else: high=mid
    outbound=feed.journey(graph,home,dest,low//300*300)
    pickup=seconds(config['pickup']+':00')
    back=feed.journey(graph,dest,home,pickup+1800)
    if back['arrive']>seconds(config['back_by']+':00'):
        raise ValueError('The planned pickup and return cannot meet the requested home-by time')
    walks=[{'poi':p,'route':graph.route(dest,p['point'])} for p in config.get('walks',[])]
    alternatives=[]
    for poi in config.get('alternatives',[]):
        entry={'poi':poi}
        for tag,a,b,t in [('outbound',home,poi['point'],outbound['depart']),('return',poi['point'],home,pickup+1800)]:
            try: entry[tag]=feed.journey(graph,a,b,t,max_rides=3)
            except ValueError as e: entry[tag]={'error':str(e)}
        alternatives.append(entry)
    schedules={}
    for j in [outbound,back]+[a[k] for a in alternatives for k in ('outbound','return')]:
        for leg in j.get('legs',[]):
            if leg['mode']=='ride': schedules[leg['from']+'|'+leg['route']]=feed.times(leg['from'],leg['route'])
    return {'outbound':outbound,'return':back,'walks':walks,'alternatives':alternatives,'stops':feed.stops,'departures':schedules,'gtfs':feed.provenance}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True); p.add_argument('--request')
    p.add_argument('--osm',type=Path,required=True); p.add_argument('--gtfs',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True); p.add_argument('--prepared',type=Path,help='Previously checked private route-data JSON; request overrides are not allowed')
    p.add_argument('--put',action='store_true'); p.add_argument('--operator',type=Path,default=Path(__file__).resolve().parents[2])
    a=p.parse_args(); os.umask(0o077); started=time.monotonic()
    if a.prepared and a.request: p.error('A prepared pack cannot be changed by a new request; recompute routes')
    # A public checkout must never accidentally acquire coordinates or scenes.
    a.out.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(a.out,0o700)
    root=Path(__file__).resolve().parents[2]
    for base in (root,a.operator.resolve()):
        try: relative=a.out.resolve().relative_to(base)
        except ValueError: continue
        check=subprocess.run(['git','-C',str(base),'check-ignore','-q',str(relative)],capture_output=True)
        if check.returncode: p.error('Output inside a checkout must be ignored by Git')
    config=request_config(json.loads(a.config.read_text()),a.request)
    raw=json.loads(a.osm.read_text()); graph=Graph(raw)
    feed=Feed(a.gtfs,config['date'],a.out/('gtfs-'+config['date']+'.json.gz'))
    records=json.loads(a.prepared.read_text()) if a.prepared else plan(graph,config,feed)
    for key in ('outbound','return'):
        if records[key]['service_date']!=config['date']: raise ValueError('Prepared journey date differs from trip date')
    if a.prepared:
        if records.get('gtfs',{}).get('sha256')!=feed.provenance['sha256']:
            raise ValueError('Prepared journeys need the same recorded GTFS hash')
        home=(config['home']['latitude'],config['home']['longitude']); dest=config['destination']['point']
        for key,start,end in [('outbound',home,dest),('return',dest,home)]:
            legs=records[key]['legs']
            if distance(legs[0]['route']['start'],start)>1 or distance(legs[-1]['route']['end'],end)>1:
                raise ValueError('Prepared journey endpoints differ from the private profile')
    scenes=compose(graph,config,records,a.out)
    manifest={'built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'seconds':round(time.monotonic()-started,3),'request':a.request,'service_date':config['date'],'osm':raw.get('provenance',{}),'gtfs':feed.provenance,'files':{str(f.relative_to(a.out)):hashlib.file_digest(f.open('rb'),'sha256').hexdigest() for f in scenes.iterdir() if f.is_file()},'position':'unavailable until measured or explicitly given','verification':'Independent route and departure checks plus phone capture/frame checks are separate release gates.'}
    (a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if a.put:
        subprocess.run([sys.executable,str(a.operator/'soy/tools/scene.py'),'put',str(scenes),'--show','-m','Offline trip pack'],cwd=a.operator,check=True)
    print(json.dumps({'scenes':len(manifest['files'])-1,'elapsed_seconds':round(time.monotonic()-started,2),'published':a.put,'position':'unavailable'}))

if __name__=='__main__': main()
