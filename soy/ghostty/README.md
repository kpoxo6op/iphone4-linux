# Ghostty on the iPhone 4

**Use libghostty-vt for terminal semantics.** The pinned C API built for ARMv7
and passed a real shell/PTY test on our Linux iPhone 4 on 20 October 2026.
The framebuffer scenes still use the original Soy renderer; the library is
not integrated into the visible shell yet.

The library owns escape sequences, terminal cells, styles, cursor state,
scrollback, alternate screens and resizing. Soy still owns the PTY process,
phone display, fonts, touch gestures and scene lifecycle. Markdown needs a
reader that produces terminal output or its existing document layout.
libghostty-vt does not include Ghostty's GPU renderer and cannot supply the
missing touch or Wi-Fi drivers.

## Pinned inputs

- [Ghostty](https://github.com/ghostty-org/ghostty/tree/b58ef1d678be2747c830bc1b1e6c0a086afecf9a):
  `b58ef1d678be2747c830bc1b1e6c0a086afecf9a`, MIT.
- Source archive:
  `https://codeload.github.com/ghostty-org/ghostty/tar.gz/b58ef1d678be2747c830bc1b1e6c0a086afecf9a`
  SHA-256 `60c710ff2295c004901a5a99bdb11a548a022db4fa357e20b15c74637538a8f9`.
- Zig 0.16.0, x86_64 Linux host:
  `https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz`
  SHA-256 `70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00`.
- Phone target: `arm-linux-musleabihf`, Cortex-A8, Linux 6.17.0-rc1.
- C headers: the same revision's `include/ghostty/vt.h`.

The current upstream C API explicitly says it is unstable. Keep headers and
library on this exact revision until an intentional upgrade passes the probe.
SIMD is disabled for this first portability check. This is not the final
optimized build.

## Two integration problems found

1. TinyIo used the direct Linux `lseek` syscall on 32-bit targets, which Zig
   rejects because its offset does not fit `usize`. Apply
   [the small patch](patches/tinyio-linux32-seek.patch). It follows Zig 0.16's
   `std.Io.Threaded` selection of `llseek` on 32-bit Linux without libc,
   preserving all 64 offset bits. Other platforms retain the original path.
   The build exercises compilation of this branch; the PTY probe does not
   independently certify large-file seeking.
2. In this non-SIMD static build, Wuffs exports weak `calloc`/`free` stubs for
   otherwise unused image helpers. Normal archive order selected those stubs
   before musl; a real C allocation returned NULL. Put libc before Ghostty in
   a linker group, as below. Verified symbols are strong `T calloc` and
   `T free`, and the actual-phone probe allocates and frees cell buffers.
   Do not silently work around this by avoiding allocations in a test.

## Reproduce

Download, verify and extract the pinned archives outside Git. Set absolute
paths to the extracted source, Zig executable and ARM musl tools:

```sh
export GHOSTTY_SRC=/path/to/ghostty-b58ef1d678be2747c830bc1b1e6c0a086afecf9a
export ZIG=/path/to/zig-x86_64-linux-0.16.0/zig
export CC=/path/to/arm-linux-gcc
export STRIP=/path/to/arm-linux-strip
export NM=/path/to/arm-linux-nm
export SOY_REPO="$PWD"
export SOY_GHOSTTY_OUT="$SOY_REPO/output/soy/ghostty-arm"

patch -d "$GHOSTTY_SRC" -p1 < soy/ghostty/patches/tinyio-linux32-seek.patch
(
  cd "$GHOSTTY_SRC"
  "$ZIG" build -Demit-lib-vt=true -Dtarget=arm-linux-musleabihf \
    -Dcpu=cortex_a8 -Doptimize=ReleaseFast -Dsimd=false -j2 \
    --prefix "$SOY_GHOSTTY_OUT"
)
"$CC" -O2 -std=c11 -Wall -Wextra -Werror -DGHOSTTY_STATIC -static \
  -march=armv7-a -mfpu=vfpv3-d16 -mfloat-abi=hard \
  -I"$GHOSTTY_SRC/include" soy/ghostty/phone_probe.c \
  -Wl,--start-group -lc "$SOY_GHOSTTY_OUT/lib/libghostty-vt.a" \
  -Wl,--end-group -lm -pthread -o output/soy/ghostty-phone-probe
"$NM" output/soy/ghostty-phone-probe | rg ' [TW] (calloc|free)$'
"$STRIP" output/soy/ghostty-phone-probe
```

Using the owner's private SSH configuration, copy that executable to
`/run/soy/ghostty-vt-probe`, chmod 700, and run it. It neither opens the
framebuffer nor changes the running shell. A 15-second alarm bounds execution.

## Evidence and next step

[phone-result.json](phone-result.json) records the actual result and artifact
hashes. The probe forks `/bin/sh` on a real PTY, feeds its output in three-byte
chunks and checks Ghostty's public render-state API. It tests Cyrillic split
across reads, colors/bold, erase/cursor behavior, box characters, alternate
screen restoration, clean-state tracking, incremental updates and resize.

This small workload peaked at 1,464 KiB RSS, with 794,624 bytes in terminal
pages. The stripped probe is about 1.9 MiB. These figures are not a memory
budget for a complete application or a large scrollback, and its short parse
time is not a display frame-rate measurement.

Next: add an optional PTY-backed Soy scene using this library's render state
and the existing phone display path. Keep the current Markdown reader until
the new path matches its legibility and behavior. First prove a real TUI's
output, bounded scrollback, resize and child-process cleanup; then measure
complete frame times. Keep SSH independent of both renderers.
