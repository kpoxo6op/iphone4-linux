#!/usr/bin/env python3
"""Public route boundary checks: holiday service and forbidden shortcuts.

The real-data external checks own distance and timetable accuracy. This small
fixture owns calendar overrides and access failures that are unsafe to create
on the phone and need not occur in today's source feed. No hardware claims.
"""
import csv,io,json,sys,tempfile,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'nav'))
from graph import Graph
from gtfs import Feed,seconds,clock

nodes=[(1,0,0),(2,.001,0),(3,.001,.002),(4,0,.002),(5,.02,.02),(6,.02,.022)]
elements=[{'type':'node','id':n,'lat':a,'lon':b} for n,a,b in nodes]
def way(n,ns,**tags):return {'type':'way','id':n,'nodes':ns,'tags':{'highway':'footway',**tags}}
elements += [way(10,[1,2,3,4],name='Public path'),way(11,[1,4],access='private'),way(12,[5,6],name='Arrival path')]
g=Graph({'elements':elements}); route=g.route((0,0),(0,.002))
assert 440<route['metres']<450 and all(11 not in s['ways'] for s in route['steps'])
try: g.route((0,0),(.02,.02))
except ValueError: pass
else: raise AssertionError('Disconnected walking graphs must not be joined')
checks={'private_shortcut_excluded':True,'disconnected_walk_rejected':True}
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp)/'feed.zip'
 with zipfile.ZipFile(path,'w') as z:
  def table(name,header,rows):
   s=io.StringIO();w=csv.writer(s);w.writerow(header.split(','));w.writerows(rows);z.writestr(name+'.txt',s.getvalue())
  table('feed_info','feed_publisher_name,feed_start_date,feed_end_date',[['Fixture','20261026','20261026']])
  table('calendar','service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date',[['weekday',1,1,1,1,1,0,0,'20260101','20261231']])
  table('calendar_dates','service_id,date,exception_type',[['weekday','20261026',2],['holiday','20261026',1]])
  table('stops','stop_id,stop_code,stop_name,stop_lat,stop_lon',[['A','A','Origin',0,.002],['B','B','Arrival',.02,.02]])
  table('routes','route_id,route_short_name,route_type',[['R','7','3']])
  table('trips','route_id,service_id,trip_id,trip_headsign',[['R','weekday','removed','Wrong service'],['R','holiday','added','Holiday']])
  table('stop_times','trip_id,arrival_time,departure_time,stop_id,stop_sequence',[[trip,t,t,stop,seq] for trip in ('removed','added') for t,stop,seq in [('09:00:00','A',1),('09:20:00','B',2)]])
 f=Feed(path,'2026-10-26',Path(tmp)/'cache.gz'); j=f.journey(g,(0,0),(.02,.022),seconds('08:40:00'))
 assert [l['trip'] for l in j['legs'] if l['mode']=='ride']==['added']
 assert j['kind']=='scheduled' and j['service_date']=='2026-10-26'
 assert Feed(path,'2026-10-26',Path(tmp)/'cache.gz').times('A')[0]['trip']=='added'
 checks['calendar_exceptions_override_weekday_and_survive_cache']=True
 try: Feed(path,'2026-10-27')
 except ValueError: pass
 else: raise AssertionError('Expired feed must fail closed')
 checks['out_of_coverage_date_rejected']=True
assert seconds('25:05:00')==90300 and clock(90300)=='01:05 (+1d)'
checks['after_midnight_keeps_service_day']=True
print(json.dumps({'passed':True,'scope':'Synthetic public routing boundary; no hardware claims','checks':checks},indent=2))
