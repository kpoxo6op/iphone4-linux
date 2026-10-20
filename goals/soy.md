# Soy: scenes on the real iPhone

Owner: master for design/runtime; DeepSeek kernel and drivers lanes for hardware;
DeepSeek qemu lane for deployment, crash recovery and repeatable checks.

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
