# Soy

A small, living text surface. Tell AI what you want to see; it builds a scene,
puts it in Git, and sends it to the phone. The phone keeps displaying it without
an AI connection. Scenes can stay, change, or disappear whenever you ask.

The [design foundations](foundations.md) explain the researched principles,
their application and the checks required for new work. This document records
the current product choices.

## AI draws SoyOS

The owner set this on 21 October 2026. AI draws the whole design, and AI can
change it fluidly at any time. That covers the scenes, the layout and the visual
language. SoyOS has no apps beyond ordinary Linux tooling. Its main product is
scenes that an LLM creates for the person who asks for them. People say what
they want to see and experience. They do not install, configure or maintain
anything.

How this will work technically is still open. The first working path, built
on 22 October 2026, is the scene library: AI writes a Markdown scene, and
`soy/tools/scene.py` checks it, saves it in a private Git library and
publishes it into the running renderer without a restart. The phone comes back
with the last published scenes after every reboot. [Writing scenes](scenes.md)
has the format and the commands. It is a first step, not a decided
architecture. Record new mechanisms here once they are actually built, and
don't present an unbuilt one as settled.

## The feel

Dark, quiet, legible. Warm white text, a little phosphor green, generous space.
A large number or a few lines of writing should own the screen. The iPhone's
640 × 960 display is the canvas, not a desktop squeezed into a phone.

- One scene at a time. No dashboard of microscopic panels.
- Body text starts at 36 physical pixels; headings at 48. Primary numbers can
  use 96. Cyrillic gets the same care as Latin. Never shrink text to fit more.
- Near-black background only. Colour has a job: green for availability, amber
  for energy, cyan for reading and links. Use words as well as colour.
- Monospace type, thin rules and simple text graphs supply the retro character.
  No fake scanlines, flickering text, ornamental terminal output or loading theatre.
- Fresh data stays fresh. Missing data appears as unavailable, never as a
  plausible invented number. History begins when observations begin.
- Touch is a requirement. Keyboard and SSH controls also use the same actions.

## Movement

Swipe left/right to move between scenes. Drag up/down to read within a scene.
Horizontal movement changes place; vertical movement changes reading position.
Lock to the dominant axis after a small threshold so a diagonal drag does not
accidentally turn a page. Content follows horizontal movement before release;
a short drag returns to the original page. The bottom page control has roomy
previous/next hit regions. Its dots indicate position; they are not tiny
individual buttons. No arrows, scene counters or navigation instructions
surround it.

Reading position belongs to each scene. Returning to a post should not lose
your place. The first version has no settings that pretend to work.

**60 fps is required throughout movement.** Any completed-frame interval over
16.67 ms in the phone acceptance workload is a blocking defect. Report
missed frames and the worst gap; an average above 60 does not pass.
Use a short, interruptible slide, around 180 ms, with an ease-out
curve. Touch feedback must begin on the next rendered frame. Static scenes
sleep between input and data changes; there is no reason to redraw 60 identical
frames a second. Report measured frame times on the phone before calling it
smooth. A software framebuffer copy is not proof of tear-free scanout.

Panels use an opaque surface over a fixed dimmed backdrop. Keep the content
quiet while the panel follows the finger; repeated full-screen blending adds
no necessary information. During movement, reuse prepared text and panel
images. Restore live controls at rest, including their pressed feedback.

## First five scenes

1. **Battery.** Large percentage, charge state, actual observation history.
   Until the battery driver exists, show an honest empty state.
2. **Network.** Wi-Fi state, active link, live receive/send rates and a small
   traffic history. Credentials never enter a scene or Git.
3. **Reader.** A Russian Borex Telegram post with rendered Markdown, links,
   emphasis and comfortable wrapping. Scroll the content, not the header.
4. **Files.** Root filesystem use and RAM use. Distinguish RAM rootfs from
   phone flash; do not label the whole memory pool as disk space.
5. **Settings.** Read-only specimen: dark appearance, large type, gestures and
   scene updates. No working toggles in this version.

## Scenes belong to you

A bundle is an ordered `index` plus UTF-8 Markdown files. Frontmatter supplies
an ID, label, accent and optional large-number treatment. Markdown supplies the
content. Read-only bindings insert device facts; graph bindings draw histories.
New scenes do not need new navigation code. New capabilities can be implemented
by AI in the runtime when a request actually needs them.

