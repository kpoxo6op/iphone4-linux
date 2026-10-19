# Tailscale + SSH on the phone

## Sub-features

P0/M4b makes the phone reachable for later development. Its full acceptance
contract is goals/remote-access.md; that contract takes precedence.

## How to get to it (user POV)

From an authorized, separate tailnet peer, connect by public-key SSH to the
phone's own Tailscale address. An SSH session to the laptop is not this feature.

## Driving it with hardware verification

Preconditions: cable, identified phone, reviewed reversible RAM boot, working
Internet path and explicit hardware/tailnet authorization. Currently blocked.

- Offline workers may prepare pinned ARMv7 binaries, config, TUN dependencies,
  resource estimates and a credential-free runbook inside their assigned scope.
- Later, a hardware-authorized run must prove peer-to-phone identity, SSH file
  I/O, wrong-key and excluded-peer rejection, reconnect after interruption,
  and the 30-minute session required by the goal. Keep secrets out of evidence.
- Exercise the documented reboot/re-enrollment recovery path and record which
  state is volatile. No NAND persistence is implied by this requirement.

## Gotchas

USB-shared Internet can precede Wi-Fi and touch. A SOCKS-only userspace tunnel,
package installation or daemon-start log is not incoming SSH connectivity.
Integrated Tailscale SSH is optional; ordinary SSH over the tailnet comes first.
