# Initial validation, 2026-10-20 NZDT

The maintainer ran the new verifier inside the qemu worker's real filesystem
sandbox. The worker was rebuilding output/images, so doctor correctly reported
missing artifacts there. A subsequent run used completed files under
output/buildroot/images and passed against its own copied snapshot:

```sh
python3 /acceptance/verify.py qemu --images output/buildroot/images \
  --results output/pstack-verification
```

Run: `20261019T110617Z-kl4v0z89`. Exit code: 0.

Observed: ARMv7 Linux 6.18.7 boot, public-key SSH, rejection of a different key,
random file write/read, and persistence across a clean power cycle. Both boot
logs, raw result, harness log and receipt survived cleanup. The temporary image
snapshot and the harness's private keys/disposable disk were removed.

| Input | SHA256 |
| --- | --- |
| zImage | 6a03aeb9a77d2b2775562969fdc25e32171ca6341f4af3efe2b563ea501ae6c7 |
| vexpress-v2p-ca9.dtb | cb35d197143510bcdadf022f925c23735c4e453f4aa7a207cfbc2b6fb99cb24d |
| rootfs.ext4 | 085f643ceea435b65e39193dbd95f20d770d899e2c76ccbe204b1f8567de3f5f |
| qemu_smoke.py | 31f2e57584e406407243369c7732da6a9fd2fea672881b1f29a365c6276008de |

Raw evidence remains in the local qemu checkout under
`output/pstack-verification/20261019T110617Z-kl4v0z89/`. This checked snapshot
does not establish reproducibility of the worker build script, nor does it
cover password rejection, a TUI action, Tailscale, or phone hardware. A changed
image requires new proof. M1/M2 are not accepted as a whole by this run.

Eight harness tests passed, including the two receipt boundaries: a missing
new build cannot reuse an old pass, and modified bytes change image identity
without doctor claiming boot success. Skill frontmatter and local references
validated. The live OpenCode API discovered both local commands and all eleven
skills in each of the three worker checkouts.
