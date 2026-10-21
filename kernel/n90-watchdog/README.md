# A4 watchdog

The timer block at `0xbf102000` carries a watchdog at `+0x20`, laid out like
the Apple M1 watchdog's second channel:

| Offset | Register | Behaviour on the phone, 21 October 2026 |
|---|---|---|
| `+0x20` | CUR_TIME | Counts at 24 MHz even when disarmed; writing 0 restarts it |
| `+0x24` | BITE_TIME | Reset point; 0 at boot |
| `+0x2c` | CTRL | Bit 2 enables the reset; 0 at boot |

Linux's s5l8930 reboot already uses these registers. A test armed it for 20 s
and kicked it every 8 s for 32 s, then stopped: the phone reset into DFU and
the boot watcher brought Linux back.

`n90-wdt` arms it (60 s by default) and restarts the count every 10 s at
SCHED_FIFO 50. A frozen kernel stops the kicks and the SoC resets.
`harness/phone_boot.py` starts it on every boot, and keep (`kernel/n90-keep`)
restarts it if it dies.

SIGTERM leaves a final 30 s count rather than disarming. A normal `reboot`
resets the SoC well before that, and a deploy's new kicker re-arms the full
timeout. On 22 October a reboot after a crashed Wi-Fi probe hung in
`device_shutdown()` on a lock the crashed probe still held; the old kicker
had disarmed on SIGTERM, so the phone sat half rebooted until a hard reset.
Send SIGUSR1 to disarm on purpose.

A reset does not release the phone's DHCP lease, and the gadget picks a new
MAC each boot, so NetworkManager offered the next boot nothing until the old
lease expired (one hour). The profile now uses 120 s leases with a spare
`10.84.4.3`, and the boot pass adds `10.84.4.2` to the phone when it comes up
on the spare address.
