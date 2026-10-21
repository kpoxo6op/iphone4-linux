# N90 backlight, buttons and GPIO

These patches give the phone a working PMU backlight switch, the five physical
buttons as an input device, and the A4 GPIO controller. They come from the drivers
lane's `patches/experimental/n90-display-power` series. Two fixes came out of the
first phone test on 21 October 2026.

- **Wrong GPIO base.** Apple's device tree gives `0x3fa00000` relative to
  `arm-io`. The physical address is `0xbfa00000`, matching the VIC and timer
  nodes and openiBoot's `GPIO`. On the first test kernel every GPIO access
  went to the RAM alias, so I2C saw no devices. That kernel was not kept.
- **A4 GPIO encoding.** openiBoot writes `0x210` (input) and `0x212`/`0x213`
  (output). Bit 4 is set in all of them. The quirk now sets it too. The live
  button pins read `0x211` at rest, which matches.

The board nodes live in `n90-boot-display-power.dts`. This is the knownboot DTB
with a GPIO controller, `gpio-keys-polled`, `i2c-gpio` on pins 75/76 and
`backlight@74` added, plus `panic=10`. It does not patch the upstream N90 DTS:
the phone boots this flat DTB.

## Phone results, 21 October 2026

Kernel `497fa0e4…` and DTB `9567afd1…`, booted by
`harness/phone_boot.py run --test-zimage … --test-dtb …`:

| Check | Result |
|---|---|
| Boot | Linux USB, strict USB and tailnet SSH, same Tailscale node |
| GPIO at `0xbfa00000` | Buttons read `0x211`, ringer `0x210`, I2C pins `0x211` after setup |
| I2C (`i2c-gpio`) | `i2cdetect` sees `0x0d`, `0x29`, `0x39` and the PMU at `0x74` |
| PMU at boot | `0x66=0xbb`, `0x67=0x04` (level 1500), `0x68=0x15`: iBoot's values, matching openiBoot's register contract |
| `bl_power=4` | `0x68` reads back `0x00` |
| `bl_power=0` | `0x66=0xd4`, `0x67=0x00`, `0x68=0x15` (level 1696) |
| Soy idle | after 60 s, `display_state: blanked`, `backlight: off`, PMU `0x68=0x00`; `wake` over the control FIFO lights it again (`0x15`) |
| Buttons | `gpio-keys-polled` registered as `event0`; no physical press tested |

Every result here is a register readback. Nobody has looked at the screen yet,
so a dark panel is still to be confirmed by eye.

## Build

```sh
cd linux-8e79d535d2068ae9b9475d2e6850a6edd67fad5b   # same tree as knownboot
patch -p1 < 0001-pinctrl-apple-gpio-s5l8930.patch
patch -p1 < 0002-backlight-pmu-s5l8930.patch
cp <knownboot build>/.config $O/.config
scripts/config --file $O/.config $(sed -n 's/^CONFIG_\(.*\)=y/--enable \1/p' config-fragment.config)
make ARCH=arm CROSS_COMPILE=arm-buildroot-linux-gnueabihf- O=$O olddefconfig zImage
$O/scripts/dtc/dtc -I dts -O dtb -o n90-backlight.dtb n90-boot-display-power.dts
```

The toolchain is the Buildroot `armv7-eabihf--glibc--stable-2025.08-1` (GCC
14.3.0) that built the knownboot zImage. `CONFIG_TUN=y` makes the kernel
independent of the initramfs's `tun.ko`.

## Lean build, 22 October 2026

Same tree and patches plus `0003-clocksource-s5l8930-sched-clock.patch`, with
`lean.config` applied to the backlight `.config` before `olddefconfig`.
The knownboot configuration had lockdep, lock debugging and the function
tracer on. On the phone a `getppid` took 13 µs and reading one sysfs file
1.4 ms; Soy's network telemetry alone took 12 ms, which stalled frames.

The timer driver registered no `sched_clock`, so the scheduler accounted time
in 10 ms jiffies. Patch 0003 registers the 24 MHz counter.

| | Backlight kernel `497fa0e4` | Lean kernel `e899dceb` |
|---|---:|---:|
| `getppid` | 13.1 µs | 0.79 µs |
| open/read/close sysfs | 1413 µs | 129 µs |
| Soy network telemetry | 11.8 ms | 2.2 ms |
| sched_clock | 100 Hz jiffies | 24 MHz, 41 ns |

It booted through `harness/phone_boot.py run --test-zimage` on 21 October
12:13 UTC with the backlight DTB `9567afd1`, with USB and tailnet SSH, and runs
the touch driver and Soy. uinput is built in.
