"""Private, source-grounded graph and checkpoint inputs for n90-sense."""
import datetime,heapq,json,math,subprocess
from pathlib import Path
from zoneinfo import ZoneInfo
from graph import distance

def build_sense(graph,config,records,out,wmm,cof):
    out=Path(out);out.mkdir(parents=True,exist_ok=True,mode=0o700)
    shop=config['destination']['point'];bus=records['return']['legs'][0]['route']['end']
    home=[config['home']['latitude'],config['home']['longitude']]
    def point(id,label,xy,accuracy=15):return dict(id=id,label=label,point=xy,accuracy=accuracy)
    return_ride=next(l for l in records['return']['legs'] if l['mode']=='ride')
    bus_stop=records['stops'][return_ride['from']]
    checkpoints=[point('shop',config['destination']['tags'].get('name','Destination'),shop),
                 point('bus-home',bus_stop['stop_code']+' '+bus_stop['stop_name'],bus)]
    checkpoints += [point('walk-'+str(i),w['poi']['tags'].get('name','Walk '+str(i+1)),w['poi']['point']) for i,w in enumerate(records.get('walks',[]))]
    checkpoints += [point('home','Home',home,30)]
    priority=config.get('checkpoint_order',[])
    checkpoints.sort(key=lambda p:priority.index(p['id']) if p['id'] in priority else len(priority))
    for direction in ('outbound','return'):
        for leg in records[direction]['legs']:
            if leg['mode']=='ride':
                for endpoint in ('from','to'):
                    stop=records['stops'][leg[endpoint]];id='stop-'+stop['stop_code']
                    if any(p['id']==id for p in checkpoints):continue
                    checkpoints.append(point(id,(stop['stop_code']+' '+stop['stop_name'])[:60],[float(stop['stop_lat']),float(stop['stop_lon'])],25))
    (out/'checkpoints.tsv').write_text(''.join(f"{p['id']}\t{p['point'][0]}\t{p['point'][1]}\t{p['accuracy']}\t{p['label'].replace(chr(9),' ')}\n" for p in checkpoints))
    # Dijkstra on the reversed directed graph: legal distances TO each target.
    reverse={}
    for a,adj in graph.adj.items():
        for b,d,w in adj:reverse.setdefault(b,[]).append((a,d))
    def reach(target):
        a,b,d,w,t,q,gap=graph.snap(target);cost={}
        if any(v==b and wid==w for v,_,wid in graph.adj[a]):cost[a]=d*t+gap
        if any(v==a and wid==w for v,_,wid in graph.adj[b]):cost[b]=d*(1-t)+gap
        queue=[(v,k) for k,v in cost.items()];heapq.heapify(queue)
        while queue:
            c,n=heapq.heappop(queue)
            if c!=cost[n]:continue
            for v,d in reverse.get(n,[]):
                new=c+d
                if new<6000 and new<cost.get(v,math.inf):cost[v]=new;heapq.heappush(queue,(new,v))
        return cost
    distances=[reach(shop),reach(bus)]
    lat0,lon0=shop
    def xy(p):return ((p[1]-lon0)*111195.08*math.cos(math.radians(lat0)),(p[0]-lat0)*111195.08)
    # Include the entire pedestrian neighbourhood around route checkpoints,
    # rather than force particles onto the single planned line.
    centres=[p['point'] for p in checkpoints];edges=[]
    for a,b,d,w in graph.edges:
        aa,bb=graph.nodes[a],graph.nodes[b]
        if not any(distance(aa,c)<1800 or distance(bb,c)<1800 for c in centres):continue
        vals=[*xy(aa),*xy(bb)]
        for costs in distances:vals += [costs.get(a,-1),costs.get(b,-1)]
        edges.append(' '.join(f'{x:.3f}' for x in vals))
    if len(edges)>80000:raise ValueError('Sense graph exceeds bounded phone capacity')
    (out/'graph.txt').write_text(f'{lat0} {lon0}\n'+'\n'.join(edges)+'\n')
    day=datetime.date.fromisoformat(config['date']);year=day.year+(day-datetime.date(day.year,1,1)).days/(datetime.date(day.year+1,1,1)-datetime.date(day.year,1,1)).days
    result=subprocess.run([str(wmm),str(cof)],input=f'{year} 0 {lat0} {lon0}\n',text=True,capture_output=True,check=True)
    model=json.loads(result.stdout);(out/'wmm.json').write_text(json.dumps(model,indent=2))
    pickup=datetime.datetime.fromisoformat(config['date']+'T'+config['pickup']).replace(tzinfo=ZoneInfo('Pacific/Auckland')).timestamp()
    (out/'model.txt').write_text(f"{model['declination_deg']} {model['field_uT']} {pickup}\n")
    (out/'wifi-known.tsv').touch(exist_ok=True)
    (out/'wifi-hints.tsv').write_text(''.join(str(p['id'])+'\t'+p['tags'].get('name','').replace(chr(9),' ').replace(chr(10),' ')+'\n' for p in config.get('wifi_landmarks',[]) if p.get('tags',{}).get('name')))
    (out/'manifest.json').write_text(json.dumps({'schema':1,'graph_edges':len(edges),'checkpoints':len(checkpoints),'graph_source':graph.__class__.__name__,'position':None,'model':model,'date':config['date']},indent=2))
    return {'edges':len(edges),'checkpoints':len(checkpoints),'position_initialized':False}
