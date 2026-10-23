# Updates over the air

Every change used to reach the phone as a push from the laptop, over USB or
Tailscale. Now the phone pulls its own updates: wherever it has Wi-Fi, it
checks the repository's latest GitHub release, installs it if it is newer
than what it runs, and puts the old software back if it is not healthy a
minute later. The laptop only builds and signs releases.

## What a release is

`harness/phone_release.py build` makes three files in `output/release`:

| File | |
| --- | --- |
| `phone-release.manifest` | `version`, `commit`, `committed` (the commit's time), `tar` (its SHA-256), then one `file PATH SHA256 MODE` line per file |
| `phone-release.manifest.sig` | Ed25519 signature of the manifest |
| `phone-release.tar` | the files |

A release holds the Soy renderer and its fonts and the phone's own tools:
`n90-keep`, the Wi-Fi keeper, `n90-firewall` and its rules, `n90-scene`,
`n90-story`, `n90-battery`, `n90-time`, `n90-ota`, `n90-sig` and the
updater's `wget`. Never Apple firmware, kernel modules, Wi-Fi keys, scenes
or the story model: those stay with the boot pass. `publish` creates a
GitHub release from the commit and marks it latest.

The signing key is `.runtime/phone/private/ota/signing.key` on the laptop,
never in Git; its public half is `ota.pub` here, installed on the phone as
`/etc/n90/ota.pub`. `n90-sig` signs and verifies with TweetNaCl's Ed25519
(public domain, downloaded and hash-checked by the Makefile).

## On the phone

`n90-ota serve`, which keep runs, checks five minutes after it starts and
then every six hours (every half hour while nothing answers). A check:

1. fetches the manifest and signature from
   `https://github.com/kpoxo6op/iphone4-linux/releases/latest/download`;
2. refuses anything without a good signature, with a malformed version, or
   from a commit no newer than the one running, and anything it rolled back
   before;
3. fetches the tar and refuses it unless it and every file match the
   manifest;
4. makes a renderer release beside the current one with the scenes the
   phone shows, sharing unchanged files, and runs the renderer's own check;
5. installs the tools, keeping copies, switches the renderer, restarts the
   services and reloads the firewall rules;
6. a minute later checks keep, the renderer (the new binary, scenes loaded),
   the battery reader, the Wi-Fi keeper, the firewall and the new updater.
   Healthy: it records the version and drops all but the current and
   previous renderer releases. Not: it puts everything back and remembers
   not to try that release again.

Events go in Soy's journal (`ota installed`, `ota rolled-back`); details in
`/run/ota/ota.log`.

The phone's own busybox `wget` has no HTTPS, so `kernel/n90-ota` also builds
BusyBox 1.38.0 as nothing but `wget` with its built-in TLS
(`/opt/n90-ota/wget`). That TLS does not check certificates. It does not
need to: a download counts only once the signature and the hashes do.

The boot pass installs the updater and records what it installed as
`laptop-<commit>` with that commit's time, so the phone takes a release only
when it comes from a newer commit than the laptop's checkout.

```sh
make -C kernel/n90-ota                    # n90-sig (phone and laptop), wget
python3 harness/phone_release.py build    # or publish
n90-ota check                             # on the phone, now
N90_OTA_URL=http://10.84.4.1:8000 n90-ota check   # from the laptop over USB, for tests
```

## On the phone, 24 October 2026

From a test server on the laptop's end of the USB cable: a release built
from `758c4d6` (24 files, 8.1 MB) was verified, installed and found healthy
67 s after the check started; the renderer ran from
`/opt/soy/releases/ota-2026-10-23-758c4d6`. A second release whose Wi-Fi
keeper exits at once was installed, failed the health check ("n90-wifi-keep
is not running") and was rolled back: the phone kept `758c4d6`, the real
keeper came back and Wi-Fi stayed connected.
