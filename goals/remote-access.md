# M4b / P0: Tailscale + SSH remote development

The actual iPhone runs Linux, its own tailscaled, and SSH, so authorized machines
can develop and inspect it remotely. Completion requires a real connection to
the phone's own tailnet node, not just installed packages or a tunnel to a laptop.

## Implementation order

1. M1–M3 provide ARMv7 userspace and a reproducible N90 kernel; M4 proves phone
   boot and USB networking. Prepare packages before hardware arrives.
2. Pin an upstream Linux ARM Tailscale build and checksum, or reproducibly build
   with GOARCH=arm/GOARM=7. Record version, provenance, binary size and memory.
   Measure the fit within 512 MB rather than assuming it is comfortable.
3. Prefer normal TUN networking. Check CONFIG_TUN, /dev/net/tun, routing, DNS,
   CA certificates, system time, entropy and firewall behavior. The current N90
   config has CONFIG_TUN=m: ship the matching module/loading path or a reviewed
   built-in fragment. A zImage alone does not contain that module.
4. First use ordinary public-key SSH over Tailscale with the planned Dropbear
   server and an explicit development account/root policy. Preserve USB SSH for
   recovery. Tailscale SSH's integrated server (`tailscale set --ssh`) is a
   separate optional path; do not accidentally replace recovery access.
5. Share Internet from the USB host initially. Wi-Fi later removes that cable
   dependency. Touch must not hold up remote access.
6. Keep enrollment and node identity outside images/Git. Use a normal user-owned
   enrollment flow at the hardware milestone. For RAM boots, document private
   host-assisted identity restoration or explicit re-enrollment. Do not write
   NAND to achieve this early, or claim persistence without a reboot test.

## Acceptance

- ARM guest preflight: pinned binaries execute, tailscaled starts, TUN works,
  init restarts the daemon, and resource use is recorded. This is emulator
  evidence only. Outbound userspace SOCKS alone does not prove inbound SSH.
- Real phone: from an authorized laptop reach the phone's tailnet address, run
  uname, write/read/hash a file, transfer a patch and retrieve dmesg/build logs.
  Record whether development uses a local compiler or cross-compile + transfer.
- Reject an unauthorized SSH key and an intentionally excluded test tailnet
  identity/device. No public Internet SSH listener or broad tailnet policy.
- Keep a remote shell usable for 30 minutes, measure resident memory, interrupt
  the network link and reconnect after restoring it.
- Reboot through the reviewed RAM-boot procedure and recover remote access;
  state clearly whether enrollment/identity restoration is manual or persistent.
- Keep raw evidence private; publish sanitized results and artifact hashes.
  Never publish keys, tailnet identities, addresses or authentication state.

Current offline work does not authorize changes to the user's live tailnet,
credentials or host firewall. Actual phone installation awaits hardware tests.
Integrated Tailscale SSH is optional if ordinary SSH over Tailscale meets the goal.

## Primary sources

- [Linux installation](https://tailscale.com/kb/1031/install-linux)
- [Official builds](https://pkgs.tailscale.com/stable/)
- [TUN and userspace networking](https://tailscale.com/docs/concepts/userspace-networking)
- [Tailscale SSH and ordinary SSH over Tailscale](https://tailscale.com/docs/features/tailscale-ssh)
