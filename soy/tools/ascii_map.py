#!/usr/bin/env python3
"""Draw a place as an 8-bit tile map scene from OpenStreetMap data.

Each map is a grid of 26 x N DejaVu Sans Mono cells (22 x 47 px at the default
36 px size). Water is drawn with quadrant blocks, so the coastline has twice the
grid's resolution; roads are box-drawing lines whose weight shows their class
(double motorway, heavy main road, light street). Colours come from Soy's
Markdown: water in the scene accent, roads in ink, place names in bold, street
names in grey. Soy's fonts fill the whole cell with box drawing and block
elements, so the tiles join without seams.

Data comes from osm_extract.py. Example, the North Shore with a pin:

  python3 soy/tools/ascii_map.py region.json --id map-shore --label "North Shore" \
      --center=-36.776,174.735 --km-per-col 0.446 --rows 22 --top 14 \
      --roads motorway,trunk,primary,secondary --place Albany --place Takapuna \
      --pin "679=-36.7224,174.7237" --out map-shore.md
"""
import json
import math
import sys
import unicodedata

from PIL import Image, ImageDraw

COLS = 26
ASPECT = 47 / 22
F = 6  # fine raster pixels per quadrant side
N_, E_, S_, W_ = 0, 1, 2, 3
QUADS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
WEIGHT = {"LIGHT": 1, "SINGLE": 1, "HEAVY": 2, "DOUBLE": 3}
ARMS = {"UP": (N_,), "DOWN": (S_,), "LEFT": (W_,), "RIGHT": (E_,),
        "VERTICAL": (N_, S_), "HORIZONTAL": (E_, W_)}


def box_table():
    """Map (n, e, s, w) arm weights to a box-drawing character, from Unicode names."""
    table = {}
    for code in range(0x2500, 0x2580):
        name = unicodedata.name(chr(code), "")
        if any(word in name for word in ("DASH", "ARC", "DIAGONAL")):
            continue
        parts = name.replace("BOX DRAWINGS ", "").split(" AND ")
        arms = [0, 0, 0, 0]
        lead = None
        for part in parts:
            words = part.split()
            weights = [WEIGHT[w] for w in words if w in WEIGHT]
            if weights and words[0] in WEIGHT:
                lead = weights[0]
            weight = weights[-1] if weights else lead
            for word in words:
                for arm in ARMS.get(word, ()):
                    arms[arm] = weight
        if weight and any(arms):
            table.setdefault(tuple(arms), chr(code))
    return table


BOX = box_table()


def glyph_for(arms):
    arms = list(arms)
    if not any(arms):
        return " "
    top = max(arms)
    # One weight per cell keeps the tiles clean: motorways cross nothing at grade,
    # and a side street meeting a main road takes the main road's weight.
    arms = [top if (a == 3 or top < 3) and a else 0 for a in arms]
    if sum(1 for a in arms if a) == 1:  # a dead end draws through the cell
        i = next(i for i, a in enumerate(arms) if a)
        arms[(i + 2) % 4] = arms[i]
    for candidate in (arms, [top if a else 0 for a in arms]):
        if tuple(candidate) in BOX:
            return BOX[tuple(candidate)]
    return "+"


class Page:
    def __init__(self, lat0, lon0, km_per_col, rows):
        self.lat0, self.lon0, self.rows = lat0, lon0, rows
        self.kc, self.kr = km_per_col, km_per_col * ASPECT
        self.kx = 111.32 * math.cos(math.radians(lat0))
        self.ky = 110.95

    def cell(self, lat, lon):
        return (COLS / 2 + (lon - self.lon0) * self.kx / self.kc,
                self.rows / 2 + (self.lat0 - lat) * self.ky / self.kr)


