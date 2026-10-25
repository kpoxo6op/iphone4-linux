"""Offline pedestrian routing over raw OSM ways (metres, WGS84).

No network or personal defaults. Routes preserve way provenance; private/no-foot
ways and motorways are excluded. Foot oneway, access barriers and disconnected
components are respected. Endpoint links are explicit and distance-bounded.
"""
import heapq
import math
from collections import defaultdict

R = 6371008.8

def distance(a, b):
    p, q = map(math.radians, (a[0], b[0]))
    d = math.radians(b[0] - a[0]); e = math.radians(b[1] - a[1])
    return 2 * R * math.asin(min(1, math.sqrt(math.sin(d/2)**2 + math.cos(p)*math.cos(q)*math.sin(e/2)**2)))

def bearing(a, b):
    p,q=map(math.radians,(a[0],b[0])); d=math.radians(b[1]-a[1])
    return math.degrees(math.atan2(math.sin(d)*math.cos(q), math.cos(p)*math.sin(q)-math.sin(p)*math.cos(q)*math.cos(d)))%360

def walkable(t):
    h=t.get('highway','')
    if h in ('','motorway','motorway_link','trunk','trunk_link','construction','proposed','raceway','bus_guideway'):
        return False
    foot=t.get('foot',t.get('access','yes'))
    if foot in ('no','private','customers','delivery','agricultural','forestry','use_sidepath'):
        return False
    if h=='cycleway' and t.get('foot') not in ('yes','designated','permissive','official'):
        return False
    return not (t.get('area')=='yes' or t.get('informal')=='yes' or t.get('ford')=='yes' or t.get('tidal')=='yes' or t.get('motorroad')=='yes' or t.get('impassable')=='yes')

