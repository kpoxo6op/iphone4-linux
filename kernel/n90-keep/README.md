# keep: the phone restarts its own services

`keep.sh` runs on the phone as `/usr/sbin/n90-keep`. `harness/phone_boot.py`
installs it last on every boot and adds `::respawn:/usr/sbin/n90-keep` to
`/etc/inittab`, so Busybox init restarts keep itself if it stops. It needs no
laptop: away from USB the phone still looks after itself.

Every 2 s keep checks five processes. One that has been gone for 6 s is started
the same way the boot starts it:

| Service | Process | Started as |
|---|---|---|
| Soy | `soy` | `/opt/soy/current/soy … --scene <last scene>` (from `status.json`), pid in `/run/soy/renderer.pid` |
| Touch | `n90-touch` | `n90-touch serve n90-z2.bin` in `/opt/n90-touch` |
| Battery | `n90-battery` | `n90-battery serve` |
| Watchdog kicker | `n90-wdt` | `n90-wdt 60 10`, well inside the 60 s hardware timeout |
| Wi-Fi keeper | `n90-wifi-keep` | `/usr/sbin/n90-wifi-keep` ([kernel/n90-wifi](../n90-wifi/README.md)) |

When Soy needs a third restart within two minutes, keep makes
`/opt/soy/previous` current again before starting it, so a release that keeps
crashing cannot strand the phone. It rolls back once; the next sync or deploy
brings the library's scenes back.

## Oopses

keep takes over from the kernel's `panic_on_oops`, which it sets to 0. A
panic reboots at once and loses the oops message, while the laptop's
follower ([watching the phone](../../docs/watching-the-phone.md)) copies the
kernel log over the network as it is written. When the kernel taints itself
with `TAINT_DIE`, keep notes the oops in Soy's journal and, 30 s later,
restarts the phone with sysrq `b` if it is on USB power, where the laptop
boots it again. On battery a damaged phone that still shows pages is more use
than one waiting in DFU mode, so it keeps running. `/run/keep/hold-oops`
pauses the restart, for driver experiments.

## Holds

Tools that stop a service on purpose write an expiry time (epoch seconds) to
`/run/keep/hold-NAME` first: `soy/tools/deploy.py` holds `soy`,
`kernel/n90-touch/deploy.py` holds `touch`. To stop a service for longer,
write a later expiry the same way. keep logs to `/run/keep/keep.log`.

## On the phone, 22 October 2026

Each process killed with `kill -9` under the lean kernel:

| Killed | Back after | Check |
|---|---|---|
| `n90-battery` | 6 s | files under `/run/power_supply` update again |
| `soy` | 8 s | same scene; the display capture is pixel-identical to the one before |
| `n90-touch` | 6 s | Soy sees the physical touch device again after 7 s |
| `n90-wdt` | 6 s | phone still up 70 s later, past the 60 s watchdog |
| `soy`, three times in a minute | 9–11 s each | third restart switched to the previous release |
