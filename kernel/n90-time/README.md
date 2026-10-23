# Time on the phone

The phone had no NTP client and no kernel RTC. The laptop's boot pass set the
clock with `date -s` in whole seconds, so it started up to a second wrong,
then drifted at whatever rate the crystal happened to run, with nothing to
correct it. Before the boot pass reached it, the clock read 1970.

`n90-time` keeps it right:

- **Network time.** Whenever a server answers, it asks `nz.pool.ntp.org`
  (then `time.cloudflare.com`, `pool.ntp.org`) with SNTP (RFC 4330), keeps
  the answer with the shortest round trip, and steps the clock (or slews
  it, under 50 ms). Every 15 minutes; every minute, backing off, while
  nothing answers. Outgoing UDP 123 and its replies pass the firewall.
- **Drift.** Over each stretch of an hour or more it adds up the corrections
  it made and folds them into the kernel's clock frequency (`adjtimex`), so
  the clock keeps time between syncs and offline. The follower keeps the
  learned value on the laptop (`.runtime/phone/private/time-freq-ppm`) and the
  boot pass applies it again at the next boot.
- **The PMU's clock.** After each sync it stores the PMU counter's offset
  again (`n90-battery clock save`), so the clock that runs while the phone
  is off stays aligned, and logs how far it had wandered. At start, a clock
  that is still unset (before 2026) is set from the PMU, which is what a boot
  without the laptop will need.

State for Soy and the laptop is in `/run/time`: `source` (`ntp`, `pmu` or
`laptop`), `synced`, `offset_ms`, `freq_ppm`, `server`, `pmu_offset_s`, and
`time.log`. Soy shows `{{time.clock}}`, `{{time.date}}` and `{{time.sync}}`
([live values](../../docs/soy/scenes.md#live-values)). keep starts
`n90-time serve` and restarts it if it stops.

```sh
make -C kernel/n90-time            # output/time/n90-time, static, musl
n90-time sync                      # on the phone: once, now
n90-time freq 12.5                 # apply a correction in ppm
```

It is built against musl, as Soy is, so that the static binary's resolver
works: a static glibc binary would need NSS modules the phone does not have.

## On the phone, 24 October 2026

The first sync, 14 minutes after the boot pass had set the clock, found it
413.7 ms behind `nz.pool.ntp.org` and took 80 ms. That is the boot pass's
whole-second `date -s`, not drift. A slew of that size would have taken the
kernel more than 13 minutes, so offsets over 50 ms are now stepped. After
the correction the PMU-based clock read one second behind network time, its
one-second resolution.

After the next reboot (20:48 UTC) the boot pass installed it and keep started
it; its first sync, a second later, found the clock 1117 ms behind and
corrected it. The boot pass still sets whole seconds; this is why.
