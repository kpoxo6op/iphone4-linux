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

## Measurements and hypotheses

The framebuffer is 640 × 960, XRGB8888, with a 2560-byte stride. One full frame
is 2,457,600 bytes. At 60 complete frames per second, one copy alone moves
roughly 147 MB/s before layout, blending, extra copies or scanout.

The first renderer's mmap presentation reached 221 ms for a cold full update.
A pwrite experiment then showed a 501 ms presentation p95 across an interactive
scene run. Both fail the intended experience. A fast best-case copy benchmark
did not predict actual interaction.

The pinned kernel's `drivers/gpu/drm/drm_fbdev_shmem.c` sets deferred framebuffer
updates to `HZ / 20`, about 50 ms. Its mmap path also uses deferred I/O.
This is direct source evidence of a scheduling constraint, not proof that it
explains every observed delay. The real renderer now reports scan, transfer
and retained-frame copy time separately to locate the additional cost.

A paced, identical-pixel diagnostic measured about 46–53 ms average for mmap
methods and 12 ms for pwrite. Those are transfer diagnostics, not end-to-end
FPS or physical display measurements. In particular, unchanged pixels are an
easier workload than scrolling text.

Instrumentation found a second, avoidable bottleneck: one actual frame spent
151.844 ms comparing rows, 1.766 ms transferring pixels and 8.515 ms retaining
a copy. On the native pwrite path we removed the full-frame comparison and
retained copy. Presentation already runs only when content changes.

After that change, ten reader/storage transitions produced 99 submitted
frames: presentation mean 12.659 ms, p95 20.411 ms and maximum 64.094 ms,
including the cold first frame. The final transfer took 6.792 ms. This is a
useful improvement, but it still misses the 16.7 ms p95 target and excludes
layout, composition, input latency and physical scanout. It is not a 60 FPS
claim. Local receipts: `output/soy/deploy-no-scan.json` and
`output/soy/presentation-no-scan.json`.

## Work order

1. **Locate the delay.** Time layout, composition, dirty detection, transfer and
   retained-frame copies independently. Measure process CPU and wall time.
   Keep the same scene, input sequence and compiler flags for comparisons.
2. **Fix presentation.** Evaluate the current pwrite/mmap paths and a bounded
   DRM dumb-buffer/damage experiment. Preserve the previous renderer and
   independent SSH. Do not reflash merely to explore a userspace path.
3. **Keep work out of the gesture loop.** Cache document layout and reusable
   rendered content. Collapse input bursts to the latest position rather than
   rendering a backlog. Render data changes only where needed.
4. **Pace complete frames.** Keep a stable deadline during motion; don't turn
   a slow frame into additional queued delay. Distinguish submitted frames,
   finished copies and actual visible scanout.
5. **Finish interaction.** Add measured inertial scrolling and a reduced-motion
   option after presentation is fast enough. Preserve axis lock, cancellation
   and each scene's reading position.

## Acceptance

The goal is 60 Hz when useful and supported. Initially require a sustained
software frame interval p95 at or below 16.7 ms for a controlled ten-second
drag/scroll workload, record p99 and the longest stall, and measure input-to-
completed-frame latency. These are project targets, not claims about current
performance. If the display path has a lower proven limit, document it and the
next experiment rather than relabeling a slow run as smooth.

Static reading must sleep without needless full-frame updates. Network
telemetry may refresh once per second without stalling navigation. SSH must
remain usable throughout. Finally inspect actual finger interaction and
visible display motion: synthetic input and framebuffer reads cannot prove
physical responsiveness, vsync or absence of tearing.
