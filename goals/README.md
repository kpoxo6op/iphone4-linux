# Goals and acceptance gates

| Gate | Deliverable | Evidence required | Owner |
|---|---|---|---|
| M0 | Safe visible worker setup | Sandbox negative checks, exact model route, GUI sessions | Maintainer |
| M1 | ARMv7 boot, shell, file I/O | Pinned build, QEMU boot log, independent acceptance harness | qemu |
| M2 | SSH and small TUI | Reject wrong SSH key; file survives reboot; actual TUI interaction | qemu |
| M3 | N90 kernel and RAM userspace | Pinned source, successful cross-build, ARM ELF, DTB, hashes | kernel |
| M4 | Cable-day boot and USB SSH | N90 identification and real phone logs; RAM first | kernel / connected phone |
| **M4b — P0** | **Tailscale + SSH on the phone: remote development** | Authorized laptop reaches the phone's own tailnet node; shell, transfer, reconnect and denial checks pass | [remote-access](remote-access.md) / phone |
| M5 | Wi-Fi and touch | Reviewed driver patches, then actual packets and input events | drivers / phone |
| M6 | Persistent storage and usable handheld | Recovery plan, tested storage mapping, safe power behavior | Requires phone |
| Soy | Touch text scenes and Russian Markdown | [Design, runtime, real display, touch, Wi-Fi and recovery checks](soy.md) | Master / all lanes |

**20 October 2026:** M4's first RAM boot and USB SSH passed on the real N90AP.
The phone also joined Tailscale; shell, PTY, file I/O and wrong-key rejection
passed through its own tailnet node. [Exact artifacts and evidence](../docs/first-phone-attempt.md)
are recorded. A 30-minute session also passed. M4b remains open for interrupted-link recovery,
an excluded tailnet identity check and a repeat RAM boot with identity restoration.

The drivers worker prepares evidence and compile-tested patches for M5, but
must stop before claiming untested hardware works. Stable USB networking
precedes Wi-Fi; RAM rootfs precedes NAND.

The cable is now available. [First-connection assignments](cable-day.md) cover
model identification, the RAM bootloader and the USB remote-access handoff.

**M4b is the main product milestone.** Run Tailscale on the phone so subsequent
bring-up can happen remotely. USB-shared Internet can come first; Wi-Fi, touch
and TUI polish are not prerequisites. Installing binaries alone is not a pass.
The first enrollment and connection now work on hardware. Finish the
reliability checks without requiring NAND installation.

Soy now renders on the real framebuffer. The current focus is
[Ghostty-informed rendering performance](../docs/soy/performance.md), touch and
Wi-Fi drivers, plus reliable deployment. Its design basis is saved in
[foundations](../docs/soy/foundations.md), not left in chat.

[GitHub goals](https://github.com/kpoxo6op/iphone4-linux/issues) track scope and
review. See the [agent workflow](../docs/agent-workflow.md).

Free workers may run 24/7 without a calendar expiry. Completion, unchanged
blockers or resource limits still stop a lane. Continuous availability does not
override these gates or permit busywork after an assigned goal is finished.
