# Starting evidence

Snapshot: 2026-10-19. These are starting points, not proofs of a working phone.

- [N90 kernel](https://github.com/archeYR/linux/tree/8e79d535d2068ae9b9475d2e6850a6edd67fad5b):
  Linux 6.17-rc1; s5l8930_defconfig; arch/arm/boot/dts/samsung/s5l8930-apple-n90.dts.
  Prior initial-support commit describes framebuffer and USB working, with UART
  probing but untested. This project has not reproduced that phone result.
- [openiBoot A4](https://github.com/iDroid-Project/openiBoot/tree/master/plat-a4):
  SDIO, SPI, I2C, PMU and NAND references. Pin a revision before deriving code.
  A4 NAND writes are explicitly unsafe in upstream documentation.
- [Earlier touchscreen reference](https://github.com/iDroid-Project/openiBoot/blob/master/plat-s5l8900/multitouch-z2.c):
  earlier-generation source, not a drop-in iPhone 4 driver.
- [iPhone 4 teardown](https://www.ifixit.com/Teardown/iPhone+4+Teardown/3130):
  BCM4329 Wi-Fi and TI touch hardware identification.
- [brcmfmac documentation](https://wireless.docs.kernel.org/en/latest/en/users/drivers/brcm80211.html):
  BCM4329 SDIO support still needs a functioning SDIO host, power/reset,
  firmware and board-specific NVRAM.
- [Buildroot 2026.08](https://buildroot.org/downloads/buildroot-2026.08.tar.xz),
  SHA256 87aaca4164ea9d5c8085854953018263f7963f07c22e73a2a2185cc98c581c34.
- Kernel archive URL:
  https://codeload.github.com/archeYR/linux/tar.gz/8e79d535d2068ae9b9475d2e6850a6edd67fad5b
  SHA256 8de3787fbc1db68b07facdbfebe4115d12b2b97bbd2f8009d88f638c118ce57a.

The kernel DT exposes a simple framebuffer, UART, interrupt controllers, timer
and USB. Generic compiled-in MMC/Wi-Fi options do not establish a functioning
iPhone SDIO path. Persistent storage requires more than a generic filesystem:
NAND controller, ECC and flash translation/recovery need independent validation.
