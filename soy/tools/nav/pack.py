"""Compose private text-first navigation scenes and their evidence manifest."""
import json,math,os
from pathlib import Path
from gtfs import clock
from maps import ascii_map


def minutes(metres): return math.ceil(metres/72)
def name(poi): return poi['tags'].get('name','Destination')
def compass(degrees): return ('north','north-east','east','south-east','south','south-west','west','north-west')[int((degrees+22.5)//45)%8]

def turn_list(route):
    result=[]; groups=[]; pending=0
    for s in route['steps']:
        label=s['name'].removeprefix('pavement beside ').removesuffix(' Cycleway')
        generic=label in ('footway','pavement','cycleway','service','primary link','secondary','tertiary')
        if generic and s['metres']<25:
            pending+=s['metres']; continue
        if generic: label='public path' if label in ('footway','pavement','cycleway') else 'access road'
        if groups and groups[-1]['name']==label and (label not in ('public path','access road','path','steps') or abs((s['bearing']-groups[-1]['bearing']+180)%360-180)<40):
            groups[-1]['metres']+=s['metres']+pending
        else: groups.append({'name':label,'bearing':s['bearing'],'metres':s['metres']+pending})
        pending=0
    if groups: groups[-1]['metres']+=pending
    for s in groups:
        result.append(f"{compass(s['bearing']).capitalize()} via {s['name']}: about {round(s['metres']/10)*10} m.")
    return '\n\n'.join(result)

def write_scene(directory,identity,label,body,accent='cyan'):
    text=f'---\nid: {identity}\nlabel: {label}\naccent: {accent}\nsource: offline trip pack\n---\n{body.strip()}\n'
    (directory/(identity+'.md')).write_text(text)


def journey_text(journey,stops,notes=None):
    if 'error' in journey: return 'No checked journey: '+journey['error']
    lines=[]; notes=notes or {}
    for index,leg in enumerate(journey['legs']):
        if leg['mode']=='walk':
            route=leg['route']; lines.append(f"## Walk {round(route['metres'])} m · {minutes(route['metres'])} min")
            lines.append(notes.get(str(index),turn_list(route)))
        else:
            a=stops[leg['from']]; b=stops[leg['to']]
            lines.append(f"## {leg['route']} at {clock(leg['depart'])}")
            lines.append(f"{a['stop_name']} · {a['stop_code']}")
            lines.append('Towards '+(leg['headsign'] or b['stop_name'])+'.')
            lines.append(f"Get off {clock(leg['arrive'])}: {b['stop_name']} · {b['stop_code']}.")
            if len(leg.get('stops',[]))>2:
                prior=stops[leg['stops'][-2]]; lines.append('The stop before is '+prior['stop_name']+'.')
    return '\n\n'.join(lines)


def compact_journey(journey,stops,notes=None):
    if 'error' in journey:return 'No checked journey: '+journey['error']
    lines=[];notes=notes or {}
    for i,leg in enumerate(journey['legs']):
        if leg['mode']=='ride':
            a,b=stops[leg['from']],stops[leg['to']]
            lines.append(f"{leg['route']} {clock(leg['depart'])}: {a['stop_code']} {a['stop_name']} → {b['stop_code']} {b['stop_name']} at {clock(leg['arrive'])}.")
        else:
            r=leg['route'];text=notes.get(str(i),turn_list(r).replace('\n\n',' '))
            lines.append(f"Walk {round(r['metres'])} m / {minutes(r['metres'])} min. {text}")
    return '\n\n'.join(lines)


def departure_text(journey,stops,schedules,start,end):
    lines=[]
    for l in journey['legs']:
        if l['mode']!='ride': continue
        stop=stops[l['from']]; ts=schedules.get(l['from']+'|'+l['route'],[])
        selected=[r['time'] for r in ts if start<=r['seconds']<=end]
        lines += [f"## {l['route']} · stop {stop['stop_code']}",stop['stop_name'],', '.join(selected) or 'No departure in this period.']
    return '\n\n'.join(lines)


def compose(graph,config,records,output):
    """All inputs are explicit, dated and private. No fabricated live position."""
    output=Path(output); output.mkdir(parents=True,exist_ok=True,mode=0o700)
    scenes=output/'scenes'; scenes.mkdir(exist_ok=True,mode=0o700)
    stops=records['stops']; schedules=records['departures']; out=records['outbound']; back=records['return']; dest=config['destination']; notes=config.get('notes',{})
    shop=notes.get('shop',name(dest)+'\n\n'+ ' '.join(dest['tags'].get(k,'') for k in ('addr:housenumber','addr:street'))+'\n\nHoliday opening unconfirmed.')
    date=config['date']; title=notes.get('title',name(dest))
    body=f"# {title}\n\n{date} · scheduled buses\n\nLeave {clock(out['depart'])}. Arrive {clock(out['arrive'])}.\n\n{shop}\n\n{journey_text(out,stops,notes.get('outbound'))}\n\n# Later buses\n\n{departure_text(out,stops,schedules,out['depart']-900,out['depart']+5400)}\n\n{notes.get('outbound_end','Arrive at the stop five minutes early. Times are scheduled, not live.')}"
    write_scene(scenes,'reader','Getting there',body)
    lastwalk=next(l for l in reversed(out['legs']) if l['mode']=='walk'); firstwalk=back['legs'][0]
    markers=[('B',lastwalk['route']['start']),('A',firstwalk['route']['end']),('S',dest['point'])]
    for i,w in enumerate(records['walks'],1): markers.append((str(i),w['poi']['point']))
    center=(dest['point'][0]+0.0008,dest['point'][1]+0.0008)
    local,placed=ascii_map(graph,center,markers,rows=11,routes=[w['route']['geometry'] for w in records['walks']])
    reach,_=ascii_map(graph,dest['point'],[('S',dest['point'])]+[(str(i),w['poi']['point']) for i,w in enumerate(records['walks'],1)],metres_per_column=96,rings=True)
    legend=['S '+name(dest),'A bus towards City','B bus from City']+[str(i)+' '+name(w['poi']) for i,w in enumerate(records['walks'],1)]
    local_legend='\n\n'.join(x for x in legend if x[0] in placed)
    mapbody=f"# Near the shop\n\nNorth ↑   |----| 120 m\nS shop  A home  B arrival\n{config.get('map_key','Numbers: places below')}\n```\n{local}\n```\n\nDots: walking paths.\n\n~ water edge\n\n{local_legend}\n\n{notes.get('map','')}\n\n# Walking range\n\nNorth ↑   |----| 480 m\n```\n{reach}\n```\n\na 5 min · b 10 min\n\nc 15 min · S shop\n\n"+'\n\n'.join(x for x in legend if x[0] in '123')+f"\n\nEdges of mapped walking reach at 4.3 km/h. Crossings and pauses add time. Roads are approximate at this scale.\n\nOpenStreetMap contributors · ODbL. Offline extract {config.get('osm_date','date in manifest')}. No live position."
    if config.get('sense'):
        mapbody=mapbody.removesuffix('No live position.')+'Position source and age are below.'
        mapbody+='\n\n# Position\n\n{{sense.position}}\n\n{{sense.position_source}} · {{sense.position_age}}\n\n{{sense.position_accuracy}}\n'
    write_scene(scenes,'map','Map',mapbody)
    walks=[]
    pickup=sum(int(v)*m for v,m in zip(config['pickup'].split(':'),(3600,60)))
    for i,w in enumerate(records['walks'],1):
        r=w['route']; n=minutes(r['metres']); leave=clock(pickup-300-n*60)
        text=notes.get('walks',{}).get(str(w['poi']['id']),turn_list(r)+'\n\nReturn by reversing this route.')
        walks.append(f"# {i} {name(w['poi'])}\n\n{round(r['metres'])} m · {n} min each way\n\nLeave by {leave} for the shop by {clock(pickup-300)}. Pickup assumed {config['pickup']}.\n\n{text}")
    walks.append(notes.get('walks_end','If pickup changes, leave one walking time plus five minutes before the new pickup.'))
    if config.get('sense'):
        walks.append('# Return timing\n\n{{sense.target}} · {{sense.distance}}\n\n{{sense.eta}}\n\n{{sense.leave_by}}\n\nEstimates update after a landmark fix. Scheduled bus times are on Getting home.')
    write_scene(scenes,'walks','While you wait','\n\n'.join(walks))
    homebody=f"# Home by {config['back_by']}\n\n{journey_text(back,stops,notes.get('return'))}\n\nHome about {clock(back['arrive'])}.\n\n# Departures home\n\n{departure_text(back,stops,schedules,10*3600,13*3600)}\n\n{notes.get('return_end','')}\n\n# If you are lost\n\n{notes.get('recovery','Return to the named departure stop using the route card. Ask a person for the stop by its number. This phone has no mobile service.')}\n\n# Battery\n\n{{{{battery.state}}}} · {{{{battery.voltage}}}}\n\n{notes.get('battery','Battery duration has not been measured. Sleep the screen between checks. Keep a reserve for the way home.')}"
    write_scene(scenes,'home','Getting home',homebody,'amber')
    alternatives=[]
    for alt in records.get('alternatives',[]):
        poi=alt['poi']; tag=poi['tags']; address=' '.join(tag.get(k,'') for k in ('addr:housenumber','addr:street')).strip(); phone=tag.get('phone',tag.get('contact:phone',''))
        address=address or config.get('alternative_addresses',{}).get(str(poi['id']),'Address not mapped; use the named centre.')
        text=f"# {name(poi)}\n\n{address}\n\n{phone}\n\nPublic-holiday opening unconfirmed.\n\n{poi.get('route_endpoint','')}\n\n## There\n\n{compact_journey(alt['outbound'],stops,config.get('alternative_notes',{}).get(str(poi['id']),{}).get('outbound'))}\n\n## Home\n\n{compact_journey(alt['return'],stops,config.get('alternative_notes',{}).get(str(poi['id']),{}).get('return'))}"
        alternatives.append(text)
    if alternatives: write_scene(scenes,'alternatives','Other centres','\n\n'.join(alternatives))
    ids=['reader','map','walks','home']+(['alternatives'] if alternatives else [])
    (scenes/'index').write_text('\n'.join(ids)+'\n')
    (output/'route-data.json').write_text(json.dumps({'config':config,**records},separators=(',',':')))
    # Never imply that a destination or a planned origin is a measured fix.
    (output/'position.json').write_text(json.dumps({'position':None,'source':'unavailable','reason':'Trip planning does not locate the phone.'})+'\n')
    for p in output.rglob('*'):
        if p.is_file(): os.chmod(p,0o600)
    return scenes
