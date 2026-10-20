# iphone4-linux

AI-native Linux for the iPhone 4. Turn an old phone into a tiny Linux box
you can SSH into.

We’re starting with the original GSM N90AP (iPhone3,1). The project is still
being built; there is no phone-tested installer yet.

The intended system has a Linux kernel, file I/O, SSH, basic CLI tools and a
small TUI. Wi-Fi, touch and persistent phone storage are later hardware gates.
QEMU validates ARM userspace; it does not emulate the iPhone's peripherals.

**The main product milestone is [Tailscale + SSH on the phone](goals/remote-access.md).**
This enables remote development for the rest of bring-up. USB-shared Internet
can come first; touch and Wi-Fi do not block the initial tailnet path.

## Current work

**Linux is running on the real phone.** On 20 October 2026, the N90AP booted
Linux 6.17.0-rc1 and joined Tailscale. SSH works over both USB and the phone's
own tailnet connection. Interactive terminals, file read/write and rejection
of a wrong SSH key passed on the hardware. A 30-minute tailnet session also passed.

**[Soy](soy/README.md)** now displays five text scenes on the phone: battery,
network, a Russian Markdown post, storage and a settings preview. Scenes live
in Git and update over SSH. Its [design foundations](docs/soy/foundations.md)
come from inspected TUIs and established interaction guidance.
[Ghostty is our rendering reference](docs/soy/performance.md).
Its [terminal library passes an ARMv7 shell test on this phone](soy/ghostty/README.md);
the visible renderer has not been switched to it yet.
Physical touch and Wi-Fi are still missing, and smoothness remains active work.

It boots into RAM and gets Internet through Platt's USB connection. Reboot
recovery, Wi-Fi, touch and persistent installation are still work ahead.
See the [first-boot evidence](docs/first-phone-attempt.md) and
[access from Platt](docs/platt-usb.md).

Three independent OpenCode workers are assigned [goals](goals/README.md):

1. **qemu**: deployment, recovery and runtime checks for Soy.
2. **kernel**: repeatable RAM boot, private identity restoration and display bring-up.
3. **drivers**: evidence-based Wi-Fi, touch and storage bring-up work.

Workers use **DeepSeek-V4.1-Flash-1017** through
`opencode/deepseek-v4.1-flash-free`, at the highest effort (`max`).
[OpenCode announced the free route's 1017 update on 20 October](https://x.com/opencode/status/2112220734768779441).
The live catalog confirms zero input, output and cache prices and the `max`
variant. It still uses the generic Free name and an older release date, so the
1017 version attribution comes from that announcement. There is no paid fallback.

Each worker has a separate local checkout. Results require review before they
are merged or published. A worker's completion note is a claim, not a hardware
test. See [worker rules](AGENTS.md), [milestones](goals/README.md), and
[source evidence](docs/sources.md).

[The review workflow](docs/agent-workflow.md) adds GitHub goal issues and at most
ten event-triggered senior reviews per Auckland day, at least two hours apart.
DeepSeek continues the implementation.

[pstack is installed locally](docs/pstack/README.md) with `/poteto-mode` and
`/verify-iphone4`. `/goals` uses its bounded investigation/build workflow and
feature verification map automatically.

[Critical alerts go through Soyclaw](docs/alerts.md). Routine work stays quiet;
failures and specific decisions reach the owner's private Telegram chat.

## Minimal acceptance harness

`python3 harness/verify.py doctor --images PATH` checks prerequisites.
`python3 harness/verify.py qemu --images PATH` runs the smoke test below against
snapshotted images and retains a unique receipt with image hashes and logs.

`python3 harness/qemu_smoke.py --images PATH` boots real ARM artifacts in QEMU,
injects a fresh SSH public key into a disposable rootfs copy, checks authenticated
SSH and file I/O, rejects another key, and checks persistence after a reboot.
It fails when artifacts or required behavior are missing. It does not build an
image or claim iPhone hardware support.

Requires Python 3, qemu-system-arm, OpenSSH client and e2fsprogs on Linux.
The worker supplies `zImage`, `vexpress-v2p-ca9.dtb`, and `rootfs.ext4`.
There are no prebuilt images in this initial scaffold.

`harness/probe_initramfs.py` separately tests the unchanged phone initramfs
with a QEMU vexpress reference kernel:

```sh
python3 harness/probe_initramfs.py --initramfs PATH --kernel PATH --dtb PATH \
  --key PATH --out NEW_DIRECTORY
```

The key must match one already authorized in the archive. This catches
failures in `/init`, BusyBox init, Dropbear, PTY allocation and file I/O that
an overlay-on-ext4 test can miss. It also rejects a wrong SSH key. The
reference kernel, virtual RNG and virtual network cannot validate the
phone's kernel, TUN module or peripherals.

## Long-running work

The local supervisor can run around the clock, with separate visible OpenCode
sessions, periodic checkpoints, backoff on errors, and an explicit stop on
completion, an unchanged blocker, or a resource limit. The assigned device
operator can boot and flash this phone with the owner's authorization. Workers
cannot push Git, change host credentials, or call other models. Local state and logs are
ignored by Git. `/goals NAME` is a project command; this OpenCode version has no
native persistent goals API. The supervisor supplies the continuation loop.

Free workers have no time-of-day restriction or calendar expiry. The supervisor
checks the exact route, `max` support and zero prices before dispatching work;
an independent watchdog checks every minute and stops active workers if those
checks fail or a session changes model. Soyclaw reports that condition. This
checks OpenCode's advertised prices; it cannot independently audit provider billing.
Provider quota errors keep assignments queued and retry after 30 minutes,
backing off to two hours. They do not trigger paid fallback or demand babysitting.
The existing goal, retry, resource and 96-cycle limits still apply. Completed
work waits for review instead of generating busywork. Laptop sleep, shutdown
or loss of connectivity pauses local work.

Start: `python3 harness/control.py start`

Status: `python3 harness/control.py status`

Stop: `python3 harness/control.py stop`

The launcher requires the local setup generated by the maintainer. Worker
checkouts and supervisor state are outside the public checkout. The source
contains no account credentials, phone firmware, or personal backups.
