# Worker review — 21 October 2026

The three OpenCode lanes were stopped at the owner's request. All three had
reported `ready_for_review`. Their checkouts in `iphone4-linux-workers/` are
untouched, including uncommitted work.

## Kernel lane — kept

- The hash-bound knownboot fallback (`phone/recovery/knownboot-manifest.json`)
  and the one real DFU → openiBoot → Linux run at 14:00 NZDT were correct and
  are what `harness/phone_boot.py` boots. Its claim that the loader's iBSS
  payload was "compiled in" was wrong. `loadibec` reads `iBSS.n90ap` and its
  payload from the working directory. Without them it tried Apple's servers
  and failed. The boot script now stages both.
- Its identity-restore state machine (S4–S9) is replaced by the simpler
  pinned-link restore in `phone_boot.py`, which ran on three real reboots.
- `failure-trace.md` is useful. `CONFIG_PSTORE_RAM` is off, so the reserved
  ramoops region collects nothing. That gap is still open.

## Drivers lane — kept, with two fixes

The `n90-display-power` series was source-grounded and close. On the phone it
had the GPIO block at the arm-io-relative `0x3fa00000` instead of
`0xbfa00000`, so it touched a RAM alias. The A4 GPIO encoding also missed bit
4. After both fixes the PMU backlight switches on the real phone; see
[kernel/n90-display-power](../kernel/n90-display-power/README.md). Its USB
link-loss diagnostic plan is still unverified, because the 08:42 stall has not
recurred.

## Qemu lane — nothing new to take

Its last status repeats the 20 October master evidence and describes a
loopback/devpts boot fix. That fix is not in the knownboot initramfs: `lo` is
still down on the phone, but nothing tested so far needs it. Its Soy
supervisor work was not finished.
