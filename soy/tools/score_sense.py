#!/usr/bin/env python3
"""Score pre-reset predictions against held-out, given field checkpoints.

The current fix is never used in the prediction being scored. Prior fixes may
anchor it. This is sequential checkpoint validation, not leave-one-trip-out.
Heading requires an independently supplied bearing event; fitted calibration
residuals are not heading truth. No GPS or synthetic examples count as field.
"""
import argparse,datetime,json,math,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('journal',type=Path);p.add_argument('--since',required=True,help='ISO timestamp with timezone delimiting the actual field trial');p.add_argument('--walk-metres',type=float,help='Independently established walking workload, not inferred from detected steps');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
start=datetime.datetime.fromisoformat(a.since)
if start.tzinfo is None:p.error('--since requires a timezone')
events=[json.loads(l) for l in a.journal.read_text().splitlines() if l.strip()];events=[e for e in events if e.get('t',0)>=start.timestamp()]
def distance(x,y):
 lat1,lon1,lat2,lon2=map(math.radians,(*x,*y));return 6371008.8*2*math.asin(min(1,math.sqrt(math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2)))
fixes=[];headings=[]
for e in events:
 if e.get('e')=='sense_fix' and e.get('source')=='given landmark' and e.get('predicted_lat') is not None and e.get('anchor_age_s',0)>=10:
  fixes.append({'t':e['t'],'id':e['id'],'error_m':distance((e['lat'],e['lon']),(e['predicted_lat'],e['predicted_lon'])),'given_accuracy_m':e.get('accuracy_m'),'model_accuracy_m':e.get('predicted_accuracy_m')})
 if e.get('e')=='sense_bearing_reference' and e.get('heading_valid') and e.get('independent_source'):
  headings.append(abs((e['heading_deg']-e['reference_deg']+180)%360-180))
median=statistics.median([e['error_m'] for e in fixes]) if fixes else None
heading=statistics.median(headings) if headings else None
workload=a.walk_metres is not None and a.walk_metres>=1000
result={'scope':'Given checkpoints, with current fix withheld; prior fixes may anchor estimates','checkpoint_samples':len(fixes),'median_position_error_m':median,'heading_reference_samples':len(headings),'median_heading_error_deg':heading,'worst_heading_error_deg':max(headings) if headings else None,'position_target_m':50,'heading_target_deg':5,'independent_walk_metres':a.walk_metres,'workload_pass':workload,'position_pass':None if median is None or not workload else median<50,'heading_pass':None if heading is None else max(headings)<=5,'status':'field_evidence_missing' if not fixes or not headings or not workload else 'scored','checkpoint_errors':fixes,'limits':['Given landmarks carry their own placement error.','No heading reference means no heading-accuracy result.','A 1 km field walk must be established separately; a short run cannot pass that workload.']}
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('checkpoint_errors','limits')}))
