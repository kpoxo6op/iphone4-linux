# Touch: reuse decision and implementation plan

Research before implementation, 20 October 2026. The owner activated expanded
phone gestures, and then explicitly asked us to look for existing software
before writing a gesture engine. The plant boot animation remains deferred.

## Decision

Use pinned LVGL 9.6.0 for the embedded UI input, scrolling, animation and
widget lifecycle. The ARMv7 build and virtual-contact behavior checks pass, but the measured
frame cadence still fails the 60 fps release gate.
Keep libghostty-vt for terminal semantics: it serves a different layer.
Use the existing text-first visual design, not a toolkit's stock demo styling.

| Candidate | Evidence | Fit here |
| --- | --- | --- |
| [LVGL](https://github.com/lvgl/lvgl/releases/tag/v9.6.0) | Embedded C library with software rendering; scrolling already supports momentum, elasticity and snapping. Multitouch recognizers include pinch, rotation and two-finger swipe. | Best fit for the framebuffer phone and existing C/musl toolchain. Prove performance and input behavior before switching the UI. |
| [libinput](https://wayland.freedesktop.org/libinput/doc/latest/gestures.html) | Its documentation explicitly leaves touchscreen gesture interpretation to callers; its gesture API principally concerns indirect devices such as touchpads. | Could normalize device input, but would not replace the gesture work the owner wants reused. |
| [Slint](https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backends_and_renderers/) | Offers software rendering and Linux KMS integration, including ARMv7 guidance. | Credible alternative, but introduces a new language/build/runtime boundary. LVGL more directly covers this C application and the required interactions. |
| [libghostty-vt](../../soy/ghostty/README.md) | Already tested on this phone; handles terminal state rather than a touch scene UI. | Retain it for PTY scenes. Do not mistake its terminal core for a scrolling widget or display driver. |

Primary references:

- [LVGL multitouch recognition](https://lvgl.io/docs/open/9.5/main-modules/indev/gestures)
- [LVGL scroll physics and snapping](https://lvgl.io/docs/open/9.1/overview/scroll)
- [Official Linux port](https://github.com/lvgl/lv_port_linux)
- [Linux Type B contact protocol](https://cdn.kernel.org/doc/html/latest/input/multi-touch-protocol.html)
- [Linux event synchronization and dropped events](https://cdn.kernel.org/doc/html/latest/input/event-codes.html)
- [Linux uinput simulation](https://cdn.kernel.org/doc/html/latest/input/uinput.html)

The versioned source, not an assumption about an older tutorial, determines
which APIs and driver behaviors we use. Pin LVGL to commit
`80ca777e37a2b176770726a02e07a6fb79ef0b39` (v9.6.0, MIT).

## What must remain ours

The meaning of an edge gesture, the presentation of a scene, telemetry and
Markdown are product decisions. So are the phone's framebuffer adapter and
any missing contact transport adaptation. Reuse the library's physics and
recognizers; keep added code focused on those boundaries.

- Horizontal drag changes scenes with native snapping and edge resistance.
- Vertical drag reads; momentum stops when touched again.
- Pinch adjusts document text size around the reading position, within usable
  limits. A second contact must not accidentally activate a page or button.
- Top edge reveals a compact read-only device-status sheet.
- Bottom edge reveals a scene picker with large tap targets.
- Panels can be dismissed by reversing their gesture or tapping outside.
- Double tap and long press get context-specific actions, not global surprises.
- No permanent gesture instructions, branding, fake settings or invented data.

## Evidence boundary

The live N90 kernel exposes no physical touchscreen, SPI or I2C device.
The matching uinput module loaded without reboot, creating `/dev/uinput`.
A virtual multitouch touchscreen can exercise the actual Linux evdev path,
the recognizer, widgets and framebuffer on the ARM phone. Its name and status
must say virtual. Passing that test cannot certify the physical digitizer.

Physical touch still needs board-specific transport, reset/interrupt wiring,
firmware/calibration provenance and a driver. Existing source work found no
N90 implementation to enable with a simple switch. Do not copy older iPhone
or ARM64 Touch Bar register values into this board.

Acceptance uses replayable contact streams, observed pixels/state, interruption
and dropped-event recovery, memory and frame timings, plus eventual finger
input on the real display. Research and this decision do not count as those
checks passing.

## Implementation evidence

The prototype reuses LVGL's snapping, momentum, elastic scroll, hit testing,
multitouch recognition and object lifecycle. Linux Type B/single-touch input
translation, fixed-panel DRM damage submission and scene policy are local.
No physical digitizer driver is fabricated.

Pixman 0.46.4 (MIT) supplies its existing ARM NEON paths for flat fills, owned
cached images and nearest-neighbour pinch preview. LVGL retains ordering and
clipping; unsupported tasks fall back to LVGL. The extension is tied to the
pinned LVGL private draw-task structures. Transparent cached glyphs are
premultiplied once; opaque modal backdrops let LVGL avoid repainting the
covered document. The backdrop is dimmed once when the panel opens; an opaque
card snapshot moves during the gesture, with native live controls restored at
rest. A scrolled inner list invalidates its snapshot so stale content cannot
replace the live list. These decisions follow measured failures, not a claim that
choosing a library guarantees speed.

A 128 MiB pixel-cache cap includes snapshots and prepared text layouts.
Small immutable documents prebuild their five sizes before the first frame;
a released pinch switches the layout and preserves its paragraph anchor.
Large/live documents retain the bounded synchronous fallback and still need
incremental preparation. See [performance.md](performance.md) for exact
hardware results, failed experiments and remaining work. Boot artwork remains
unimplemented.

The [Opus 5.5 review](review-2026-10-21.md) records the owner's requested
maximum-effort consultation and the disposition of its findings. Evdev
readiness wakes LVGL's existing timers; periodic reads still support held
contacts and long presses. Telemetry sources retain their one-second cadence
but are sampled in separate phases so one frame does not perform all reads.
