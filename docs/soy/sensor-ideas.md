# Sensor and device ideas

Brainstorm, 22 October 2026. Nothing here is built. Each idea says how
feasible it is, what evidence that rests on, and the first step. Every
idea stays inside the [Soy rules](design.md#permanent-ui-rules): text
first, one purpose per scene, honest empty states, 60 fps while moving.

## How we pushed the ideas

Boris asked us to apply Felix Rieseberg's
[How to be more ambitious](https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/)
to this brainstorm. Its four kinds of ambition, applied:

- **Altitude: the goal beyond the goal.** The ask is "use the sensors".
  The aim behind it is a phone that understands its situation, so that
  AI shows the right scene before anyone asks. That makes the first
  deliverable a shared sense layer that AI can read and write scenes
  from, not a separate demo for each driver. Each sensor added later
  makes every scene smarter.
- **Depth: work like the best in the field.** Use datasheet registers
  and real calibration rather than "it prints numbers". Every sensor gets
  an outside judge: gravity measures 1 g, the compass agrees with the
  Pixel's, lux agrees with the Pixel's light sensor, and a Wi-Fi position
  agrees with the Pixel's GPS. Set hard goals and treat them as
  reasonable: tilt scrolling with zero missed frames, and less than
  100 ms from picking the phone up to a lit, legible screen.
- **Range: verbs instead of nouns.** "Camera, GPS, Wi-Fi" become
  *notice, orient, locate, remember, signal, listen, see*. Each verb
  borrows methods from a field: a naturalist's field notebook (a daily
  record of what the phone sensed), a cartographer's map of places made
  from radio fingerprints, a typographer's sunlight setting, and an
  instrument maker's gauges.
- **Self-efficacy.** Wi-Fi on this phone looked out of reach on
  20 October. By 22 October it was joining networks. The hard items
  below are rated honestly, but "hard" is not "no".

## What the hardware gives us

Source evidence comes from the repository's phone results. Part numbers
are teardown knowledge that still has to be checked against the iOS N90
device tree before anyone writes a driver.

| Part | Likely chip | Evidence so far |
| --- | --- | --- |
| I2C0 (bit-banged, pins 75/76) | | Works. `i2cdetect` sees `0x0d`, `0x29`, `0x39`, PMU `0x74` ([display-power](../../kernel/n90-display-power/README.md)) |
| Compass | AKM AK8975 (addresses `0x0c`–`0x0f`) | `0x0d` answers on I2C0. Probably this part |
| Light and proximity | TAOS TSL2771-family | `0x39` or `0x29` answers on I2C0. Probably this part |
| Accelerometer | ST LIS331DLH (`0x18`/`0x19`) | Not seen on I2C0, so probably on a second I2C bus |
| Gyroscope | ST L3G4200D (`0x68`/`0x69`) | Not seen on I2C0, so probably on the second bus |
| Ringer switch | GPIO | Already reads `0x210` ([display-power](../../kernel/n90-display-power/README.md)) |
| Vibrator | PMU output or GPIO | Unknown. The device tree should name it |
| Temperatures | PMU ADC `tdev1`–`tdev4`, `tbat` | Channels are known; scales are not ([battery](../../kernel/n90-battery/README.md)) |
| Bluetooth | BCM4329 (shared with Wi-Fi), HCI over a UART | Wi-Fi half works. Needs an A4 UART driver and patch firmware from iOS |
| Audio and microphone | Cirrus Logic codec over I2S | No Linux driver for the codec or the A4 audio path |
| GPS | Broadcom BCM4750 per teardowns | Proprietary protocol, no open driver. Wiring to the A4 or the baseband unconfirmed |
| Cameras | 5 MP rear, VGA front, through Apple's ISP | Undocumented ISP. The hardest item on this list |

Linux already has drivers for the AK8975, the TSL2771 family, the
LIS331DLH and the L3G4200D. For the four motion and light parts, the work
is mostly bus and device tree, not new drivers.

## Ranked ideas

Ranked by usefulness, beauty, how much AI it unlocks, and feasibility,
in that order of weight.

### 1. The sense layer, and AI that reads it

**What.** One small service publishes every reading as plain files under
`/run/sense/`, in the same style `n90-battery` uses for
`/run/power_supply`. That covers motion, heading, lux, proximity,
ringer, temperatures, Wi-Fi surroundings and later location. Scenes bind
to these with `{{sense.*}}` the way they bind to battery today. The
development host keeps a short rolling copy so AI can see what the phone
is experiencing and write scenes for it.

