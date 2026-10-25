"""Independent route evidence, cached by exact request URL in private storage."""
import hashlib,json,time,urllib.request
from pathlib import Path

def osrm(start,end,directory):
    url=f'https://routing.openstreetmap.de/routed-foot/route/v1/driving/{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson&steps=true'
    p=Path(directory)/('osrm-'+hashlib.sha256(url.encode()).hexdigest()[:20]+'.json')
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists(): record=json.loads(p.read_text())
    else:
        with urllib.request.urlopen(url,timeout=30) as r: raw=r.read()
        record={'url':url,'fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'sha256':hashlib.sha256(raw).hexdigest(),'response':json.loads(raw)}
        p.write_text(json.dumps(record,indent=2));p.chmod(0o600);time.sleep(1.1)
    d=record['response']
    if d.get('code')!='Ok' or not d.get('routes'): raise ValueError('Independent router returned no route')
    return {'file':str(p),'url':url,'network_metres':d['routes'][0]['distance'],'endpoint_gaps':[w['distance'] for w in d['waypoints']],'response':d}