Git is the source of truth on the development host. The device receives a
small versioned release over SSH through Tailscale. It doesn't need Git, a
compiler, a browser, or an on-device model. Update by staging and checking a
bundle, then switching it atomically. Retain the prior working release.
Reload scene content without terminating SSH or Tailscale. A broken scene or
crashed renderer must not strand the phone. Markdown is content, never shell
code. Private Wi-Fi and node identities live outside scene bundles.

## References, and what we take from them

The actual Glow example, btop main screenshot and Superfile demo were inspected
on 20 October 2026, alongside Apple's touch guidance. These are the resulting
decisions, not dependencies or screens to copy wholesale:

| Reference | Observation | Decision in Soy |
| --- | --- | --- |
| [Glow example](https://github.com/charmbracelet/glow/blob/main/example.png) | Paragraph space, headings and emphasis make a long document readable without putting each block in a box. | Give the Russian post most of the display. Keep headings distinct, body text large and margins consistent. |
| [btop screenshots](https://github.com/aristocratos/btop#screenshots) | Values carry units, and histories sit next to current readings. Its desktop layout is far too dense for this phone. | Pair download/upload values with their units and a time-labelled graph. One subject per scene; no miniature dashboard. |
| [Superfile demo](https://github.com/yorukot/superfile/blob/main/website/src/assets/demo.png) | Colour and border contrast distinguish focus; muted supporting text stays subordinate. | Use a restrained palette and readable secondary labels. Do not transplant its panes, command footer or many simultaneous colours. |
| [Apple: discoverable design](https://developer.apple.com/videos/play/wwdc2021/10126/) | Familiar controls and consistent motion communicate navigation; hiding everything is not the same as simplifying it. | Keep a visible page control and direct manipulation. Remove the tutorial footer rather than hiding all navigation. |
| [Apple: page controls](https://developer.apple.com/design/human-interface-guidelines/page-controls) | Bottom-centred indicators suit an ordered set of peer pages; too many become hard to read. | Five neutral indicators, a clear current mark, generous previous/next hit areas. Show a window of indicators for longer scene lists. |
| [Apple: motion](https://developer.apple.com/design/human-interface-guidelines/motion) | Motion should follow the gesture, be brief and allow interruption. | Finger-following page movement, cancelable short drags and a brief settle. No idle ornament animation. |

## Permanent UI rules

The same rules are in `AGENTS.md` so they apply before an agent edits the UI.

1. **Content owns the screen.** No repeated `soy` wordmark, project title,
   counter, build number or debug strip. A scene title or post author provides
   context; branding does not.
2. **Do not narrate ordinary controls.** No permanent “swipe / tap” footer,
   keyboard help or tutorial prose. Use familiar controls, spatial continuity
   and feedback. Explain an unusual action only where it occurs.
3. **Write what the thing is.** No slogans such as “Room to think” or “Connected
   things”. Use plain labels, real values and concise empty states.
4. **Minimal does not mean invisible.** Keep the page control. Large targets
   surround its small marks; don't require precision tapping or memorised
   secret gestures.
5. **No pretend functionality.** Missing hardware produces an unavailable
   state. Settings remain explicitly read-only. Colour never substitutes for
   the text that explains a state.
6. **Review the rendered result.** Inspect native pixels and a 320 × 480
   rendition representing the physical screen's layout. Read the Russian,
   inspect every initial scene and empty state, and test navigation and scroll
   retention. After deployment compare an actual framebuffer capture.

The first prototype broke these rules with excessive chrome, slogans and a
gesture instruction footer. Those are rejected patterns, not defaults for
future generated scenes.

## Hardware truth, 20 October 2026

The current phone has a working 640 × 960, 32-bit simpledrm framebuffer and
Tailscale SSH. No Linux input device, wireless interface or battery power-supply
node was present at the initial Soy probe. Evdev gesture handling can be built
and tested now, but physical touch is accepted only after actual finger events.
The workers own the missing driver and recovery experiments. Saved Wi-Fi
profiles do not mean the radio is connected. RAM-boot identity restoration and
persistent storage remain separate work.
