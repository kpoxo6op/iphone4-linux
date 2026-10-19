---
name: verify-iphone4
description: Verify iPhone Linux build artifacts and QEMU SSH/file behavior using the independent harness and feature map, with explicit hardware limits.
---

# Verify iPhone Linux

Read [the feature map](features/README.md), then only the relevant feature.
The primary offline user surface is the ARM shell over SSH and the terminal
UI. The physical phone is a separate, currently unavailable surface.

## Doctor and drive

Workers use the read-only acceptance mount:

```sh
python3 /acceptance/verify.py doctor --images output/images
python3 /acceptance/verify.py qemu --images output/images
```

In the main checkout, replace `/acceptance` with `harness`. Doctor only checks
prerequisites and hashes artifacts. `ready` is not a successful boot. Missing
images or tools produce a nonzero exit with named blockers; fix the owning
build or record the blocker. Never manufacture images to satisfy doctor.

The qemu command snapshots the supplied images, calls the existing real boot
harness, and retains a unique receipt with hashes, command, exit code, logs
and result under output/verification/. It runs only one QEMU acceptance test
per results directory. Its proof covers the snapshot listed in the receipt.
A later rebuild requires a new run. No build command is supplied by this skill;
the assigned worker's reviewed build script owns that operation.

## Evidence and cleanup

Read receipt.json, harness.log, result.json and boot logs. A command that
returns nonzero or a receipt without passed=true is not a pass. A worker can
write local receipts, so the maintainer independently reruns before acceptance.
QEMU proves ARM userspace only; no result approves an iPhone hardware gate.

The boot harness removes its disposable disk and private SSH keys and stops
the exact QEMU process it launched. The wrapper removes only its image
snapshot; receipts and logs survive. Do not kill other sessions or remove
their evidence. If the host kills a run, missing receipt means interrupted,
not passed. Report a surviving snapshot for scoped cleanup.

## Coverage limits

Boot/SSH execution requires a completed image. Doctor and fail-closed behavior
can run before the build finishes. The existing smoke test does not test SSH password
rejection, TUI interaction, Tailscale or physical peripherals; follow the map
and report those separately. Never turn a planned check into a verified claim.
