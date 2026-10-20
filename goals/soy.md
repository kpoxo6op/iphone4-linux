# Soy: scenes on the real iPhone

Owner: DeepSeek workers implement screens and recovery; the master owns the
LVGL touch integration and reviews bounded handoffs. Existing recovery, remote-access and hardware goals remain
active. The owner requested this delegation on 20 October 2026.

## Current assignments

All lanes read this whole goal, then work only on their assignment below.
Start from the published Soy source in `/seed/handoff/soy-master-source.tar.gz`.
Record its commit and archive hash. Keep an isolated working copy and deliver
small patches against that baseline under the owned paths below; do not edit
the master checkout, governance or another lane's files.

**drivers — battery first, then network.** Work in `research/soy-screens/`;
hardware patches remain in `patches/experimental/`. Continue the existing
Wi-Fi, touch-device and battery-driver investigation alongside screen work.

- Battery: make remaining charge immediately legible, with charge state and
  a useful usage/history graph. Read actual power-supply telemetry when
  available. Missing capacity, an unplugged source, invalid values and a fresh
  history must each remain honest. Never infer capacity from uptime or invent
  a discharge curve. No estimated time remaining without defensible evidence.
- Network: show the actual active link, Wi-Fi association state, receive/send
  rates with units and a time-labelled history. Handle no interface, no route,
  counter reset and link changes. Do not claim Internet access from an
  interface merely existing. No SSID/password or account details in screenshots.
- A missing phone driver does not block implementing and rendering the screen.
  Use clearly labelled offline fixtures for missing/zero/charging/discharging
  or disconnected/idle/busy cases. Deliver the real telemetry adapter too;
  fixture results cannot establish hardware support.
- Handoff: scene files, narrowly scoped telemetry patches, native and logical
  size captures, executable boundary checks, and the exact missing hardware
  evidence. Keep driver bring-up notes separate from UI fixture results.

**qemu — recovery plus reader, storage and settings.** Work in `soy-runtime/`.
Keep the existing supervisor, update rollback and crash-recovery work. Alternate
bounded recovery and screen deliverables so neither disappears behind a rewrite.

- Reader first: preserve the third scene and the Russian author's wording.
  Make headings, emphasis, paragraphs, quotes, links and code readable at the
  existing large type scale. Verify long words, mixed scripts, beginning/middle/
  end, retained reading position and valid/invalid reload. The last line must
  be reachable. Keep link behavior honest; no decorative button that does nothing.
- Storage next: distinguish RAM rootfs, memory and actual mounted flash.
  Use consistent units; handle absent, zero, full and changing measurements.
- Settings stays a quiet, explicitly read-only specimen. No new preferences,
  pretend toggles, branding or instructional footer.
- Use the pinned libghostty-vt for any PTY-backed scene. Its successful phone
  probe is the starting point. Prove child-process cleanup and bounded
  scrollback. Do not replace the readable Markdown scene until the replacement
  passes its visual and behavioral checks; no homemade ANSI parser.
- Handoff each screen separately, plus recovery evidence. A killed UI, invalid
  bundle and repeated deployment must leave independent SSH usable. Document
  what requires the kernel operator rather than claiming an unrun phone test.

**kernel — recovery and display performance.** Work in `phone/soy-display/`
and the existing phone paths. Keep repeatable RAM boot and private identity
restoration ahead of optional presentation experiments. Remain the sole USB
operator; other lanes send artifacts rather than racing the device.

- Measure complete frame cadence, longest stalls and input-to-completed-frame
  latency for the existing scene/scroll workload. Preserve the previous working
  display and SSH path. Start with the documented direct-simpledrm baseline, then make
  one source-grounded improvement at a time. No kernel reflash for an experiment
  that can run in userspace.
- Report cold and warm results, memory and idle CPU. **60 fps is mandatory**:
  every completed-frame interval must be at most 16.67 ms in the acceptance
  workloads, including the first moving frame and release/reflow. A passing
  average does not compensate for stalls. Static screens may sleep.
  Distinguish framebuffer writes
  from verified physical scanout. Do not certify smoothness from a copy loop.
- Prioritize the missing physical touchscreen transport. The master has adopted
  pinned LVGL 9.6.0 for expanded gestures; reuse it. Its real-phone uinput tests
  prove the software path, not the N90 digitizer. Deliver source-grounded board
  transport, firmware/reset/interrupt evidence and contact events to the master.
  Do not replace the gesture engine or reflash the live phone during the master
  display session. Boot artwork remains deferred.

