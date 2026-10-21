# N90 battery and charger readings

Work in progress, 22 October 2026. `n90-battery` has not run on the phone yet.

## What the phone has

| Part | Where | Source |
|---|---|---|
| PMU | Dialog D1815, I2C0 `0x74` (`pmu,d1815`) | N90 device tree, iOS 7.1.2 |
| Gas gauge | TI bq27540 on HDQ through UART5 (`/arm-io/uart5/gas-gauge`), enabled by PMU GPIO 5 (`function-battery_swi`) | N90 device tree |
| External power | PMU register `0x07`: `0x08` USB, `0x10` FireWire | openiBoot `plat-a4/pmu.c` |
| ADC | mux `0x30`: the channel plus `0x10` starts a conversion (channel 3 needs `0x20` and 80 ms first); done flag `0x20` in `0x02`; 12-bit result from `0x32` (high byte) and the low nibble of `0x31` | openiBoot `query_adc()` |
| ADC channels | 0 vcc_main, 1 ich, 2 tbat, 4 vbat, 5 ibat, 7 adc_in7 (thermistor), 11–14 tdev1–4, 15 vbus; 6 is the USB charger D+/D− divider | AppleD1815PMU sensor table in the iOS 7.1.2 kernelcache; openiBoot for 6 |

| USB input current limit | register `0x2b`: bits 0–4 a code (5 = 100 mA, 21 = 500 mA, up to 2000 mA), bit 7 set when software chose it | AppleD1815PMUPowerSource, iOS 7.1.2 kernelcache `0x8098bc80` (code to mA) and `0x8098ddfe` (write) |

openiBoot's `pmu_voltage` reads `0x8e:0x8d` as millivolts. Those registers
sit in the power-NVRAM range (`0x80`–`0x8f`, iBoot's own state), so they are
probably not a live measurement; `probe` prints them for comparison.

One reading exists, from 21 October 2026 on USB power (`0x07 = 0x4b`):
vcc_main 3741, ich 6, tbat 736, vbat 3171, vbus 3769, tdev 611–694 counts, and
`0x8e:0x8d` = 4062. If VBAT uses Dialog's usual 2.5–4.5 V range,
`2500 + counts × 2000 / 4096` gives 4048 mV, within 14 mV of iBoot's
record. That is an inference until a second reading confirms it. An `ich` of
6 counts on USB suggests the battery was not charging, which fits a 100 mA
input limit. The register that says whether the charger is actually
charging is still unknown. The gas gauge is the accurate
source of percentage; reading it means implementing HDQ timing on UART5.

## The reader

```sh
make                      # output/battery/n90-battery
n90-battery probe         # supply register, power NVRAM, every ADC channel
n90-battery serve         # files under /run/power_supply every 10 s
```

`serve` writes power_supply-style files, which Soy reads like a kernel
power_supply: `usb/online`, `battery/status`, and the raw `vbat_counts` and
`ich_counts`. Once `probe` has been matched against known voltages, set
`N90_VBAT_UV_PER_COUNT` (and `N90_VBAT_OFFSET_UV`) to publish
`voltage_now` plus `capacity` estimated from a typical Li-ion open-circuit
curve, marked `capacity_source: voltage`; Soy then shows `~71%`. Set
`N90_ICH_CHARGING_COUNTS` to tell charging from merely powered. Without
calibration it never writes a voltage, percentage or charge state.

Reads use one combined I2C transfer, so the backlight driver and
`n90-touch` cannot move the PMU register pointer in between.

## Next on the phone

1. `probe` on USB power and on battery; confirm the VBAT scale and check that
   `0x07` follows the cable.
2. Read `0x2b`. If it is 100 mA, `usb-limit 500` (what iOS allows a USB
   host) and watch `ich` and `vbat` rise if the battery charges.
3. Start `serve` from `harness/phone_boot.py` after the touch driver, with
   the confirmed scale.
4. Gas gauge: HDQ over UART5 for the real percentage.
