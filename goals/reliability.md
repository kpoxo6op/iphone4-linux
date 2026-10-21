# SoyOs: boot without button sequences

Owner priority, 21 October 2026: stop depending on repeated manual DFU entry.
Boot and recovery come first, the 60-second idle display second, then other UI
work. The owner has already authorized erasing and flashing this iPhone.
Do not ask for that permission again. Host and unrelated devices are outside scope.

The master currently owns the phone connection. All lanes work independently
on the deliverables below and hand changes to the master. Do not open USB,
send payloads, reset, flash or operate phone SSH while this ownership applies.
The master must explicitly hand the device back before a lane operates it.

Read the current `.opencode/review-feedback.json` and
`/seed/handoff/usb-outage-2026-10-21.md`. The owner reset the phone and it now
enumerates as the pinned N90 in Apple recovery. Repeated button attempts have
not reached DFU. The master is investigating the documented Legacy iOS Kit
DFU-IPSW route; no successful software DFU or new Linux boot is claimed yet.

Use the existing pstack workflow, free DeepSeek 1017 at max, two build jobs
total, and the existing completion notes. Do not create another journal or
replace existing worker source. The master will review and integrate patches.

## Kernel lane: reliable boot and kernel failure evidence

Work in `phone/recovery/` and `phone/soy-display/`.

1. Research and prepare a boot route that avoids human button timing. Start
   from pinned upstream Legacy iOS Kit, powdersn0w and openiBoot sources.
   Distinguish software entry to DFU, host-assisted RAM boot, and a boot chain
   installed on the phone that survives power loss. Compare the actual N90
   dependencies and choose the smallest working next step. Existing Apple
   recovery is available; do not report the phone as physically absent.
2. Make the fallback and repeat-boot artifacts reproducible and hash-bound.
   Fix the existing identity-restoration circular dependency: a fresh RAM boot
   generates a new SSH host key, so checking the old key before restoring it
   cannot work. Propose an authenticated bootstrap tied to the pinned phone
   and exact uploaded payload, then restore the existing identity privately.
   No blanket host-key bypass, credentials in images, or automatic re-enrollment.
3. Prepare bounded failure tracing for the actual kernel: boot ID, kernel
   revision, USB state transitions, panic/oops and relevant DWC2/PHY events.
   Inspect existing pstore/ramoops support and reserved memory first. Determine
   which evidence survives a warm reset, power loss, USB loss or a frozen kernel;
   do not claim RAM logging survives all of them. Use existing kernel facilities
   before inventing tracing. Keep the RAM/framebuffer/load-address map valid.
4. Handoff a bounded host boot state machine and exact experiment commands.
   Every stage has a deadline, observed USB identity/mode, and a failure result.
   Stop repeated same-cause failures. A successful tool exit is not boot proof.

Acceptance requires real reboot -> SoyOs + owner USB SSH + existing Tailscale
identity, with no button sequence or fresh account login. Separately prove a
complete power loss if claiming persistent installation. Offline preparation
may be ready for review but cannot satisfy those hardware checks. Before
deliberately panicking/resetting the phone, the master must have verified the
recovery path; preserve the only working channel until then.

## Qemu lane: UI crashes must leave recovery usable

Work in `soy-runtime/`; retain the current review's unresolved findings.

1. Finish PID-file publication and process-ownership failure handling, atomic
   release switching, and complete evidence for the reviewed supervisor patch.
   Failed publication must not leave live untracked children. A failed switch
   must retain the previous selection. Do not kill an unrelated/reused PID.
2. Recover a killed or hung Soy renderer with bounded retries and a verified
   fallback. Preserve a valid last scene/reading position where available.
   Repeated crashes must stop retry storms and retain a useful failure record.
   SSH and Tailscale must remain independent of the UI supervisor.
3. Keep bounded private diagnostic records with boot/release/build identity,
   exit signal/status, last UI heartbeat and monotonic timing. Export failure
   evidence to the host when reachable. Set storage/rotation limits suitable
   for a 512 MiB RAM-rootfs phone; record space and steady-state overhead.
4. Test the real process/SSH boundary in ARM QEMU: killed renderer, hung
   renderer, invalid release, failed atomic switch, full storage and repeated
   crashes. A surviving sleep sentinel does not prove SSH works. Reuse existing
   passing checks; add only coverage for a credible failure not already owned.

Deliver a small reviewable patch, complete scripts and artifact hashes,
reproducible commands and raw evidence. QEMU cannot establish phone recovery.

## Drivers lane: explain link loss and provide a usable sleep/wake path

Work in `research/recovery/` and existing `patches/experimental/` paths.

1. Turn the DWC2/PHY source investigation into a minimal diagnostic plan that
   distinguishes host disconnect, phone USB failure, kernel hang and power
   loss. Name the observations that discriminate them. Do not infer battery
   health from age or a retained framebuffer. Keep unique identifiers private.
2. Find source-grounded N90 backlight and physical wake input support. The
   renderer's idle code currently draws black and sleeps; it does not power
   down the backlight. Produce the smallest compatible driver/DT changes and
   explain the boot dependencies. No guessed registers or fabricated telemetry.
3. Design recovery from display sleep that cannot strand the owner: reliable
   wake input, preserved scene, SSH still available, and a fallback if physical
   wake support is absent. Synthetic contacts prove the software path only.
4. Deliver a bounded phone test plan and one focused patch, not another large
   source-string test suite. Coordinate USB/kernel changes with the kernel lane.

## Completion notes

Each cycle updates `notes/GOAL.md` and `notes/status.json`: what failed, the
first wrong state observed, exact change, commands/exit codes, evidence and
hashes, remaining blocker, and next experiment. Separate source, cross-build,
emulator and real-phone claims. Preserve crash evidence before restart. Report
`ready_for_review` only for the concrete deliverable, never overall acceptance.
