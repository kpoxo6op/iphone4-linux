# Connecting the phone

Connect the powered-on iPhone to Platt with the USB data cable. Leave iOS running
and unlock it if possible. There is no need to enter recovery or DFU.

Platt checks for the phone every 30 seconds while awake. It reads USB mode and,
in normal iOS mode, requests only the product type, board model, iOS version
and build. It uses `ideviceinfo -s` to avoid automatic pairing. The watcher
does not run recovery commands, send payloads or change the phone's storage.

The sanitized result goes to the workers automatically. A new observation
wakes workers waiting for review and steers those already running. Existing
review holds, cost checks and resource limits remain in force. A different or
unidentified model cannot qualify the N90 image for use.

The first connected device has not yet been tested. USB detection establishes
the connection and model only. The loader, RAM boot and USB network path still
need review and actual hardware evidence before SSH or Tailscale can work.
The owner has authorized flashing and erasing this phone; another permission
prompt is not required. The watcher identifies the device, and the maintainer
executes device steps once the matching boot procedure and artifacts are ready.

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
