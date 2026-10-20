#!/usr/bin/env python3
"""Process-level recovery contracts for the LVGL runtime, without device input.

Catches duplicate writers, invalid/oversized AI scene updates, lost reading
position and shutdown leaks. Kernel gesture checks live in check_touch.py.
"""

import argparse, json, os, shutil, subprocess as sp, time, hashlib
from pathlib import Path

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
proc = None
args = [
    str(a.binary.resolve()),
    "--headless",
    "--assets",
    str(root / "assets"),
    "--scenes",
    str(out / "scenes"),
    "--run",
    str(run),
]


def wait(pred, seconds=8):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if proc.poll() is not None:
            raise AssertionError("renderer exited")
        try:
            s = json.loads((run / "status.json").read_text())
            if pred(s):
                return s
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.03)
    raise AssertionError("state did not arrive")


def command(s):
    with (run / "control").open("w") as f:
        f.write(s + "\n")


def capture():
    path = run / "frame.ppm"
    path.unlink(missing_ok=True)
    command("capture")
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if path.exists() and path.stat().st_size == 640 * 960 * 3 + 15:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        time.sleep(0.03)
    raise AssertionError("capture incomplete")


try:
    with (out / "runtime.log").open("w") as log:
        proc = sp.Popen(
            args,
            stdout=log,
            stderr=sp.STDOUT,
            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1"},
        )
        wait(lambda s: s["scene"] == "battery")
        duplicate = sp.run(args, capture_output=True, timeout=8)
        checks["single_writer"] = (
            duplicate.returncode != 0 and b"already running" in duplicate.stderr
        )
        command("goto reader")
        wait(lambda s: s["scene"] == "reader" and s["page_x"] == 1280)
        command("scroll 900")
        wait(lambda s: s["scroll"] == 900)
        before = capture()
        command("reload")
        wait(lambda s: s["scene"] == "reader" and s["scroll"] == 900)
        time.sleep(0.2)
        checks["reload_keeps_reading_position"] = capture() == before
        command("scroll -9600")
        wait(lambda s: s["scroll"] == 0)
        checks["scroll_command_clamps_top"] = True
        command("scroll 9600")
        wait(lambda s: s["scroll"] == s["content_height"] - 748)
        checks["last_line_reachable"] = True
        index = (out / "scenes/index").read_text()
        doc = out / "scenes/hello.md"
        doc.write_text(
            "---\nid: hello\nlabel: Notes\naccent: cyan\n---\n# Привет, мир.\n\n**New** content and `code`.\n"
        )
        (out / "scenes/index").write_text(index + "hello\n")
        command("reload")
        wait(lambda s: s["count"] == 6)
        command("goto hello")
        wait(lambda s: s["scene"] == "hello" and s["page_x"] == 3200)
        time.sleep(0.3)
        before = capture()
        checks["hot_add_scene"] = True
        for name, broken in [
            ("invalid_bundle", "broken"),
            ("oversized_scene", "---\nid: hello\n---\n" + "x" * 131073),
            ("excessive_blocks", "---\nid: hello\n---\n" + "x\n" * 2050),
        ]:
            doc.write_text(broken)
            command("reload")
            time.sleep(0.3)
            s = wait(lambda s: s["scene"] == "hello")
            checks[name + "_retains_pixels"] = capture() == before and s["count"] == 6
        (out / "scenes/index").write_text(index)
        command("reload")
        wait(lambda s: s["count"] == 5 and s["scene"] == "battery")
        checks["remove_active_scene_recovers"] = True
        command("quit")
        proc.wait(timeout=10)
        checks["clean_shutdown"] = proc.returncode == 0
finally:
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=10)
    result = {
        "passed": bool(checks) and all(checks.values()),
        "checks": checks,
        "binary_sha256": hashlib.sha256(a.binary.read_bytes()).hexdigest(),
        "scope": "Native process, FIFO, pixels and sanitizer checks; no hardware claims",
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
raise SystemExit(0 if result["passed"] else 1)
