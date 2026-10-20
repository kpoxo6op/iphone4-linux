#!/usr/bin/env python3
"""Real ARM process + Linux uinput/evdev + LVGL + framebuffer gesture checks.

Observable contracts: contacts move pixels before release; native scroll/page
physics retain control; malformed/lost input cannot become a tap; scene reload
keeps the last valid bundle. Unlike the old FIFO checks, this exercises kernel
contact slots, calibration, hotplug and overflow. It does NOT prove glass touch.
"""

import argparse, gzip, json, subprocess as sp, time, select, hashlib
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--ssh-config", required=True, type=Path)
p.add_argument("--replay", required=True, type=Path)
p.add_argument("--out", required=True, type=Path)
p.add_argument("--only", default="")
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
checks = {}
evidence = {}
replay = None
samples = []


def remote(cmd, data=None):
    r = sp.run(ssh + [cmd], input=data, capture_output=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr.decode()[-800:] or f"remote exit {r.returncode}")
    return r.stdout


def state():
    return json.loads(remote("cat /run/soy/status.json"))


def wait(pred, timeout=5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = state()
        if pred(last):
            return last
        time.sleep(0.04)
    raise AssertionError(f"state timeout: {last}")


def command(cmd):
    # Commands here are fixed test strings, not scene content.
    remote("printf '%s\\n' '" + cmd + "' > /run/soy/control")


def send(lines):
    samples.clear()
    replay.stdin.write(lines + "\nack\n")
    replay.stdin.flush()
    if not select.select([replay.stdout], [], [], 15)[0]:
        raise TimeoutError("replay acknowledgement")
    while True:
        line = replay.stdout.readline().strip()
        if line == "ack":
            break
        if line.startswith("state:"):
            samples.append(json.loads(line[6:]))
        if replay.poll() is not None:
            raise RuntimeError("replay exited")


def xy(x, y):
    return round(x * 4095 / 639), round(y * 4095 / 959)


def down(x, y, slot=0):
    x, y = xy(x, y)
    send(f"down {slot} {100 + slot} {x} {y}\nframe\nwait 40")


def move(x, y, slot=0, ms=30):
    x, y = xy(x, y)
    send(f"move {slot} {x} {y}\nframe\nwait {ms}")


def up(slot=0):
    send(f"up {slot}\nframe\nwait 40")


def motion(x0, y0, x1, y1, steps=18, ms=16, slot=0):
    lines = []
    for i in range(1, steps + 1):
        x, y = xy(round(x0 + (x1 - x0) * i / steps), round(y0 + (y1 - y0) * i / steps))
        lines.extend([f"move {slot} {x} {y}", "frame", f"wait {ms}"])
    send("\n".join(lines))


def goto(scene, x):
    command("goto " + scene)
    wait(lambda s: s["scene"] == scene and abs(s["page_x"] - x) < 2)
    time.sleep(0.35)


def assert_check(name, ok, detail=None):
    checks[name] = bool(ok)
    if detail is not None:
        evidence[name] = detail
    print(name, "PASS" if ok else "FAIL", flush=True)
    if not ok:
        raise AssertionError(name)


def capture(name):
    command("capture")
    time.sleep(0.2)
    data = gzip.decompress(remote("gzip -c /run/soy/frame.ppm"))
    (a.out / (name + ".ppm")).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


try:
    remote(
        "cat > /run/soy/touch-replay; chmod 700 /run/soy/touch-replay",
        a.replay.read_bytes(),
    )
    replay = sp.Popen(
        ssh + ["/run/soy/touch-replay"],
        stdin=sp.PIPE,
        stdout=sp.PIPE,
        stderr=(a.out / "replay.log").open("w"),
        text=True,
        bufsize=1,
    )
    if (
        not select.select([replay.stdout], [], [], 10)[0]
        or replay.stdout.readline().strip() != "ready"
    ):
        raise RuntimeError("replay not ready")
    start = wait(lambda s: s["virtual_inputs"] == 1, 8)
    evidence["start"] = start
    assert_check("virtual_device_discovered", start["virtual_inputs"] == 1)
    if a.only in ("", "navigation"):
        goto("reader", 1280)
        before = capture("reader-before")
        down(550, 450)
        motion(550, 450, 140, 450)
        held = state()
        during = capture("page-held")
        assert_check(
            "page_follows_contact",
            held["contacts"] == 1 and 1300 < held["page_x"] < 1920 and before != during,
            held,
        )
        up()
        wait(lambda s: s["scene"] == "files" and abs(s["page_x"] - 1920) < 2)
        assert_check("page_snap", True)
        goto("reader", 1280)
        down(400, 450)
        motion(400, 450, 350, 450, 10, 25)
        send("wait 180")
        up()
        settled = wait(lambda s: abs(s["page_x"] - 1280) < 2)
        assert_check("short_drag_returns", settled["scene"] == "reader")
        goto("battery", 0)
        down(180, 430)
        motion(180, 430, 420, 430)
        held = state()
        capture("first-page-bounce")
        up()
        assert_check("first_page_elastic", held["page_x"] < 0, held)
        wait(lambda s: abs(s["page_x"]) < 2)
        goto("settings", 2560)
        down(460, 430)
        motion(460, 430, 210, 430)
        held = state()
        up()
        assert_check("last_page_elastic", held["page_x"] > 2560, held)
        wait(lambda s: abs(s["page_x"] - 2560) < 2)
        goto("reader", 1280)
        down(440, 904)
        up()
        wait(lambda s: s["scene"] == "files")
        assert_check("large_page_tap", True)
    if a.only in ("", "reading"):
        goto("reader", 1280)
        command("scroll -9600")
        time.sleep(0.6)
        down(310, 760)
        motion(310, 760, 310, 310, 20, 16)
        held = state()
        motion(310, 310, 310, 210, 6, 16)
        up()
        time.sleep(0.12)
        after = state()
        assert_check(
            "reading_momentum",
            held["scroll"] > 250 and after["scroll"] > held["scroll"] + 100,
            {"held": held, "after": after},
        )
        x, y = xy(310, 510)
        send(
            f"down 0 100 {x} {y}\nframe\nwait 140\nsample\nwait 180\nsample\nup 0\nframe\nwait 40"
        )
        stopped, stopped2 = samples
        assert_check(
            "touch_stops_momentum",
            abs(stopped["scroll"] - stopped2["scroll"]) < 4 and stopped2["panel"] == 0,
            {"a": stopped, "b": stopped2},
        )
        position = stopped2["scroll"]
        goto("files", 1920)
        goto("reader", 1280)
        assert_check("reading_position_retained", abs(state()["scroll"] - position) < 5)
        down(270, 480, 3)
        motion(270, 480, 270, 390, 8, 20, 3)
        held = state()
        up(3)
        assert_check(
            "sparse_primary_slot",
            held["contacts"] == 1 and held["scroll"] > position,
            held,
        )
        command("scroll 9600")
        time.sleep(0.7)
        end = state()
        down(310, 600)
        motion(310, 600, 310, 340)
        held = state()
        capture("document-bounce")
        up()
        time.sleep(0.8)
        settled = state()
        assert_check(
            "document_end_elastic",
            held["scroll"] > end["scroll"]
            and abs(settled["scroll"] - end["scroll"]) < 4,
            {"end": end, "held": held, "settled": settled},
        )
    if a.only in ("", "pinch"):
        goto("reader", 1280)
        command("scroll -9600")
        time.sleep(0.6)
        command("scroll 900")
        time.sleep(0.6)
        before = state()
        down(250, 440)
        x, y = xy(390, 520)
        send(f"down 3 303 {x} {y}\nframe\nwait 60")
        lines = []
        for i in range(1, 21):
            x, y = xy(250 - i * 3, 440 - i)
            xx, yy = xy(390 + i * 3, 520 + i)
            lines.extend([f"move 0 {x} {y}", f"move 3 {xx} {yy}", "frame", "wait 24"])
        send("\n".join(lines))
        during = state()
        capture("pinch-large")
        up(0)
        move(510, 580, 3)
        up(3)
        after = wait(
            lambda s: s["contacts"] == 0
            and s["pinch_scale"] == 1
            and s["font_px"] > before["font_px"]
        )
        assert_check(
            "pinch_uses_two_slots",
            during["pinch_scale"] > 1.1
            and during["pinch_events"] > before["pinch_events"]
            and after["font_px"] > before["font_px"],
            {"before": before, "during": during},
        )
        assert_check(
            "pinch_does_not_turn_page",
            after["scene"] == "reader"
            and abs(after["page_x"] - 1280) < 2
            and after["panel"] == 0,
            after,
        )
        before_small = after
        down(180, 480)
        down(460, 480, 3)
        lines = []
        for i in range(1, 21):
            x, y = xy(180 + i * 3.5, 480)
            xx, yy = xy(460 - i * 3.5, 480)
            lines.extend([f"move 0 {x} {y}", f"move 3 {xx} {yy}", "frame", "wait 24"])
        send("\n".join(lines))
        smaller = state()
        capture("pinch-small")
        send("up 0\nup 3\nframe\nwait 300")
        after = wait(lambda s: s["contacts"] == 0 and s["pinch_scale"] == 1)
        assert_check(
            "pinch_zoom_out",
            smaller["pinch_scale"] < 0.85
            and after["font_px"] < before_small["font_px"]
            and after["scene"] == "reader"
            and abs(after["page_x"] - 1280) < 2,
            {"before": before_small, "during": smaller, "after": after},
        )
        # Switching from inertial reading into a two-finger gesture must cancel
        # the old motion without letting the remaining contact turn a page.
        down(470, 650)
        motion(470, 650, 470, 220, 12, 10)
        x, y = xy(200, 480)
        xx, yy = xy(440, 480)
        send(
            "up 0\nframe\nwait 120\nsample\nwait 120\nsample\n"
            f"down 0 100 {x} {y}\nframe\nwait 16\n"
            f"down 3 303 {xx} {yy}\nframe\nwait 40"
        )
        first_moving, before_moving = samples
        lines = []
        for i in range(1, 21):
            x, y = xy(200 - i * 3, 480)
            xx, yy = xy(440 + i * 3, 480)
            lines.extend([f"move 0 {x} {y}", f"move 3 {xx} {yy}", "frame", "wait 20"])
        send("\n".join(lines))
        held_moving = state()
        send("up 0\nup 3\nframe\nwait 300")
        resumed = wait(lambda s: s["contacts"] == 0 and s["pinch_scale"] == 1)
        assert_check(
            "pinch_interrupts_reading",
            before_moving["scroll"] > first_moving["scroll"]
            and held_moving["pinch_scale"] > 1.1
            and resumed["font_px"] > before_moving["font_px"]
            and resumed["scene"] == "reader"
            and abs(resumed["page_x"] - 1280) < 2
            and resumed["panel"] == 0,
            {"before": before_moving, "held": held_moving, "after": resumed},
        )
        assert_check(
            "pinch_cache_stays_bounded",
            held_moving["cache_bytes"] <= 128 * 1024 * 1024
            and resumed["cache_bytes"] <= 128 * 1024 * 1024,
        )
        # Double tap returns to default reading size, without a stray page action.
        down(300, 480)
        up()
        send("wait 90")
        down(302, 482)
        up()
        time.sleep(0.3)
        assert_check("double_tap_text_size", state()["font_px"] == 36, state())
    if a.only in ("", "panels"):
        goto("reader", 1280)
        down(320, 8)
        motion(320, 8, 320, 410, 22, 16)
        held = state()
        capture("status-sheet-held")
        up()
        opened = wait(lambda s: s["panel"] == 1 and s["panel_open"] > 470)
        assert_check(
            "top_edge_sheet",
            held["panel"] == 1 and held["panel_open"] > 100,
            {"held": held, "open": opened},
        )
        down(320, 440)
        motion(320, 440, 320, 40, 22, 16)
        up()
        wait(lambda s: s["panel"] == 0)
        assert_check("reverse_closes_sheet", True)
        down(320, 8)
        motion(320, 8, 320, 410, 22, 16)
        up()
        wait(lambda s: s["panel"] == 1 and s["panel_open"] > 470)
        down(320, 750)
        up()
        wait(lambda s: s["panel"] == 0)
        assert_check("outside_tap_below_top_sheet", True)
        down(320, 952)
        motion(320, 952, 320, 320, 25, 16)
        held = state()
        up()
        wait(lambda s: s["panel"] == 2 and s["panel_open"] > 590)
        assert_check(
            "bottom_edge_picker", held["panel"] == 2 and held["panel_open"] > 100, held
        )
        capture("scene-picker")
        # Picker begins at screen y=360: first row is y=460..556.
        down(280, 508)
        up()
        wait(lambda s: s["panel"] == 0 and s["scene"] == "battery")
        assert_check("picker_tap_selects_scene", True)
        goto("reader", 1280)
        down(320, 952)
        motion(320, 952, 320, 320, 25, 16)
        up()
        wait(lambda s: s["panel"] == 2 and s["panel_open"] > 590)
        down(320, 180)
        up()
        wait(lambda s: s["panel"] == 0 and s["scene"] == "reader")
        assert_check("outside_tap_above_bottom_sheet", True)
        down(300, 450)
        send("wait 760")
        up()
        wait(lambda s: s["panel"] == 3 and s["panel_open"] > 410)
        assert_check("long_press_text_controls", True)
        capture("text-controls")
        down(300, 220)
        up()
        wait(lambda s: s["panel"] == 0)
        assert_check("outside_tap_dismisses", True)
    if a.only in ("", "recovery"):
        goto("reader", 1280)
        before = state()
        down(220, 470)
        down(420, 470, 3)
        move(190, 470)
        move(450, 470, 3)
        down(320, 600, 5)
        up(5)
        up(0)
        up(3)
        time.sleep(0.3)
        after = state()
        assert_check(
            "third_contact_cancels_pinch",
            after["font_px"] == before["font_px"]
            and after["scene"] == "reader"
            and after["contacts"] == 0
            and after["panel"] == 0,
            after,
        )
        goto("reader", 1280)
        down(300, 540)
        move(300, 400)
        send("disconnect")
        wait(lambda s: s["virtual_inputs"] == 0 and s["contacts"] == 0, 8)
        assert_check("removal_cancels_contact", True)
        send("connect")
        wait(lambda s: s["virtual_inputs"] == 1, 8)
        down(440, 902)
        up()
        wait(lambda s: s["scene"] == "files")
        assert_check("hotplug_recovers_navigation", True)
        goto("reader", 1280)
        down(310, 450)
        before = state()
        send("flood\nframe\nwait 180")
        up()
        time.sleep(0.5)
        after = state()
        assert_check(
            "kernel_overflow_cancels",
            after["dropped_events"] > before["dropped_events"]
            and after["contacts"] == 0,
            after,
        )
        down(440, 902)
        up()
        wait(lambda s: s["scene"] == "files")
        assert_check("navigation_after_overflow", True)
    evidence["finish"] = state()
except Exception as e:
    evidence["error"] = str(e)
    try:
        evidence["failure_state"] = state()
    except Exception:
        pass
    raise
finally:
    if replay and replay.poll() is None:
        try:
            replay.stdin.write("quit\n")
            replay.stdin.flush()
            replay.wait(timeout=5)
        except Exception:
            replay.terminate()
            replay.wait(timeout=5)
    result = {
        "passed": bool(checks) and all(checks.values()) and "error" not in evidence,
        "checks": checks,
        "evidence": evidence,
        "scope": "Real phone virtual touchscreen; physical digitizer remains unverified",
    }
    (a.out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": checks}), flush=True)
