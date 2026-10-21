# N90 battery and charger readings

`n90-battery` runs on every boot (`harness/phone_boot.py`). Since 22 October
2026 it restarts the charger when the PMU's charge timer runs out, and it
publishes the battery voltage and charge state for Soy. The percentage is
still an estimate from the voltage, shown only on battery.

## What the phone has

| Part | Where | Source |
|---|---|---|
| PMU | Dialog D1815, I2C0 `0x74` (`pmu,d1815`) | N90 device tree, iOS 7.1.2 |
| Gas gauge | TI bq27540 on HDQ through UART5 (`/arm-io/uart5/gas-gauge`), enabled by PMU GPIO 5 (`function-battery_swi`) | N90 device tree |
| External power | PMU register `0x07`: `0x08` USB, `0x10` FireWire | openiBoot `plat-a4/pmu.c` |
| ADC | mux `0x30`: the channel plus `0x10` starts a conversion (channel 3 needs `0x20` and 80 ms first); done flag `0x20` in `0x02`; 12-bit result from `0x32` (high byte) and the low nibble of `0x31` | openiBoot `query_adc()` |
| ADC channels | 0 vcc_main, 1 ich, 2 tbat, 4 vbat, 5 ibat, 7 adc_in7 (thermistor), 11–14 tdev1–4, 15 vbus; 6 is the USB charger D+/D− divider | AppleD1815PMU sensor table in the iOS 7.1.2 kernelcache; openiBoot for 6 |
| Charger state | register `0x08` (with `0x07`–`0x0b` read as one status block): bit 5 the charge timer ran out, bit 3 the charge ended; restart by writing `0x2e & 0x08` to `0x2e`, then the old value | AppleD1815PMUPowerSource, kernelcache `0x8098ce18` (status read) and `0x8098cfb0` (restart) |
| USB input current limit | register `0x2b`: bits 0–4 a code (5 = 100 mA, 21 = 500 mA, up to 2000 mA), bit 7 set when software chose it | AppleD1815PMUPowerSource, iOS 7.1.2 kernelcache `0x8098bc80` (code to mA) and `0x8098ddfe` (write) |

openiBoot's `pmu_voltage` reads `0x8e:0x8d` as millivolts. Those registers
sit in the power-NVRAM range (`0x80`–`0x8f`, iBoot's own state), so they are
probably not a live measurement; `probe` prints them for comparison.

## Readings on the phone

| | 21 Oct, on USB | 22 Oct 08:45, on USB, before | after the charger restart |
|---|---|---|---|
| `0x08` | | `0x29` (timeout, end) | `0x05` |
| ich | 6 | 0 | ~1275 |
| vbat | 3171 | 2880 | ~3170 (charging) |
| iBoot's `0x8e:0x8d` | 4062 mV | 3920 mV | |

`2500 + counts × 2000 / 4096` mV puts both VBAT readings 14 mV below
iBoot's own boot-time record, so the scale holds. The USB input limit was
already 500 mA (`0x2b = 0x95`). What stopped charging was the charge timer:
register `0x08` bit 5 set, `ich` at 0, and the battery falling from about
4.05 V to 3.9 V overnight while plugged in. Writing `0x2e & 0x08` to `0x2e`
and then the old value, as AppleD1815PMUPowerSource does
(`0x8098cfb0`), cleared the flags and started a 1275-count charge current
at once. `serve` repeats that five minutes after a timeout, or at the end of a
charge below 4.1 V, at most every five minutes. The scales of `ich` and the
other channels are still unknown; the gas gauge (HDQ over UART5) remains the
accurate source of percentage.

## The reader

```sh
make                      # output/battery/n90-battery
n90-battery probe         # supply register, power NVRAM, every ADC channel
n90-battery serve         # files under /run/power_supply every 10 s
```

`serve` writes power_supply-style files every 10 s, which Soy reads like a
kernel power supply: `usb/online`, `battery/status` (Charging, Not charging,
Full or Discharging), `battery/voltage_now`, the raw `vbat_counts`,
`ich_counts` and `charge_flags`, and on battery `capacity` estimated from a
typical Li-ion open-circuit curve, marked `capacity_source: voltage` (Soy
shows `~71%`). It writes no percentage on USB, where charging lifts the
voltage, and logs each charger restart to `/run/n90-battery.log`.

Reads use one combined I2C transfer, so the backlight driver and
`n90-touch` cannot move the PMU register pointer in between.

## Next

1. Learn the `ich` scale (charge current in mA) and how long a full charge
   takes.
2. Measure drain on battery with the display on and blanked.
3. Gas gauge: HDQ over UART5 for the real percentage.