def water(page, data, lakes_min=2.0):
    """Quadrant water mask from coastline barriers flood-filled from their water side."""
    w, h = COLS * 2 * F, page.rows * 2 * F
    image = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(image)
    scale = 2 * F
    lines = []
    for way in data["coast"]:
        pts = [(c * scale, r * scale) for c, r in (page.cell(a, b) for a, b in way)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) < -20 or min(xs) > w + 20 or max(ys) < -20 or min(ys) > h + 20:
            continue
        draw.line(pts, fill=1, width=1)
        lines.append(pts)
    for lake in data["water"]:
        pts = [(c * scale, r * scale) for c, r in (page.cell(a, b) for a, b in lake["pts"])]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) < 0 or min(xs) > w or max(ys) < 0 or min(ys) > h:
            continue
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) >= lakes_min * F * F:
            draw.polygon(pts, fill=4)
    # OSM coastline keeps land on the left and water on the right. Every region
    # between barriers takes the side most of its bordering segments vote for,
    # so one odd pier or islet cannot flood a whole harbour with land.
    import numpy as np
    from scipy import ndimage
    grid = np.array(image)
    regions, _ = ndimage.label(grid == 0)
    votes = {}
    for pts in lines:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 0.8:
                continue
            nx, ny = -(y2 - y1) / length, (x2 - x1) / length
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            for side, vote in ((1.6, 1), (-1.6, -1)):
                x, y = int(mx + nx * side), int(my + ny * side)
                if 0 <= x < w and 0 <= y < h and regions[y, x]:
                    votes[regions[y, x]] = votes.get(regions[y, x], 0) + vote * length
    wet = [k for k, v in votes.items() if v > 0]
    grid = np.where(np.isin(regions, wet), 2, grid)
    image = Image.fromarray(grid.astype(np.uint8))
    pixels = image.load()
    quads = [[False] * (COLS * 2) for _ in range(page.rows * 2)]
    for qr in range(page.rows * 2):
        for qc in range(COLS * 2):
            score = 0.0
            for y in range(qr * F, qr * F + F):
                for x in range(qc * F, qc * F + F):
                    v = pixels[x, y]
                    score += 1.0 if v in (2, 4) else 0.5 if v == 1 else 0.0
            quads[qr][qc] = score >= F * F * 0.5
    return quads


CLASS = {"motorway": 3, "trunk": 2, "primary": 2, "secondary": 1, "tertiary": 1,
         "unclassified": 1, "residential": 1, "motorway_link": 1, "trunk_link": 1,
         "primary_link": 1, "secondary_link": 1, "tertiary_link": 1}


def keep_top(page, data, classes, top):
    """Generalise: keep motorways, plus the `top` longest named roads of `classes` on the page."""
    lengths = {}
    for road in data["roads"]:
        if road["hw"] not in classes or road["hw"] == "motorway" or not road["name"]:
            continue
        cells = [page.cell(a, b) for a, b in road["pts"]]
        span = sum(math.hypot(c2 - c1, (r2 - r1) * ASPECT)
                   for (c1, r1), (c2, r2) in zip(cells, cells[1:])
                   if 0 <= c1 < COLS and 0 <= r1 < page.rows)
        lengths[road["name"]] = lengths.get(road["name"], 0) + span
    return {name for name, _ in sorted(lengths.items(), key=lambda kv: -kv[1])[:top]}


def roads(page, data, classes, weight_of=None, top=None):
    """Cell arms per weight: {(c, r): [n, e, s, w]} built from 4-connected cell paths."""
    grid = {}
    weight_of = weight_of or CLASS
    chosen = keep_top(page, data, classes, top) if top else None
    for road in data["roads"]:
        if road["hw"] not in classes:
            continue
        if chosen is not None and road["hw"] != "motorway" and road["name"] not in chosen:
            continue
        weight = weight_of[road["hw"]]
        path = []
        for (a1, b1), (a2, b2) in zip(road["pts"], road["pts"][1:]):
            c1, r1 = page.cell(a1, b1)
            c2, r2 = page.cell(a2, b2)
            steps = max(1, int(max(abs(c2 - c1), abs(r2 - r1)) * 4))
            for i in range(steps + 1):
                t = i / steps
                cell = (math.floor(c1 + (c2 - c1) * t), math.floor(r1 + (r2 - r1) * t))
                if not path or path[-1] != cell:
                    if path and abs(cell[0] - path[-1][0]) + abs(cell[1] - path[-1][1]) == 2:
                        # Diagonal step: go through the corner nearer the true line.
                        fx, fy = c1 + (c2 - c1) * t, r1 + (r2 - r1) * t
                        a, b = (cell[0], path[-1][1]), (path[-1][0], cell[1])
                        da = abs(fx - (a[0] + .5)) + abs(fy - (a[1] + .5))
                        db = abs(fx - (b[0] + .5)) + abs(fy - (b[1] + .5))
                        path.append(a if da <= db else b)
                    path.append(cell)
        for (c0, r0), (c1, r1) in zip(path, path[1:]):
            step = (c1 - c0, r1 - r0)
            arms = {(1, 0): (E_, W_), (-1, 0): (W_, E_), (0, 1): (S_, N_), (0, -1): (N_, S_)}.get(step)
            if not arms:
                continue
            for cell, arm in (((c0, r0), arms[0]), ((c1, r1), arms[1])):
                if 0 <= cell[0] < COLS and 0 <= cell[1] < page.rows:
                    slot = grid.setdefault(cell, [0, 0, 0, 0])
                    slot[arm] = max(slot[arm], weight)
    return grid


