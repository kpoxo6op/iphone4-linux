# Phone networking

`udhcpc.script` replaces Buildroot's udhcpc default script on the phone; the
boot pass (`harness/phone_boot.py`, `deploy_dhcp_script`) installs it, and
the running clients pick it up at their next renewal.

It differs in one place. A renewal that brings the same address, router and
DNS servers now changes nothing. The stock script deleted and re-added the
default route on every renewal. On USB, with the laptop's 120 s leases, that
was every minute, and each time tailscaled logged `LinkChange: major` and
rebuilt its connections, a TLS handshake that costs seconds of CPU on the A4.

On 22 October, before: 26 such link changes in 29 minutes, and tailscaled
used 13.6 % of the CPU over a 30 s window that held one. After: no link
change in the following 10 minutes, and tailscaled used 0.2 % over a quiet
two minutes.

## Firewall

On Wi-Fi and hotspots the phone now answers nothing but Tailscale's own
encrypted port. Its services, today only SSH, are reachable over the USB
cable from this computer and over the tailnet.

| From | Before (23 October) | After |
| --- | --- | --- |
| Another device on the same Wi-Fi or hotspot | SSH answered on the phone's IPv4 address and its public IPv6 address; the phone answered pings | Nothing answers; the packets are dropped and counted |
| The tailnet (Boris's devices only) | SSH | SSH |
| USB from this computer (`10.84.4.1`) | SSH | SSH |
| Tailscale peers on the same network | direct WireGuard on UDP 41641 | the same |

SSH itself was already sound: Dropbear runs with `-s -g` (keys only), the
one authorized key is this computer's `iphone4-linux-platt`, root's password
is locked, and Dropbear is 2026.94. The home router (OpenWrt) rejects
connections from the Internet to the LAN, IPv6 included, so the exposure was
to whoever shared the network: other devices at home, other hotspot users.

### How

`firewall.nft` is one nftables table, `inet n90`, with a default-drop input
chain:

- accept loopback, `usb0` from `10.84.4.1`, everything on `tailscale0`
  (Tailscale admits only the tailnet's devices), and replies to the
  phone's own connections;
- accept Tailscale's WireGuard port (UDP 41641), DHCP answers, and the
  IPv6 neighbour discovery and router adverts that keep an address;
- drop the rest. Unicast packets addressed to the phone go through the
  `blocked` counter first; broadcast and multicast chatter is dropped
  uncounted. Nothing is filtered on the way out; nothing is forwarded.

`n90-firewall` (`firewall.sh`) also turns ICMP redirects off in both
directions. `make -C kernel/n90-net` builds what it needs into
`output/net`: a static `nft` 1.1.7 (libnftnl 1.3.2, libmnl 1.0.5, mini-gmp;
netfilter.org releases with good Netfilter Core Team signatures and the
SHA-256 sums in the Makefile) and six modules from the lean kernel tree
`e899dceb`: `nfnetlink`, `nf_tables`, `nf_defrag_ipv4`, `nf_defrag_ipv6`,
`nf_conntrack` and `nft_ct`. The kernel already had `CONFIG_NETFILTER=y`
and nf_tables as modules; nothing in the kernel image changed.

`CONFIG_MODVERSIONS` is off and the knownboot fallback kernel reports the
same version string with different structure layouts, so the modules load
only into the kernel whose build stamp (`uname -v`) is in `/opt/net/kernel`.
Elsewhere the phone keeps Wi-Fi without a firewall, as before, and says so.

### Where it runs

- The boot pass runs `deploy.py` before installing Wi-Fi
  (`harness/phone_boot.py`, `deploy_firewall`). It copies everything,
  loads it, and opens fresh SSH connections over USB and the tailnet. Unless
  they confirm within 60 s, the phone deletes the rules by itself, so a bad
  rule cannot lock the laptop out.
- The Wi-Fi keeper runs `n90-firewall check` before each join attempt and
  every 20 s: it loads the firewall if it is missing (once per boot), and
  refreshes `/run/net/firewall` and `/run/net/blocked`.
- Soy shows both as `{{net.firewall}}` and `{{net.blocked}}`
  ([live values](../../docs/soy/scenes.md#live-values)). Loads and failures go
  in Soy's journal; `/run/net/firewall.log` has the details.

```sh
make -C kernel/n90-net
python3 kernel/n90-net/deploy.py --ssh-config .runtime/phone/private/ssh_config
ssh -F .runtime/phone/private/ssh_config iphone4-usb nft list ruleset
```

### On the phone, 23 October 2026

All six modules loaded into the running lean kernel without a taint, and
`nft -c` accepted the rules before they went in. From this computer on the
same home Wi-Fi, a connect scan of every TCP port:

| Address | Before | After |
| --- | --- | --- |
| `192.168.20.136` (Wi-Fi IPv4) | 22 open, 65,534 refused | 65,535 silent |
| the phone's public IPv6 address | 22 open, 65,534 refused | 65,535 silent |

Pings over Wi-Fi stopped answering. From node-0 on the same LAN,
`tailscale ping` still went direct to `192.168.20.136:41641`, and a TCP
connection to the phone's tailnet address on port 22 still succeeded. SSH
over USB and over the tailnet kept working, and the scan raised the
`blocked` counter by tens of thousands of packets.

Not covered: the phone's own outgoing traffic is not limited, and any of
Boris's tailnet devices can reach the SSH port (a key is still required).
A Tailscale access rule could narrow that to this computer.
