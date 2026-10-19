# ARM shell, persistent files and terminal UI

## Sub-features

- M1: a real ARMv7 kernel reaches a usable shell.
- M2: the authorized SSH key succeeds, another key fails, passwords are disabled,
  a random file survives a clean power cycle, and one TUI action works.

## How to get to it (user POV)

SSH to the disposable QEMU guest; launch the TUI in its terminal. Host command
output or a static terminal screenshot is not evidence of guest interaction.

## Driving it with the harness

Preconditions: completed zImage, vexpress-v2p-ca9.dtb and rootfs.ext4 under
output/images; dependencies reported by doctor.

- Run `python3 /acceptance/verify.py doctor --images output/images`.
- Run `python3 /acceptance/verify.py qemu --images output/images`. Receipt and
  raw result must show ARMv7, good-key access, wrong-key rejection, file
  write/read and persistence after the second boot.
- Separately show a password-only authentication attempt rejected and the
  effective Dropbear arguments. The existing smoke does not cover passwords.
- Follow the worker's TUI evidence recipe only after inspecting its script.
  Capture launch, a real action and changed state from inside the guest.

## Gotchas

`DROPBEAR_ARGS=-w` also forbids root pubkey login. Do not fix it by enabling
password login. A make-to-tee pipeline can hide failure. A populated cache can
hide an unreproducible build. Test those boundaries in the owning build script.
No QEMU result proves N90 USB, Wi-Fi, touch, NAND, charging or thermal behavior.
