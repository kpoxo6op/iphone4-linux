# Worker contract

Read your assigned goal before writing code. Work only in your assigned checkout.
Use .opencode/skills/pstack-iphone/SKILL.md for each goal cycle and its
verify-iphone4 feature map for evidence. These are project-local pstack
adaptations; this contract and the supervisor's limits take precedence.
Use the shell tool for files and commands; it is wrapped by the maintainer's
filesystem sandbox. Do not bypass it or change OpenCode configuration, this
contract, goal definitions, or the acceptance harness. The original acceptance
files are mounted read-only at /acceptance. Local copies are not authoritative.
OpenCode uses its built-in build agent. Extra tools remain approval-gated for
free-route compatibility; the supervisor rejects every extra access request.
Do not request approval or use direct file tools. Use the sandboxed shell.

- Use only DeepSeek-V4.1-Flash-1017 through opencode/deepseek-v4.1-flash-free at max effort. No paid fallback. Never consult
  another model, spawn agents, use paid coding assistants, or install plugins.
- No sudo, host package installs, host services, credentials, other repositories
  or unrelated private network services. Phone access is assigned below.
- The owner has authorized unrestricted development on this iPhone, including
  exploits, bootloader changes, flashing, repartitioning and erasing it. There
  is no data to preserve and no additional permission prompt is needed.
  The kernel lane is the current device operator. Its sandbox exposes the
  pinned phone through /dev/bus/usb, including recovery/DFU re-enumeration.
  One kernel shell owns the device at a time. Other lanes develop in parallel
  and hand artifacts to the operator; they do not race it on USB.
  Identify the target, use source-grounded experiments, keep raw device logs
  under ignored output/hardware, and redact unique device identifiers from
  public notes. Device authorization does not include Platt or other devices.
- Public upstream source downloads are allowed. Record exact URLs, revisions,
  hashes and licenses. Do not redistribute Apple firmware or proprietary blobs.
- At most two compilation jobs. Keep downloads/builds in .cache or output. Do
  not use /tmp for large builds. Do not background daemons/builds outside the
  supervisor's control. Use bounded shell commands and retain logs.
- No fabricated drivers, register addresses, tests, logs or passing results.
  Label each result: source evidence, cross-compile, emulator, or real hardware.
  Emulation cannot prove iPhone USB, SDIO, Wi-Fi, touch, NAND, charging or thermal safety.
  The device operator should now gather real hardware evidence.
- Never weaken a failing test to pass, substitute preprinted success markers,
  remove required features, or mark missing hardware tests complete. If an
  acceptance check appears wrong, document the issue and stop for review.
- Prefer small changes and real boundary tests. Do not churn style, add a UI
  framework, or port an entire desktop. Do not push, publish, message upstream,
  or merge other workers' code. Local commits on codex/* are allowed.
- Every work cycle updates notes/GOAL.md and notes/status.json. Include exact
  commands, exit codes, artifact hashes, evidence paths, unresolved risks and
  the next experiment. Keep a short chronological experiment log.
- After three failures with the same cause, stop that approach, explain the
  evidence and try a materially different bounded approach. If none is credible,
  set blocked. A missing physical device is a real blocker, not an invitation
  to invent results. Stop when the assigned deliverable is ready for review.

notes/status.json schema:

```json
{"status":"working|ready_for_review|blocked","summary":"specific result",
 "evidence":["relative/path"],"next":"next action or missing prerequisite"}
```

ready_for_review means the worker believes the criteria pass. Only the master
reviewer can accept a milestone. Never call the overall phone project complete.
