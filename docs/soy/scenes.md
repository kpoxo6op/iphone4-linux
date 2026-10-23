# Writing scenes

How to put something on the phone. This is for AI and for people. Read the
[design foundations](foundations.md) and the [design guide](design.md) before
designing a new kind of scene; this page covers the format and the tool.

```sh
python3 soy/tools/scene.py put groceries.md --show
```

That checks the scene, saves it in the scene library, and publishes it to the
phone while the renderer keeps running. Whatever the person was reading stays
where it was. `--show` brings the new scene to the front.

## A scene

A scene is one Markdown file with a short frontmatter block. The library's
`index` file lists scene IDs in swipe order, at most 32.

```markdown
---
id: groceries
label: Groceries
accent: sage
---
# Saturday

- Oat milk
- Rye bread
- **Coffee**, the dark one
```

| Key | Required | Meaning |
| --- | --- | --- |
| `id` | yes | `A-Z a-z 0-9 - _`, at most 40 characters. It is also the file name. |
| `label` | no | Shown small at the top of the scene, at most 63 bytes. Write what it is. |
| `accent` | no | `sage` (availability, the default), `cyan` (reading, links), `amber` (energy) or `muted`. |
| `hero` | no | `true` turns the first `#` heading into a 96 px value, such as `82%`. ASCII only. |
| `source` | no | Where the content came from. Not displayed. |

Any other key is rejected. For a plain Markdown file without frontmatter,
`put` writes it: the ID comes from the file name or `--id`, the label from
`--label`, the colour from `--accent`.

## Markdown that renders

The renderer reads one line at a time and never joins lines, so **write each
paragraph on a single line**. Lines wrap at word boundaries on screen.