**Why.** This is the altitude move. Every later idea becomes a scene
plus a rule, not a new subsystem. AI stops guessing the context and
starts reading it.

**Feasibility.** High. It is ordinary userspace on top of the working
I2C and the existing binding mechanism ([scenes](scenes.md)).

**First step.** Write the `/run/sense/` file contract and the
`{{sense.*}}` binding with ringer and PMU temperatures only. Both are
already readable, so there is no driver work.

### 2. Ringer switch as the one real switch

**What.** The side switch becomes the phone's mode: *open* for normal
scenes, *quiet* for one calm scene (the time, a single note, nothing
live, backlight at its minimum). AI decides what "quiet" shows for Boris
and can change it.

**Why.** A physical, eyes-free control that already exists and needs no
new UI. It is a beautiful match for a text-first phone.

**Feasibility.** Very high. The GPIO already reads.

**First step.** Add the ringer pin to `gpio-keys-polled` as a switch
event, publish `sense/ringer`, and give one scene a quiet variant.

### 3. Light-aware type

**What.** The ambient light sensor drives the backlight and a sunlight
setting. In bright light, body text goes bold and pure white, secondary
grey brightens, and amber and cyan go up a step. At night, the screen
dims to the lowest legible level and drops the green.

**Why.** The aged panel is hard to read outdoors, and
[foundations](foundations.md#contrast-is-measurable-taste-is-not-a-passing-test)
already says contrast numbers ignore sunlight. This makes the phone
measure it.

**Feasibility.** High, if `0x39` or `0x29` is the TSL2771. The Linux
`tsl2772` IIO driver covers that family.

**First step.** Read the ID register at both addresses, and match the
nodes in the iOS device tree under `/arm-io/i2c0`.

**Judge.** Lux agrees with the Pixel's light sensor within the datasheet
tolerance across indoor, shade and sun.

### 4. Pick up, put down, pocket

**What.** Face down on the table turns the screen off. In a pocket
(proximity covered plus darkness) it stays off and touch is ignored.
Lifting the phone wakes it straight to the scene you left, before your
thumb reaches the glass.

**Why.** It saves battery, it stops accidental pocket swipes, and it
feels magical while staying quiet.

**Feasibility.** Medium-high. Proximity is probably on I2C0 already. The
accelerometer is probably on a second I2C bus that needs its pins from
the device tree.

**First step.** Find the second I2C bus and its pins in the N90 device
tree, then add an `i2c-gpio` node for it the same way the first was
added.

**Judge.** Less than 100 ms from lift to lit screen, measured on the
phone's journal. Zero false wakes over a night face down.

### 5. Places without GPS

**What.** Wi-Fi scans become a fingerprint of where the phone is. AI
learns and names places from them ("Home", "Office", "Car on the
hotspot") and shows the scene that fits each place. A second scene, the
*radio weather*, draws nearby networks as a text spectrum by channel with
signal strength and its history.

**Why.** It gives location context today, privately, with hardware
that already works. It is useful and beautiful as text.

**Feasibility.** High. The BCM4329 scans and joins. Fingerprints stay on
the phone and host. An optional lookup through
[BeaconDB](https://beacondb.net) would send nearby network IDs to a
third party, so it stays off unless Boris turns it on.

**First step.** Log `iw scan` results every minute into
`/run/sense/wifi` for a day, then cluster them.

**Judge.** Place labels agree with the Pixel's GPS.

### 6. Tilt reading and landscape

**What.** Tilting the phone gently scrolls a long post, like a book on a
lectern, and stops with a flat hand. Turning the phone sideways reflows
the scene into a 960-wide reading column.

**Why.** It allows one-handed reading with no thumb, and pairs with the
volume-button paging.

**Feasibility.** Medium. It needs the accelerometer (idea 4), and the
renderer's layout must handle a second orientation at 60 fps.

**First step.** After idea 4, record accelerometer noise at rest and
choose a dead zone from it. Prototype tilt-scroll behind the existing
scroll path.

**Judge.** Zero missed frames in the acceptance workload while tilting.

### 7. Compass and the way home

**What.** A text compass rose with a large heading number, plus an arrow
and distance to a place Boris chooses (home, Platt, a friend). The place
comes from idea 5 or 11.

**Why.** It is a calm, beautiful instrument, and it is honest about
accuracy because the scene shows the calibration state.

**Feasibility.** Medium-high. `0x0d` is probably the AK8975, which has a
Linux IIO driver. Tilt compensation needs the accelerometer.

**First step.** Read the AK8975 `WIA` register at `0x0d`. It should
return `0x48`.

**Judge.** Heading agrees with the Pixel's compass within 5°, after a
figure-eight calibration.

### 8. A haptic grammar

**What.** The vibrator speaks a small vocabulary that AI can use: a tick
when a page settles, two soft pulses for "a scene changed", and a long
pulse for a real fault. Scenes can ask for a pattern, but never for
decoration.

**Why.** It gives feedback without looking or making sound.

**Feasibility.** Medium-high, once the drive is found. It is probably a
PMU output or a GPIO.

**First step.** Search the iOS device tree and the AppleD1815PMU driver
for the vibrator function and its register or pin.

### 9. Bluetooth keyboard, and who is around

**What.** A Bluetooth keyboard turns the phone into a pocket terminal
and a way to type requests to AI. A BLE scan scene lists what is nearby
in plain words: headphones, a watch, beacons, and how near each is.

**Why.** Real text input makes "fully AI-driven" interactive on the
device itself.

**Feasibility.** Medium. The BCM4329's Bluetooth half sits on a UART.
That needs an A4 UART driver (the gas gauge on UART5 needs one too, so
the work is shared), `hci_uart` with Broadcom patch firmware extracted
from iOS and not redistributed, and the reset and wake GPIOs from the
device tree.

**First step.** Find the Bluetooth UART, its pins and its firmware file
in the iOS device tree and root filesystem.

### 10. Say what you want to see

**What.** Hold a volume button and speak. The audio goes to the host,
is transcribed there, and AI builds or changes the scene. This is the
purest form of "AI draws SoyOS".

**Why.** It has the most value of anything on this list.

**Feasibility.** Low for the built-in microphone. It needs the A4 audio
path (I2S and DMA) and a codec driver Linux lacks. A Bluetooth headset
would be the bridge once idea 9 works.

**First step.** Identify the codec's part number and I2C address from
the device tree. Check whether any of `0x0d`, `0x29` or `0x39` is the
codec rather than a sensor.

### 11. Real location

**What.** A *where am I* scene: a large place name, coordinates, and the
age of the fix.

**Feasibility.** Low for the built-in GPS. Teardowns list a Broadcom
BCM4750. Its protocol is proprietary, Linux has no driver, and whether
it hangs off the A4 or the baseband is unconfirmed. Two honest bridges
exist today. Wi-Fi places (idea 5). And the Pixel, which is already the
hotspot, can publish its own GPS fix to the phone over Tailscale (for
example, a Termux job). The scene must then say "Pixel's location", not
pretend the iPhone found it.

**First step.** Confirm the GPS chip's bus in the device tree. In
parallel, have the Pixel send its fix to the host once a minute.

### 12. An eye made of text

**What.** The camera image is rendered as characters on the screen: a
live text viewfinder. AI can describe what the phone sees, read a sign,
or keep a picture log in the field notebook.

**Why.** It is the most beautiful thing on this list, and the most
SoyOS.

**Feasibility.** Very low for now. The sensors sit behind Apple's
undocumented ISP, with no Linux support. Scoping it means reading the
iOS camera drivers. This is a moonshot to keep in view, not to schedule.

**First step.** List the camera and ISP nodes in the device tree and
the iOS drivers that own them, and estimate the reverse-engineering cost
from that.

## The field notebook (ties it together)

Once ideas 1 to 5 exist, AI writes one scene each evening: where the
phone went (by place name), how bright it was, how long it sat face down,
the battery's day, and anything unusual it noticed. It is plain prose at
reading size, made only from observed data, with honest gaps. It turns
sensors into something Boris would actually read.

## Suggested order

1. Sense layer with ringer and temperatures (ideas 1 and 2). No new
   drivers.
2. Name the I2C0 devices from the device tree, then light (3) and
   compass (7).
3. Second I2C bus, then accelerometer: pick-up and pocket (4), and tilt
   (6).
4. Wi-Fi places (5) and the field notebook.
5. Vibrator (8). Then the UART work for Bluetooth (9), which unlocks
   voice by headset (10).
6. GPS and cameras stay research until the device tree says otherwise.

Steps 2 and 3 need someone to drive the phone. Only one thread does
that at a time.
