# Rendering toward Ghostty's standard

The owner selected [Ghostty](https://github.com/ghostty-org/ghostty) as Soy's
reference on 20 October 2026: crisp text, immediate response and smooth movement
on a real device. The first Soy prototype does not meet that standard.

## What the reference actually does

We inspected Ghostty revision
`b58ef1d678be2747c830bc1b1e6c0a086afecf9a`, rather than assuming a remembered
architecture. Ghostty is MIT-licensed.

- Its [renderer thread](https://github.com/ghostty-org/ghostty/blob/b58ef1d678be2747c830bc1b1e6c0a086afecf9a/src/renderer/Thread.zig)
  wakes for ordinary updates and schedules animation work separately. It
  distinguishes updating frame data from drawing, and accounts for a backend
  that controls vsync.
- Its [generic renderer](https://github.com/ghostty-org/ghostty/blob/b58ef1d678be2747c830bc1b1e6c0a086afecf9a/src/renderer/generic.zig)
  retains shaping and scrollbar state and separates frame resources from
  presentation. It tracks both rendering health and the application's ability
  to present a frame.
- Its [font atlas](https://github.com/ghostty-org/ghostty/blob/b58ef1d678be2747c830bc1b1e6c0a086afecf9a/src/font/Atlas.zig)
  gives glyph images reusable storage. Soy already bakes a small atlas; it still
  needs better retention of laid-out document content during scrolling.
- The [project README](https://github.com/ghostty-org/ghostty/tree/b58ef1d678be2747c830bc1b1e6c0a086afecf9a)
  describes platform-specific GPU renderers and an embeddable terminal core.
  The terminal core is a candidate if Soy gains real PTY-backed scenes.

Our decision is to learn from those boundaries now. A GTK desktop application
is not the initial phone shell. The present phone exposes simpledrm framebuffer
output; a working accelerated PowerVR rendering stack has not been established.
Importing a GPU renderer cannot supply that missing driver.

The [ARMv7 feasibility check](../../soy/ghostty/README.md) now passes on the
real iPhone: shell output through a PTY, Cyrillic, styles, cursor updates,
alternate screens and resize. The decision is to reuse libghostty-vt for
terminal semantics. Its C API supplies incremental render state for our
display adapter. It does not include the GPU renderer. The existing Markdown
scenes remain useful while a PTY scene is integrated.

## Current display path

The display is 640 × 960 XRGB8888, stride 2560. One full frame is 2,457,600
bytes: 60 copies per second move about 147 MB/s before any composition.
The LVGL prototype draws directly into a cached DRM dumb buffer and submits
its damage through synchronous `DRM_IOCTL_MODE_DIRTYFB`. The adapter validates
the fixed simpledrm mode and restores the previous CRTC on clean exit. The
old framebuffer renderer remains available for recovery; SSH is independent.

Pinned LVGL 9.6.0 owns input, layout, scroll physics and animation. Immutable
paragraph snapshots avoid laying out and blending every glyph during a drag.
Pinned Pixman 0.46.4 supplies an ARM NEON nearest-neighbour pinch preview via
LVGL's draw-unit extension. Text reflows from its original source after release.
The small extension uses private LVGL draw structures, so upgrades require
rechecking clipping, task ordering and source lifetime.

The kernel's fbdev **mmap** path uses deferred I/O with a `HZ / 20` delay.
That is not a general 50 ms limit on framebuffer output: fbdev **pwrite** damage
uses `drm_fb_helper_damage_range` and immediate work scheduling. Earlier notes
conflated these paths. Direct simpledrm avoids the fbdev scheduling path, but
still copies pixels. A completed copy does not prove panel scanout, vsync or
absence of tearing. The current boot framebuffer reports no measured refresh
rate, and no accelerated PowerVR driver has been established.

Source references: pinned kernel `drivers/gpu/drm/sysfb/simpledrm.c`,
`drivers/gpu/drm/sysfb/drm_sysfb_modeset.c`,
`drivers/gpu/drm/drm_damage_helper.c`,
`drivers/gpu/drm/drm_fbdev_shmem.c` and `drivers/gpu/drm/drm_fb_helper.c`;
[Linux DRM UAPI](https://docs.kernel.org/gpu/drm-uapi.html);
[LVGL source](https://github.com/lvgl/lvgl/tree/80ca777e37a2b176770726a02e07a6fb79ef0b39);
[Pixman](https://gitlab.freedesktop.org/pixman/pixman/-/tree/pixman-0.46.4).

## Real touch, lean kernel and NEON scanout — 22 October 2026

Physical touch now arrives from the N1 controller (`kernel/n90-touch`) at
62.5 Hz. Boris called the first swipes laggy. Measured causes and fixes:

1. **Display copy.** simpledrm's `DIRTYFB` copied a full frame in 9.5 ms.
   Soy now copies damage itself with 128-bit NEON stores into a
   write-combined `/dev/mem` mapping of the scanout buffer (from
   `/proc/iomem`): 3.3–4 ms. `SOY_SCANOUT=dirtyfb` restores the kernel copy.
2. **Debug kernel.** Lockdep, lock debugging and the function tracer made
   syscalls 10–50× slower (sysfs read 1.4 ms), so telemetry stalled frames
   by 10–20 ms. The lean kernel (`kernel/n90-display-power/lean.config`) also
   registers a 24 MHz `sched_clock` and runs HZ 1000.
3. **Preemption.** Soy runs `SCHED_FIFO` 10 and the touch driver FIFO 20, so
   tailscaled bursts and telemetry readers no longer interrupt a frame.
4. **Animation pacing.** While an animation runs, Soy steps it and draws again
   at once instead of waiting for the next 8 ms tick.

`check_frames.py --host iphone4-usb` (the replay runs at FIFO 20, like the
touch driver; tailnet SSH adds WireGuard work that real use does not have).
Lean kernel `e899dceb`, Soy `prototype-613489419040`:

| Surface | Average fps | p95 | p99 | Worst | Misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reading | 106.2 | 10.5 ms | 11.0 ms | 12.3 ms | 0 / 1096 |
| Pages | 85.5 | 13.0 ms | 14.8 ms | 19.6 ms | 1 / 891 |
| Pinch in | 83.9 | 13.4 ms | 14.2 ms | 22.4 ms | 1 / 865 |
| Pinch out | 95.8 | 12.9 ms | 14.1 ms | 22.2 ms | 1 / 987 |
| Top sheet | 120.7 | 8.7 ms | 9.9 ms | 33.1 ms | 2 / 1242 |
| Bottom sheet | 113.8 | 10.0 ms | 10.9 ms | 29.2 ms | 2 / 1169 |

Before these changes the same pages run averaged 52.8 fps with 577 misses.
**Five of six surfaces still miss the release gate** by one or two frames:
the frame that settles the view after release (8–13 ms idle wait plus a
12–17 ms full redraw), and the first frame of a cold sheet (25 ms of
construction). Pages and pinch render in ~11 ms including the 4 ms copy, so
there is little headroom. Next: prepare sheets at rest, avoid the full-view
rebuild at the end of a gesture, and move the touch driver into the kernel
with the ATN interrupt instead of polling.

## Morning of 22 October 2026: fair server, cache budget, snap pacing

Three things moved the frame results, measured with `check_frames.py --host
iphone4-usb` on the lean kernel with keep (`kernel/n90-keep`) and the battery
reader running, as on every boot now:

1. **The kernel's fair server.** Since Linux 6.12 a deadline server gives
   normal tasks 50 ms per second whenever real-time tasks keep the CPU busy.
   Soy renders at `SCHED_FIFO`, so as soon as keep or tailscaled had work
   during a gesture, Soy stopped for 50 ms once a second: reading went from
   0 to 6–10 misses with a 61 ms worst frame. With keep and the battery reader
   stopped, 0 misses. `harness/phone_boot.py` now gives the fair server 0.5 ms
   every 50 ms instead. keep also no longer runs `pidof`, which read every
   process's command line under its mmap lock.
2. **The cache budget.** A sixth, text-heavy scene filled the 128 MiB budget,
   so the bottom sheet found no room for its card snapshot and redrew live
   controls every frame (163 misses), and a pinch found no room for its
   preview. Soy now reserves the sheet backdrop, the sheet card and the pinch
   preview before preparing scene layouts, leaves room for every page's swipe
   snapshot when it decides which layouts to prepare, and has 160 MiB
   (about 200 MB of RAM stays available).
3. **Snap pacing.** Snaps last 0.3 ms per pixel between 48 and 180 ms and land
   once within 1.5 px, so the last pixel of a page snap no longer arrives late.

| Surface | Average fps | p95 | p99 | Worst | Misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reading | 108.3 | 10.6 ms | 11.8 ms | 15.3 ms | 0 / 1121 |
| Pages | 86.8 | 13.0 ms | 14.1 ms | 15.5 ms | 0 / 897 |
| Pinch in | 85.1 | 13.5 ms | 14.4 ms | 22.0 ms | 2 / 886 |
| Pinch out | 96.7 | 12.9 ms | 13.8 ms | 16.1 ms | 0 / 1002 |
| Top sheet | 120.7 | 8.7 ms | 9.9 ms | 33.2 ms | 2 / 1244 |
| Bottom sheet | 104.3 | 11.2 ms | 11.9 ms | 27.5 ms | 2 / 1072 |

**Three surfaces still miss the gate.** The sheet misses are the frame after
the sheet reaches its closed end while the finger stays down (the next three
moves of the finger produce no motion, which looks like LVGL's 10 px drag
threshold applying again) and the frame that removes the closed sheet after
release (a 17 ms full redraw). Pinch misses are the release frame (the release
arrives 8 ms after the last move, then the new layout draws in 12 ms) and
occasional preview frames at 14–15 ms.

## Afternoon of 22 October 2026: sheets pass

Three changes, measured with `check_frames.py --host iphone4-usb` on the lean
kernel with keep, the battery reader and the laptop's log follower running:

1. **Edge-pulled sheets follow from the first pixel.** LVGL's 14 px scroll
   threshold also stayed in its running total, so the first time a sheet came
   back to closed under the finger and the finger turned round, the sheet sat
   still for 14 px (33 ms). During an edge press the threshold is 1 px.
2. **Closing a sheet restores the screen instead of redrawing it.** Soy keeps
   the undimmed screen from when the sheet opened; if nothing under the sheet
   changed, the close deletes the sheet without invalidating, copies those
   pixels back and presents them (about 7 ms instead of a 17 ms full redraw),
   in the same pass as the release that closed it.
3. **No telemetry reads during motion.** One source every 0.2 s cost up to
   7 ms and pushed motion frames past the gate; sources now wait while a
   finger or an animation is moving something.

| Surface | Average fps | p95 | p99 | Worst | Misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reading | 105.5 | 10.7 ms | 11.2 ms | 12.4 ms | 0 / 1095 |
| Pages | 82.6 | 13.5 ms | 14.7 ms | 16.0 ms | 0 / 856 |
| Pinch in | 84.8 | 13.2 ms | 14.0 ms | 21.3 ms | 1 / 874 |
| Pinch out | 96.6 | 12.8 ms | 13.8 ms | 21.4 ms | 1 / 994 |
| Top sheet | 121.0 | 8.6 ms | 9.6 ms | 11.6 ms | 0 / 1245 |
| Bottom sheet | 90.4 | 12.9 ms | 13.4 ms | 14.4 ms | 0 / 928 |

**Pinch still misses one frame, at release.** The release arrives about 9 ms
after the last preview frame and the new text size takes 12 ms to lay out,
draw and transfer, so that frame completes 21 ms after the one before. A
cheaper intermediate frame does not fit either: a preview frame alone takes
8.5 ms. Passing needs the new layout ready before the fingers lift. Pages run
close to the gate (worst 16.0 ms), and earlier runs the same afternoon
missed 1–3 frames at 16.7–19 ms.

## Evening of 22 October 2026: all six surfaces pass

The pinch explanation above was wrong. In the trace the release arrived
while the last preview frame was still drawing; the 9 ms gap came after it:
the pass that read the release only marked the new text size, then the loop
waited in `poll()` (up to 8 ms) before the next pass applied it and drew the
new layout (12.5 ms). The main loop now applies a size the input just chose
right after that pass's refresh, so the new layout follows the last preview
frame at once: the release intervals are 13.2 ms (pinch in) and 12.6 ms
(pinch out), against 21.8 ms before.

Measured with `check_frames.py --host iphone4`: the phone on a USB charger
rather than the laptop, reached over Tailscale through home Wi-Fi, with keep,
the battery reader, the Wi-Fi keeper and the laptop's log follower running.

| Surface | Average fps | p95 | p99 | Worst | Misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reading | 108.7 | 10.5 ms | 11.3 ms | 11.9 ms | 0 / 1127 |
| Pages | 86.0 | 13.0 ms | 14.2 ms | 14.9 ms | 0 / 889 |
| Pinch in | 85.6 | 13.2 ms | 14.0 ms | 15.2 ms | 0 / 893 |
| Pinch out | 89.8 | 13.9 ms | 16.0 ms | 16.5 ms | 0 / 930 |
| Top sheet | 121.1 | 8.5 ms | 9.5 ms | 11.6 ms | 0 / 1245 |
| Bottom sheet | 96.0 | 12.1 ms | 12.9 ms | 14.3 ms | 0 / 986 |

**No surface misses the gate.** The margin is thin: pinch out's worst, 16.5 ms,
is a preview frame in the middle of the gesture, and pages reach 14.9 ms.
These are virtual contacts and completed damage copies; panel scanout and
the glass are not measured.

## Latest phone measurement — still fails

21 October 2026, N90AP, Linux 6.17.0-rc1, ARM binary
`d4ebd5c6b584f78219feaf963a503c29f7e33907f3e41713c8a2b025c0f8fab3`.
Each run uses locally generated virtual contacts on the phone and measures
completed DRM damage copies. Normal telemetry sampling remains enabled.
These measurements do not establish physical touch or LCD scanout.

| Surface | Average fps | p95 interval | Worst interval | Intervals over 16.67 ms |
| --- | ---: | ---: | ---: | ---: |
| Reading | 76.35 | 15.44 ms | 37.74 ms | 32 / 898 |
| Pages | 62.89 | 18.13 ms | 40.09 ms | 142 / 731 |
| Pinch in | 63.72 | 18.30 ms | 41.36 ms | 120 / 690 |
| Pinch out | 72.61 | 17.99 ms | 51.40 ms | 65 / 799 |
| Top sheet | 104.22 | 12.15 ms | 34.90 ms | 24 / 1176 |
| Bottom sheet | 80.65 | 15.15 ms | 37.33 ms | 27 / 909 |

**All six runs fail the release gate.** A higher average does not excuse the
remaining stalls. The largest zoom-out gap contains a 24.28 ms synchronous copy
call and 82 involuntary context switches; that is evidence to investigate
copy/scheduling interaction, not proof that pixel bandwidth alone is the cause.
The kernel accounts CPU time in 10 ms increments, so those trace fields cannot
precisely assign each short stall. Raising the renderer to nice −10 did not
improve the reading run and was reverted.

Phone-local timing marks also expose onset costs. Time from initial contact
submission to the first completed frame carrying new input was 69 / 59 / 89 /
75 / 125 / 134 ms in the order above. These include recognition thresholds
and preparation, and are not event-to-photon latency. Cold sheets still require
too much construction work. Do not present warm frame averages as proof of
immediate touch feedback.

The [machine-readable results](touch-results.json) include source and binary
hashes, behavior checks and limitations. The [raw evidence archive](touch-evidence-2026-10-21.tar.gz)
contains the exact contact streams, untrimmed CSV histories, replay output and
build receipt. Archive SHA-256:
`e34ccff46ca55ab9c30eb4a37df2197384e377f7c2692c6d1de10ee17d566ed1`.
Local experiments are retained under `output/soy/frames-complete-*`.

The full 29-case phone suite passed after the input-wakeup and phased-sampling
changes. The later pinch-only optimization was checked with the affected
pinch/recovery cases, including zoom-out and pinch during inertial reading.
The final runtime edit adds sheet-kind and font-size trace columns; it does
not change gesture behavior. The native sanitizer boundary checks and the fallback renderer's shared-data
checks pass. Their individual artifact hashes and scopes are in the results;
none of them certifies frame pacing or physical touch.

## Original baseline

21 October 2026, real N90AP ARM Linux, virtual kernel multitouch input. These
are completed damage-copy intervals, including the moving sequence and release;
they are not physical finger or panel measurements. Exact contact streams and
raw traces are retained locally under `output/soy/frames-final-*`. Candidate
`prototype-ca7df26afb9c` predates the subsequent optimization experiments.

| Surface | Average fps | p95 interval | Worst interval | Intervals over 16.67 ms |
| --- | ---: | ---: | ---: | ---: |
| Reading | 63.97 | 17.37 ms | 47.97 ms | 154 |
| Pages | 40.48 | 28.82 ms | 47.38 ms | 486 |
| Pinch | 54.42 | 19.40 ms | 692.19 ms | 340 |
| Sheet | 18.90 | 61.52 ms | 88.00 ms | 214 |

Mean rendering-plus-copy times were 12.93 / 21.42 / 14.55 / 47.91 ms;
copy times alone averaged 6.07 / 7.25 / 6.34 / 7.57 ms. The release reflow
stall is real and must remain in the result. An earlier sine-shaped pinch
workload reached the font-size clamp and stopped changing pixels. It was
replaced with continuously changing, bounded coordinates; the pass threshold
was not relaxed.

## Acceptance and next work

**Every moving surface must meet 60 fps on the actual phone.** Every completed
frame interval in the acceptance workload must be at most 16.67 ms, including
cold gesture start and release/reflow. Report p95, p99, the worst interval and
all misses. An average above 60, configured timer frequency, desktop result or
copy-only loop cannot pass. Keep the failure visible until it is resolved.

Run `soy/tools/check_frames.py` for reading, pages, pinch and sheets. The
phone generates contacts locally; SSH round trips do not determine cadence.
The bounded trace includes monotonic refresh/copy timing, contact sequence and
visible scroll/page/panel/scale state, damage bounds, CPU accounting, context
switches and telemetry/status work. Use `pinch-out` and `bottom-sheet` too.
The status field `input_present_max_ms`
starts when userspace reads input; it is diagnostic, not kernel-event-to-photon
latency. Input-onset latency and eventual physical scanout need separate proof.

Viewport/card caches, prepared font layouts, input-ready wakeups and phased
sampling are now implemented. The [Opus 5.5 review](review-2026-10-21.md)
records the findings and changes. Next: explain the remaining copy/scheduling
outliers, prepare cold sheets ahead of contact, update live values without
whole-view rebuilding, and prepare large/live documents incrementally.
Preserve input cancellation, reading anchors and explicit memory bounds.
Reuse the pinned libraries rather than writing another gesture engine.
Any kernel experiment must retain a recoverable boot and independent SSH;
the present userspace work does not require a reboot.

Static screens may sleep. Telemetry must not block motion. Independent SSH
must remain usable. Synthetic contact replay and framebuffer readback cannot
replace eventual finger-on-glass and visible-motion verification.
