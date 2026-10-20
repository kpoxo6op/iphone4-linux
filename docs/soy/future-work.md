# Touch and future boot animation

The owner activated expanded touch on the evening of 20 October 2026.
The implementation and reuse decision are in [touch-research.md](touch-research.md).
Physical digitizer acceptance remains separate from virtual-input testing.

## Growing soybean plant at boot

**Planned, not active.** The touch activation does not activate this artwork.

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
