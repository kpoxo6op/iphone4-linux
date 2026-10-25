"""Dated GTFS schedules and a connection-scan public-transport router.

Service exceptions override weekly calendars. Times beyond 24:00 retain their
service-day meaning. Scheduled data is never represented as realtime. Foot
transfers use the pedestrian router, not straight lines across barriers.
"""
import bisect,csv,datetime,gzip,hashlib,io,json,math,os,zipfile
from collections import defaultdict
from pathlib import Path
from graph import distance

def seconds(s):
    h,m,v=map(int,s.split(':')); return h*3600+m*60+v

def clock(t):
    h,m=divmod(round(t)//60,60)
    return f'{h%24:02d}:{m:02d}'+(f' (+{h//24}d)' if h>=24 else '')

class Feed:
    def __init__(self,source,date,cache=None):
        self.date=datetime.date.fromisoformat(date); self.source=Path(source)
        sha=hashlib.file_digest(self.source.open('rb'),'sha256').hexdigest()
        if cache and Path(cache).exists():
            with gzip.open(cache,'rt') as f: d=json.load(f)
            if d.get('sha256')==sha and d.get('date')==date and d.get('schema')==2:
                self.__dict__.update({k:d[k] for k in ('stops','routes','trips','connections','transfers','provenance')}); self._index(); return
        z=zipfile.ZipFile(source)
        def rows(n):
            if n not in z.namelist(): return iter(())
            return csv.DictReader(io.TextIOWrapper(z.open(n),encoding='utf-8-sig'))
        info=list(rows('feed_info.txt')); day=self.date.strftime('%Y%m%d'); weekday=self.date.strftime('%A').lower()
        if info and (day<info[0].get('feed_start_date',day) or day>info[0].get('feed_end_date',day)):
            raise ValueError('Requested date is outside the GTFS feed validity range')
        services={r['service_id'] for r in rows('calendar.txt') if r['start_date']<=day<=r['end_date'] and r[weekday]=='1'}
        exceptions=[r for r in rows('calendar_dates.txt') if r['date']==day]
        for r in exceptions:
            if r['exception_type']=='1': services.add(r['service_id'])
            elif r['exception_type']=='2': services.discard(r['service_id'])
        self.routes={r['route_id']:r for r in rows('routes.txt')}
        self.trips={r['trip_id']:r for r in rows('trips.txt') if r['service_id'] in services}
        self.stops={r['stop_id']:r for r in rows('stops.txt') if r.get('stop_lat') and r.get('stop_lon')}
        self.transfers=list(rows('transfers.txt'))
        times=defaultdict(list)
        for r in rows('stop_times.txt'):
            if r['trip_id'] in self.trips and r['stop_id'] in self.stops:
                if not r.get('arrival_time') or not r.get('departure_time'):
                    raise ValueError('Untimed stop needs explicit interpolation; refusing fabricated times')
                times[r['trip_id']].append((int(r['stop_sequence']),r['stop_id'],seconds(r['arrival_time']),seconds(r['departure_time']),r.get('pickup_type','0'),r.get('drop_off_type','0')))
        frequencies=defaultdict(list)
        for r in rows('frequencies.txt'):
            if r['trip_id'] in self.trips:
                if r.get('exact_times')!='1': raise ValueError('Frequency service has no exact departures; cannot publish precise times')
                frequencies[r['trip_id']].append(r)
        self.connections=[]
        for trip,st in times.items():
            st.sort(); variants=[(trip,0)]
            if frequencies[trip]:
                variants=[]
                for f in frequencies[trip]:
                    for t in range(seconds(f['start_time']),seconds(f['end_time']),int(f['headway_secs'])):
                        key=trip+'@'+str(t); self.trips[key]=self.trips[trip]; variants.append((key,t-st[0][3]))
            for key,offset in variants:
                for a,b in zip(st,st[1:]):
                    dep=a[3]+offset; arr=b[2]+offset
                    if arr<dep: raise ValueError('Non-monotonic trip times')
                    self.connections.append((dep,arr,a[1],b[1],key,a[4] in ('','0'),b[5] in ('','0')))
        self.connections.sort()
        self.provenance={'url':'https://gtfs.at.govt.nz/gtfs.zip','sha256':sha,'feed_info':info,'service_date':date,'timezone':'Pacific/Auckland','active_services':sorted(services),'exceptions':exceptions,'kind':'scheduled, not live'}
        if not self.connections: raise ValueError('No scheduled services on requested date')
        if cache:
            d={k:getattr(self,k) for k in ('stops','routes','trips','connections','transfers','provenance')}; d.update(sha256=sha,date=date,schema=2)
            Path(cache).parent.mkdir(parents=True,exist_ok=True)
            with gzip.open(cache,'wt') as f: json.dump(d,f,separators=(',',':'))
            os.chmod(cache,0o600)
        self._index()

    def _index(self):
        self.departures=defaultdict(list); self.grid=defaultdict(list); self.walk_cache={}
        for c in self.connections: self.departures[c[2]].append(c)
        for sid,s in self.stops.items():
            s['point']=(float(s['stop_lat']),float(s['stop_lon']))
            # A terminal stop can be an alighting target without ever having a
            # departing connection. Excluding it loses otherwise valid trips.
            self.grid[self.cell(s['point'])].append(sid)
        self.transfer_min={}; self.forbidden=set()
        for t in self.transfers:
            k=(t['from_stop_id'],t['to_stop_id'])
            if t.get('transfer_type')=='3': self.forbidden.add(k)
            if t.get('min_transfer_time'): self.transfer_min[k]=int(t['min_transfer_time'])

    @staticmethod
    def cell(p): return math.floor(p[0]*200),math.floor(p[1]*200)

    def nearby(self,p,radius):
        y,x=self.cell(p); r=math.ceil(radius/400)+1; result=[]
        for yy in range(y-r,y+r+1):
            for xx in range(x-r,x+r+1):
                for sid in self.grid.get((yy,xx),()):
                    if distance(p,self.stops[sid]['point'])<=radius: result.append(sid)
        return result

    def walking(self,graph,p,sids,reverse=False,max_metres=1300):
        if not reverse:
            return graph.distances_to(p,{sid:self.stops[sid]['point'] for sid in sids},limit=max_metres)
        result={}
        for sid in sids:
            try:
                q=self.stops[sid]['point']; route=graph.route(q,p,limit=max_metres) if reverse else graph.route(p,q,limit=max_metres)
                if route['metres']<=max_metres: result[sid]=route
            except ValueError: pass
        return result

    def transfers_from(self,graph,sid):
        if sid in self.walk_cache: return self.walk_cache[sid]
        p=self.stops[sid]['point']; paths=self.walking(graph,p,[s for s in self.nearby(p,1000) if s!=sid and (sid,s) not in self.forbidden],max_metres=1300)
        self.walk_cache[sid]=paths; return paths

    def journey(self,graph,start,end,depart,types=('3',),max_walk=1300,transfer_slack=180,max_rides=2):
        origins=self.walking(graph,start,self.nearby(start,max_walk),max_metres=max_walk)
        targets=self.walking(graph,end,self.nearby(end,max_walk),reverse=True,max_metres=max_walk)
        # Stop labels retain the boarding count: the fastest three-bus path
        # must not erase a usable one-bus arrival before a simple connection.
        reached={}; boarded={}
        for sid,path in origins.items():
            t=depart+math.ceil(path['metres']/1.2)
            reached[sid,0]=(t,({'mode':'walk','from':'origin','to':sid,'depart':depart,'arrive':t,'route':path},None,path['metres']))
        best=math.inf; final=None
        for dep,arr,fr,to,trip,pickup,dropoff in self.connections:
            if dep<depart: continue
            if dep>best: break
            rt=self.routes[self.trips[trip]['route_id']]
            if rt['route_type'] not in types: continue
            for rides in range(1,max_rides+1):
                state=boarded.get((trip,rides))
                if pickup and (fr,rides-1) in reached:
                    at,path=reached[fr,rides-1]
                    slack=max(transfer_slack,self.transfer_min.get((fr,fr),0))
                    if at+slack<=dep and (state is None or path[2]<state[2]): state=path
                if state is None: continue
                leg={'mode':'ride','trip':trip,'route':rt['route_short_name'],'headsign':self.trips[trip].get('trip_headsign',''),'from':fr,'to':to,'depart':dep,'arrive':arr}
                state=(leg,state,state[2]); boarded[trip,rides]=state
                old=reached.get((to,rides))
                if not dropoff or (old and (arr>old[0] or (arr==old[0] and state[2]>=old[1][2]))): continue
                reached[to,rides]=(arr,state)
                if to in targets:
                    path=targets[to]; finish=arr+math.ceil(path['metres']/1.2)
                    total_walk=state[2]+path['metres']
                    if finish<best or (finish==best and (final is None or total_walk<final[2])):
                        best=finish; final=({'mode':'walk','from':to,'to':'destination','depart':arr,'arrive':finish,'route':path},state,total_walk)
                if rides==max_rides: continue
                for other,path in self.transfers_from(graph,to).items():
                    t=arr+max(math.ceil(path['metres']/1.2),self.transfer_min.get((to,other),0))
                    old=reached.get((other,rides)); total_walk=state[2]+path['metres']
                    if old is None or t<old[0] or (t==old[0] and total_walk<old[1][2]):
                        reached[other,rides]=(t,({'mode':'walk','from':to,'to':other,'depart':arr,'arrive':t,'route':path},state,total_walk))
        if final is None: raise ValueError('No dated journey with mapped walking connections')
        legs=[]
        while final:
            leg,final,_=final; legs.append(leg)
        legs.reverse(); grouped=[]
        for leg in legs:
            if grouped and leg['mode']=='ride' and grouped[-1]['mode']=='ride' and grouped[-1]['trip']==leg['trip']:
                grouped[-1]['stops'].append(leg['to']); grouped[-1]['to']=leg['to']; grouped[-1]['arrive']=leg['arrive']
            else:
                leg=leg.copy()
                if leg['mode']=='ride': leg['stops']=[leg['from'],leg['to']]
                grouped.append(leg)
        for leg in grouped:
            if leg['mode']=='walk':
                r=leg['route']; leg['route']=graph.route(r['start'],r['end'],limit=max_walk+200)
        return {'depart':depart,'arrive':best,'legs':grouped,'service_date':str(self.date),'kind':'scheduled','transfer_slack_seconds':transfer_slack,'walking_mps':1.2,'max_rides':max_rides}

    def times(self,sid,route=None,after=0,before=30*3600):
        seen=set(); result=[]
        for dep,arr,fr,to,trip,pickup,_ in self.departures.get(sid,()):
            r=self.routes[self.trips[trip]['route_id']]['route_short_name']
            if pickup and after<=dep<=before and (not route or route==r) and (dep,trip) not in seen:
                seen.add((dep,trip)); result.append({'seconds':dep,'time':clock(dep),'route':r,'trip':trip,'headsign':self.trips[trip].get('trip_headsign','')})
        return result
