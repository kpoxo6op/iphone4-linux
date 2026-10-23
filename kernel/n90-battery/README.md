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
charge below 4.1 V, at most every five minutes.

A new cable starts the PMU at 100 mA again (`0x2b = 0x85`). On 22 October,
plugged into a source other than the laptop after an hour on battery, the
phone said Not charging with `ich` at 0, using more than the input allowed;
raising the limit to 500 mA brought `ich` to about 1450 counts with VBUS
6 % lower. `serve` now raises it once per plug-in through `usb-limit`, which
puts the old value back if VBUS sags by more than a tenth. The scales of `ich` and the
other channels are still unknown; the gas gauge (HDQ over UART5) remains the
accurate source of percentage.

## The reader

```sh
make                      # output/battery/n90-battery
n90-battery probe         # supply register, power NVRAM, every ADC channel
n90-battery meter         # the phone's draw on USB (stop serve first)
n90-battery adc 5 400 signed   # average one ADC channel
n90-battery serve         # files under /run/power_supply every 10 s
n90-battery poweroff      # switch the phone off through the PMU
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

## Clock

The PMU counts seconds in `0x4c`–`0x4f` (little-endian) and keeps counting
while the phone is off: +20 in 20.04 s on 22 October. It read 151,235 s
then, so it counts from some PMU reset rather than 1970, and no offset to
the real time turned up among the PMU's registers. The boot pass sets the
phone's time from the laptop and then runs `n90-battery clock save`, which
keeps epoch minus counter in the PMU's general-purpose bytes `0x84`–`0x87`,
marked with `0x5a` in `0x88` (openiBoot names iBoot's use of `0x80`–`0x83`
and `0x8f`; iBoot records the boot voltage in `0x8d`–`0x8e`). A boot without
the laptop can then run `n90-battery clock load` to set the system time.
The offset lasts as long as the battery keeps the PMU powered.

```sh
n90-battery clock         # pmu counter 151235 s, clock 2026-10-22 01:34:22 UTC, system +0 s
n90-battery clock save    # store the offset from the system time
n90-battery clock load    # set the system time from the PMU
```

## Last stop

The phone keeps nothing across a reboot, but the PMU does: its seconds
counter runs while the phone is off, and its general-purpose bytes keep their
values. `serve` writes a heartbeat to `0x89`–`0x8c` every minute: a state, the
counter in minutes (low 16 bits) and the battery voltage (10 mV steps above
3 V). Since 24 October the heartbeat's state also says what the phone was
doing: `0xb0` plus bit 0 screen on, bit 1 on USB, bit 2 charging, bit 3 hot
(`0xa1`, plain running, from older builds still reads). A planned stop
writes its own state first: `0xa2` low battery, `0xa3` keep restarting after
an oops (`mark oops`), `0xa4` poweroff, `0xa5` a restart on purpose (`mark
reboot`), `0xa6` too hot.

At the next boot the laptop's boot pass runs `n90-battery lastrun` before
`serve` starts. It turns the record into a `last_stop` event in Soy's
journal and marks it reported (`0xa0`), so it is told once. A heartbeat
state still there means the phone stopped without warning: a crash, the
watchdog, a battery that gave out first, or a hard reset, last seen within
a minute of the recorded time, and now with what it was doing: "last stop:
unexpected, last seen 20:37 UTC, 4110 mV; screen on, on USB, charging" (read
back on 24 October from a hand-written `0xb7`). `scene.py journal` prints
it as, for example, "Before the boot at 19:22: was restarted on purpose;
last seen 19:12, 4.17 V".

Those 16 PMU bytes are the only memory on the phone that survives a reset.
On 24 October, markers written across the 128 KiB that the device tree
reserves for ramoops (`0x0ffe0000`) read zero after a reboot: the phone
waits in DFU mode for minutes while the laptop boots it, and nothing
refreshes its RAM then. So after a stop the laptop's boot pass writes a
crash report from what the follower last copied (the kernel log, keep's log
and the journal up to a minute past the last heartbeat) to
`.runtime/phone/private/crashes/`; a stop that was planned gets none.

On 22 October the record survived a restart, DFU mode and the laptop's boot
unchanged; iBoot's boot-voltage bytes beside it (`0x8d`–`0x8e`) changed.
iBoot names `0x80`–`0x83`, `0x8d`–`0x8f`; the clock offset uses
`0x84`–`0x88`; `0x89`–`0x8c` read zero before.

## Charging and heat

Nothing watched the battery's temperature, and charging a lithium cell above
45 °C or below 0 °C wears it; a worn cell also heats more as it charges.

`serve` now reads the PMU's temperature channels every 10 s: tbat (2) and
tdev1-4 (11-14), which the N90 device tree places at the SIM, the RF power
amp, the camera and the A4 ("H3P proximity"). Each reads lower as it warms.
On 24 October two busy processes for three minutes took tdev4 from 568 to
484 counts, the camera's from 565 to 516, and tbat from 712 to 705, and they
recovered as the phone cooled.

The scale is an assumption, not documentation: 50 µA into a 10 kΩ NTC
(B 3435 K), read against 2.5 V, as Dialog's other PMUs measure TBAT. It puts
the idle phone on its charger at 28-34 °C, which is plausible, while a scale
off by half or double would read near 13 °C or 46 °C. Read the temperatures
as estimates within about 5 °C. They are in
`/run/power_supply/battery/temp` (tenths of a degree, with `temp_source`
`estimate`) and `/run/thermal/{sim,rf,camera,soc}`, and Soy shows
`{{battery.temp}}` and `{{phone.temp}}`.

| Battery | Charging |
| --- | --- |
| below 40 °C | normal: 500 mA in |
| 40-45 °C | gentle: 300 mA in, about 100 mA of it into the battery |
| 45 °C and above, or 0 °C and below | held: the USB input limit drops to 100 mA, below what the phone uses, until it is back under 40 °C (or over 3 °C) |

`charge_hold` (`warm`, `hot` or `cold`) and Soy's `{{battery.state}}` say
which; each change goes in the journal. The low-battery rescue does not
override a hold. Without frequency scaling on this kernel, heat cannot slow
the A4 down; at 70 °C on the A4's sensor or 50 °C in the battery the phone
creates `/run/thermal/hot` and sheds optional work (`n90-story` waits), and
at 90 °C or 60 °C for 30 s it notes the reason and switches itself off
(stop state `0xa6`).

On the phone, with the hold threshold lowered to 28 °C for the test
(`N90_CHARGE_HOT`), the battery at 29.2 °C held charging: the limit went
from 500 to 100 mA and `status` read Not charging; with the normal
thresholds back, charging and the 500 mA limit returned within 20 s. The
heat shutdown has not been triggered on purpose.

## Low battery

Three readings in a row (30 s) under 3.45 V, about 2 % on the open-circuit
curve, make `serve` switch the phone off before the battery browns it out:
it notes the shutdown in Soy's journal, waits 20 s so the laptop's follower
can copy the logs if it can reach the phone, and calls the power-off unless
the battery is charging again by then. Power then starts the phone into DFU
mode, where the laptop boots it.

Until 23 October this only happened on battery. On 22-23 October a USB input
limit left at 100 mA, less than the phone uses, ran the battery flat while
plugged in (unexpected stop at 07:49 NZDT, at or below 3.0 V). Now a USB
source that is not charging the battery counts too, and before that, below
3.6 V on USB without charging, `serve` asks for 500 mA again and restarts
the charger, at most every five minutes.

`poweroff` is openiBoot's `pmu_poweroff()` for the A4: mask the wake events
in `0x0c`–`0x11`, drive the PMU GPIO outputs low, set `0x12` (OOCSHDWN).
Neither the threshold nor the power-off has run on the phone yet.

## Power draw

While the charger is held at its input limit, the charge current is that
limit minus what the phone uses, so `ich` doubles as a meter. On 22
October, charging on a USB charger with the display blanked, `ich` read
409, 913 and 1356 counts at 300, 400 and 500 mA: about 4.7 counts per mA
(4.4 to 5.0 between steps), and the phone drawing about 210 mA (194 to 219)
whatever the limit. At 500 mA, 20 s per step, noise about ±6 mA:

| Change | Draw |
|---|---|
| Display blanked, idle (Wi-Fi, Tailscale, the laptop's follower) | about 210 mA |
| Display on, idle (backlight at 1696) | +48 mA |
| Processor fully busy (`yes`) | +34 mA |
| Wi-Fi power saving off instead of on (`n90-wifi power`) | no change |

On battery the same day, display blanked for 44 of 46 minutes, the voltage
fell from 3994 to 3809 mV, 84 to 52 % on the open-circuit curve: about
41 % an hour, roughly 2.5 hours from full. With about 210 mA that puts the
battery near 0.5 Ah against 1.42 Ah new, an estimate until the gauge
reports its capacity. The processor's own work is a small part of the draw;
most of it is hardware that stays powered at full speed: no processor clock
or voltage scaling, the display pipeline and panel still running while
blanked, and possibly other peripherals or the modem.

### Measuring without an ammeter, 23 October

`n90-battery meter` lowers the USB input limit a step at a time until the
charger stops: the draw lies between the last limit that still charged and
the first that did not, and the charge current at the last step narrows it.
Below 200 mA the limit moves in 10 mA steps, above it in 50 mA steps. It needs
USB power, stops nothing but the charge, puts the limit back afterwards (also
on SIGINT, SIGTERM and SIGHUP), and must not run beside `serve`, which shares
the PMU's ADC. `meter 300` instead holds one limit and averages the charge
current; near a full battery the charger tapers and that reading drifts, so
the stepping meter is the one to trust. `n90-battery adc 5 400 signed`
averages the battery-current channel (`ibat`), which reads as a signed
12-bit value, positive while the battery discharges, about one count per mA
(105 counts across a 100 mA step of the input limit), and noisy enough to
need hundreds of readings.

With these, the screen blanked, on the laptop's USB:

| Change | Result |
|---|---|
| Baseline | charging stopped between 200 and 250 mA in five runs (estimates 182-227 mA) |
| Display controller's scanout stopped | stopped between 150 and 180 mA in two of three runs; battery current at a 50 mA limit 87 counts against 120, about 30 mA less |
| Wi-Fi interface down | 188 against 206 mA |
| Touch driver stopped, then touch power (LDO 12) off | no change |
| TV-out and camera supplies (LDOs 2 and 10) off | 177 against 178 mA at a fixed limit |
| Scanout and the DSI high-speed clock off | 175 mA, not clearly below scanout alone |

The scanout result is now in Soy: it stops the CLCD while blanked
([idle display](../../docs/soy/idle-display.md#display-scanout)). Neither
the LDOs nor touch power are worth switching. The absolute numbers carry the
meter's uncertainty: the input limit's real current and the `ich` scale are
inferred, not calibrated against an instrument. They also do not settle the
battery's capacity. Running flat in about twelve hours behind a 100 mA limit
fits a 0.5 Ah battery with a 140 mA draw as well as a 1.3 Ah battery with
210 mA, so the earlier "worn to a third" estimate is not established.

## Next

1. Gas gauge: HDQ over UART5 for the real percentage, current and capacity,
   and the answer on whether the battery is worn.
2. A timed run on battery with the screen off, now that scanout stops.
3. What else stays powered: the A4 at a fixed 800 MHz with no voltage
   scaling, the panel itself (only the backlight goes off), USB while
   plugged in. Register experiments belong on the laptop's USB, where a hang
   recovers without a button.
