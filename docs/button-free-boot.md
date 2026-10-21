# Boot without buttons — 21 October 2026

A reboot of the phone now returns to Linux, owner SSH and the phone's own
Tailscale node with nobody touching it. `harness/phone_boot.py` drives the
whole chain from Platt; the phone watcher starts it when needed.

## Why every reset now lands in DFU

GPT's DFU-IPSW restore (`harness/phone_dfu_restore.py`, Legacy iOS Kit
revision `23622f8f`) ended at 13:52 NZDT with the intended LLB write error.
Since then the phone has no bootable LLB, so the boot ROM enters DFU on every
reset. That replaces the Home/Power button sequence. It is still a
host-assisted RAM boot: nothing on the phone survives power loss on its own,
and Platt must be connected to load Linux.

## The chain

| Stage | Observed USB | What runs | Deadline |
|---|---|---|---|
| iOS normal (if ever seen) | `05ac:129x` | `ideviceenterrecovery` | 180 s |
| Recovery | `05ac:1281` | the reviewed DFU-IPSW restore | 20 min + 120 s |
| DFU | `05ac:1227` | `loadibec-fixed` (limera1n, iBSS, openiBoot) | 240 s, then 420 s for openiBoot |
| openiBoot | `0525:1280` | `oibc` uploads the four knownboot files and `go 0x0c100000` | 3 attempts × 600 s |
| Linux | `0525:a4a1` | identity restore, then Soy deploy | 180 s per check |

The loader and `oibc` run in a bubblewrap sandbox whose `/dev/bus/usb`
contains only the pinned phone's node. Every kit file is checked against the
knownboot hashes (`phone/recovery/knownboot-manifest.json`, plus `oibc`
`5083a208…` and the local-only iBSS and payload) before any upload.

## Identity after a fresh RAM boot

Each RAM boot starts with a new Dropbear host key, an empty
`tailscaled.state` and the clock at 1970. That is why SSH and Tailscale
failed after the 14:00 boot. The boot pass now:

1. Waits for the `iphone4` interface, which udev only creates for the gadget
   on socket `3-4`, and for port 22 on `10.84.4.2`.
2. Tries the saved strict `known_hosts`. If it already matches, nothing is
   changed.
3. Otherwise connects once with a throwaway `known_hosts` over that
   point-to-point link, checks `/proc/device-tree/model` is
   `Apple iPhone 4`, sets the host's time, installs the saved
   `tailscaled.state` and Dropbear host key, and restarts both services.
4. Verifies strict SSH over USB, then strict SSH over the tailnet to the same
   boot ID.

No re-enrollment, no change to the saved `known_hosts`, no global trust
change. Private state stays in ignored `.runtime/phone/private/`.

## Hardware results

| Run (UTC) | Start | Linux USB | SSH + Tailscale | Result |
|---|---|---|---|---|
| 09:14 | reboot → DFU | — | — | Failed: the loader needs iBSS in its working directory; without it, it sent openiBoot straight to DFU. Fixed. |
| 09:29 | DFU | 09:34:56 | 09:35:23 | Passed |
| 09:37 | reboot → DFU | 09:43:12 | 09:43:58 | USB, Tailscale and the restored key worked; the pass reported failure because it checked 5 s after the Dropbear restart. Now retried for 60 s. |
| 09:44 | reboot → DFU | 09:49:48 | 09:50:25 | Passed in one unattended pass, Soy redeployed at 09:50:39. Reboot to ready: 6 min 21 s. |

Each reboot was `reboot` over SSH. The phone re-enumerated in DFU within
seconds every time. Raw stage logs are private under
`.runtime/phone/private/boot-runs/`.

## Kernel choice

The pass boots the [backlight kernel](../kernel/n90-display-power/README.md)
first (`497fa0e4…`, DTB `9567afd1…` with `panic=10`, both hash-checked from
`.runtime/phone/private/backlight-20261021/`). If a pass with it fails, the
next pass boots plain knownboot, and keeps doing so until
`phone_boot.py reset-failures`. A panic reboots into DFU, where the watcher
starts that fallback pass. A kernel that hangs without panicking still needs
a physical reset. `phone_boot.py status` shows `kernel` and
`backlight_failures`.

At 10:21 UTC a `reboot` came back by itself on the backlight kernel: Linux USB
at 10:27:31, strict USB and tailnet SSH at 10:27:59, and Soy deployed at
10:28:14. At 10:29:15 Soy reported `blanked` and `backlight: off`, and PMU
register `0x68` read `0x00`. The fallback itself has not been exercised; doing
so would need a deliberately failing kernel.

## Morning check

1. Leave the phone untouched for a minute. The screen should go fully dark,
   not just black with the light on.
2. Press Home or Power. The reader should come back lit, at the same place.
3. Press Power while it is lit. It should go dark at once.

If the screen stays lit while `cat /run/soy/status.json` says
`backlight: off`, the PMU write is not reaching the panel. Report that in
issue #4.

## Display

Soy, with the 60-second idle blanking (`0131047`), is reinstalled at the end of
every pass. On the 09:35 boot it reported `display_state: blanked` 60 s after
start, and a capture of the active KMS buffer was 640 × 960 with every pixel
black. The backlight stays on: the running kernel has no backlight driver.
The drivers lane's `n90-display-power` patch series (PMU backlight over
`i2c-gpio`, polled buttons) is compile-tested only and is the next step.

## Operating it

```sh
python3 harness/phone_boot.py run             # one bounded pass
python3 harness/phone_boot.py status          # last result
python3 harness/phone_boot.py reset-failures  # after three failed passes
```

The watcher (`iphone4-linux-phone.timer`, every 30 s) starts
`iphone4-linux-boot.service` when the phone is in normal, recovery, DFU or
openiBoot mode, or in Linux with SSH failing. Three consecutive failed passes
stop automatic starts until `reset-failures`.

## Still open

- A frozen kernel or a hang before USB still needs a physical reset.
- Power loss was not tested. It should behave like a reboot (power-on goes to
  DFU), but only while the phone is on the cable and Platt is running.
- Persistent install on NAND was not attempted.
