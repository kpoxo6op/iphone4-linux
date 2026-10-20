---
name: pstack-iphone
description: Run the iPhone Linux goal workflow with pstack investigation, small experiments, evidence and bounded review. Use for /goals or /poteto-mode in this project.
---

# pstack for iPhone Linux

This is the project's OpenCode adaptation of Lauren Tan's pstack. AGENTS.md,
the assigned goal and supervisor limits govern it. Use DeepSeek 1017 at max;
the existing senior timer owns cross-model review. Do not spawn agents, switch
models, install plugins, contact others or merge. The assigned device operator
may access this iPhone as described in AGENTS.md and goals/cable-day.md.

At a checkpoint, read the goal, notes/GOAL.md, notes/status.json and any
.opencode/review-feedback.json. Preserve in-flight builds. Name one observable
exit condition and pick the appropriate path below. Read only the principle
needed for the decision, using the sandbox shell; paths below are relative to
this skill. Do not load the whole stack each turn.

- **Investigate an unknown:** trace the pinned source, distinguish fact from
  hypothesis, and name the observation that would disprove the hypothesis.
  Source research ends with cited findings and missing observations, not a
  claim that a driver works. See ../principle-prove-it-works/SKILL.md.
- **Repair a failure:** save the failing command, exit code and relevant log;
  trace the first wrong state; change the smallest responsible part; run the
  same check again. See ../principle-fix-root-causes/SKILL.md. After two fixes
  fail on the same assumption, read ../principle-attack-the-premise/SKILL.md
  and test that assumption before a third fix.
- **Build a deliverable:** choose the smallest unit with a real check, state
  its inputs and outputs, implement it, then verify before building on it.
  See ../principle-build-the-lever/SKILL.md and
  ../principle-sequence-verifiable-units/SKILL.md. Do not rebase a running
  worker checkout; maintainer integration owns Git topology.

For verification, read ../verify-iphone4/SKILL.md and the matching feature map.
For tests, use ../principle-test-behavior-not-implementation/SKILL.md: name the
observable contract, credible failure and existing coverage before adding one.
When a correction recurs, propose a structural check rather than adding more
rules. Workers propose acceptance changes; only the maintainer edits them.

Keep the existing notes/GOAL.md as the single chronological experiment trail.
For each meaningful decision record the hypothesis, command and exit code,
result, evidence path and next action. Do not invent a second journal. Record
which review findings were fixed, disproved with evidence, or remain blocked.
Record artifact hashes and the code revision or dirty diff used. No secrets.

Update notes/status.json at each cycle. ready_for_review is a request, not
acceptance. Inconclusive, missing artifacts and hardware unavailable are not
passes. Stop at the goal's deliverable or a concrete blocker. The P0 outcome is
real-phone Tailscale + SSH; offline preparation never satisfies that gate.