**Immediate performance defects:** the master's LVGL prototype does not meet
the 60 fps gate. Use `soy/tools/check_frames.py` and its bounded `frames.csv`
trace for reading, pages, pinch and sheets; preserve the strict failure result.
Kernel lane owns display-copy and scheduling investigation. Qemu lane owns
incremental layout preparation for documents outside the new bounded font cache,
further page/sheet composition work, and recovery. Small static documents now
prebuild font variants; preserve their anchor and ownership checks. Keep the
128 MiB pixel-cache cap. Add bounded release retention that keeps the running
release, verified rollback and original fallback: repeated test deployments
filled the RAM filesystem, and staging correctly failed before switching. Work in the existing assigned
paths and submit small patches for the master to test on the phone. Reuse LVGL,
Pixman and the current adapters. Do not add a framework, lower the threshold,
hide slow frames, render fake updates at zoom limits, or label the prototype
accepted. See `docs/soy/performance.md` for the measured baseline and priorities.

Use the [Opus review](../docs/soy/review-2026-10-21.md) to avoid repeating fixed
experiments. Extend coverage to zoom-out, bottom sheets, cold gesture onset,
release, live scenes and a pinch interrupting reading. Do not count a 10 ms
quantized CPU sample as precise per-frame attribution. The matching kernel
enables high-resolution timers but lacks fine virtual CPU accounting and
scheduler statistics; its S5L clocksource also has an unresolved sched-clock
TODO. Investigate that from source and measurements before proposing a new
kernel. A nice −10 experiment did not solve the misses and was reverted.
Do not starve SSH with a real-time busy loop.

Qemu's next UI handoff should prepare sheets before contact without freezing
live values, update live bindings without rebuilding the entire view, and
preserve the existing 128 MiB cache limit. Kernel's next handoff should explain
the remaining copy/scheduling outliers with a bounded trace and a proposed
experiment that preserves the current RAM boot. Physical touchscreen transport
remains its hardware priority. Keep recovery work active in both lanes.

## Delivery and scope

For every screen: state its purpose, explain the relevant existing design
principles, inspect captures at 640 × 960 and 320 × 480, and supply a small
reproducible process-boundary test for a credible failure. No test counts,
source-text assertions or visual approval invented by the worker. Record
commands, exit status, artifact hashes, limitations and next action in
`notes/GOAL.md` and `notes/status.json`. Submit one bounded result for review
before starting a wholesale redesign. Do not repeat passing work without a
changed input or concrete failure.

The owner activated expanded touch after the original delegation. Read
[touch-research.md](../docs/soy/touch-research.md) and use the refreshed handoff
baseline. Screen and recovery patches now target `soy/src/touch.c` (LVGL) and
shared `soy/src/scene_data.h`; `soy/src/soy.c` is the retained fallback. Do not
ship a parallel gesture recognizer or restore the old runtime over the new one.
[Boot art](../docs/soy/future-work.md) remains **planning only**: do not research
or implement it now. No paid fallback or new worker model route is authorized.

## Shared product acceptance

Deliver the first five scenes in this exact order: battery, network, Russian
Markdown reader, files, settings. Follow docs/soy/design.md. Touch navigation,
large Cyrillic text, dark-only presentation and useful frame pacing are part
of the product. Settings are explicitly a stub. Wi-Fi credentials stay private.
Read docs/soy/foundations.md for the researched design principles. The owner
selected Ghostty as the rendering and responsiveness reference; follow the
measured work order in docs/soy/performance.md. Prefer reusing libghostty-vt
for terminal semantics. The ARMv7 feasibility check now passes on the actual
phone; see soy/ghostty/README.md and its pinned build/probe. Do not build
another ad-hoc ANSI terminal parser. A PTY scene must use the library's state,
bound scrollback and clean up its child process. Preserve the existing reader
until the replacement is visually and behaviorally verified.

Acceptance distinguishes:

1. Source: scene schema, design tokens and provenance in Git; no passwords or
   account identity. New Markdown scene can be added/reordered/removed without
   changing renderer source.
2. Host: render all five scenes; long Russian lines wrap without clipping;
   malformed bundle keeps previous content; gesture navigation and scrolling
   share the same action path as remote control. Crash/rollback tests preserve
   an independent SSH path.
3. Phone: deploy ARM binary over Tailscale, read back framebuffer and inspect it;
   prove scene change and Markdown scroll through runtime status and pixels;
   measure RSS, idle CPU and frame timing. A host screenshot is not this proof.
4. Touch: real finger events move scenes and scroll the reader. No synthetic
   event or remote command can satisfy physical-touch acceptance.
5. Wi-Fi: home and Pixel profiles saved privately; association, DHCP, DNS and
   phone Tailscale SSH actually work over a wireless interface. Saving a config
   without a radio is preparation only. Preserve USB access during experiments.
6. Recovery: interrupted update/bad bundle/crashed UI retains a usable prior
   release and SSH. A repeated RAM boot restores private identities separately.

Keep the running phone while doing source/build work. The kernel lane remains
sole USB operator. Coordinate destructive experiments with the master while
live deployment tests are active; owner authorization already covers this phone.
Stop a repeated failed hypothesis after three attempts and state the concrete
missing evidence. No fabricated battery values, touch events, Wi-Fi associations,
frame-rate claims or completion notes. Notify the owner only for a real decision
or critical fault through the existing master alert path.
