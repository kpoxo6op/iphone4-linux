# Offline sense layer

`n90-sense` reads the AK8975B and LIS331DLH through the kernel I2C adapters.
It publishes plain files and JSON under `/run/sense`, accepts a small FIFO
command vocabulary, and keeps private breadcrumbs. It is Linux tooling for
scenes. It does not provide a GPS fix.

The N90 iOS device tree identifies compass address `0x0d` on I2C0 and
accelerometer `0x19` on I2C2, GPIO79/80. `n90-i2c2.ko` registers the standard
Linux `i2c-gpio` adapter through GPIO descriptors, without private MMIO writes.
The chip label must match the actual platform (`bfa00000.gpio` on the measured
kernel). Source-grounded mounting matrices, row-major, are:

- Compass: `(0,-1,0), (-1,0,0), (0,0,-1)`.
- Accelerometer: `(0,1,0), (-1,0,0), (0,0,-1)`.

No Apple firmware or device-tree blob is included. Part/register references:
[AKM AK8975 MS1187-E-02](https://www.robotpark.com/image/data/PRO/91462/AK8975.pdf)
pp. 12–15 and 24–28; [ST LIS331DLH Doc ID 15094 Rev 3](https://www.st.com/resource/en/datasheet/lis331dlh.pdf).
AKM self-test includes ASA sensitivity adjustment and ST2 overflow/error checks.
LIS self-test uses the 12-bit ±2g limits: X/Y 120–550, Z 140–750 LSB.
The probe returns the sensors to power-down; the service uses 50 Hz acceleration
and about 8 Hz magnetic samples. It does not touch the gyro or GPS UART.

## Build and inputs

```
python3 kernel/n90-sense/build.py --cc /path/to/arm-linux-gcc --static
```

The optional module build also needs `--kernel-src`, `--kernel-build` and
`--kernel-cross` for the exact running kernel. At most two build jobs.
The build receipt pins NOAA's WMM2025 Linux archive and SHA-256. NOAA/NCEI's
geomagnetic implementation and coefficients are United States Government works
in the public domain, without use restrictions. The wrapper accepts private
coordinates on stdin; it never echoes them. It checks the model's five-year
validity. Geoid heights are not used: inputs are WGS84 ellipsoid height.

`soy/tools/nav/sense_pack.py` exports a bounded, private pedestrian neighbourhood,
checkpoint list and graph distances to the shop and homeward bus stop. The
coordinate origin is a projection reference, **never an initial position**.
`model.txt` contains the computed declination, total field and pickup epoch.
The private `wifi-known.tsv` may contain explicitly mapped BSSIDs; SSID-name
matches are only hints. `wifi-hints.tsv` contains OSM names near the planned
route. Neither Wi-Fi mechanism contacts a location service.

## File contract, schema 1

All files are private, replaced atomically once per second. `updated` is the
Unix publication time; zero or older than five seconds means unavailable.
`state.json` is the machine-readable position/source/uncertainty/age snapshot.
The corresponding scene bindings are `{{sense.NAME}}`:

| Name | Meaning |
|---|---|
| `heading` | Tilt-compensated true heading after accepted calibration, or unavailable |
| `steps` | Detected steps; not a measured distance |
| `position` | Estimated coordinates, or unavailable |
| `position_name` | Last given/mapped landmark name |
| `position_source` | Given landmark, known Wi-Fi, steps + compass, or unavailable |
| `position_age` | Time since the anchor fix |
| `position_accuracy` | Model uncertainty, including time without observed movement |
| `target`, `distance`, `eta`, `leave_by` | Mapped walking estimate to the shop or return stop; crossing time is extra |
| `mode` | Walking estimate or on-bus last-fix mode |
| `calibration` | Figure-eight progress or rejection/acceptance |
| `wifi`, `wifi_hint` | Kernel BSS-cache sightings with per-entry age; name hints are not fixes |

Distance uses reverse Dijkstra labels on the same permitted OSM graph as the
trip pack. Unreachable or distant targets say unavailable. The pickup time is
a trip assumption, not a repair-shop promise. After pickup the default target
becomes the return stop; the FIFO can choose either target explicitly.

`control` accepts `fix ID`, `calibrate`, `cancel`, `mode walk`, `mode bus`,
`target shop` and `target bus`. Unknown IDs and overlong lines are rejected.
Only IDs from `checkpoints` appear in Soy's **I'm here** sheet. On-bus mode
keeps the last fix and grows its uncertainty; it does not turn a timetable
into a measured position. The physical two-second interaction target still
needs the owner's trial; virtual contacts are not that evidence.

## Calibration, estimation and evidence

A 40-second figure eight fits a full 3-D ellipsoid: hard-iron centre and a
symmetric soft-iron correction. It requires at least 120 samples, coverage in
all eight corrected octants, plausible scale and residual below 8% of the WMM
field. Samples outside 80–120% of the expected field or without fresh gravity
make heading unavailable. Tilt comes from the N90 acceleration matrix. An
accepted fit does not prove ±5°; compare an independent bearing away from the
charger, metal and magnetic interference.

The 256-particle bootstrap filter advances only after a real/given fix and
valid heading. It samples stride (default 0.75 m, not calibrated to the owner)
and heading, weights candidates by distance to nearby public walking segments,
and resamples. It rejects constraints beyond eight metres rather than jumping
to a remote road. The initial three-peak cadence gate reduces isolated bumps;
its start-up steps are not all advanced. The filter constrains position to segments but does not enforce foot-oneway direction during estimation; planned routes do. It does not classify transport modes,
model stairs or prove which side of a close parallel path the owner occupies.
Model uncertainty is deliberately not a measured 95% accuracy result.

`journal.jsonl` retains up to 32 MiB without silently rotating away an offline
trip. It records fixes, the estimate **before** each fix, steps/headings,
calibration samples and cached Wi-Fi sightings. `n90-wifi sightings` reads nl80211 without requesting a scan; the existing Wi-Fi keeper continues to own scanning and association. Name hints require an observation less than two minutes old. `scene.py journal pull` keeps
separate producer cursors and appends both journals to the existing private
daily files. `score_sense.py --since` selects the actual field trial and scores
pre-reset predictions; prior fixes may anchor the estimate. Heading accuracy
requires independent bearing-reference events. Missing references stay missing.
A one-kilometre walk and screen-off energy increment still require field/device
evidence; mathematical fixtures cannot pass them.

Native checks use the real FIFO/files and isolated `/run`:
`soy/tools/check_sense_boundary.py`. They own unknown/stale state, fix validation,
reading-position preservation and one-time journal transfer. The existing scene
boundary check owns ordinary reload/recovery; it does not exercise a sensor
producer. `check_calibration.py` owns orientation sign and calibration degeneracy
against independently rotated vectors; real probes cannot supply known magnetic
vectors. Actual self-test, power and frame results belong in the private operator
report and must be labelled real hardware.

For a cached private trip profile, `soy/tools/trip.py --request 'Town today 9:30, back by 13:00' --config PROFILE --osm EXTRACT --gtfs FEED --out PRIVATE --sense --put --operator OPERATOR` computes and installs both scenes and sense inputs. A native WMM caller is built alongside the phone binaries. The operator must already have the sensor binaries and exact-kernel adapter built; the first build/source download and independent release checks are separate from cached pack timing. Destination names must resolve uniquely in the private profile. Changed appointments discard old curated walking notes and require fresh checks. This is a bounded compiler, not unrestricted natural-language geocoding.
