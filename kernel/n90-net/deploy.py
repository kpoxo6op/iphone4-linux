#!/usr/bin/env python3
"""Install and load the phone's firewall (kernel/n90-net/README.md#firewall).

Copies nft, the netfilter modules of the running kernel, the rules and
n90-firewall to the phone, then loads them. A firewall that locked the
laptop out would be hard to undo, so the phone takes the rules away again
by itself unless new SSH connections confirm within 60 s: over USB always,
and over the tailnet when that worked before the rules went in.
"""
import argparse
import io
import json
from pathlib import Path
import subprocess as sp
import sys
import tarfile
import time

HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser()
p.add_argument('--ssh-config', type=Path, required=True)
p.add_argument('--host', default='iphone4-usb')
p.add_argument('--tailnet-host', default='iphone4')
p.add_argument('--build', type=Path, default=HERE.parents[1] / 'output/net',
               help='output of `make -C kernel/n90-net`')
a = p.parse_args()

MODULES = ('nfnetlink', 'nf_tables', 'nf_defrag_ipv4', 'nf_defrag_ipv6',
           'nf_conntrack', 'nft_ct')


def remote(host, command, data=None, timeout=45):
    return sp.run(['ssh', '-F', str(a.ssh_config.resolve()), '-o', 'BatchMode=yes',
                   '-o', 'ConnectTimeout=8', host, command],
                  input=data, capture_output=True, timeout=timeout)


def reachable(host):
    try:
        return remote(host, 'true', timeout=30).returncode == 0
    except sp.TimeoutExpired:
        return False


files = {f'opt/net/{m}.ko': (a.build / f'{m}.ko', 0o644) for m in MODULES}
files['opt/net/kernel'] = (a.build / 'kernel', 0o644)
files['usr/sbin/nft'] = (a.build / 'nft', 0o755)
files['usr/sbin/n90-firewall'] = (HERE / 'firewall.sh', 0o755)
files['etc/n90/firewall.nft'] = (HERE / 'firewall.nft', 0o644)
missing = [str(path) for path, _ in files.values() if not path.exists()]
if missing:
    raise SystemExit('missing ' + ', '.join(missing) + '; run make -C kernel/n90-net')
blob = io.BytesIO()
with tarfile.open(fileobj=blob, mode='w') as tar:
    for name, (path, mode) in files.items():
        data = path.read_bytes()
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = len(data), mode, int(time.time())
        tar.addfile(info, io.BytesIO(data))
sent = remote(a.host, 'mkdir -p /opt/net /etc/n90 && tar -xf - -C /', blob.getvalue(), 120)
if sent.returncode:
    raise SystemExit('copy failed: ' + sent.stderr.decode()[-300:])

tailnet_before = reachable(a.tailnet_host)
loaded = remote(a.host, 'rm -f /run/net/confirmed; n90-firewall load && '
                '{ (sleep 60; [ -e /run/net/confirmed ] || { nft delete table inet n90; '
                'n90-firewall status; echo "$(date \'+%F %T\') removed: not confirmed" '
                '>> /run/net/firewall.log; }) >/dev/null 2>&1 </dev/null & }')
if loaded.returncode:
    detail = remote(a.host, 'tail -3 /run/net/firewall.log').stdout.decode().strip()
    raise SystemExit('firewall not loaded: ' + (detail or loaded.stderr.decode()[-300:]))
usb_after = reachable(a.host)
tailnet_after = reachable(a.tailnet_host)
if not usb_after or (tailnet_before and not tailnet_after):
    raise SystemExit('a new connection failed after loading; the phone removes the rules '
                     f'within 60 s (USB {usb_after}, tailnet {tailnet_before}->{tailnet_after})')
remote(a.host, 'touch /run/net/confirmed')
state = remote(a.host, 'cat /run/net/firewall /run/net/blocked').stdout.decode().split()
print(json.dumps({'firewall': state[0] if state else None,
                  'blocked': state[1] if len(state) > 1 else None,
                  'usb': usb_after, 'tailnet': tailnet_after}))
sys.exit(0 if state and state[0] == 'On' else 1)
