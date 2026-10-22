# Idle display

21 October 2026. The owner deferred further gesture performance tuning and
asked for the display to turn off when unused. The runtime now defaults to
60 seconds of inactivity. **Phone deployment is pending: neither USB nor
Tailscale could reach the phone during this change.**

## Behavior

- A still page blanks after 60 seconds. Live data and AI scene updates do not
  keep it lit. A held contact or ongoing scrolling postpones the timeout.
- Wake restores the same scene, reading position and type size. A waking touch
  sequence is consumed until all contacts lift, including a second finger.
  The next touch works normally. Physical touch remains a separate driver gate.
- `wake` or navigation through the private control FIFO wakes it remotely.
  `sleep` blanks immediately, cancels unfinished motion and closes an open sheet.
- While blanked, LVGL stops refreshing. The loop waits up to 100 ms for status
  and sampling; readable input and FIFO commands interrupt that wait immediately.
  Telemetry continues, scene updates remain possible, and SSH stays independent.
- Nothing is added to the visible interface. This is not a lock screen or an
  authentication feature. The system does not suspend or reboot.

## Backlight

**21 October 2026, evening:** with the [N90 display-power kernel](../../kernel/n90-display-power/README.md),
Soy switches the PMU backlight off when it blanks and back on when it wakes. It
also wakes on the Home or Power button, and Power puts it to sleep. The PMU
register readback confirms each switch; no one has yet looked at the panel.
On the knownboot kernel, which has no backlight device, status reports
`backlight: unavailable` and the behaviour below still applies.

### Earlier analysis (knownboot kernel)

The pinned phone kernel's N90 device tree declares only a `simple-framebuffer`
for display output. It declares no backlight or physical key input device.
`drivers/gpu/drm/sysfb/drm_sysfb_modeset.c` implements plane disable by clearing
the framebuffer to black; this is not a panel power sequence. Calling DPMS
or framebuffer blank successfully would therefore not prove the light is off.

Source inspected: kernel revision `8e79d535d2068ae9b9475d2e6850a6edd67fad5b`,
`arch/arm/boot/dts/samsung/s5l8930-apple-n90.dts`, `s5l8930.dtsi`, and the
sysfb modeset implementation. No speculative register writes were attempted.

The [Linux backlight interface](https://docs.kernel.org/gpu/backlight.html)
distinguishes requested brightness from hardware brightness. A future driver
must expose and verify that control. Until then, status says `blanked` and
`backlight_power_control: false`; battery savings and physical shutoff are
unverified. Do not describe a black framebuffer as powered-off hardware.

The application reuses LVGL's inactivity clock, refresh timer, object layers
and evdev input path. It does not introduce a second UI loop or framework.
The [LVGL input documentation](https://docs.lvgl.io/9.3/details/main-modules/indev.html)
and the pinned 9.6.0 input/display implementation informed wake suppression.

## Idle power

With the screen blanked the phone should do almost nothing. On 22 October,
over a minute each with the screen blanked and the phone on USB:

| | Busy CPU | Timer interrupts | Biggest users (CPU jiffies a minute) |
|---|---|---|---|
| Before | 5.5 % (13.6 % in minutes with a tailscaled rebind) | 258 a second | Soy 74, n90-touch 66, keep 41 |
| After | 4.2 % | 111 a second | keep 41, n90-touch 16, Soy 8 |

What changed:

- Soy wrote `/run/soy/status.json` ten times a second even while blanked. It
  now writes it every 2 s then, and sleeps up to a second between wakeups;
  touches, buttons, the control FIFO and signals still wake it at once.
- Soy keeps `/run/soy/blanked` while blanked. n90-touch then reads the
  controller's ATN line every 50 ms instead of every 8 ms; a touch only has to
  wake the screen.
- The phone's DHCP client no longer rewrites routes on unchanged renewals,
  which made tailscaled rebuild its connections every minute
  ([kernel/n90-net](../../kernel/n90-net/README.md)).
- Wi-Fi waits for the chip's interrupt instead of polling it 100 times a
  second ([kernel/n90-wifi](../../kernel/n90-wifi/README.md)).

The panel itself stays powered (only the backlight goes off), and the A4 runs
at a fixed clock with no frequency scaling. Battery life on battery has not
been measured yet; the journal's five-minute battery samples will give it.

## Verification

`soy/tools/check_idle.py` exercises the real native process and rendered pixels
with sanitizers: live-data inactivity, diagnostics while asleep, reload while
asleep, exact pixel and reading-position recovery, navigation wake, disabled
timeout, invalid timeout retention and shutdown while blanked. The existing
scene-boundary check covers bundle failures, process ownership and recovery.

`soy/tools/check_touch.py --only idle` adds kernel evdev contracts: consume the
waking touch, remain awake while held, accept the next touch, stop refreshing
a live scene while asleep, and wake through SSH. `--scope qemu` explicitly
labels emulator evidence. It cannot establish physical digitizer behavior.

Results and binary hashes are in [idle-results.json](idle-results.json).
Native wake pixels were inspected at 640 × 960 and 320 × 480. No phone pixels,
panel power measurements or physical wake checks exist for this change yet.

## Device handoff

1. Once the phone is reachable, verify the current release and independent SSH.
2. Deploy the built ARM renderer with `soy/tools/deploy.py`, retaining rollback.
3. Run the idle touch check, independently capture the active KMS buffer before
   blanking, while black and after remote wake; verify the same reading position.
4. Keep backlight shutoff open until a source-grounded driver and a real
   brightness/power observation prove it. Establish a physical wake control
   without rebooting or losing USB/Tailscale access.
