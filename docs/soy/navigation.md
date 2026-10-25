# Offline trip packs

AI selects places from raw OSM and writes a private profile; `soy/tools/trip.py`
computes dated bus journeys and pedestrian routes, then writes ordinary Soy
scenes. A trip is a scene bundle plus Linux tools, with no launcher or app.
The planned origin and destination never become a current-position reading.

Keep the profile, raw regional extract, GTFS archive, route evidence and scenes
under `.runtime/phone/private/` or another ignored private directory. The tool
refuses a non-ignored output inside either checkout. Raw source attribution,
URLs, hashes, service date and build time accompany each pack.

```sh
python3 soy/tools/trip.py \
  --config .runtime/phone/private/trip/profile.json \
  --request 'Town tomorrow 9:30, back by 13:00' \
  --osm .runtime/phone/private/trip/osm.json \
  --gtfs .runtime/phone/private/trip/gtfs.zip \
  --out .runtime/phone/private/trip/pack --put
```

A profile supplies `home` (latitude, longitude and its given source), `date`,
`arrive_by`, `pickup`, `back_by`, and a `destination` OSM object with `id`,
`point: [latitude, longitude]`, `tags.name` and optional `aliases`. `walks` and
`alternatives` are arrays of similarly selected objects. AI resolves place
ambiguity in the profile; the small sentence parser does not guess between
places or geocode a home. For a new destination or date, it discards old curated
notes. A prepared, independently checked record can instead be supplied with
`--prepared`; this cannot be combined with a request override.

Use `nav/extract_osm.py` with pyosmium in a local venv to make a regional raw
extract from a PBF. It records the download URL, PBF hash, extraction time,
bounds and ODbL attribution. Source downloads are separate from the cached
pack-build timing. AT's feed is at https://gtfs.at.govt.nz/gtfs.zip .
OpenStreetMap data is © OpenStreetMap contributors, under ODbL 1.0:
https://www.openstreetmap.org/copyright . Retain the source licence and terms
with any downloaded feed; no raw data or personal profiles belong in Git.

The pedestrian graph uses segment projection, A* and explicit endpoint links.
It rejects private/no-foot, informal, tidal and ford shortcuts; it respects
`oneway:foot`. Bare road tags are not proof of a safe crossing. The graph is
2D, does not model indoor floors or every conditional restriction, and needs
independent route and visible-landmark review. Mall pins should name an actual
public entrance; a shop centroid is not an entrance. The generic turn list is
a draft for AI to turn into a short route card with catching landmarks.

The connection scan applies `calendar_dates` over the weekly calendar, checks
feed coverage and preserves times after midnight. It uses mapped pedestrian
access and transfers, three minutes of transfer/boarding slack and at most two
bus rides for the main journey. Alternate centres allow three. Departure times
are scheduled, never live. The arrive-by search reserves ten minutes before
the appointment. Frequency service without exact times is rejected rather
than turned into fictional departures.

Maps use 25 columns at the default font size and geographic north. The 5/10/15
minute contours use graph distance at 1.2 m/s. They are coarse reachability
boundaries; traffic lights, pauses and unmapped barriers add time. Zooming text
can wrap a map: return to its original text size to read the fixed grid.

`scene.py put DIRECTORY --show` checks and publishes the entire pack as one
library commit. `scene.py undo` restores the previous library. The offline
story generator leaves a trip pack alone, preserving its library and energy
reserve; removing the pack restores that behaviour. Existing scene bindings
and the phone journal continue to work.

Before delivery, check independent walking distances (including the routers'
actual snap points), three dated departures per boarding stop against the
operator, every phone capture at native and half size, and the real-phone
Reading/Pages frame gates. Use only captures for a return-route red-team pass.
Measure power and restore normal charging. Tool success is not field acceptance.

`check_navigation.py` owns holiday overrides, forbidden shortcuts, disconnected
walking graphs, feed expiry and service-day midnight semantics. The existing
`check_scene_tool.py` simulated-phone flow owns atomic bundle rejection,
publication and one-step undo. Neither proves physical touch, position,
heading, battery duration or phone frame performance.

Add `--sense` after building `kernel/n90-sense` to export the private graph,
WMM2025 model and landmark choices. With `--put`, these are installed alongside
the scenes and retained in the operator's private boot directory. Known Wi-Fi
mappings are retained; OSM-name sightings alone are hints. The Map and Walks
cards use the documented `{{sense.*}}` files. See
[`kernel/n90-sense/README.md`](../../kernel/n90-sense/README.md) for calibration,
uncertainty, controls, field scoring and hardware limitations. The arrive-by
search also reserves five minutes before its latest computed departure.
