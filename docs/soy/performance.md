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
