# Watching the phone

What this computer collects from the running phone, how to watch it live,
and what survives what. The phone runs from RAM and keeps nothing across a
reboot, so whatever matters has to reach the laptop first.

## Live and saved

`harness/phone_follow.py` runs as the user service `iphone4-linux-follow`
(`harness/phone_watch.py install` sets it up). Whenever the phone answers, on
USB (`iphone4-usb`) or over Tailscale (`iphone4`) when it is on Wi-Fi
somewhere else, it

- streams the kernel log as the kernel writes it,
- copies new lines of the service logs every 10 s (30 s over Tailscale, to
  spare the battery), and
- collects Soy's journal ([what the phone remembers](soy/scenes.md#what-the-phone-remembers)).

USB wins when both work; a phone that comes back to USB moves off Tailscale.
While the phone is out of reach the follower tries again every 30 s.

Everything lands in `.runtime/phone/private/logs/YYYY-MM-DD/`, out of Git:

| File | What |
|---|---|
| `kernel.log` | Kernel messages, each with the time and the seconds since boot. The first connection after a boot brings the boot messages too |
| `keep.log` | Services keep restarted, rollbacks, oopses |
| `soy.log` | The renderer's output |
| `battery.log`, `touch.log`, `watchdog.log` | The other services' output |
| `follow.log` | When the laptop started and stopped following, and over which link |

```sh
tail -F .runtime/phone/private/logs/$(date +%F)/*.log   # live
python3 soy/tools/scene.py journal                      # the day in plain words
```

## What survives what

| What happens | What is kept |
|---|---|
| Unplugged, on Wi-Fi | Nothing. The follower moved to Tailscale 11 s after the cable came out (22 October), and moving between home Wi-Fi and the Pixel hotspot did not interrupt it |
| Unplugged, no Wi-Fi | The phone keeps running. Its kernel log (a 128 KiB ring) and the files in `/run` wait on the phone until the laptop reaches it again |
| Kernel oops | keep notes it in the journal. On USB power it restarts the phone 30 s later, once the log has been copied, and the laptop boots it again; on battery a damaged phone that still shows pages beats one waiting in DFU mode, so it keeps running |
| Reboot, watchdog reset or panic | Everything on the phone is lost; what the laptop already collected stays. The phone then waits in DFU mode until the laptop boots it |
| Frozen kernel | The watchdog resets the phone within a minute. Messages from the last seconds are lost |

The device tree reserves 128 KiB at `0x0ffe0000` for ramoops, but the kernel
is built without `CONFIG_PSTORE_RAM`, so a panic's last messages do not survive
yet. Whether that RAM would survive the reset and the DFU boot is untested.
