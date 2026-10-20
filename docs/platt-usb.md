# Access from Platt

USB SSH and SSH through the phone's own Tailscale node both worked on
20 October 2026. Platt's active NetworkManager profile `iphone4-linux-usb`
provides Internet to the phone. Recovery mode does not provide this interface;
the phone must be running Linux.

The host udev rule names the interface `iphone4` only for vendor `0525`,
product `a4a1` or `a4a2`, on the phone's assigned USB socket `3-4`.
The profile also requires the `cdc_ether` driver. Other interfaces keep
their existing configuration.

| Setting | Value |
|---|---|
| Host address | `10.84.4.1/24` |
| Phone DHCP address | `10.84.4.2` |
| IPv4 method | NetworkManager `shared` |
| Default route on Platt | Never provided by this profile |
| IPv6 on this USB link | Disabled for the first experiment |

NetworkManager supplies DHCP, DNS forwarding and Internet sharing. The real
phone received its lease, reached an external IP and resolved DNS names.

The phone has a dedicated SSH key. Its private half remains in the
maintainer's ignored `.runtime/phone/private/` directory. The operator receives
only the public half through `/seed/handoff/iphone4-owner.pub`. Public keys
and private state are not committed.

For direct USB access:

```sh
ssh -F .runtime/phone/private/ssh_config iphone4-usb
```

For the enrolled phone over Tailscale:

```sh
ssh -F .runtime/phone/private/ssh_config iphone4
```

Both aliases use the same dedicated key. The tailnet alias verifies the same
SSH host key first observed over the pinned USB connection. Password login
is disabled. Tailnet addresses and enrollment state stay in the private
configuration. This uses ordinary Dropbear SSH over Tailscale, not Tailscale's
optional SSH server.

Each path passed an interactive terminal, a 4,096-byte file write/read/hash,
rejection of a wrong SSH key, and another successful owner login afterward.

The maintainer can inspect or disable the profile without altering the
Wi-Fi connection:

```sh
nmcli connection show iphone4-linux-usb
nmcli connection down iphone4-linux-usb
nmcli connection modify iphone4-linux-usb connection.autoconnect no
```

The phone currently boots into RAM. Keep the cable connected: it supplies
power and Internet. A reset loses the running system; automatic recovery is
not established. The maintainer saved private copies of the phone's SSH host
key and Tailscale state under `.runtime/phone/private/live-state/`, but has
not yet tested restoring them after a reboot. These files must never enter
a worker checkout, firmware image or Git.

The [first-boot record](first-phone-attempt.md) lists the exact running
artifacts and the reliability tests still outstanding.

Reference: [NetworkManager IPv4 shared settings](https://networkmanager.dev/docs/api/1.52.0/settings-ipv4.html).
