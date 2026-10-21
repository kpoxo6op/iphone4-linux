#!/usr/bin/env python3
"""Install and start the N90 touch driver on a RAM-booted phone.

Copies the static n90-touch binary and Apple's touch firmware to
/opt/n90-touch, loads uinput when the kernel lacks /dev/uinput, and starts
`n90-touch serve`. Succeeds once the multitouch input device exists.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess as sp
import sys
import time

FIRMWARE_SHA256 = '359b6154c8aaffb22eb6e9350be7c718be0bf00fbddbac257e9d10582e62428f'
NAME = 'Apple N1 multitouch (iPhone 4)'

p = argparse.ArgumentParser()
p.add_argument('--ssh-config', type=Path, required=True)
p.add_argument('--host', default='iphone4-usb')
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--firmware', type=Path, required=True)
p.add_argument('--uinput-ko', type=Path, help='module for kernels built with UINPUT=m')
a = p.parse_args()

if hashlib.sha256(a.firmware.read_bytes()).hexdigest() != FIRMWARE_SHA256:
    raise SystemExit('unexpected touch firmware')
ssh = ['ssh', '-F', str(a.ssh_config.resolve()), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=8', a.host]


def remote(command, data=None, timeout=45):
    return sp.run(ssh + [command], input=data, capture_output=True, timeout=timeout)


# The phone's keep supervisor (kernel/n90-keep) leaves touch alone meanwhile.
remote('mkdir -p /run/keep && echo $(( $(date +%s) + 120 )) > /run/keep/hold-touch; '
       'killall n90-touch 2>/dev/null; mkdir -p /opt/n90-touch')
for path, target in ((a.binary, 'n90-touch'), (a.firmware, 'n90-z2.bin')):
    r = remote(f'cat > /opt/n90-touch/{target}.new && mv /opt/n90-touch/{target}.new '
               f'/opt/n90-touch/{target}', path.read_bytes())
    if r.returncode:
        raise SystemExit(f'copy {target} failed: {r.stderr.decode()[:200]}')
remote('chmod 755 /opt/n90-touch/n90-touch')
if a.uinput_ko and remote('test -e /dev/uinput').returncode:
    remote('cat > /opt/n90-touch/uinput.ko', a.uinput_ko.read_bytes())
    r = remote('insmod /opt/n90-touch/uinput.ko')
    if r.returncode:
        raise SystemExit(f'insmod uinput failed: {r.stderr.decode()[:200]}')
remote('cd /opt/n90-touch && nohup ./n90-touch serve n90-z2.bin '
       '> /run/n90-touch.log 2>&1 < /dev/null &')
for _ in range(30):
    time.sleep(1)
    if NAME in remote('cat /proc/bus/input/devices').stdout.decode():
        remote('rm -f /run/keep/hold-touch')
        print('touch device ready')
        sys.exit(0)
print(remote('tail -20 /run/n90-touch.log; rm -f /run/keep/hold-touch').stdout.decode(),
      file=sys.stderr)
raise SystemExit('touch device did not appear')
