# USB outage — 21 October 2026

The phone stopped answering USB at 08:42 NZDT. The owner reports that the
cable stayed connected and the screen still shows Soy/Linux. A retained
screen image does not establish that the kernel is still running.

## What we measured

- At 08:41:44, the host watcher still identified the pinned N90 Linux USB device.
- At 08:42:07, Platt logged the USB disconnect and removed its Ethernet interface.
- From 08:42:14, the host detected an attachment but could not read its device
  descriptor: `error -110`, followed by address errors and failed enumeration.
- The USB root hub reports power and connection on the assigned port. It has
  no software-controlled power switching. Other devices still enumerate.
- One retry that disabled and re-enabled only the phone's assigned port
  finished at 09:23:06. The port is enabled; the phone still does not enumerate.
- All three workers were waiting for provider quota when the outage began.
  The prepared idle-display update had **not** been deployed.

The cause is unresolved. A phone kernel/USB driver stall and an electrical
connection or port problem remain possibilities. We have no battery reading
or phone kernel log from the failure, so neither battery failure nor a
specific driver bug is established. Internet and Tailscale depended on USB.

## Recovery prepared

The connection watcher still runs every 30 seconds. It now remembers a prior
Linux connection and reports its loss through Soyclaw after two minutes,
instead of treating this as a phone that has never been plugged in. The
21 October outage alert received a delivery acknowledgement.

When the pinned Linux USB device returns, the watcher tries authenticated SSH
with the saved host key. It saves kernel diagnostics privately and checks
whether Tailscale reaches the same boot. Only a verified return generates
a recovery report. It never replaces host-key trust or resets the phone.

The maintainer copied and verified the exact five artifacts from the
[successful boot](first-phone-attempt.md), plus the patched loader and local
iBSS, into a private recovery directory. Its manifest records hashes, load
addresses and remaining caveats. Saved SSH identity and Tailscale state remain
separate and private. No Apple firmware or credentials are published.

A new RAM boot and private identity restoration are still untested. The
patched loader also needs its first complete fresh-DFU test. Prepared files
are not proof that unattended recovery works.

## Next steps

If enumeration stays broken, reseating the phone-end connector is the next
physical step. A frozen phone may need a button reset and DFU afterward;
software on Platt cannot press those buttons or power-cycle this port.

On reconnection, preserve the running boot if possible. Collect evidence
before changing the renderer or kernel. If it instead returns in DFU/recovery,
the kernel operator must verify the pinned identity, use the recorded boot
artifacts, and coordinate host-assisted identity restoration. Do not reset
Platt's shared USB controller or change unrelated devices.

Private evidence: `output/hardware/usb-failure-20261021/` and
`.runtime/phone/private/recovery-knownboot-20261021/` on the maintainer's host.
