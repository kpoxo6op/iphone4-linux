# First connection to Platt

The phone is connected to Platt. A live `irecovery -q` confirmed iPhone3,1,
N90AP, CPID 0x8930, BDID 0x00, in recovery mode on 20 October 2026.
The next job is to boot Linux and establish USB SSH, then Tailscale.

The kernel lane now operates the real phone through USB inside its sandbox.
The host helper exposes only this phone's USB socket; Apple recovery/DFU
enumerations must also match its pinned ECID. Loader/Linux USB IDs on that
socket remain accessible across resets. One kernel shell owns USB at a time.
Other lanes supply software and analysis in parallel. Read the current
`.opencode/phone-observation.json` and `.opencode/device-access.json`.
Use `irecovery -q` yourself to verify access; keep its raw output under
ignored output/hardware and publish only model/mode and non-unique chip facts.

Normal iOS, recovery and DFU are separate observations. Do not infer N90 from
an Apple USB vendor ID. The current kernel targets iPhone3,1 / N90AP. A
different or unknown model blocks use of that image and requires a new plan.

## Device authorization

On 20 October 2026 the owner authorized flashing, erasing and other device work
on this project iPhone and confirmed that it holds no important data. Do not
ask for that permission again. The device operator may execute the appropriate
recovery/DFU, exploit, payload and flashing steps when the target and procedure
are established. Start with RAM boot where practical because it gives a fast
development loop; a backup is not a prerequisite imposed by this project.

Authorization does not establish a correct boot chain or make an unknown
image compatible. Confirm the actual model, source/provenance, artifact
hashes, exact command sequence and recovery procedure before executing.
The owner subsequently requested full worker access to the device. The kernel
lane may execute experiments without a separate maintainer approval. Build,
run, diagnose and iterate; do not turn this back into proposal-only work.
Keep the host sandbox and other devices isolated. Record commands and results,
and avoid pointless writes that do not test a concrete hypothesis.
The requested Tailscale/SSH work on this phone is part of the goal. The
maintainer handles phone-scoped enrollment credentials and the host USB-network
setup; workers do not receive unrelated host/account access.

## Assignments

- **kernel:** build and execute the boot path, documenting it in
  `phone/docs/first-boot.md`.
  Investigate the loader from primary source at pinned revisions. Establish
  what actually supports A4/N90, required device mode and firmware, payload
  format and load addresses, DTB/initramfs handoff, and recovery to stock iOS.
  Separate known working upstream paths from untested proposals. If a complete
  loader is missing, implement the smallest missing piece and test it. A
  physical button sequence may require the owner; report exact steps only when
  the remaining software is ready. Do not invent a command to avoid that fact.
  Also resolve the kernel options and initramfs requirements for USB Ethernet
  (ECM on Linux), TUN and key-only SSH. Preserve the existing M3 artifacts;
  changes and new builds need separate manifests. Integrate the userspace
  supplied under /seed/handoff/phone-userspace. Do not merely repeat M3 checks.
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
Prior results still need independent acceptance review, but this does not block
authorized hardware experiments. Retain completion notes and exact artifact
hashes. Stop only for a concrete external blocker or completed deliverable;
ordinary compile failures and missing loader code are work to resolve.
