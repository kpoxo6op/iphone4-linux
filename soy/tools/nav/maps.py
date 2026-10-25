"""Small north-up maps from the same OSM geometry used by the router.

Twenty-five columns fit Soy's default body type. Rings are graph-distance
reachability contours, not circles that imply walking through buildings.
"""
import math

def ascii_map(graph, center, markers, metres_per_column=24, rows=13, rings=False, routes=()):
    cols=25; scale=metres_per_column; lat,lon=center
    sx=111195*math.cos(math.radians(lat)); sy=111195
    def cell(p):
        return round((p[1]-lon)*sx/scale+(cols-1)/2),round((lat-p[0])*sy/(scale*2)+(rows-1)/2)
    grid=[[' ']*cols for _ in range(rows)]
    def dot(x,y,ch):
        if 0<=x<cols and 0<=y<rows: grid[y][x]=ch
    def line(a,b,ch):
        x,y=cell(a); xx,yy=cell(b)
        if max(x,xx)<0 or min(x,xx)>=cols or max(y,yy)<0 or min(y,yy)>=rows: return
        n=max(abs(xx-x),abs(yy-y),1)
        for i in range(n+1): dot(round(x+(xx-x)*i/n),round(y+(yy-y)*i/n),ch)
    for w in graph.map_water:
        pts=[graph.nodes[n] for n in w['nodes'] if n in graph.nodes]
        for a,b in zip(pts,pts[1:]): line(a,b,'~')
    if rings:
        points={(x,y):(lat-(y-(rows-1)/2)*scale*2/sy,lon+(x-(cols-1)/2)*scale/sx) for y in range(rows) for x in range(cols)}
        reach=graph.distances_to(center,points,limit=1180,max_distance=100)
        bands={k:min(3,math.ceil(r['metres']/360)) for k,r in reach.items()}
        for (x,y),band in bands.items():
            if any(bands.get((x+dx,y+dy),4)>band for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))): dot(x,y,'abc'[max(1,band)-1])
    else:
        for w in graph.map_ways:
            h=w['tags'].get('highway')
            if h not in ('primary','secondary','tertiary','residential','unclassified','pedestrian','living_street'): continue
            ns=w['nodes']
            for a,b in zip(ns,ns[1:]):
                if a not in graph.nodes or b not in graph.nodes: continue
                x,y=cell(graph.nodes[a]); xx,yy=cell(graph.nodes[b])
                if max(x,xx)<0 or min(x,xx)>=cols or max(y,yy)<0 or min(y,yy)>=rows: continue
                n=max(abs(xx-x),abs(yy-y),1)
                ch='-' if abs(xx-x)>2*abs(yy-y) else '|' if abs(yy-y)>abs(xx-x) else '/' if (xx-x)*(yy-y)<0 else '\\'
                for i in range(n+1): dot(round(x+(xx-x)*i/n),round(y+(yy-y)*i/n),ch)
    for route in routes:
        for a,b in zip(route,route[1:]): line(a,b,'.')
    placed=[]
    for symbol,point in markers:
        x,y=cell(point)
        if 0<=x<cols and 0<=y<rows:
            if grid[y][x] in 'SAB123L':
                raise ValueError('Map landmarks collide; use a closer map scale')
            dot(x,y,symbol); placed.append(symbol)
    # Fixed-width lines are checked here, before the renderer can wrap them.
    lines=[''.join(row) for row in grid]
    assert all(len(line)==25 for line in lines)
    return '\n'.join(lines),placed
