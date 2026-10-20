# Design foundations for Soy

Research and decisions, 20 October 2026. Read this before designing new scenes.
The [design guide](design.md) translates these foundations into the current
runtime. The rules apply to AI-generated scenes just as they do to hand-written
ones.

The owner subsequently selected **[Ghostty](https://github.com/ghostty-org/ghostty)**
as the standard to build toward for rendering and responsiveness. Its pinned
source findings and our measured next steps are in [performance.md](performance.md).

## What we studied, and why

There is no objectively best TUI. We selected working interfaces with different
strengths: Glow for sustained reading, btop for live measurements, Superfile
for focus and grouping, and Television for immediate search and contextual
detail. Their actual reference screens were inspected; image URLs and hashes
are recorded in [references.json](references.json). This is visual analysis,
not a claim that we ran usability studies on those applications.

The [Ratatui showcase](https://ratatui.rs/showcase/apps/) provided a broader
survey. Its range reinforces an important distinction: a terminal is a medium,
not a single layout. A monitoring dashboard, reader and file picker need
different arrangements.

Our interaction foundations come from [Nielsen's usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/),
[Shneiderman's eight golden rules](https://www.cs.umd.edu/~ben/goldenrules.html),
Apple's [discoverability](https://developer.apple.com/videos/play/wwdc2021/10126/),
[typography](https://developer.apple.com/design/human-interface-guidelines/typography),
[accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
and [motion](https://developer.apple.com/design/human-interface-guidelines/motion)
guidance. These explain behavior and legibility, beyond a screenshot's style.

## Start with the person's purpose

Nielsen's guidance asks interfaces to expose relevant state, use familiar
concepts, minimize memory demands and support recovery. Our interpretation:
each scene should answer a question or support an activity. “How much battery
is left?”, “Is the network carrying traffic?”, “Let me read this post.”

Write that purpose before choosing components. Give the answer visual priority.
An unrelated title, decorative number, startup log or brand competes with it.
A control must describe a real action. An empty state must explain what is
missing. The person should not need to understand Linux to read the screen.

**Review:** look at the scene for a few seconds. Can you name its purpose,
find the most important information and distinguish an action from a label?
This is a review prompt, not a measured universal “three-second rule”.

## Establish hierarchy before adding colour

[Glow's example](https://github.com/charmbracelet/glow/blob/main/example.png)
uses spacing, heading treatment and emphasis to make prose scannable.
[Superfile's demo](https://github.com/yorukot/superfile/blob/main/website/src/assets/demo.png)
separates selected, supporting and surrounding content. Both have structure
before decoration.

In Soy, the main value or article heading gets the strongest emphasis. Related
labels and values stay close; unrelated groups get more space. Align text to a
shared left edge. Use a border only when it clarifies a boundary. Keep secondary
text quieter without making it hard to read. Colour reinforces meaning; it
does not create the only distinction.

**Review:** inspect the screen in grayscale and at 320 × 480. If everything
competes equally, change grouping, size or weight before adding another colour.

## Typography is the interface

Apple recommends readable sizes, restrained typeface choices and a clear
relative hierarchy. Soy uses one licensed monospace family with Cyrillic
coverage, regular body weight, larger headings and visibly stronger emphasis.
Its character comes from the typography and simple graphics, not fake terminal
noise.

Our current scale is 36 physical pixels for body text, 48 for headings and 96
for a short primary value: approximately 18, 24 and 48 logical points at 2×.
24-pixel text is reserved for brief secondary graph annotations. These are
project choices, not numbers prescribed by a TUI library.

Wrap prose at word boundaries. Do not reduce font size to fit a long post.
Keep paragraphs separated, preserve punctuation and accents, and preserve the
author's wording. Test long Russian words, mixed Latin/Cyrillic, links, emphasis
and code. A bottom edge may reveal partial continuing content while scrolling;
it must never hide the final line at maximum scroll.

**Review:** actually read a paragraph at the intended size. Check the start,
middle and end of the document, not only the attractive title.

## Design for a hand, not a terminal keyboard

Apple's accessibility guidance recommends 44 × 44-point default controls on
iOS. Soy adopts at least 88 × 88 physical pixels for touch targets on this
screen. The visible mark may be small; its hit region cannot be. Keep adjacent
actions far enough apart to avoid ambiguous taps.

Use established gestures with consistent spatial meaning. Horizontal movement
changes scenes; vertical movement reads within a scene. Lock the axis after
intent becomes clear. The same action must work through a visible control:
the bottom page control supplies previous/next navigation.

No permanent tutorial is needed for familiar actions. Unfamiliar actions may
need a concise label or contextual explanation. Removing labels indiscriminately
would violate discoverability just as much as printing instructions everywhere.

**Review:** verify hit regions, diagonal drags, short canceled drags and the
first/last page. Physical comfort remains unverified until the phone emits
real touch events.

## Preserve place and control

Shneiderman emphasizes consistent behavior, informative feedback, reversibility
and user control. Applied here: content follows the finger, an incomplete drag
can return, an animation can be interrupted, and returning to a post preserves
reading position. A changing measurement must not move nearby controls.

An AI update must not unexpectedly switch the scene being read. Preserve the
current scene by ID when it still exists. A bad bundle keeps the last working
content. If the active scene is deliberately removed, choose a predictable
remaining scene. These are UX properties as well as deployment properties.

**Review:** start reading, navigate away, return, update another scene, then
reload an invalid bundle. The person's place and usable content should survive.

## Motion explains change

Apple's motion guidance favors meaningful, brief, interruptible feedback.
Page movement should match the finger's direction. The page control remains
stationary so the person retains a point of reference. Data updates should not
replay entrance animations. A still document should remain still.

The short settle duration is a tuning choice. **60 fps is an owner requirement,
not a nominal timer setting.** Measure complete frame intervals on the A4:
each must stay within 16.67 ms during the acceptance workload. Report every
missed budget and the worst stall, including text reflow and panel opening.
The [response-time research summarized by Nielsen](https://www.nngroup.com/articles/response-times-3-important-limits/)
explains why delayed feedback disrupts the sense of control; it does not prove
that this renderer meets a particular latency.

**Review:** measure complete update cadence, including rendering and transfer,
not just a memory-copy benchmark. Report worst delays as well as averages.
Do not call movement smooth or tear-free based on a timer setting.

## Make live information interpretable

[btop](https://github.com/aristocratos/btop#screenshots) pairs current values,
units and history. Soy borrows that relationship while avoiding its dense
desktop arrangement.

A graph needs a known quantity, scale and time window. A fresh process has only
the history it actually collected; do not stretch a few samples into an
invented hour. Zero traffic differs from unavailable telemetry. An interface
existing differs from an Internet connection working. Distinguish RAM use from
filesystem use, and distinguish a RAM filesystem from phone flash.

**Review:** test missing, zero, stale and changing readings. A screenshot full
of plausible numbers proves nothing about the data path.

## Reveal detail when it becomes relevant

[Television](https://github.com/alexpasmantier/television) combines a live result
list with selection context and an on-demand channel chooser. The useful
principle is progressive disclosure, not its particular panes or ASCII remote.

For Soy, the initial screen shows the useful answer. A longer explanation,
history or article continues below when needed. Future controls should appear
where their effects make sense. Do not add a universal toolbar, nested settings
tree or miniature desktop merely because a framework can render it.

**Review:** every persistent element should have a frequent, relevant purpose.
Less frequent detail should remain findable, not disappear behind an unexplained
gesture.

## Be quiet and honest

[Dieter Rams's principles at Vitsœ](https://www.vitsoe.com/us/about/good-design)
connect usefulness, restraint, understandable structure and honesty. Our
interpretation is that the device should leave room for its owner's content
and avoid exaggerating its abilities.

The [Command Line Interface Guidelines](https://clig.dev/#saying-just-enough)
describe the same balance in terminal output: both silence and excessive
information can obscure what matters. We carry that lesson into the display.
Routine operation stays quiet; a relevant fault is legible and specific.
Credentials, register names and diagnostic dumps belong in private operator
tools, not scenes.

Settings that cannot change are visibly read-only. Missing Wi-Fi, battery or
touch support remains an engineering limitation, not an opportunity for a
convincing mock value.

## Contrast is measurable; taste is not a passing test

We use [WCAG's contrast calculation](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
as a legibility reference, targeting at least 4.5:1 for all text. This does not
make this custom Linux surface WCAG-conformant or accessible to a screen reader.

Against `#090e0c`, the current solid colours measure: primary `#e4ebe4` 16.02:1,
secondary `#84958b` 6.16:1, sage 13.44:1, cyan 12.01:1 and amber 11.81:1.
`#26382d` is only 1.56:1: use it for nonessential separators, never essential
text or the sole indicator of a control.

These calculations do not account for the aged panel, viewing angle or sunlight.
Human inspection on the actual device is still necessary.

## What counts as a finished design change

Record the screen's purpose and the principle behind each material change.
Render all affected scenes, including their missing-data states, and inspect
native and logical-size images. Exercise navigation, cancellation, reading
position and reload through the real runtime. After deployment read back the
device framebuffer and check it. Keep evidence separate from claims about
physical touch.

The LVGL prototype now exercises adjustable type and inertial scrolling through
virtual input on the phone. Physical touch, consistent 60 fps and reduced-motion
settings remain quality gaps. Reading these principles does not satisfy them.
Future AI work must close observed gaps rather than merely add more rules.
