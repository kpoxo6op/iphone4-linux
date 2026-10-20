#!/usr/bin/python3
"""udev helper: expose this phone, including re-enumeration, to its worker.

Install a root-owned copy in /usr/local/libexec/iphone4-usb-nodes and a private
root-owned /etc/iphone4-linux-device.json. Never execute worker code as root.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

POLICY = Path('/etc/iphone4-linux-device.json')
NODES = Path('/dev/iphone4-worker-usb')


def matches(policy, devpath, vendor, product, serial):
    if devpath != policy['devpath']:
        return False
    if vendor == '05ac' and product in ('1222', '1227', '1280', '1281', '1282', '1283'):
        ecid = re.search(r'\bECID:([0-9a-fA-F]+)', serial)
        return bool(ecid and hashlib.sha256(
            str(int(ecid[1], 16)).encode()).hexdigest() == policy['ecid_sha256'])
    # Our own RAM loaders/gadget do not expose an ECID; retain the same physical
    # USB socket and these source-established IDs. No other USB port is exposed.
    return (vendor, product) in (('0525', '1280'), ('0525', 'a4a1'), ('0525', 'a4a2'))


def update(policy, env, sysroot=Path('/sys'), nodes=NODES):
    if env.get('DEVPATH') != policy['devpath']:
        return
    bus, device = int(env['BUSNUM']), int(env['DEVNUM'])
    if not (1 <= bus <= 255 and 1 <= device <= 127):
        raise ValueError('Invalid USB address')
    dest = nodes / f'{bus:03}' / f'{device:03}'
    if env.get('ACTION') == 'remove':
        dest.unlink(missing_ok=True)
        return
    if env.get('ACTION') not in ('add', 'change'):
        return
    source = sysroot / env['DEVPATH'].lstrip('/')
    vendor = (source / 'idVendor').read_text().strip()
    product = (source / 'idProduct').read_text().strip()
    serial = (source / 'serial').read_text() if (source / 'serial').exists() else ''
    allowed = matches(policy, env['DEVPATH'], vendor, product, serial)
    # Retire every old device number, including on a rejected replacement.
    nodes.mkdir(mode=0o755, exist_ok=True)
    for old in nodes.glob('*/*'):
        old.unlink()
    if not allowed:
        return
    major, minor = map(int, (source / 'dev').read_text().strip().split(':'))
    if (major, minor) != (189, (bus - 1) * 128 + device - 1):
        raise ValueError('USB character device does not match its address')
    dest.parent.mkdir(mode=0o755, exist_ok=True)
    os.mknod(dest, stat.S_IFCHR | 0o600, os.makedev(major, minor))
    os.chown(dest, policy['uid'], policy['gid'])


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Device node maintenance requires the installed udev helper')
    policy = json.loads(POLICY.read_text())
    with open('/run/lock/iphone4-usb-nodes.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        update(policy, os.environ)