class Graph:
    def __init__(self, data):
        els=data['elements']
        self.nodes={e['id']:(e['lat'],e['lon']) for e in els if e['type']=='node'}
        blocked=set()
        for e in els:
            t=e.get('tags',{}); access=t.get('foot',t.get('access'))
            if e['type']=='node' and (access in ('no','private') or (access is None and t.get('barrier') in ('yes','wall','fence'))): blocked.add(e['id'])
        self.ways={e['id']:e for e in els if e['type']=='way' and walkable(e.get('tags',{}))}
        self.map_ways=[e for e in els if e['type']=='way' and 'highway' in e.get('tags',{})]
        self.map_water=[e for e in els if e['type']=='way' and e.get('tags',{}).get('natural') in ('water','coastline')]
        self.adj=defaultdict(list); self.edges=[]; self.grid=defaultdict(list); self.snaps={}
        for wid,w in self.ways.items():
            ns=w.get('nodes',[]); t=w['tags']; direction=t.get('oneway:foot','no')
            for a,b in zip(ns,ns[1:]):
                if a not in self.nodes or b not in self.nodes or a in blocked or b in blocked: continue
                d=distance(self.nodes[a],self.nodes[b])
                if d<=0: continue
                if direction!='-1' and t.get('foot:forward')!='no': self.adj[a].append((b,d,wid))
                if direction not in ('yes','1','true') and t.get('foot:backward')!='no': self.adj[b].append((a,d,wid))
                self.edges.append((a,b,d,wid))
        # A grid avoids O(all edges) endpoint snaps. Each segment enters every
        # intersecting cell, so long streets do not disappear between vertices.
        for i,(a,b,_,_) in enumerate(self.edges):
            aa=self.cell(self.nodes[a]); bb=self.cell(self.nodes[b])
            for y in range(min(aa[0],bb[0]),max(aa[0],bb[0])+1):
                for x in range(min(aa[1],bb[1]),max(aa[1],bb[1])+1): self.grid[y,x].append(i)

    def edge_name(self,wid,a,b):
        tags=self.ways[wid]['tags']
        if tags.get('name'): return tags['name']
        kind=tags.get('highway','path').replace('_',' ')
        if tags.get('footway')!='sidewalk': return kind
        # OSM often maps sidewalks separately without repeating the street
        # name. Describe their actual, parallel neighbouring street explicitly.
        p=((a[0]+b[0])/2,(a[1]+b[1])/2); cy,cx=self.cell(p); near=[]
        for yy in range(cy-1,cy+2):
            for xx in range(cx-1,cx+2):
                for i in self.grid.get((yy,xx),()):
                    u,v,_,w=self.edges[i]; t=self.ways[w]['tags']
                    if not t.get('name') or t.get('highway') not in ('primary','secondary','tertiary','residential','unclassified'): continue
                    aa=self.nodes[u]; bb=self.nodes[v]; angle=abs((bearing(a,b)-bearing(aa,bb)+90)%180-90)
                    if angle>40: continue
                    x=math.cos(math.radians(p[0])); dx=(bb[1]-aa[1])*x; dy=bb[0]-aa[0]; den=dx*dx+dy*dy
                    f=max(0,min(1,((p[1]-aa[1])*x*dx+(p[0]-aa[0])*dy)/den)) if den else 0
                    q=(aa[0]+f*(bb[0]-aa[0]),aa[1]+f*(bb[1]-aa[1])); d=distance(p,q)
                    if d<=30: near.append((d,t['name']))
        return 'pavement beside '+min(near)[1] if near else 'pavement'

    @staticmethod
    def cell(p): return math.floor(p[0]*1000), math.floor(p[1]*1000)

    def snap(self,p,max_distance=100):
        p=tuple(p)
        if (p,max_distance) in self.snaps: return self.snaps[p,max_distance]
        cy,cx=self.cell(p); candidates=set()
        for y in range(cy-2,cy+3):
            for x in range(cx-2,cx+3): candidates.update(self.grid.get((y,x),()))
        scale=math.cos(math.radians(p[0])); best=None
        for i in candidates:
            a,b,d,w=self.edges[i]; pa=self.nodes[a]; pb=self.nodes[b]
            ax=(pa[1]-p[1])*scale; ay=pa[0]-p[0]; bx=(pb[1]-p[1])*scale; by=pb[0]-p[0]
            dx=bx-ax; dy=by-ay; den=dx*dx+dy*dy
            t=max(0,min(1,-(ax*dx+ay*dy)/den)) if den else 0
            q=(pa[0]+t*(pb[0]-pa[0]),pa[1]+t*(pb[1]-pa[1])); gap=distance(p,q)
            key=(gap,i)
            if best is None or key<best[0]: best=(key,(a,b,d,w,t,q,gap))
        if best is None or best[1][-1]>max_distance: raise ValueError('No mapped public walking access within endpoint limit')
        self.snaps[p,max_distance]=best[1]
        return best[1]

    def distances_to(self,start,ends,limit=1300,max_distance=100):
        """One bounded Dijkstra search for a whole set of nearby destinations.

        Returns route summaries; route() reconstructs any chosen itinerary.
        This is also the graph-distance instrument for walking-minute rings.
        """
        start=tuple(start)
        try: ss=self.snap(start,max_distance)
        except ValueError: return {}
        snaps={}
        for key,p in ends.items():
            try: snaps[key]=self.snap(p,max_distance)
            except ValueError: pass
        a,b,d,w,t,_,_=ss; costs={}; queue=[]
        if any(v==b and wid==w for v,_,wid in self.adj[a]): costs[b]=d*(1-t)
        if any(v==a and wid==w for v,_,wid in self.adj[b]): costs[a]=d*t
        for node,cost in costs.items(): heapq.heappush(queue,(cost,node))
        while queue:
            cost,n=heapq.heappop(queue)
            if cost!=costs[n] or cost>limit: continue
            for v,dd,ww in self.adj.get(n,()):
                new=cost+dd
                if new<=limit and new<costs.get(v,math.inf):
                    costs[v]=new; heapq.heappush(queue,(new,v))
        result={}
        for key,es in snaps.items():
            a,b,d,w,t,_,gap=es; best=math.inf
            forward=any(v==b and wid==w for v,_,wid in self.adj[a])
            backward=any(v==a and wid==w for v,_,wid in self.adj[b])
            if forward: best=min(best,costs.get(a,math.inf)+d*t)
            if backward: best=min(best,costs.get(b,math.inf)+d*(1-t))
            if ss[:2]==es[:2]:
                if t>=ss[4] and forward: best=min(best,(t-ss[4])*d)
                if t<=ss[4] and backward: best=min(best,(ss[4]-t)*d)
            total=best+ss[6]+gap
            if total<=limit: result[key]={'start':start,'end':ends[key],'metres':total,'endpoint_gaps':[ss[6],gap]}
        return result

    def route(self,start,end,max_distance=100,limit=100000):
        start=tuple(start); end=tuple(end)
        s=self.snap(start,max_distance); e=self.snap(end,max_distance)
        # Local virtual endpoints split the selected edges without changing
        # shared graph state. Directed access still applies to each half.
        extra=defaultdict(list); points={-1:s[5],-2:e[5]}
        for node,snap in ((-1,s),(-2,e)):
            a,b,d,w,t,_,_=snap
            if any(v==b and wid==w for v,_,wid in self.adj[a]):
                extra[a].append((node,d*t,w)); extra[node].append((b,d*(1-t),w))
            if any(v==a and wid==w for v,_,wid in self.adj[b]):
                extra[b].append((node,d*(1-t),w)); extra[node].append((a,d*t,w))
        if s[:2]==e[:2]:
            a,b,d,w=s[:4]
            if e[4]>=s[4] and any(v==b and wid==w for v,_,wid in self.adj[a]): extra[-1].append((-2,(e[4]-s[4])*d,w))
            if e[4]<=s[4] and any(v==a and wid==w for v,_,wid in self.adj[b]): extra[-1].append((-2,(s[4]-e[4])*d,w))
        costs={-1:0}; parent={}; queue=[(distance(s[5],e[5]),0,-1)]
        while queue:
            _,cost,n=heapq.heappop(queue)
            if cost!=costs[n]: continue
            if n==-2: break
            for v,d,w in (*self.adj.get(n,()),*extra.get(n,())):
                new=cost+d
                if new>limit or new>=costs.get(v,math.inf): continue
                costs[v]=new; parent[v]=(n,w,d)
                heapq.heappush(queue,(new+distance(points.get(v,self.nodes.get(v)),e[5]),new,v))
        if -2 not in costs: raise ValueError('No continuous permitted pedestrian route')
        n=-2; segments=[]
        while n!=-1:
            prev,w,d=parent[n]; segments.append((prev,n,w,d)); n=prev
        segments.reverse(); steps=[]; geometry=[start,s[5]]
        for a,b,w,d in segments:
            pa=points.get(a,self.nodes.get(a)); pb=points.get(b,self.nodes.get(b)); geometry.append(pb)
            tags=self.ways[w]['tags']; name=self.edge_name(w,pa,pb)
            direction=bearing(pa,pb)
            angle=abs((direction-steps[-1]['bearing']+180)%360-180) if steps else 180
            if steps and steps[-1]['name']==name and (tags.get('name') or angle<45 or d<6):
                steps[-1]['metres']+=d; steps[-1]['end']=pb; steps[-1]['ways'].append(w)
            else: steps.append({'name':name,'metres':d,'start':pa,'end':pb,'bearing':bearing(pa,pb),'ways':[w], 'highway':tags.get('highway')})
        geometry.append(end)
        return {'metres':costs[-2]+s[6]+e[6], 'network_metres':costs[-2], 'endpoint_gaps':[s[6],e[6]], 'start':start,'end':end,'geometry':geometry,'steps':steps,'source':'OpenStreetMap pedestrian graph'}
