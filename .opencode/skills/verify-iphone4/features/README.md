# Verification map

| Feature | Surface | Required proof |
| --- | --- | --- |
| [ARM shell, files and TUI](qemu.md) | QEMU vexpress-a9 | Real boot, authenticated SSH, negative auth, persistent file, interactive TUI |
| [Phone kernel package](kernel.md) | Cross-compiled artifacts | Reproducible inputs, ARM ELF, N90 DTB, config and matching modules |
| [Tailscale + SSH](remote-access.md) | Actual iPhone | Independent peer connects to the phone's own node, reconnect and negative access checks |

Record the feature, entry point, exact input hashes/revision, command, exit code
and evidence paths. Changed inputs invalidate prior proof. Source analysis,
cross-compilation, emulation and physical observation are distinct evidence
levels. An unavailable precondition is a blocker, never a skipped pass.
