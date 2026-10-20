# Soy touch and frame timing

Read `AGENTS.md`, `docs/soy/touch-research.md` and `docs/soy/performance.md`.
Build the pinned LVGL/Pixman source with `soy/tools/build_touch.py`. Record
the build receipt, project-source hashes and exact ARM binary SHA-256.

Three independent contracts:

1. **Runtime behavior.** `soy/tools/check_scene_boundary.py` runs the native
   sanitizer build through real scene reloads, rendering and process ownership.
   `soy/tools/check_touch.py` uses a named virtual Linux touchscreen on the
   actual phone. It exercises contact following, momentum, interruption,
   zoom-in/out, edge sheets, outside taps, slot loss, hotplug and event overflow.
   These catch failures the old high-level FIFO gesture checks cannot reach.
2. **Motion timing.** `soy/tools/check_frames.py` accepts `reading`, `pages`,
   `pinch`, `pinch-out`, `sheet` and `bottom-sheet`. Keep all completed-frame
   intervals, release/reflow, misses, worst stalls and onset observations.
   Every moving interval must be within 16.67 ms. An average, a nominal timer,
   CPU-only timing or a clipped trace cannot pass. Inspect cold start, settling
   and live-scene updates too; the six workloads alone are not full coverage.
3. **Physical result.** Read back the active KMS buffer independently with
   `soy/tools/display_capture.c` and inspect native and 320 × 480 images.
   Separately require real finger-generated contacts and visible behavior on
   the display. KMS bytes and virtual contacts cannot prove the digitizer,
   panel refresh timing or absence of tearing.

Use a new output directory for each changed build. Name which observable
contract a new check protects and why existing coverage is insufficient.
Reuse passing checks only while their relevant inputs remain unchanged.
Preserve failed receipts and distinguish a tool error from a measured failure.

Only the assigned operator or maintainer runs phone tests. Keep independent
SSH, the current RAM boot and a known working renderer available. No generic
process kills, kernel reboot, real-time starvation, secret-bearing fixtures or
private SSH configuration in evidence. A passing runtime check does not close
the still-failing frame gate.

Idle policy has a separate process check: `soy/tools/check_idle.py`. It protects
inactivity from telemetry/AI updates and verifies black pixels plus exact reader
restoration. `check_touch.py --only idle` exercises wake-contact suppression,
held contacts, the next actionable touch and SSH wake. Use `--scope qemu` for
emulator runs; never report those as phone tests. Neither check proves backlight
power-off. Follow `docs/soy/idle-display.md` for the remaining hardware gate.
