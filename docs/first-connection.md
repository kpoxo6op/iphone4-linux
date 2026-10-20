# Connecting the phone

The phone is connected. On 20 October 2026, a real USB query confirmed an
iPhone 4 GSM, iPhone3,1 / N90AP, A4 CPID 0x8930, BDID 0x00, in recovery mode.
The same query passed inside the kernel worker's sandbox.

Platt checks for the phone every 30 seconds while awake. It reads USB mode and,
in normal iOS mode, requests only the product type, board model, iOS version
and build. It uses `ideviceinfo -s` to avoid automatic pairing. The watcher
does not run recovery commands, send payloads or change the phone's storage.

The sanitized result goes to the workers automatically. A new observation
wakes workers waiting for review and steers those already running. Existing
review holds, cost checks and resource limits remain in force. A different or
unidentified model cannot qualify the N90 image for use.

USB identification establishes the connection and model only.
The loader, RAM boot and USB network path still
need review and actual hardware evidence before SSH or Tailscale can work.
The owner authorized unrestricted worker development on this phone, including
flashing and erasing. No further device-work permission prompt is required.
The kernel worker now executes the experiments; the other lanes support it.

## Device access

The kernel lane sees `/dev/bus/usb` backed by a directory containing only the
phone. A root-owned udev helper updates its device node across USB resets.
Apple recovery/DFU must match the pinned ECID and physical USB socket.
The openiBoot and Linux gadget IDs are also allowed on that same socket.
Normal iOS access is not exposed by this helper yet; the host watcher can still
identify it. Keep the phone on the same USB socket while experiments run.

The helper is `harness/usb_device_nodes.py`, installed root-owned at
`/usr/local/libexec/iphone4-usb-nodes`. Its private root-owned device policy is
`/etc/iphone4-linux-device.json`, and the scoped udev rule is
`/etc/udev/rules.d/70-iphone4-worker.rules`. It creates only USB character
device nodes under `/dev/iphone4-worker-usb`; it never executes worker code.
The sandbox selects the single `device_owner` in private runtime settings and
serializes that lane's shell commands. Platt's files and other USB devices
remain outside the worker's writable filesystem.

Raw hardware output belongs under ignored `output/hardware`. Unique device
identifiers must be redacted from public completion notes. The maintainer has
shared the checksummed userspace bundle and phone kernel config under
`/seed/handoff` so the lanes can integrate their work.

## Local operation

Installed Debian packages: `libimobiledevice-utils`, `irecovery`, and their
dependencies; `usbmuxd` was already installed and starts through its udev rule.
The watcher deliberately does not invoke `irecovery`.

```sh
python3 harness/phone_watch.py status
systemctl --user status iphone4-linux-phone.timer
```

`python3 harness/phone_watch.py install` installs the user timer.
The project's ordinary `control.py stop` stops it too.

The latest snapshot is `.runtime/phone/observation.json`, copied into each
worker's protected `.opencode/phone-observation.json`. Only selected facts are
stored; no UDID, serial, ECID, device name or pairing record is written. Both
destinations stay outside public Git. Snapshots carry the observation time;
disconnection replaces the current state rather than leaving an old phone
reported as connected.

Soyclaw stays quiet for a successful identification. If model identification
continues to fail, multiple Apple mobile devices are present, or the model
does not match, the next regular alert check reports the required action after
the condition persists for two minutes.

Worker assignments: [cable day](../goals/cable-day.md).

Tool behavior comes from the installed help and upstream
[ideviceinfo source](https://github.com/libimobiledevice/libimobiledevice/blob/1.3.0/tools/ideviceinfo.c).
USB mode matching follows the installed upstream-derived
[usbmuxd](https://github.com/libimobiledevice/usbmuxd) and
[libirecovery](https://github.com/libimobiledevice/libirecovery) udev rules.
