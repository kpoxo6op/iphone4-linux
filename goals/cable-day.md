# First connection to Platt

The cable is here. The owner will connect the phone to Platt. The first job is
to identify it and prepare a recoverable RAM boot. A connected USB device is
not evidence that Linux boots.

The maintainer handles the host and read-only identification. Workers retain
their existing sandbox: no phone, USB, pairing records or host services. They
can read the sanitized snapshot at `.opencode/phone-observation.json` when
available. It contains USB mode and selected model/software facts, never a
serial number, UDID, ECID, device name, account or pairing material.

Normal iOS, recovery and DFU are separate observations. Do not infer N90 from
an Apple USB vendor ID. The current kernel targets iPhone3,1 / N90AP. A
different or unknown model blocks use of that image and requires a new plan.

## Device authorization

On 20 October 2026 the owner authorized flashing, erasing and other device work
on this project iPhone and confirmed that it holds no important data. Do not
ask for that permission again. The maintainer may execute the appropriate
recovery/DFU, exploit, payload and flashing steps when the target and procedure
are established. Start with RAM boot where practical because it gives a fast
development loop; a backup is not a prerequisite imposed by this project.

Authorization does not establish a correct boot chain or make an unknown
image compatible. Confirm the actual model, source/provenance, artifact
hashes, exact command sequence and recovery procedure before executing.
Workers keep their existing offline sandbox and prepare reviewable artifacts
and commands; device execution belongs to the maintainer. An observation
alone does not authorize a sandbox escape or arbitrary register/storage writes.
Live tailnet enrollment and host firewall changes remain separate from phone
flashing authorization.

## Assignments

- **kernel:** prepare the RAM boot handoff in `phone/docs/first-boot.md`.
  Investigate the loader from primary source at pinned revisions. Establish
  what actually supports A4/N90, required device mode and firmware, payload
  format and load addresses, DTB/initramfs handoff, and recovery to stock iOS.
  Separate known working upstream paths from untested proposals. If a complete
  loader is missing, name the smallest missing implementation; do not invent a
  runnable sequence. A bounded host-only loader build is useful if supported.
  Also resolve the kernel options and initramfs requirements for USB Ethernet
  (ECM on Linux), TUN and key-only SSH. Preserve the existing M3 artifacts;
  proposed changes and any new builds need separate manifests.
- **qemu:** prepare `notes/phone-remote-access-handoff.md` and a reusable
  userspace staging command for RAM-rootfs integration. Keep ownership of the
  ARM userspace, Dropbear and Tailscale init. Export binaries, libraries,
  provenance, sizes and hashes without private keys or a tailnet identity.
  Audit userspace versus the phone kernel ABI and 512 MiB memory budget.
  Exercise the unresolved DNS, CA, time, entropy and netfilter prerequisites
  in the existing guest where meaningful. Explain what USB gadget setup and
  host Internet sharing will require; do not modify Platt's network/firewall.
  Preserve working QEMU acceptance evidence and the P0 process-lifecycle fixes.
- **drivers:** prepare `research/first-connection.md` for model/mode triage
  and the USB-controller/gadget prerequisites in the pinned kernel. Focus on
  the earliest observable boot and USB network signals. Review the existing
  M5 plan so Wi-Fi, touch and MMIO proposals do not obstruct M4/P0. Supply
  source locations and a short list of missing observations, not another
  broad parser rewrite.

Use `.opencode/review-feedback.json` for the latest outstanding findings.
Prior results still need independent review. New cable-day work does not mark
them accepted. Retain completion notes and exact artifact hashes. Stop at a
specific missing observation instead of polling the phone or making up a pass.
