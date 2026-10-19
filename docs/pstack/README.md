# pstack in iphone4-linux

Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/d457567332aa6989e753ea289f30ea2bfbc80bc0/pstack)
is a set of engineering skills, principles and task playbooks. It is not a
Linux toolchain or a promise of autonomous hardware bring-up. The pinned
upstream contains 56 skills and 23 playbooks. This project installs nine small
principle skills unchanged and adapts the workflow for the existing OpenCode
workers. [upstream.lock.json](upstream.lock.json) records their source and
hashes; [LICENSE](LICENSE) preserves Lauren's MIT license.

## What we learned and applied

[Lauren's guide](https://x.com/poteto/status/2094457600259842065) places a
project-specific verification skill at the center: agents need to drive the
real surface and inspect its effects. The upstream
[verification generator](https://github.com/cursor/plugins/blob/d457567332aa6989e753ea289f30ea2bfbc80bc0/pstack/skills/create-verification-skill/SKILL.md)
adds a feature map, repeatable controls, diagnosis and retained evidence.

| pstack mechanism | Local application |
| --- | --- |
| poteto-mode routes tasks to playbooks | pstack-iphone routes an assigned goal to investigation, repair or a small build increment |
| Build the Lever / Prove It Works | verify.py runs the existing QEMU harness against snapshots and records hashes, logs and a receipt |
| Feature map | QEMU shell/files/TUI, N90 artifact package, and actual-phone Tailscale + SSH have distinct proof requirements |
| Attack the Premise / Fix Root Causes | Two failed fixes on one assumption require a discriminating observation before another attempt |
| Show Me Your Work | Existing notes/GOAL.md remains the sole experiment trail; each decision names evidence and a next action |
| Interrogate | The existing bounded senior reviewer uses failure-path, stale-state, complexity and behavioral-test lenses |
| Orchestrate | Maintainer owns briefs and acceptance, isolated workers own implementation, completion requests review |
| Encode Lessons in Structure | New verification receipts prevent a missing-image attempt from borrowing an older pass |

Read the [upstream guide](https://github.com/cursor/plugins/tree/d457567332aa6989e753ea289f30ea2bfbc80bc0/pstack/docs/guide)
for the broader stack: design exploration, performance and hillclimbing,
runtime/trace forensics, prototypes, skill evals, PR babysitting, stacked
shipping, session pickup and safe pause. Those are situational workflows,
not mandatory ceremonies for every kernel build. The upstream advice to
start small and add checks for demonstrated failures guides this adaptation.

## Installed use

OpenCode exposes `/poteto-mode GOAL` and `/verify-iphone4 FEATURE` from this
project. `/goals NAME` loads pstack-iphone automatically. Workers read the
skills through their existing sandbox shell; no additional tool permission,
provider, paid panel or global skill installation is required. The .opencode
tree is already mounted read-only inside worker shells.

```sh
python3 harness/verify.py doctor --images /path/to/output/images
python3 harness/verify.py qemu --images /path/to/output/images
```

Doctor reports prerequisites, not a boot verdict. QEMU runs produce distinct
output/verification/RUN/receipt.json files bound to the image and harness
hashes. Rebuilds need new proof. The senior packet includes the latest receipt,
but worker-controlled receipts still require independent maintainer checks.

## Deliberate adaptations

- DeepSeek-V4.1-Flash-1017 uses the OpenCode free route at max effort, around
  the clock without a calendar expiry. Goal and resource limits still apply.
  Senior review allows at most ten attempts per Auckland day, two hours apart.
- Cursor Task/arena/swarm panels, model defaults, /loop, Bugbot, Slack
  automations and automatic shipping are not installed. Existing workers,
  timer and GitHub publisher supply the authorized orchestration.
- No source skill can authorize hardware access, tailnet enrollment, secrets,
  publication by a worker, relaxed acceptance or changing the assigned goal.
- Tailscale and hardware recipes remain blocked until their prerequisites
  exist. A generated recipe is not hardware evidence.
- No claim of measured productivity improvement is made. Acceptance is better
  traceability and actual worker use; a future comparison needs a controlled
  task and outcome metric, not more test or line counts.

Updates are manual: inspect a new upstream revision, compare the selected
files, preserve the license and revalidate the local workflow. No auto-update
can import a changed model policy or shipping permission.

See [initial validation](validation.md) for the first real QEMU run and its
limits. This establishes an executable verification path, not a measured
improvement in model quality.
