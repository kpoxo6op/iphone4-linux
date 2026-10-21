# N90 Wi-Fi (BCM4329 on SDIO)

Work in progress, 21–22 October 2026. Wi-Fi does not work yet.

## Wiring

| Function | Where | Source |
|---|---|---|
| SDIO host | SDHCI 3.00 at `0x80000000`, SoC interrupt 38 (VIC1 line 6). Capabilities `0x69a530b0`: 48 MHz base clock, 3.3 V, high speed, no SDMA or ADMA, so transfers run in PIO | register read on the phone; device tree `/arm-io/sdio` |
| Clock gate | PMGR gate `0x24` (`0xbf1010a0`); the host reads zeros while it is off | openiBoot `plat-a4/sdio.h`, phone |
| Chip power | PMU GPIO 8 (register `0x58`): bit 1 high, `0x09` → `0x0b`. iOS sets it in `gpio-activate-defaults`; without it the chip never answers CMD5 | device tree `/arm-io/i2c0/pmu`, phone |
| WL_REG_ON | GPIO 6 (`function-device_reset`): low 12 ms, high, then 150 ms before CMD5 | device tree, openiBoot |
| Chip | SDIO `02d0:4329`, functions 1–3 | phone enumeration |
| Firmware | iOS 7.1.2 `/usr/share/firmware/wifi/4329b1/bachelor.bin` (4.221.54.30, `n90-keepalive` build) as `brcmfmac4329-sdio.bin`, `bachelor-murata.txt` as the NVRAM. Apple's files: kept in `.runtime/phone/private/wifi`, not in Git | IPSW rootfs |

The device tree's `vendor-id` is filled in by iBoot, so the IPSW does not say
whether this phone has the Murata or the USI module. Their NVRAMs differ only
in `boardtype` and `rxpo2g`.

## Driver

`0001-mmc-sdhci-s5l8930.patch` adds `sdhci-s5l8930`, an SDHCI platform glue.
Without a device tree node, `fixed=1` registers the host at its known
address, interrupt, clock gate and WL_REG_ON. Two quirks:

- The BCM4329 CIS has no function 0 FUNCE tuple, so the core computes a 0 Hz
  clock after reading it. The glue runs the bus at `max_mhz` instead
  (default 25).
- The card interrupt is polled by the MMC core every 10 ms unless
  `card_irq=1`. If the A4 host cannot mask the card interrupt, using it
  would storm.

`sdio-probe.c` sends CMD5 by hand to vary power, clock and reset ordering
without the driver.

Build the modules against the lean kernel tree (`e899dceb`); `CONFIG_MODVERSIONS`
is off, so `KBUILD_MODPOST_WARN=1` lets brcmfmac link without a full
`Module.symvers`:

```sh
make -C $SRC O=$BUILD ARCH=arm CROSS_COMPILE=arm-buildroot-linux-gnueabihf- \
  KBUILD_MODPOST_WARN=1 drivers/mmc/host/sdhci-pltfm.ko \
  drivers/mmc/host/sdhci-s5l8930.ko net/wireless/cfg80211.ko \
  lib/crypto/libarc4.ko drivers/net/wireless/broadcom/brcm80211/brcmutil/brcmutil.ko \
  drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
  drivers/net/wireless/broadcom/brcm80211/brcmfmac/wcc/brcmfmac-wcc.ko
```

## Results

1. With the gate, PMU GPIO 8 and WL_REG_ON, the host enumerates the chip:
   SDIO functions 1–3, 4-bit bus at 24 MHz.
2. Loading `libarc4`, `cfg80211`, `brcmutil`, `brcmfmac` and `brcmfmac-wcc`
   on 21 October reset the phone within about 20 s. No log survived. The lean
   kernel has `CONFIG_PANIC_ON_OOPS=y` and boots with `panic=10`, so any oops
   reboots it; that fits the timing. A battery brownout when the radio starts
   is the other candidate: 25 minutes earlier VBAT read about 4.05 V on USB
   with almost no charge current (`kernel/n90-battery`).
3. After that reset openiBoot accepted no kernel upload until a hard reset.

## Next attempt

1. `n90-battery probe`; raise the USB input limit to 500 mA if it is 100 mA.
2. `echo 0 > /proc/sys/kernel/panic_on_oops`, and stream `/proc/kmsg` to the
   laptop over SSH so the last messages survive.
3. Write `0x0b` to PMU `0x58`, then `insmod sdhci-pltfm.ko` and
   `insmod sdhci-s5l8930.ko fixed=1 max_mhz=12` (polled card interrupt).
4. Load the stack one module at a time and read the log between steps.
5. Afterwards write `0x09` back to `0x58`, so a reset does not leave the radio
   powered.
