# kernel: M3

Current priority: operate the connected N90AP and boot Linux, then reach
key-only SSH over USB. Follow [device work](cable-day.md). You have real USB
access and full owner authorization; do not stop at a proposal or wait for
another approval. Preserve the M3 reproduction and review evidence below.

Reproducibly cross-compile archeYR/linux at
8e79d535d2068ae9b9475d2e6850a6edd67fad5b, using s5l8930_defconfig and
samsung/s5l8930-apple-n90.dtb. This is Linux 6.17-rc1, not latest upstream.

Own: phone/ build script, source lock, configuration fragments, patches and
phone/docs/. Do not duplicate or edit the qemu lane's Buildroot external tree.
Use a pinned public Bootlin toolchain (Buildroot's own package metadata is a
source of verified toolchain URL/hash) or a compatible existing cross compiler.
Seed downloads are mounted read-only at /seed; copy/link into your .cache.

First reproduce the upstream build without unrelated changes. Preserve vmlinux,
zImage, DTB, final .config, build log, compiler identity and SHA256 manifest in
output/phone/. Use readelf to establish 32-bit ARM, inspect DTB compatibility,
and document required boot arguments and loader assumptions from actual source.
Prepare a minimal initramfs with BusyBox if practical after kernel passes;
do not block a reproducible kernel deliverable on a speculative rootfs port.
Device boot and storage writes are owner-authorized on the pinned phone.
Prefer RAM boot for fast iteration. Do not claim USB works based solely on compilation.

Report existing driver/DT omissions relevant to USB console/RAM rootfs. Propose
only source-grounded minimal patches and retain upstream provenance and license.
No invented register programming. A successful build with a warning about the
untested boot handoff is preferable to pretending a DFU loader is ready.

Deliver exact build and verification commands, hashes and notes/GOAL.md. The
master will inspect artifacts and re-run relevant checks before acceptance.
