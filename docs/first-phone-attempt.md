# First Linux boot — 20 October 2026

The actual iPhone 4 now runs Linux, serves SSH over USB, and has its own
working Tailscale connection. The maintainer logged in through the phone's
tailnet address and tested an interactive terminal and file transfer.

This is a RAM boot on an original GSM iPhone 4: `iPhone3,1`, board `N90AP`,
chip `0x8930`. It is not a persistent installation. Internet comes through
Platt over USB; Wi-Fi and touch have not passed hardware tests.

## What ran on the phone

| Check | Result |
|---|---|
| Kernel | `6.17.0-rc1`, `armv7l` |
| Device tree | `Apple iPhone 4` |
| PID 1 | BusyBox `init` |
| USB Ethernet | `0525:a4a1`, configuration 1, host `cdc_ether` |
| USB SSH | Owner key login and interactive PTY passed |
| Internet | External IP ping and DNS lookup passed |
| Tailscale | `1.104.1`, `Running`, native kernel TUN |
| Tailnet SSH | Commands and interactive PTY passed |
| File I/O | 4,096-byte write/read with matching SHA-256 over both SSH paths |
| Wrong SSH key | Rejected over both paths; owner login still worked afterward |
| Development transfer | Patch roundtrip matched byte-for-byte; kernel log retrieved over tailnet SSH |

Builds currently run on the host and are transferred to the phone. No native
compiler on the phone was tested.

After enrollment, `tailscaled` used about 32 MiB RSS and Linux reported
about 383 MiB available memory. This is one idle measurement, not a peak
or a load test.

The first image needed live setup: loopback was brought up, the clock was
set from Platt before TLS enrollment, and devpts was remounted with explicit
permissions. Workers are folding these into the next boot procedure. Later
rebuilt archives have not yet run on the phone.

M4's first boot and USB SSH are demonstrated. M4b's first remote session
passes, with more reliability checks to finish: a 30-minute session,
deliberate link interruption/reconnection, an excluded tailnet identity,
and a repeat RAM boot with identity restoration. Private copies of the SSH
host key and Tailscale state exist on Platt; restoration has not been tested.

## How we got here

The successful DFU sequence was Home + Power for eight seconds, then Home
alone for twenty seconds. The screen stayed black and Platt saw `05ac:1227`.

The first `loadibec` run sent the limera1n exploit and began iBSS transfer,
then crashed during reconnect. Its old USB library freed its shared context
on a failed open and reused that context on the next attempt. The worker
built a fix, but this session did not prove that fix through a fresh DFU run.

The worker continued with the installed `irecovery`, sent the iBSS payload
and openiBoot, and issued `go jump 0x41000000`. openiBoot appeared as
`0525:1280` at 21:45:37 NZDT and answered through `oibc`. The worker uploaded
the kernel, DTB, initramfs and RAM entry stub. Linux USB Ethernet appeared
at 21:48:43; the maintainer then connected with SSH and enrolled Tailscale.

## Exact booted artifacts

These are the artifacts uploaded for this successful boot, not the most
recent files in the worker's output directory.

| Artifact | SHA-256 |
|---|---|
| openiBoot | `29d65d295aae4ce2318d30756e427dd9f177daf05280eaeafa7670cea6e22cb2` |
| zImage | `936edd3f9419d393993a03a061f05f3cd848fd8dcf0b16be1ad610add3db0563` |
| DTB | `5b8288fc08b604e3d4305e33f812cf29249baf5d37d881126862f1a9c7bf116a` |
| RAM entry stub | `ebeff1d0f2d94d8419949eeae0e5522421c69f2461fb4573f21f14375c57ab79` |
| initramfs | `5513ddf992f8a74157a45265d2744ccee07d09d60cef0017aca65ce8c109ec1c` |

## Evidence

Raw logs stay in ignored local directories because they can contain device
and account identifiers. No Apple firmware or enrollment state is published.

- Kernel worker: `output/hardware/20261020-openiboot-evidence.txt`,
  `20261020-linux-usb-evidence.txt`, `20261020-openiboot-ramboot-commands.txt`
  and `20261020-openiboot-ramboot-attempt.log`.
- Maintainer: `output/hardware/master-phone-smoke.json` and
  `output/hardware/master-tailnet-smoke.json`.
- The same booted initramfs also passed all seven independent QEMU checks in
  `output/master-initramfs-20261020-2209-isolated/result.json`. That test uses a
  reference kernel and virtual RNG; it does not prove iPhone peripherals.

See [access from Platt](platt-usb.md) for the private local SSH configuration
and [the remaining remote-access checks](../goals/remote-access.md).
