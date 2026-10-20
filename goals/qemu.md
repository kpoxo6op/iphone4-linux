# qemu: M1 and M2

Current priority: the qemu assignment in [first connection](cable-day.md).
Keep the M1/M2 image and P0 lifecycle evidence intact while preparing the handoff.

Build a reproducible minimal ARMv7 Linux system using Buildroot 2026.08,
Cortex-A8-compatible hard-float userspace, and QEMU vexpress-a9. This is NOT
iPhone emulation. Use the external Bootlin armv7-eabihf musl stable toolchain
supported by that Buildroot release to avoid spending hours rebuilding GCC.

Own: build scripts, Buildroot external tree, QEMU configuration and TUI code.
Do not implement the phone kernel profile; the kernel lane owns that work.

Start with upstream qemu_arm_vexpress_defconfig; its Linux version is 6.18.7.
Use source hashes. Disable building host QEMU; use the installed qemu-system-arm.
Bootloader is unnecessary for this emulator target. Include BusyBox, Dropbear,
tmux, dialog, htop and nnn if feasible. Console ttyAMA0, DHCP eth0, ext4 rootfs.
Allow root SSH with injected public keys only; disable SSH passwords. Create
/root/.ssh in the image. No real user key or fixed private key in source/images.

Required artifact names in output/images: zImage, vexpress-v2p-ca9.dtb,
rootfs.ext4. May symlink/copy from the Buildroot output. Rootfs must fit an SD
image accepted by QEMU. Run /acceptance/qemu_smoke.py --images output/images.
Record raw boot logs and result JSON. Then demonstrate a real dialog/TUI screen
inside tmux and exercise one action; checking an executable exists is not enough.

Deliver one build command, exact dependencies, checksums, logs, a concise README
for this lane, and notes/GOAL.md. Do not edit /acceptance or harness/. No CI or
container framework is required. Kernel compilation and userspace behavior are
the work; skip decorative project scaffolding.
