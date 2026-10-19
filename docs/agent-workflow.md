# Planner, workers and review

The senior model owns goals, acceptance and targeted corrections. DeepSeek
V4.1 Flash 1017 at max effort implements in isolated checkouts. GitHub issues
carry goals, evidence checkpoints and decisions. Workers have no GitHub
credentials and cannot merge their own work.

## Research applied

- [Anthropic, November 2025](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents):
  durable progress records, small increments and end-to-end acceptance improve
  resumability and expose premature completion claims. Here: goal files,
  notes/GOAL.md, structured status and an independent QEMU test.
- [Cursor, January 2026](https://cursor.com/blog/scaling-agents): separate
  planning, implementation and judging worked better than flat coordination in
  their experiments. Here: non-overlapping lanes and concrete reviewer feedback.
- [GitHub safe outputs](https://github.github.com/gh-aw/reference/safe-outputs/):
  separate model decisions from authenticated writes. Here: a deterministic
  publisher can comment only on preconfigured issues in this repository. The
  senior model returns structured decisions without GitHub or shell tools.

These are engineering patterns, not proof that cheaper models can solve unknown
hardware behavior or that adding agents always helps. The phone remains a
required test instrument; source-only checks cannot certify drivers.

## Operating loop

1. A maintainer creates an issue with scope, dependencies, owned paths, evidence
   and a stopping point. It links to the goal in Git.
2. The worker implements one increment, records commands/results and leaves a
   completion or blocker note. No automatic merge or hardware success claim.
3. A deterministic timer watches completion, blockers or six-hour stale work.
   Ordinary build waits do not justify repeated expensive review calls.
4. At most **two senior review attempts per Auckland calendar day**, at least
   six hours apart, review bounded packets. No new evidence/event means no call.
   Failures also consume a slot. The seven-day deadline and off-peak window apply.
5. GPT-6 Astra uses **ultra**, its highest locally advertised effort. Shell,
   multi-agent, web and configured MCP access are disabled. It reviews supplied
   evidence only and returns `changes_requested`, `hold`, `continue`, or
   `ready_for_manual_merge`. Missing evidence prevents acceptance.
6. The publisher posts validated decisions on assigned GitHub issues and writes
   feedback for the worker. The off-peak supervisor resumes it with corrections.
   An ambiguous publication is not blindly resent.
7. A maintainer reviews the actual diff and independently verifies checks before
   a curated PR/merge. Automatic review is not release or hardware approval.

This is a steering checkpoint, not an exhaustive code review. Packets contain a
bounded selection of source, notes, artifact metadata and log tails. Omitted
files are listed. No conversation dumps, credentials, firmware or node state.

## Reviewer rules

Identify the failing contract, file/evidence and next experiment; do not just
say "try harder." Three repeats require a different approach or a blocker.
Do not reward line counts, test counts or perpetual activity. Keep independent
source-integrity checks, but remove tests that merely freeze current constants
or duplicate a report. MMIO reads can hang or have side effects: read-only is
not a synonym for hardware-safe.

Control: `python3 harness/control.py status|stop`. Review timer:
`systemctl --user status iphone4-linux-review.timer`. Private records live in
`.runtime/reviews/`; GitHub holds sanitized decisions. Senior review cannot
enroll a tailnet, flash a phone, push worker code or execute experiments.