| Write | Get |
| --- | --- |
| `# Heading` | 48 px heading (19 characters a line) |
| `## Heading`, `###` … | a bold body-size line with a little space above |
| plain text | 36 px body text, about 26 characters a line |
| blank line | 20 px of space |
| `**bold**` | bold |
| `*emphasis*` | grey text (there is no italic) |
| `` `code` `` | accent-coloured text |
| `[label](url)` | the label in the accent colour; links do not open yet |
| `- item` or `* item` | a bullet |
| `> quote` | grey text beside an accent rule |
| a line of three backticks | starts or ends a code block |
| `{{graph.battery}}` or `{{graph.network}}` alone on a line | an observed history graph |
| `\*`, `\[`, `` \` `` | the literal character |

Tables, images, HTML, `_underscores_`, `~~strike~~` and numbered-list layout
are not supported; they show as typed. `1. First` still reads fine as text.
A single `*` or `[` changes the colour of the rest of its line: escape it.

The type is DejaVu Sans Mono with Latin, Latin-1, Cyrillic, dashes, quotes,
`•`, `…`, `←↑→↓↔`, `€`, `−` and box drawing. Anything else, including emoji
and `✓`, shows as `?`. People pinch to change the text size; the layout
follows.

## Live values

`{{key}}` inserts a device reading that refreshes every second:

| Key | Value |
| --- | --- |
| `battery.percent` | `82%`; `~82%` when estimated from voltage (on battery only); `—` without a reading |
| `battery.state` | `Charging`, `On battery`, `On USB power`, `Full`… or `Battery unavailable` |
| `battery.voltage` | `3.92 V`, or `—` |
| `net.link` | the interface carrying the default route, `USB` for the cable |
| `net.wifi` | `Connected`, `Not connected` or `Unavailable` |
| `net.rx`, `net.tx` | receive and send rates, such as `12 KiB/s` |
| `net.firewall` | `On`, `Off` or `Not installed` ([firewall](../../kernel/n90-net/README.md#firewall)) |
| `net.blocked` | packets addressed to the phone that the firewall dropped since it loaded, or `—` |
| `memory.used`, `memory.available` | RAM |
| `storage.kind`, `storage.usage` | root filesystem kind and use |

An unknown key shows `[unavailable]`. Scenes cannot run commands or fetch
anything; new readings are added to the renderer when a request needs them.

Each scene is limited to 128 KiB and 2,048 lines. Long content scrolls.

## Commands

| Command | What it does |
| --- | --- |
| `put FILE [--show] [--at N] [-m WHY]` | Add a scene, or replace the one with the same ID in place. `-` reads standard input. |
| `remove ID` | Take a scene off the phone. |
| `show ID` | Bring a scene to the front now and after every reboot. |
| `list` | Library history, what the phone shows (`>`), and the scene that opens after a reboot (`*`). |
| `undo` | Return to the scenes before the last change. Run it again to redo. |
| `publish [-m WHY]` | Check, save and publish edits made directly in the library, such as a new order in `index`. |
| `preview ID-or-FILE --out x.png` | Render at 640 × 960 on this computer. Live values come from this computer. |
| `capture --out x.png` | Save what the phone is displaying. |
| `sync` | Make the phone match the library. The boot uses it. |

`-m` records why, for example the request that led to the change. Exit codes:
0 the phone shows it, 1 rejected or failed, 3 saved but the phone was out of
reach.

## Where scenes live

The library is a private Git repository at `.runtime/phone/private/scenes`,
outside the public repository. Run `scene.py` from the checkout that boots the
phone, which holds that directory and the SSH configuration; elsewhere it
refuses rather than start a second library. It starts as a copy of the default scenes in
`soy/scenes`. `git -C .runtime/phone/private/scenes log` is the history of
everything shown on the phone.

Every change is checked by the native renderer first, so a rejected scene
never leaves this computer, and the message names the scene, line or key at
fault. On the phone, the new release shares the running binary and fonts, its
hashes and scenes are checked again, then it is switched in atomically and the
renderer reloads. The previous release stays as `/opt/soy/previous`. The tool
tries USB first, then Tailscale.

When the phone is out of reach, the change is still saved (exit code 3). The
phone watcher on the laptop notices when the phone is back on USB and syncs it
within about 30 seconds; any later `put`, `publish` or `sync` also brings it
over, and every boot installs the library's last saved scenes. If those fail on the phone, the boot falls back to
the default scenes so the screen is never empty.

## Where you were

Each scene's reading position and text size survive restarts and reboots.
Soy keeps `/run/soy/positions` (one `id scroll zoom` line a scene) at most
2 s behind, the laptop's follower copies it to
`.runtime/phone/private/soy-positions`, and the boot pass puts it back before
Soy starts. The phone still opens on the scene `show` chose; going back to
any other scene finds it where it was left.

## What the phone remembers

Soy keeps a journal of what it showed, so whoever draws the next scene can
see how the last ones were used. It is a JSON line per event in
`/run/soy/journal.jsonl` on the phone: the renderer starting, each settled
scene change with how far the scene being left was read, sleep and wake with
the reason (idle, power, home, touch, remote), text size changes, scene
reloads, a battery sample every five minutes, keep's restarts and kernel
oopses.

The laptop's follower ([watching the phone](../watching-the-phone.md)) copies
new lines to `.runtime/phone/private/journal/` on this computer, one file per
day: every 10 s over USB, every 30 s over Tailscale when the phone is on Wi-Fi
elsewhere. The phone keeps its journal in RAM, so a field test out of reach
comes back with it as long as the phone did not reboot.

```sh
python3 soy/tools/scene.py journal                 # today, in plain words
python3 soy/tools/scene.py journal --day 2026-10-22
python3 soy/tools/scene.py journal pull            # copy now
```

The summary gives screen-on time per scene and how far each was read, the
battery at the start and end of the day, how the screen woke and slept,
anything keep restarted, and any kernel oops. The journal stays on this
computer and out of Git.

## Before calling a scene done

Look at it: `preview` before publishing, `capture` after. Check the
hierarchy, wrapping and the last line at 640 × 960 and at half size, as the
design rules require. Don't repeat the label as the first heading. Show real
values or say what is missing.

## Checks

`python3 soy/tools/check_scene_tool.py --out output/scene-tool-check` runs the
tool and `deploy.py` against a simulated phone: busybox ash in a private
namespace with a headless renderer. It covers the boot install, hot publishing,
kept reading position, rejected scenes, remove, undo, show, capture, offline
saves and the Tailscale fallback. It makes no hardware claims.
