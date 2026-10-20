# Phone kernel package

## Sub-features

M3 supplies a reproducible N90 kernel package and documented RAM-root handoff.
It does not prove phone boot.

## How to get to it (user POV)

Run the kernel lane's documented build command from an empty build/cache
directory. Inspect output/phone; a developer must be able to reproduce it.

## Driving it with artifact tools

Preconditions: the pinned source/toolchain, build command and package exist.

- Save build command and exit code; propagate compiler/make failures even
  when logs pass through tee. Retained old artifacts cannot count as new output.
- Run `readelf -h output/phone/vmlinux`; require ELF32 and ARM. Record the
  compiler identity, source revision, config and SHA256 manifest.
- Inspect the DTB with dtc/fdtget against the pinned source's N90 compatible
  strings. A filename alone cannot establish board identity.
- Record the provenance of extracted sources as well as archives. A clean
  build must not depend on untracked directories from the first attempt.
- For CONFIG_TUN=m, provide matching tun.ko plus a loading path, or propose
  a separately reviewed built-in config fragment. zImage alone is insufficient.

## Gotchas

USB console, boot arguments and loader handoff need source-grounded reasoning
and later hardware evidence. BusyBox compilation is not a mounted rootfs.
An initramfs cpio archive is not a /dev/ram0 block image. The assigned device
operator now has owner authorization to test the matching artifacts on hardware.
