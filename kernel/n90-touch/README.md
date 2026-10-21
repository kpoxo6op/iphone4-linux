# N90 touch controller bring-up

Work in progress, 21–22 October 2026. Nothing here gives finger input yet.

## Wiring (Apple's N90 device tree, iOS 7.1.2)

| Function | Where |
|---|---|
| Bus | SPI1, `0x82100000`, VIC IRQ 30, clock gate on at boot |
| Chip select | GPIO 49 (port 6 pin 1), also `enable_cs` |
| Reset | GPIO 20 (port 2 pin 4), active low, released as high-Z |
| Attention (ATN) | GPIO 21 (port 2 pin 5), active low, level |
| Power | PMU LDO12: register `0x16` bit 1. Off at boot. |
| Clock enable | PMU GPIO 0 (register `0x50`), already high after openiBoot |

Apple's GPIO function arguments encode a pin as `[bit, port]`, so pin =
port × 8 + bit. The I2C pins 75/76 already in the backlight DTS confirm this.

## A4 SPI controller

Same register layout as openiBoot `plat-a4/spi.c` and close to Linux
`spi-apple.c`: CTRL `0x00`, CFG `0x04`, STATUS `0x08`, PIN `0x0c`, TXDATA
`0x10`, RXDATA `0x20`, CLKDIV `0x30`, RXCNT `0x34`, TXCNT `0x4c`. The window
repeats every `0x100`. STATUS bits 6–10 hold the TX FIFO level and 11–15 the
RX level. The block only shifts while CTRL.RUN is set: words written to an
idle block are dropped. The divider base is 24 MHz (an 83 kHz transfer of 20
bytes takes 2.1 ms on the phone).

## Controller

The iOS kext personality for `multi-touch,n90` is `AppleMultitouchN1SPI`
(not the iPhone 3G Z2 class). `0x10008ffc` reads `0x4e3101a7` ("N1", rev
`0x01a7`). Firmware is `Constructed Firmware` from
`/usr/share/firmware/multitouch/N90.mtprops` (key `N1F55,1`, version
`0x0098`): one HBPP data packet loading 57,864 bytes at address 0. It is
Apple's file, kept private under `.runtime/phone/private/touch/`.

From the iOS 7.1.2 kernelcache (`AppleMultitouchSPI` 250.16.5):

1. Power-on: enable CS and clock, REQ_WAKEUP (`19 c1`) + 10 ms, a dummy HBPP
   transfer so SCLK idles high, release reset as high-Z, wait 15 ms.
2. Upload the constructed firmware, expect HBPP ack `0x4bc1`.
3. Prox and multi-touch calibration (`multi-touch-calibration` from the
   device tree, upload at `0x400200`). iOS skips it when absent.
4. `MTSPIBootloader_N1::performCalibSeq`: write `0x1000300c=0x16e4`,
   `0x1000305c=0x20`, `0x10003058=6`, `0x10003000=3`, read `0x10003800`,
   send `1f 01`, wait 65 ms, ATN ack.
5. EXECUTE (`1d 53`, address `0x10001800`, value 1), wait 40 ms.
6. Before talking to running firmware after 100 ms idle: `ee` wake frame.

## Status, 22 October 2026

The controller runs Apple's firmware on the phone. The missing piece was the
clock: PMU GPIO 0 must read `0x53`. openiBoot leaves it at `0x13`, which keeps
the bootloader talking but never starts the controller's CPU (its data RAM
stays untouched after EXECUTE). With `0x53` the CPU zeroes its BSS, raises
ATN after calibration, and answers reports:

| Report | Value |
|---|---|
| Interface version | 1, max packet 660 bytes |
| Family ID (`0xd1`) | `0x55` |
| Sensor (`0xd3`) | 15 rows × 10 columns, bcdVersion `0x98` |
| Surface (`0xd9`) | 5000 × 7500 (0.01 mm: 50 × 75 mm) |

The bus runs at 8 MHz with 5/10 µs CS delays once the firmware is up
(Apple's node: 124 ns SCLK). The bootloader stage keeps openiBoot's 83 kHz
and 4.5 MHz.

`n90-touch serve` publishes touches through uinput as "Apple N1 multitouch
(iPhone 4)" (bus SPI, Type B slots, 640 × 960, `INPUT_PROP_DIRECT`), which Soy
counts as a physical input. It polls ATN every 1 ms during a gesture and 4 ms
when idle (under 1% CPU). Not yet verified: frames from an actual finger,
the finger-state values (Touch Bar Z2 uses 3 = start, 4 = move), and the axis
orientation (Y is flipped like openiBoot; `Z2_FLIP_X`, `Z2_FLIP_Y`, `Z2_SWAP`
override). `Z2_RAW=n` logs the first n raw frames to stderr.

No factory calibration is loaded: this phone keeps MtCl in NAND syscfg and
iOS proceeds without it too.

## Running it

```sh
make                                   # output/touch/n90-touch
./extract_firmware.py <iPhone3,1_7.1.2_11D257_Restore.ipsw> \
    ../../.runtime/phone/private/touch/n90-z2-0x0098.bin
./deploy.py --ssh-config ../../.runtime/phone/private/ssh_config \
    --binary ../../output/touch/n90-touch \
    --firmware ../../.runtime/phone/private/touch/n90-z2-0x0098.bin \
    --uinput-ko ../../output/touch/uinput.ko
```

`harness/phone_boot.py` runs the same deploy after Soy on every boot. The
backlight kernel built uinput as a module; `CONFIG_INPUT_UINPUT=y` is now in
the config fragment, and until the next kernel build the matching
`uinput.ko` (built from the same tree, kernel `497fa0e4`) is copied over.
