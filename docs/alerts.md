# Critical reports through Soyclaw

The project sends critical reports to Boris's existing private Telegram chat
with Soyclaw. A local systemd timer checks every five minutes. It uses the
OpenClaw message CLI, without starting an agent or paying for another model.

It reports:

- A worker exhausting its resource or API-retry limit.
- A senior review failing, losing its result, or having an uncertain GitHub post.
- A stopped supervisor, review timer or free-model watchdog while the project is enabled.
- An unavailable free route, missing max effort, or changed/unknown prices.
  Active workers are interrupted; there is no paid fallback.
- An active worker using the wrong model/effort. It is interrupted too.
- Three consecutive failures to check OpenCode.
- A specific decision or access requirement the senior reviewer assigns to Boris.
- An explicitly configured deadline ending (the ongoing run has none).

Every message names the problem, the next action and the relevant GitHub issue.
Normal compilation, queued reviews, routine fixes and the
already-known missing phone cable stay quiet. A request for a human decision
must name a concrete action and put the affected goal on hold. Workers cannot
send arbitrary messages or choose a recipient.

Delivered incidents are not sent again until they clear and recur. If Telegram
is offline, reports remain queued and send when it recovers. A send with an
uncertain acknowledgment retries at most three times, thirty minutes apart;
the same alert ID identifies any duplicate. An unconfirmed third attempt is
recorded as delivery_unknown. Telegram acknowledged the one-off setup test
on 2026-10-20 NZDT; the delivery ID stays in the private local ledger.

This is a laptop monitor. It cannot report while the laptop is asleep, powered
off, or disconnected; the timer catches up after it returns. It does not
provide an independent check of its own process or of a dead laptop. Reports
identify maintainer problems but do not themselves repair them or authorize
phone access. The project still has the integration limitation described in
the review workflow.

## Local operation

```sh
python3 harness/notify.py status
systemctl --user status iphone4-linux-notify.timer
```

`python3 harness/control.py stop` stops alerts along with worker and review
services. `start` re-enables the installed alert timer. Routing and delivery
state live under ignored `.runtime/notifications/`; recipient details and
credentials are never committed. The notifier uses the existing OpenClaw
configuration and does not copy the bot token.

Installation on another machine requires a private config.json in that
directory with `command` (absolute OpenClaw executable), `openclaw_config`
(existing config path), `account` and `target` (Boris's private allowlisted
Telegram chat). Keep it mode 0600, then run `python3 harness/notify.py install`.
Use `test` only for an intentional delivery test; `check` is the normal quiet
monitor invocation.