class Canvas:
    def __init__(self, page):
        self.page = page
        self.ch = [[" "] * COLS for _ in range(page.rows)]
        self.st = [["land"] * COLS for _ in range(page.rows)]
        self.taken = [[0] * COLS for _ in range(page.rows)]  # 2 label, 1 major road

    def put(self, c, r, ch, style, taken=0):
        if 0 <= c < COLS and 0 <= r < self.page.rows:
            self.ch[r][c], self.st[r][c] = ch, style
            self.taken[r][c] = max(self.taken[r][c], taken)

    def label(self, text, lat, lon, style="name", anchor="center", tries=None):
        c, r = self.page.cell(lat, lon)
        c, r = int(c), int(r)
        n = len(text)
        starts = {"center": c - n // 2, "right": c + 2, "left": c - n - 1}
        options = tries or [(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0), (-2, 0), (2, 0)]
        best = None
        for kind in ([anchor] if anchor != "center" else ["center"]) + ["right", "left"]:
            for dc, dr in options:
                c0, r0 = starts[kind] + dc, r + dr
                if c0 < 0 or c0 + n > COLS or not 0 <= r0 < self.page.rows:
                    continue
                cost = abs(dc) + abs(dr) * 2 + (0 if kind == anchor else 3)
                for i in range(n):
                    t = self.taken[r0][c0 + i]
                    cost += 100 if t == 2 else 6 if t == 1 else 0
                    cost += 1 if self.st[r0][c0 + i] == "water" else 0
                if best is None or cost < best[0]:
                    best = (cost, c0, r0)
        if best is None or best[0] >= 100:
            return False
        _, c0, r0 = best
        for i, ch in enumerate(text):
            self.put(c0 + i, r0, ch, style, 2)
        return True

    def markdown(self):
        lines = []
        for r in range(self.page.rows):
            out, run, style = [], "", None
            for c in range(COLS):
                ch, st = self.ch[r][c], self.st[r][c]
                if ch in "*`[]\\":
                    ch = "\\" + ch
                st = {"land": "ink", "road": "ink", "pin": "bold", "name": "bold",
                      "street": "muted", "water": "accent", "shield": "bold", "note": "muted"}[st]
                if ch.strip() == "" and st in ("accent", "bold", "muted"):
                    st = "ink"
                if st != style and run:
                    out.append(wrap(run, style))
                    run = ""
                style = st
                run += ch
            if run:
                out.append(wrap(run, style))
            line = "".join(out)
            if line[:1] in "#>" or line[:2] in ("- ", "* "):
                line = "\\" + line
            lines.append(line)
        return lines


def wrap(text, style):
    if style == "accent":
        return "`" + text + "`"
    if style == "bold":
        return "**" + text + "**"
    if style == "muted":
        return "*" + text + "*"
    return text


def draw(page, data, classes, places=(), pins=(), shields=(), streets=0, weight_of=None, top=None):
    canvas = Canvas(page)
    quads = water(page, data)
    for r in range(page.rows):
        for c in range(COLS):
            bits = (quads[2 * r][2 * c] * 1 | quads[2 * r][2 * c + 1] * 2 |
                    quads[2 * r + 1][2 * c] * 4 | quads[2 * r + 1][2 * c + 1] * 8)
            if bits:
                canvas.put(c, r, QUADS[bits], "water")
    grid = roads(page, data, classes, weight_of, top)
    canvas.chosen = keep_top(page, data, classes, top) if top else None
    for (c, r), arms in grid.items():
        canvas.put(c, r, glyph_for(arms), "road", 1 if max(arms) >= 2 else 0)
    if shields:
        motorway_numbers(canvas, data, grid)
    for marker, text, lat, lon in pins:
        c, r = map(int, page.cell(lat, lon))
        canvas.put(c, r, marker, "pin", 2)
    for marker, text, lat, lon in pins:
        if text:
            canvas.label(text, lat, lon, "pin", anchor="right",
                         tries=[(0, 0), (0, -1), (0, 1), (-1, 0), (1, 0)])
    for text, lat, lon, style in places:
        canvas.label(text, lat, lon, style)
    if streets:
        street_labels(canvas, data, streets, canvas.chosen)
    return canvas


def motorway_numbers(canvas, data, grid):
    """Write each state highway's number on a straight stretch of its own line."""
    import re
    page = canvas.page
    cells = {}
    for road in data["roads"]:
        if road["hw"] != "motorway":
            continue
        match = re.search(r"SH ?(\d+[A-Z]?)", road["ref"])
        if not match:
            continue
        for a, b in road["pts"]:
            c, r = map(math.floor, page.cell(a, b))
            if 0 <= c < COLS and 0 <= r < page.rows:
                cells.setdefault(match.group(1), []).append((c, r))
    for number, found in sorted(cells.items(), key=lambda kv: -len(kv[1])):
        straight = [(c, r) for c, r in found
                    if canvas.ch[r][c] in "║═" and canvas.taken[r][c] < 2]
        if not straight:
            continue
        mid = found[len(found) // 2]
        straight.sort(key=lambda cr: abs(cr[0] - mid[0]) + abs(cr[1] - mid[1]))
        for c, r in straight:
            start = c if canvas.ch[r][c] == "║" else c - (len(number) - 1) // 2
            span = range(start, start + len(number))
            if all(0 <= x < COLS and canvas.taken[r][x] < 2 and
                   (x == c or canvas.ch[r][x] in " ═" or canvas.st[r][x] == "water") for x in span):
                for i, x in enumerate(span):
                    canvas.put(x, r, number[i], "shield", 2)
                break


def street_labels(canvas, data, count, chosen=None):
    """Name the longest streets inside the page, beside their own line."""
    page = canvas.page
    lengths = {}
    for road in data["roads"]:
        name = road["name"]
        if not name or "Motorway" in name or (chosen is not None and name not in chosen):
            continue
        cells = [page.cell(a, b) for a, b in road["pts"]]
        inside = [(c, r) for c, r in cells if 0 <= c < COLS and 0 <= r < page.rows]
        if len(inside) < 2:
            continue
        span = sum(math.hypot(c2 - c1, (r2 - r1) * ASPECT)
                   for (c1, r1), (c2, r2) in zip(inside, inside[1:]))
        entry = lengths.setdefault(name, [0, []])
        entry[0] += span
        entry[1].extend(inside)
    for name, (span, cells) in sorted(lengths.items(), key=lambda kv: -kv[1][0])[:count]:
        short = (name.replace(" Road", " Rd").replace(" Street", " St").replace(" Avenue", " Av")
                 .replace(" Drive", " Dr").replace(" Terrace", " Tce").replace(" Place", " Pl")
                 .replace(" Crescent", " Cres").replace(" Parade", " Pde").replace(" Highway", " Hwy"))
        mid = cells[len(cells) // 2]
        c, r = mid
        lat = page.lat0 - (r - page.rows / 2) * page.kr / page.ky
        lon = page.lon0 + (c - COLS / 2) * page.kc / page.kx
        canvas.label(short, lat, lon, "street",
                     tries=[(0, -1), (0, 1), (2, -1), (-2, -1), (2, 1), (-2, 1), (0, -2), (0, 2)])


def scale_line(page, style_note=""):
    for km in (0.2, 0.5, 1, 2, 5, 10, 20):
        cols = km / page.kc
        if cols >= 3:
            break
    cols = max(2, round(cols))
    unit = f"{int(km * 1000)} m" if km < 1 else f"{km:g} km"
    bar = "└" + "─" * (cols - 2) + "┘"
    return "*" + bar + " " + unit + (" · " + style_note if style_note else "") + "*"


def main():
    import argparse
    p = argparse.ArgumentParser(description="Draw an 8-bit tile map scene from osm_extract.py data.")
    p.add_argument("data")
    p.add_argument("--id", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--center", required=True, help="LAT,LON of the middle of the map")
    p.add_argument("--km-per-col", type=float, required=True)
    p.add_argument("--rows", type=int, default=14, help="14 rows fit one screen with the scale line")
    p.add_argument("--roads", default="motorway,trunk,primary,secondary")
    p.add_argument("--top", type=int, help="keep motorways plus this many of the longest named roads")
    p.add_argument("--place", action="append", default=[],
                   help="a place name from the data, or NAME=LAT,LON; drawn in bold capitals")
    p.add_argument("--pin", action="append", default=[], help="LABEL=LAT,LON, drawn as a solid block")
    p.add_argument("--streets", type=int, default=0, help="name this many of the longest streets")
    p.add_argument("--accent", default="cyan")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    data = json.load(open(a.data))
    lat0, lon0 = map(float, a.center.split(","))
    page = Page(lat0, lon0, a.km_per_col, a.rows)

    def where(text):
        if "=" in text:
            name, at = text.split("=", 1)
            return (name, *map(float, at.split(",")))
        for place in data["places"]:
            if place["name"] == text:
                return text, place["lat"], place["lon"]
        raise SystemExit(f"No place called {text} in {a.data}")

    places = [(name.upper(), lat, lon, "name") for name, lat, lon in map(where, a.place)]
    pins = [("█", name, lat, lon) for name, lat, lon in map(where, a.pin)]
    weights = {k: v for k, v in CLASS.items()}
    weights.update({"trunk": 2, "primary": 2})
    canvas = draw(page, data, set(a.roads.split(",")), places=places, pins=pins, shields=True,
                  streets=a.streets, weight_of=weights, top=a.top)
    lines = ["---", f"id: {a.id}", f"label: {a.label}", f"accent: {a.accent}",
             "source: OpenStreetMap contributors, ODbL", "---"]
    lines += canvas.markdown() + [scale_line(page)]
    with open(a.out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
