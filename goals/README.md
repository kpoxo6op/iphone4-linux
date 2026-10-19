# Goals and acceptance gates

| Gate | Deliverable | Evidence required | Owner |
|---|---|---|---|
| M0 | Safe visible worker setup | Sandbox negative checks, exact model route, GUI sessions | Maintainer |
| M1 | ARMv7 boot, shell, file I/O | Pinned build, QEMU boot log, independent acceptance harness | qemu |
| M2 | SSH and small TUI | Reject wrong SSH key; file survives reboot; actual TUI interaction | qemu |
| M3 | N90 kernel and RAM userspace | Pinned source, successful cross-build, ARM ELF, DTB, hashes | kernel |
| M4 | Cable-day boot and USB SSH | N90 identification and real phone logs; RAM-only first | Requires phone |
| M5 | Wi-Fi and touch | Reviewed driver patches, then actual packets and input events | drivers / phone |
| M6 | Persistent storage and usable handheld | Recovery plan, tested storage mapping, safe power behavior | Requires phone |

M1–M3 can be attempted now. M4–M6 cannot be accepted without the actual phone.
The drivers worker can prepare evidence and compile-tested patches for M5, but
must stop before claiming hardware works. Stable USB networking should precede
Wi-Fi; RAM rootfs should precede NAND. Exact phone variant must be confirmed.

The initial run window is seven days. Completion, unchanged blockers or resource
limits stop a lane early. Extending the calendar does not override these gates.
