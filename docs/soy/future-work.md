# Future touch and boot animation

Owner request, 20 October 2026. **Planned, not active.** Current workers continue
screens, recovery and hardware bring-up. These projects need a later explicit
activation; finishing today's work does not activate them.

## Touch that feels like a phone

First establish real multi-contact input on the physical device, including
contact IDs, coordinates, timestamps, release and interrupted-event recovery.
A synthetic FIFO gesture is useful for regression checks, not hardware proof.
Continue today's basic touch-driver work without treating it as this expanded
interaction project.

Then design the interaction map before implementing:

- Taps, double taps and long presses where each has a useful, visible purpose.
- Direct horizontal page dragging and vertical reading, velocity-aware release,
  inertial scrolling and interruptible settling.
- Elastic resistance and a clean return at the first/last scene and document
  boundaries. A boundary must feel intentional rather than frozen.
- Pinch handling with a defined result, such as readable document zoom around
  the fingers' focal point. Set useful limits, preserve place and avoid
  accidental scene changes during a pinch.
- Swipes from the top and bottom, with distinct documented destinations.
  Choose those destinations during the future design phase; do not invent
  panels or settings now. Provide cancellation and resolve conflicts with
  page scrolling and the bottom page control.
- Gesture arbitration: axis locking, finger-count changes, interrupted contact
  streams, palm/noise rejection where supported, and animation interruption.
- Comfortable targets, discoverability, a reduced-motion path and an equivalent
  way to reach essential actions without an obscure gesture.

Deliver an interaction specification and state transitions, then replayable
event-stream checks, then real finger demonstrations on the phone. Measure
response latency and sustained frame cadence during gestures. A modern phone
feel is the target; a list of recognized gestures is not completion.

## Growing soybean plant at boot

The visible boot experience is one full-screen ASCII soybean plant growing
against the dark background. No shell, kernel messages, login prompt, logo
text, slogan, progress percentage or permanent instructions on the LCD.
This specifically requested boot artwork is separate from ordinary scene
chrome. Keep diagnostic logs and remote recovery available privately.

### Research before drawing or coding

The first future deliverable is a research folder committed to the repository:

1. Study animation craft: staging and silhouette, timing and spacing, anticipation,
   arcs, follow-through, overlap, holds and restraint. Explain which principles
   actually improve slow organic growth on this tiny display.
2. Find and watch exceptional terminal/ASCII animations and strong plant-growth
   animation references. Compare real sequences, not repository popularity or
   a list of links. Record source URLs, authors, dates and reuse terms.
3. Produce legally shareable annotated frame studies or original diagrams:
   what changes between frames, where attention moves, why a hold works, how
   character density conveys shape without flicker.
4. Translate that research into a concrete art direction, storyboard, timing
   sheet and evaluation criteria for this phone. Commit the research and
   design packet before beginning production animation.

Do not claim the research has happened yet. Reference work is inspiration;
do not redistribute someone else's animation without appropriate rights.

### Craft and runtime

Make the final sequence frame by frame: individually reviewable text frames,
an editable timing track and contact sheets in Git. A generic spinner, random
character reveal or unreviewed procedural growth is not the requested artwork.
The seed, emerging shoot, unfolding leaves and final silhouette should form
one coherent composition. Test actual ASCII glyphs at the phone's scale.

Keep playback lightweight and deterministic. Precompute assets; do not render
with an AI model on the device. Compare frame pacing and perceived flicker on
the real LCD. Do not introduce a fake progress meter or delay a ready phone
solely to finish a long performance. Design a graceful readiness transition
and a quiet hold if boot takes longer than the main sequence.

Recovery comes first: missing/corrupt frames, a killed animation process and
an early/late boot-ready signal must not block SSH or strand startup. Keep
diagnostics accessible even while the LCD remains free of terminal output.
Change the boot display path only after the existing recovery plan is proven.

Completion requires the research packet, crafted frame assets and timing,
actual-phone playback evidence, failure/recovery checks and human visual
review. Compilation, a desktop GIF or a high nominal FPS is insufficient.
