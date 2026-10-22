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
