# Worker contract

## Soy UI rules

Read `docs/soy/foundations.md` and `docs/soy/design.md` before changing any scene,
renderer or interaction. Start with the person's task and the underlying
principles, not a blacklist or a collection of fashionable screenshots.
The owner's reference for text rendering and responsiveness is
[Ghostty](https://github.com/ghostty-org/ghostty). Read
`docs/soy/performance.md` before changing the display path. Measure the running
phone; a nominal FPS setting or a desktop benchmark is not acceptance.
Expanded touch uses pinned LVGL 9.6.0, selected after the owner explicitly
requested research and reuse. Read `docs/soy/touch-research.md` and build with
`soy/tools/build_touch.py`. Keep libghostty-vt for terminal semantics. These
are complementary libraries, not permission to add another UI framework.
Pixman 0.46.4 supplies cached image composition and the pinch preview scaler. The fixed-panel simpledrm
adapter reports completion of damage copies, not synchronized panel scanout.
These are owner requirements, including for the master maintainer:

- AI draws all of SoyOS and can redraw it fluidly. There are no apps beyond
  Linux tooling; the product is scenes an LLM creates on request. Do not add
  app launchers, app stores or app frameworks. How AI updates scenes on the
  device is still undecided, so don't present a mechanism as final.

- The screen belongs to the content. Never stamp `soy`, a project name, a
  scene counter, debug metadata or decorative branding above every scene.
  A concise scene title or the actual author of a post is useful context.
- No permanent “swipe”, “tap”, keyboard hints, tutorial footers or instructions
  explaining ordinary navigation. Use familiar visible controls and motion.
  Help belongs in context when something actually needs explaining.
- No filler slogans, AI sales copy or cute substitutes for clear labels.
  Say “Battery”, “Network”, “Storage”; spend the remaining pixels on content.
- Design for this 3.5-inch touch screen. Large readable type, dark theme,
  generous hit areas, one main purpose per view. Do not shrink a desktop TUI.
- **60 fps is a release requirement for every moving UI surface.** Measure on
  the actual iPhone, including input processing, rendering and framebuffer
  transfer. During motion, each completed-frame interval must be at most
  16.67 ms in the acceptance workload; report missed frames and the worst
  interval, not just an average. A nominal timer, a copy-only benchmark or
  a desktop result does not pass. Lagging gestures, pinch previews, sheets
  or transitions are blocking defects. Static screens may sleep. Do not
  claim 60 fps or smoothness while measured motion misses this requirement.
- Gestures must manipulate content while the finger moves, support cancellation,
  and preserve reading position. A release-only animation is insufficient.
- Show measured data or an honest empty state. No fake history, connections,
  settings, progress or working touch claims.
- Research means inspecting actual reference screens and recording which
  concrete choices follow from them. A list of repository links is not a design.
- Before delivery, inspect rendered screens at 320 × 480 logical size and
  native 640 × 960. Check hierarchy, wrapping, clipping, controls and empty
  states. Verify device framebuffer output after deployment. Synthetic input
  tests do not establish physical touch support.

Apply these rules to generated scenes as well as the runtime. Do not restore
removed clutter to make a screen look “finished”.

## Worker operation

Read your assigned goal before writing code. Work only in your assigned checkout.
Use .opencode/skills/pstack-iphone/SKILL.md for each goal cycle and its
verify-iphone4 feature map for evidence. These are project-local pstack
adaptations; this contract and the supervisor's limits take precedence.
Use the shell tool for files and commands; it is wrapped by the maintainer's
filesystem sandbox. Do not bypass it or change OpenCode configuration, this
contract, goal definitions, or the acceptance harness. The original acceptance
files are mounted read-only at /acceptance. Local copies are not authoritative.
OpenCode uses its built-in build agent. Extra tools remain approval-gated for
free-route compatibility; the supervisor rejects every extra access request.
Do not request approval or use direct file tools. Use the sandboxed shell.

- Use only DeepSeek-V4.1-Flash-1017 through opencode/deepseek-v4.1-flash-free at max effort. No paid fallback. Never consult
  another model, spawn agents, use paid coding assistants, or install plugins.
- No sudo, host package installs, host services, credentials, other repositories
  or unrelated private network services. Phone access is assigned below.
- The owner has authorized unrestricted development on this iPhone, including
  exploits, bootloader changes, flashing, repartitioning and erasing it. There
  is no data to preserve and no additional permission prompt is needed.
  The kernel lane is the current device operator. Its sandbox exposes the
  pinned phone through /dev/bus/usb, including recovery/DFU re-enumeration.
  One kernel shell owns the device at a time. Other lanes develop in parallel
  and hand artifacts to the operator; they do not race it on USB.
  Identify the target, use source-grounded experiments, keep raw device logs
  under ignored output/hardware, and redact unique device identifiers from
  public notes. Device authorization does not include Platt or other devices.
- Public upstream source downloads are allowed. Record exact URLs, revisions,
  hashes and licenses. Do not redistribute Apple firmware or proprietary blobs.
- At most two compilation jobs. Keep downloads/builds in .cache or output. Do
  not use /tmp for large builds. Do not background daemons/builds outside the
  supervisor's control. Use bounded shell commands and retain logs.
- No fabricated drivers, register addresses, tests, logs or passing results.
  Label each result: source evidence, cross-compile, emulator, or real hardware.
  Emulation cannot prove iPhone USB, SDIO, Wi-Fi, touch, NAND, charging or thermal safety.
  The device operator should now gather real hardware evidence.
- Never weaken a failing test to pass, substitute preprinted success markers,
  remove required features, or mark missing hardware tests complete. If an
  acceptance check appears wrong, document the issue and stop for review.
- Prefer small changes and real boundary tests. Do not churn style, add a UI
  framework, or port an entire desktop. Do not push, publish, message upstream,
  or merge other workers' code. Local commits on codex/* are allowed.
- Every work cycle updates notes/GOAL.md and notes/status.json. Include exact
  commands, exit codes, artifact hashes, evidence paths, unresolved risks and
  the next experiment. Keep a short chronological experiment log.
- After three failures with the same cause, stop that approach, explain the
  evidence and try a materially different bounded approach. If none is credible,
  set blocked. A missing physical device is a real blocker, not an invitation
  to invent results. Stop when the assigned deliverable is ready for review.

notes/status.json schema:

```json
{"status":"working|ready_for_review|blocked","summary":"specific result",
 "evidence":["relative/path"],"next":"next action or missing prerequisite"}
```

ready_for_review means the worker believes the criteria pass. Only the master
reviewer can accept a milestone. Never call the overall phone project complete.
