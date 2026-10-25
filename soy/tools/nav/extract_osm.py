#!/usr/bin/env python3
"""Extract full road ways and named facilities from a Geofabrik OSM PBF.

Use pyosmium in a local venv. Output is raw OSM elements with provenance, suitable
for graph.py. The bbox includes all way vertices; no clipped road shortcuts.
"""
import argparse,hashlib,json,os,time
from pathlib import Path
import osmium
p=argparse.ArgumentParser(); p.add_argument('source',type=Path); p.add_argument('output',type=Path); p.add_argument('--bbox',required=True,help='south,west,north,east'); p.add_argument('--url',required=True); a=p.parse_args()
s,w,n,e=map(float,a.bbox.split(',')); elements=[]; nodes={}
def inside(lat,lon): return s<=lat<=n and w<=lon<=e
class Extract(osmium.SimpleHandler):
 def node(self,obj):
  if not obj.location.valid() or not inside(obj.location.lat,obj.location.lon): return
  tags=dict(obj.tags)
  if tags.get('amenity') in ('library','toilets','cafe','theatre','bus_station','ferry_terminal') or tags.get('craft')=='electronics_repair' or tags.get('shop') in ('mobile_phone','mall') or tags.get('natural') in ('beach','water') or tags.get('leisure') in ('park','garden') or tags.get('barrier') or tags.get('highway')=='bus_stop':
   nodes[obj.id]={'type':'node','id':obj.id,'lat':obj.location.lat,'lon':obj.location.lon,'tags':tags}
 def way(self,obj):
  tags=dict(obj.tags)
  if not ('highway' in tags or tags.get('leisure') in ('park','garden') or tags.get('natural') in ('beach','water','coastline') or tags.get('amenity') in ('library','toilets','cafe','theatre') or tags.get('shop') in ('mobile_phone','mall') or tags.get('craft')=='electronics_repair'): return
  ns=[(r.ref,r.lat,r.lon) for r in obj.nodes if r.location.valid()]
  if not any(inside(lat,lon) for _,lat,lon in ns): return
  for i,lat,lon in ns: nodes.setdefault(i,{'type':'node','id':i,'lat':lat,'lon':lon})
  elements.append({'type':'way','id':obj.id,'nodes':[i for i,_,_ in ns],'tags':tags,'center':{'lat':sum(lat for _,lat,_ in ns)/len(ns),'lon':sum(lon for _,_,lon in ns)/len(ns)}})
Extract().apply_file(str(a.source),locations=True,idx='flex_mem')
provenance={'url':a.url,'source_sha256':hashlib.file_digest(a.source.open('rb'),'sha256').hexdigest(),'extracted_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'licence':'ODbL 1.0','attribution':'OpenStreetMap contributors','bbox':[s,w,n,e]}
a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({'provenance':provenance,'elements':elements+list(nodes.values())},separators=(',',':'))); os.chmod(a.output,0o600)
print(json.dumps({'ways':len(elements),'nodes':len(nodes),'sha256':hashlib.file_digest(a.output.open('rb'),'sha256').hexdigest()}))
