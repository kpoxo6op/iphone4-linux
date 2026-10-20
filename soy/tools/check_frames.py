#!/usr/bin/env python3
"""Measure completed frames during real-phone uinput motion, not configured Hz.

Ten-second contact streams run on the phone, so SSH round trips cannot set the
animation cadence. Trace intervals include scheduling, input, drawing and the
synchronous simpledrm damage copy. This still cannot measure panel scanout.
"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess as sp
import time

p = argparse.ArgumentParser()
p.add_argument("--ssh-config", type=Path, required=True)
p.add_argument("--replay", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
p.add_argument(
    "--surface",
    choices=["reading", "pages", "pinch", "pinch-out", "sheet", "bottom-sheet"],
    required=True,
)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
ssh = [
    "ssh",
    "-F",
    str(a.ssh_config.resolve()),
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "iphone4",
]


def remote(command, data=None):
    r = sp.run(ssh + [command], input=data, capture_output=True, timeout=45)
    r.check_returncode()
    return r.stdout


def point(x, y):
    return round(x * 4095 / 639), round(y * 4095 / 959)


def contact(command, slot, x, y):
    x, y = point(x, y)
    return (
        f"{command} {slot} "
        + (f"{100 + slot} " if command == "down" else "")
        + f"{x} {y}"
    )


remote(
    "cat > /run/soy/touch-replay; chmod 700 /run/soy/touch-replay",
    a.replay.read_bytes(),
)
remote("printf 'goto reader\n' > /run/soy/control")
time.sleep(0.6)
remote("printf 'scroll -9600\n' > /run/soy/control")
time.sleep(0.6)
remote("printf 'scroll 900\n' > /run/soy/control")
time.sleep(0.6)
initial = json.loads(remote("cat /run/soy/status.json"))
if initial["panel"] or initial["contacts"] or initial["scene"] != "reader":
    raise SystemExit("Reader must be settled with no open panel or contact")
commands = ["wait 1300", "sample", "mark touch_down"]
pinching = a.surface in ("pinch", "pinch-out")
if pinching:
    commands += [contact("down", 0, 200, 480), contact("down", 3, 440, 480), "frame"]
elif a.surface == "sheet":
    commands += [contact("down", 0, 320, 10), "frame"]
elif a.surface == "bottom-sheet":
    commands += [contact("down", 0, 320, 950), "frame"]
else:
    commands += [contact("down", 0, 480, 650), "frame"]
commands += ["wait 8"]
for i in range(1250):
    # Constant motion with a reversal, not a sine wave that sits on identical
    # integer pixels near its extrema. Stay inside the real pinch size limits;
    # a clamped, unchanged preview should sleep, not manufacture 60 new frames.
    cycle = (i + 1) % (80 if pinching else 250)
    half = 40 if pinching else 125
    wave = cycle / half if cycle <= half else (2 * half - cycle) / half
    if a.surface == "reading":
        commands.append(contact("move", 0, 480, 650 - 350 * wave))
    elif a.surface == "pages":
        commands.append(contact("move", 0, 480 - 380 * wave, 650))
    elif a.surface == "sheet":
        commands.append(contact("move", 0, 320, 10 + 440 * wave))
    elif a.surface == "bottom-sheet":
        commands.append(contact("move", 0, 320, 950 - 560 * wave))
    else:
        px = initial["font_px"]
        change = (
            -min(0.30, (px - 32) / px)
            if a.surface == "pinch-out"
            else min(50 / 120, (54 - px) / px)
        )
        if abs(change) < 0.04:
            raise SystemExit("Start pinch away from the font-size limit")
        spread = 120 * (1 + change * wave)
        commands += [
            contact("move", 0, 320 - spread, 480),
            contact("move", 3, 320 + spread, 480),
        ]
    if not i:
        commands += ["mark motion_start"]
    commands += ["frame", "wait 8"]
commands += ["mark release", "up 0"]
if pinching:
    commands += ["up 3"]
commands += ["frame", "wait 800", "sample", "quit"]
stream = "\n".join(commands) + "\n"
(a.out / "contacts.txt").write_text(stream)
r = sp.run(
    ssh + ["/run/soy/touch-replay"],
    input=stream.encode(),
    capture_output=True,
    timeout=40,
)
(a.out / "replay.log").write_bytes(r.stdout + r.stderr)
r.check_returncode()
states = [
    json.loads(line[6:])
    for line in r.stdout.decode().splitlines()
    if line.startswith("state:")
]
marks = {
    line.split()[0][5:]: float(line.split()[1])
    for line in r.stdout.decode().splitlines()
    if line.startswith("mark:")
}
if len(states) != 2:
    raise SystemExit("Missing phone-local before/after observations")
remote("printf 'trace\n' > /run/soy/control")
time.sleep(0.2)
data = remote("cat /run/soy/frames.csv")
(a.out / "frames.csv").write_bytes(data)
rows = [
    r
    for r in csv.DictReader(io.StringIO(data.decode()))
    if states[0]["frames"] <= int(r["frame"]) < states[1]["frames"]
]
# Keep the first and last moving frame, every intermediate stall, and repeated
# submitted frames. Only the idle tail after the final movement is excluded.
keys = ["scroll", "page", "panel", "scale", "panel_kind", "font_px"]
changed = [
    i for i in range(1, len(rows)) if any(rows[i][k] != rows[i - 1][k] for k in keys)
]
active = rows[max(0, changed[0] - 1) : changed[-1] + 1] if changed else []
intervals = [
    (float(b["end_s"]) - float(c["end_s"])) * 1000 for c, b in zip(active, active[1:])
]
render = [(float(r["end_s"]) - float(r["start_s"])) * 1000 for r in active]
transfer = [float(r["transfer_ms"]) for r in active]


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean_ms": sum(values) / len(values),
        "p95_ms": ordered[(len(values) - 1) * 95 // 100],
        "p99_ms": ordered[(len(values) - 1) * 99 // 100],
        "worst_ms": max(values),
    }


missed = sum(v > 1000 / 60 for v in intervals)
first_input = next(
    (
        row
        for row in rows
        if float(row["end_s"]) >= marks["touch_down"]
        and int(row["input"]) > states[0]["input_frames"]
    ),
    None,
)
first_motion = next(
    (rows[i] for i in changed if float(rows[i]["end_s"]) >= marks["motion_start"]),
    None,
)
result = {
    "surface": a.surface,
    "scope": "ARM Linux uinput to completed DRM damage copy; panel scanout unverified",
    "backend": states[1]["backend"],
    "input_sha256": hashlib.sha256(stream.encode()).hexdigest(),
    "intervals": summarize(intervals),
    "render_and_present": summarize(render),
    "transfer": summarize(transfer),
    "cpu_render_and_present": summarize([float(r["render_cpu_ms"]) for r in active]),
    "cpu_transfer": summarize([float(r["transfer_cpu_ms"]) for r in active]),
    "touch_down_to_first_input_frame_ms": (
        (float(first_input["end_s"]) - marks["touch_down"]) * 1000
        if first_input
        else None
    ),
    "motion_start_to_first_changed_frame_ms": (
        (float(first_motion["end_s"]) - marks["motion_start"]) * 1000
        if first_motion
        else None
    ),
    "onset_scope": "uinput write to completed damage copy; gesture thresholds included; not glass latency",
    "missed_16_67ms_intervals": missed,
    "average_completed_fps": 1000 * len(intervals) / sum(intervals) if intervals else 0,
    "passed": bool(intervals) and not missed and len(intervals) >= 590,
    "before": states[0],
    "after": states[1],
}
(a.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k not in ("before", "after")}))
raise SystemExit(0 if result["passed"] else 1)
