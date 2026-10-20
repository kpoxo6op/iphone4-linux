#!/usr/bin/env python3
"""Idle policy through the real process, FIFO, status and rendered pixels.

Live telemetry or AI reloads must not prevent blanking, and wake must retain
reading position. Existing scene tests never wait for inactivity. This native
check makes no panel-power or physical-input claim; check_touch.py owns evdev.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import time

p = argparse.ArgumentParser()
p.add_argument("--binary", type=Path, required=True)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
out = a.out.resolve()
out.mkdir(parents=True, exist_ok=False)
shutil.copytree(root / "scenes", out / "scenes")
run = out / "run"
run.mkdir()
checks = {}
error = None
proc = None


def state():
    return json.loads((run / "status.json").read_text())


def wait(pred, seconds=8):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if proc.poll() is not None:
            raise AssertionError("renderer exited")
        try:
            s = state()
            if pred(s):
                return s
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.03)
    raise AssertionError(f"state timeout: {state()}")


def command(s):
    with (run / "control").open("w") as f:
        f.write(s + "\n")


def capture(name):
    path = run / "frame.ppm"
    path.unlink(missing_ok=True)
    command("capture")
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if path.exists() and path.stat().st_size == 640 * 960 * 3 + 15:
            data = path.read_bytes()
            (out / f"{name}.ppm").write_bytes(data)
            return data
        time.sleep(0.03)
    raise AssertionError("capture incomplete")


def check(name, ok):
    checks[name] = bool(ok)
    if not ok:
        raise AssertionError(name)


try:
    with (out / "runtime.log").open("w") as log:
        proc = sp.Popen(
            [
                str(a.binary.resolve()),
                "--headless",
                "--assets",
                str(root / "assets"),
                "--scenes",
                str(out / "scenes"),
                "--run",
                str(run),
                "--idle-seconds",
                "2",
            ],
            stdout=log,
            stderr=sp.STDOUT,
            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1"},
        )
        wait(lambda s: s["display_state"] == "awake")
        # The battery scene has live bindings. Sampling must not count as use.
        asleep = wait(lambda s: s["display_state"] == "blanked")
        black = capture("idle-black")
        check("live_scene_blanks_to_black", not any(black[15:]))
        for _ in range(12):
            command("trace")
            time.sleep(0.1)
        check(
            "diagnostics_do_not_wake_or_render",
            state()["display_state"] == "blanked"
            and state()["frames"] == asleep["frames"],
        )
        command("goto reader")
        wait(lambda s: s["display_state"] == "awake" and s["page_x"] == 1280)
        command("scroll 650")
        wait(lambda s: s["scroll"] == 650)
        before = capture("reader-before")
        wait(lambda s: s["display_state"] == "blanked")
        command("reload")
        time.sleep(0.5)
        check(
            "reload_stays_dark",
            state()["display_state"] == "blanked" and capture("reload-black") == black,
        )
        command("wake")
        wait(lambda s: s["display_state"] == "awake" and s["scroll"] == 650)
        check("wake_restores_reader_pixels", capture("reader-after") == before)
        command("sleep")
        wait(lambda s: s["display_state"] == "blanked")
        command("next")
        wait(lambda s: s["display_state"] == "awake" and s["scene"] == "files")
        check("remote_navigation_wakes", True)
        command("idle 0")
        command("wake")
        wait(lambda s: s["idle_timeout_s"] == 0)
        time.sleep(2.4)
        check("timeout_can_be_disabled", state()["display_state"] == "awake")
        command("idle -1")
        command("idle 999999999999999999999999")
        time.sleep(0.2)
        check("invalid_timeout_retains_setting", state()["idle_timeout_s"] == 0)
        command("sleep")
        wait(lambda s: s["display_state"] == "blanked")
        command("quit")
        proc.wait(timeout=10)
        check("shutdown_while_blanked", proc.returncode == 0)
except Exception as exc:
    error = str(exc)
    raise
finally:
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=10)
    result = {
        "passed": bool(checks) and all(checks.values()) and error is None,
        "checks": checks,
        "error": error,
        "binary_sha256": hashlib.sha256(a.binary.read_bytes()).hexdigest(),
        "scope": "Native process, FIFO, pixels and sanitizer; no phone or backlight-power proof",
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
