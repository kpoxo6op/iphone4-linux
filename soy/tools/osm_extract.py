#!/usr/bin/env python3
"""Cut coastline, roads, lakes and place names for ascii_map.py out of an OSM extract.

Needs pyosmium (`pip install osmium`) and a .osm.pbf such as Geofabrik's New
Zealand extract. Minor streets are kept only inside the --streets boxes, where
street-level maps will be drawn; everything else keeps the main roads.

  python3 soy/tools/osm_extract.py new-zealand.osm.pbf --bbox=-37.10,174.45,-36.60,175.05 \
      --streets=-36.760,174.680,-36.690,174.770 --out region.json
"""
import argparse
import json

import osmium

ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
MINOR = {"tertiary", "unclassified", "residential", "tertiary_link"}


def box(text):
    s, w, n, e = map(float, text.split(","))
    return s, w, n, e


def inside(lat, lon, area):
    s, w, n, e = area
    return s <= lat <= n and w <= lon <= e


p = argparse.ArgumentParser()
p.add_argument("pbf")
p.add_argument("--bbox", type=box, required=True, help="S,W,N,E")
p.add_argument("--streets", type=box, action="append", default=[], help="S,W,N,E; repeatable")
p.add_argument("--out", required=True)
a = p.parse_args()

out = {"coast": [], "roads": [], "water": [], "places": []}
processor = (osmium.FileProcessor(a.pbf, osmium.osm.NODE | osmium.osm.WAY)
             .with_locations()
             .with_filter(osmium.filter.KeyFilter("natural", "highway", "place")))
for obj in processor:
    tags = obj.tags
    if obj.is_node():
        if "place" in tags and "name" in tags and inside(obj.location.lat, obj.location.lon, a.bbox):
            out["places"].append({"name": tags["name"], "place": tags["place"],
                                  "lat": obj.location.lat, "lon": obj.location.lon})
        continue
    natural, highway = tags.get("natural"), tags.get("highway")
    if natural not in ("coastline", "water") and highway not in ROADS:
        continue
    pts = [(round(n.lat, 6), round(n.lon, 6)) for n in obj.nodes if n.location.valid()]
    if not pts or not any(inside(lat, lon, a.bbox) for lat, lon in pts):
        continue
    if natural == "coastline":
        out["coast"].append(pts)
    elif natural == "water":
        if obj.is_closed():
            out["water"].append({"name": tags.get("name", ""), "pts": pts})
    elif highway not in MINOR or any(inside(lat, lon, b) for b in a.streets for lat, lon in pts):
        out["roads"].append({"hw": highway, "name": tags.get("name", ""), "ref": tags.get("ref", ""),
                             "pts": pts})
json.dump(out, open(a.out, "w"))
print({k: len(v) for k, v in out.items()})
