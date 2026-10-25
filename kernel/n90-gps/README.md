# N90 GPS investigation

The BCM4750 has **not produced a GPS fix or a valid protocol reply**. These
bounded observation tools are development instruments, not a location service.
They are not installed by the phone's boot path.

## Source evidence

- The N90 iOS 7.1.2 device tree places `gps,bcm4750` under UART4 at
  `0x82900000`, hardware interrupt 26. Reset is GPIO30 and standby GPIO31.
  The UART TX/RTS functions use GPIO66/68. A hardware interrupt number is not
  a Linux IRQ number; a future driver must map it through the VIC domain.
- [openiBoot A4](https://github.com/archeYR/openiBoot/tree/0e6178b235068c29a3289131049467e8ae90124e/plat-a4),
  GPL-3.0-or-later, supplies the UART register layout, clock-gate calculation
  and GPIO encoding. UART4's physical gate is `0xbf1010e0`, not a direct
  multiplication of the device tree's logical clock-gate ID.
- [Motorola's BCM4750 control driver](https://github.com/faux123/kernel-moto-atrix4g/blob/8b51696ef75cf11c6161b69d72a6c234d01e2029/drivers/misc/bcm4750.c),
  GPL-2.0, describes reset and power controls on another board. Its GPIO numbers
  are not applicable to N90.
- Static inspection of the owner's local iOS 7.1.2 `locationd`,
  `AppleEmbeddedGPS`, `AppleS5L8930X` and `libgll.dylib` confirms the separate
  host library, `/dev/tty.gps`, 115200 baud and binary packet initialization.
  `libgll` identifies GPSBCM4750-84. Its measurement engine, acquisition/tracking
  code, position engine and ECPU patch stages are host-side software. An exposed
  UART alone does not make an NMEA receiver.

The original firmware source is
[Apple's N90 11D257 IPSW](https://secure-appldnld.apple.com/iOS7.1/031-4812.20140627.cq6y8/iPhone3,1_7.1.2_11D257_Restore.ipsw).
The encrypted kernel-cache SHA-256 is
`aba2a6a1c9ded4d81ba6a0e02544acbb751a97c7918f30275958992cedabacfb`;
its decompressed result is
`eef6e7b86de691dd7673cfebe569060a9b107707f33a24bc2a6929fcf46d40fd`.
Firmware, decryption material, disassembly and raw experiment payloads stay in
ignored private storage. No Apple/Broadcom firmware is redistributed here.

## Real hardware, 26 October 2026

The running UART already had an enabled gate, 8N1, polling RX/TX, FIFO enabled,
automatic RTS/CTS and divisor 12 on the 24 MHz source (nominal 115200).
Reset was high and standby low. The iOS GPIO-function implementation inverts
its logical argument: `Gps90EnterStandby(1)` means physical standby low;
`Gps90ExitStandby(0)` means high. Reset low/high correspond to physical low/high.

| Experiment | Observation |
|---|---|
| Listen in the existing state, 20 s | 0 bytes |
| Standby high, 20 s | 0 bytes |
| Standby high, reset pulse, 20 s | One `00` byte, framing/break errors |
| Source-derived initial request, 10 s | TX drained; only reset's error byte |
| Legacy autobaud followed by initial request, 10 s | Same result |
| Same sequence with manual asserted RTS, 10 s | Same result |
| Internal UART loopback, 2 s after clearing transition residue | All eight transmitted bytes returned exactly, no UART errors |

The first loopback retained a preceding break byte; its raw result is retained.
The clean loopback resets the FIFOs after changing mode and before transmitting.
It proves the bounded transport's byte path on the real A4, **not the GPS chip,
external pin continuity, actual baud timing, RF clock or satellite reception**.
The three query variants did not yield a valid packet. No arbitrary packet
fuzzing, patch download, baud sweep, phone reboot or CLCD stop was performed.
All changed GPS/UART registers were restored; kernel taint stayed 4096
(out-of-tree sensor adapter, no oops bit).

## Tools and next experiment

Build with the existing ARM toolchain, for example:

```
arm-linux-gcc -O2 -Wall -Wextra -Werror -static uart-listen.c -o uart-listen
arm-linux-gcc -O2 -Wall -Wextra -Werror -static uart-query.c -o uart-query
```

`uart-listen SECONDS PRIVATE-RX` maps registers read-only and consumes RX bytes.
`uart-query SECONDS PRIVATE-TX PRIVATE-RX` accepts at most 256 reviewed bytes,
requires the observed configuration (or its explicit internal-loopback/manual
RTS variants), bounds execution to 1–60 seconds and reports TX draining and RX
errors. If TX remains queued, it resets the TX FIFO so commands cannot escape
later. Neither tool changes pins, gates or baud. A single operator must own
UART4, verify no kernel driver owns it, and provide signal-safe restoration for
any surrounding register experiment. Use private output paths.

The next useful experiment is an electrical/clock boundary check: confirm the
receiver's supply and reference clock, and observe reset, standby, TX, RX and
RTS at the chip while replaying the reviewed request. The internal UART loopback
passes while the external receiver path remains silent. A source-grounded power
or pin-mux discrepancy could replace physical probing; neither has yet been
established. Once a valid version response exists, decode the ECPU initialization
and patch compatibility before attempting measurements and a position solution.
Do not interpret the reset break as chip identification or a fix.

A future `samsung-uart` attachment must also address its shared-driver teardown:
the current `s3c24xx_serial_remove` unregisters the UART driver globally. Hot
adding and removing an experimental port without that review can disturb UART0.
The current tools avoid registering a platform device or interrupt handler.
