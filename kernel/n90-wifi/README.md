# N90 Wi-Fi (BCM4329 on SDIO)

The phone scans and joins 2.4 GHz WPA2 networks under Linux (22 October
2026). Joining has been exercised up to the firmware's handshake offload;
see Status.

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

## Pieces

| File | What it is |
|---|---|
| `0001-mmc-sdhci-s5l8930.patch` | SDHCI glue for the A4 SDIO host (`sdhci-s5l8930`) |
| `0002-brcmfmac-sdio-probe-error-path.patch` | brcmfmac freed the bus twice when the probe failed (oops) |
| `0003-brcmfmac-old-firmware.patch` | Lets brcmfmac run Apple's 2013 firmware |
| `0004-brcmfmac-n90-diagnostics.patch` | Optional: `n90_debug`, `n90_trace`, `n90_fwerr` bring-up logging |
| `n90-wifi.c` | `scan`, `connect`, `join`, `link` over nl80211, without libnl or wpa_supplicant |
| `wifi-keep.sh` | `/usr/sbin/n90-wifi-keep`: loads the driver once per boot, joins known networks, holds a DHCP lease |
| `sdio-probe.c` | Sends CMD5 by hand, for power and reset experiments without the driver |

`harness/phone_boot.py` installs all of it on every boot (`deploy_wifi`):
the modules from `output/wifi/`, Apple's firmware and NVRAM, the tool, the
keeper, and the known networks. keep (`kernel/n90-keep`) starts the keeper
and restarts it if it stops. The keeper leaves the radio off until there is
a known network.

## Known networks

Boris keeps `SSID<TAB>password` lines in
`.runtime/phone/private/wifi/networks` on the laptop, out of Git. The boot
pass derives each network's WPA2 key (PBKDF2-SHA1, 4096 rounds, the SSID as
salt) and sends only that to `/run/wifi/networks` on the phone. The firmware
does the four-way handshake itself (brcmfmac reports
`NL80211_EXT_FEATURE_4WAY_HANDSHAKE_STA_PSK`), so the phone needs no
supplicant. The chip only does 2.4 GHz: a Pixel hotspot needs Extend
compatibility on, with WPA2 or WPA2/WPA3 security.

Apple's NVRAM has no `macaddr`; iOS adds the phone's own from syscfg.
Without one the firmware stops with `Failed to init wireless side, err: 21`.
The boot pass appends a fixed, locally administered address kept in
`.runtime/phone/private/wifi/macaddr`.

## What it took

Each step was found on the phone with the diagnostics patch.

1. **Byte-mode CMD53.** The CIS has no FUNCE tuples, so byte-mode transfers
   came out 0 bytes long. The glue sets `MMC_QUIRK_BLKSZ_FOR_BYTE_MODE`.
2. **A word late after a failed read.** The BCM4329 answers reads of
   chipcommon registers it lacks (`capabilities_ext`, `0x180000ac`) with a
   bad CRC. The A4 host keeps that block in its buffer through an SDHCI data
   reset, so every later PIO read returned the word before. brcmfmac then
   read `pmucapabilities` as `pmucontrol` and wrote it back, which stopped
   the chip's backplane; the firmware upload hung on its first block. The
   glue drains the stale words after the reset.
3. **Clean retries.** Only a reset of the whole block clears that state:
   bit 31 of its PMGR gate (`0xbf1010a0`, openiBoot `clock_gate_reset`). The
   glue pulses it at probe, so a reload no longer needs a phone restart.
4. **Card interrupts.** With the host's SDIO interrupt off, sdhci's
   `MMC_CAP2_SDIO_IRQ_NOTHREAD` also left the MMC core without its polling
   thread, so brcmfmac never heard the firmware. The glue clears it and the
   core polls every 10 ms.
5. **Old firmware.** 4.221.54.30 rejects the scan dwell-time ioctls and
   frame bursting, lacks `per_chan_info`, and reports scan results as
   `wl_bss_info` version 108 (109 without the trailing SNR). brcmfmac treated
   each of these as fatal.

## Status

| Check | Result (22 October) |
|---|---|
| Firmware download | Under a second, then `wl0: Broadcom BCM4329 802.11 Wireless Controller 4.221.54.30` |
| `wlan0` | Up; `n90-wifi features`: `psk_offload yes` |
| Scan | 6 networks on channels 1, 6, 11, strongest at -36 dBm |
| Join and DHCP | Waiting for a network's password |
| Repeated loads | Clean after the block reset |

Still open: the bus runs at 12 MHz, one block per transfer
(`single_block=1`); multi-block transfers and 25 MHz are untested. Once, on
22 October, a failed driver start took the phone off USB until a hard reset;
the failure itself is fixed, the cause of the USB loss is not known.

## Building

Apply the patches to the lean kernel tree (`e899dceb`) and build the modules;
`CONFIG_MODVERSIONS` is off, so `KBUILD_MODPOST_WARN=1` lets brcmfmac link
without a full `Module.symvers`. Then copy them to `output/wifi/`:

```sh
make -C $SRC O=$BUILD ARCH=arm CROSS_COMPILE=arm-buildroot-linux-gnueabihf- \
  KBUILD_MODPOST_WARN=1 drivers/mmc/host/sdhci-pltfm.ko \
  drivers/mmc/host/sdhci-s5l8930.ko net/wireless/cfg80211.ko \
  lib/crypto/libarc4.ko drivers/net/wireless/broadcom/brcm80211/brcmutil/brcmutil.ko \
  drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
  drivers/net/wireless/broadcom/brcm80211/brcmfmac/wcc/brcmfmac-wcc.ko
make -C kernel/n90-wifi    # output/wifi/n90-wifi
```
