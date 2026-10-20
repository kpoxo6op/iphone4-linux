# drivers: M5 preparation

Current priority: the drivers assignment in [first connection](cable-day.md).
USB remote access comes before the peripheral work below.

Investigate concrete gaps between the pinned N90 kernel and usable Wi-Fi/touch.
Own research/, patches/experimental/, and tools/analysis/. Do not edit the other
lanes' build configuration. Use public primary source code with immutable refs.

1. Establish an evidence table for clocks, GPIO, pin control, SDIO host, BCM4329
   reset/power/firmware/NVRAM, SPI transport, touchscreen firmware/input parsing,
   and PMU prerequisites. Distinguish A4 code from earlier S5L8900 examples.
2. Trace the existing openiBoot A4 SDIO/SPI/I2C/PMU code against modern Linux
   interfaces and the N90 DT. Cite file, symbol and revision for each claim.
3. Select the smallest defensible software-only experiment: a cross-compiling
   driver skeleton with no fabricated register values, a parser tested on real
   publicly available packet captures, or a source comparison tool that catches
   a concrete mapping mismatch. Do not create meaningless mocks to look busy.
4. Produce a cable-day experiment plan with observable success/failure signals,
   required firmware provenance and useful stopping points. Hand commands and
   patches to the kernel lane, which is the single device operator. Flashing
   and bootchain work on this phone are owner-authorized; this lane must not
   race the operator. Use legitimate firmware sources.

The key deliverable is a source-grounded implementable patch or precise missing
information, not a broad literature review. If hardware observations are needed
to choose registers safely, document exactly which observations and stop.
Completion notes must state explicitly what has NOT been validated on hardware.
