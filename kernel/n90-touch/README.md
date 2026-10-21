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

## Status

`z2probe.c` (userspace, `/dev/mem` + `/dev/i2c-0`) performs steps 1–5 on the
phone. All register writes and the firmware upload are acknowledged, and the
image reads back correctly. The controller's CPU never starts: its data RAM
(`0x400000`–`0x410000`, stack top `0x410000`) is untouched after EXECUTE and
the bus keeps answering with HBPP status words (`0x4879` idle, `0x4f81` for
firmware commands). Leading suspects: missing factory calibration (MtCl lives
in NAND syscfg on this phone; there is no SPI NOR), or a reference clock the
FLL (`0x1000300c`) needs.

```sh
arm-buildroot-linux-gnueabihf-gcc -O2 -Wall -static -o z2probe z2probe.c
z2probe power 1
z2probe seq n90-z2.bin R0x404d40 1aa1 w300 R0x404d40   # CPU-run check
```
