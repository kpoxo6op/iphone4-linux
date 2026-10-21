#!/usr/bin/env python3
"""Observe USB arrival and selected iOS facts; never pair or change phone mode."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess as sp

import control
import usb_device_nodes
import phone_reconnect

DATA = control.STATE / 'phone'
KEYS = {
    'ProductType': r'(?:iPhone|iPad|iPod|AppleTV)[0-9]{1,2},[0-9]{1,2}',
    'HardwareModel': r'[A-Za-z][0-9]{1,3}[Aa][Pp]',
    'ProductVersion': r'[0-9]{1,2}(?:\.[0-9]{1,2}){1,2}',
    'BuildVersion': r'[0-9]{1,3}[A-Z][0-9]{1,6}[a-z]?',
}


def command(args):
    # Capture errors: libimobiledevice may echo a UDID on failure.
    try:
        result = sp.run(args, capture_output=True, text=True, timeout=4)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, sp.TimeoutExpired):
        return None


def usb_mode(pid):
    # Debian's upstream-derived usbmuxd/libirecovery udev rules.
    if 0x1290 <= pid <= 0x12af:
        return 'normal'
    if 0x1280 <= pid <= 0x1283:
        return 'recovery'
    return {0x1227: 'dfu', 0x1222: 'wtf'}.get(pid)


def observe(sysfs=Path('/sys/bus/usb/devices'), run=command, target=None):
    devices = []
    paths = []
    for path in sorted(sysfs.iterdir()):
        try:
            vendor = (path / 'idVendor').read_text().strip().lower()
            pid = int((path / 'idProduct').read_text().strip(), 16)
            mode = usb_mode(pid) if vendor == '05ac' else None
            if (target and str(path.resolve()).removeprefix('/sys') == target['devpath']
                    and vendor == '0525'):
                mode = {0x1280: 'openiboot', 0xa4a1: 'linux_usb',
                        0xa4a2: 'linux_usb'}.get(pid)
            if mode:
                devices.append({'vendor_id': vendor, 'product_id': f'{pid:04x}',
                                'mode': mode})
                paths.append(path)
        except (OSError, ValueError):
            continue  # USB removal during enumeration is normal.
    result = {'evidence': 'host USB enumeration; not proof of successful Linux boot',
              'devices': devices, 'identity': {}, 'status': 'no_device'}
    if not devices:
        return result
    if len(devices) != 1:
        result['status'] = 'multiple_devices'
        return result
    mode = devices[0]['mode']
    if mode != 'normal':
        result['status'] = mode
        if target:
            path = paths[0]
            try:
                serial = (path / 'serial').read_text()
            except OSError:
                serial = ''
            if usb_device_nodes.matches(target, str(path.resolve()).removeprefix('/sys'),
                                        devices[0]['vendor_id'],
                                        devices[0]['product_id'], serial):
                result['identity'] = {'ProductType': 'iPhone3,1', 'HardwareModel': 'N90AP'}
                result['identity_source'] = ('pinned ECID' if devices[0]['vendor_id'] == '05ac'
                                             else 'previously identified phone on the same USB socket')
        return result  # No libirecovery commands or mode changes.
    ids = (run(['/usr/bin/idevice_id', '-l']) or '').splitlines()
    if len(ids) != 1 or not re.fullmatch(r'[0-9a-fA-F-]{20,64}', ids[0]):
        result['status'] = 'identity_unavailable'
        return result
    # UDID stays in memory. Simple connections avoid auto-pairing/handshakes.
    for key, pattern in KEYS.items():
        value = run(['/usr/bin/ideviceinfo', '-s', '-u', ids[0], '-k', key])
        if value and re.fullmatch(pattern, value):
            result['identity'][key] = value
    identity = result['identity']
    model = identity.get('ProductType')
    board = identity.get('HardwareModel', '').upper()
    if model == 'iPhone3,1' and board == 'N90AP':
        result['status'] = 'identified_n90'
    elif model and (model != 'iPhone3,1' or (board and board != 'N90AP')):
        result['status'] = 'other_model'
    else:
        result['status'] = 'identity_unavailable'
    return result


def atomic(path, value):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Refusing a symlink as an observation destination')
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        os.chmod(temp, 0o600)
        stream.write(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def start_boot(value):
    """Hand a phone that needs booting or identity restore to phone_boot.py."""
    if value.get('identity', {}).get('HardwareModel') != 'N90AP':
        return
    reconnect = DATA / 'private/reconnect.json'
    waiting_ssh = (reconnect.exists() and
                   json.loads(reconnect.read_text()).get('state') == 'waiting_ssh')
    if not (value['status'] in ('normal', 'recovery', 'dfu', 'openiboot') or
            (value['status'] == 'linux_usb' and waiting_ssh)):
        return
    record = DATA / 'private/boot.json'
    if record.exists() and json.loads(record.read_text()).get('failures', 0) >= 3:
        return
    # The unit holds the USB-operation lock; a running pass ignores this start.
    sp.run(['systemctl', '--user', 'start', '--no-block', 'iphone4-linux-boot.service'],
           check=False)


def check():
    cfg = json.loads((control.STATE / 'settings.json').read_text())
    targetfile = DATA / 'private/device-policy.json'
    target = json.loads(targetfile.read_text()) if targetfile.exists() else None
    value = observe(target=target)
    value['event_id'] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]
    value['checked_at'] = datetime.now(timezone.utc).isoformat()
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous = DATA / 'observation.json'
    old = json.loads(previous.read_text()) if previous.exists() else {}
    value['observed_since'] = (old.get('observed_since', value['checked_at'])
                              if old.get('event_id') == value['event_id']
                              else value['checked_at'])
    # A cable that has never arrived is quiet. Losing an already-running
    # phone is an outage, including across watcher/service restarts.
    if value['status'] == 'linux_usb' and value.get('identity', {}).get('HardwareModel') == 'N90AP':
        value['last_linux_usb_at'] = value['checked_at']
    elif old.get('last_linux_usb_at'):
        value['last_linux_usb_at'] = old['last_linux_usb_at']
    atomic(previous, value)
    for worker in cfg['workers']:
        atomic(Path(worker['path']) / '.opencode/phone-observation.json', value)
    changed = old.get('event_id') != value['event_id']
    if changed and value['status'] != 'no_device':
        # Supervisor owns inference, free-price checks, holds and dispatch.
        enabled = sp.run(['systemctl', '--user', 'is-enabled', control.UNIT],
                         capture_output=True).returncode == 0
        if enabled:
            sp.run(['systemctl', '--user', 'start', control.UNIT], check=True)
    phone_reconnect.check(value, DATA)
    start_boot(value)
    print(json.dumps({'status': value['status'], 'changed': changed}))


def install():
    units = Path.home() / '.config/systemd/user'
    (units / 'iphone4-linux-phone.service').write_text(
        '[Unit]\nDescription=Read-only iPhone USB identification\n'
        '[Service]\nType=oneshot\n'
        f'WorkingDirectory={control.ROOT}\nExecStart=/usr/bin/python3 {Path(__file__).resolve()} check\n'
        'TimeoutStartSec=40s\nMemoryMax=128M\nCPUQuota=25%\nUMask=0077\n'
        'NoNewPrivileges=true\n')
    (units / 'iphone4-linux-phone.timer').write_text(
        '[Unit]\nDescription=Watch for the iPhone every 30 seconds\n'
        '[Timer]\nOnBootSec=15s\nOnUnitInactiveSec=30s\nAccuracySec=1s\n'
        '[Install]\nWantedBy=timers.target\n')
    (units / 'iphone4-linux-boot.service').write_text(
        '[Unit]\nDescription=Boot the iPhone and restore its saved identity\n'
        '[Service]\nType=oneshot\n'
        f'WorkingDirectory={control.ROOT}\n'
        f'ExecStart=/usr/bin/python3 {Path(__file__).resolve().parent / "phone_boot.py"} run\n'
        'TimeoutStartSec=45min\nMemoryMax=3G\nUMask=0077\n')
    sp.run(['systemctl', '--user', 'daemon-reload'], check=True)
    sp.run(['systemctl', '--user', 'enable', '--now', 'iphone4-linux-phone.timer'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('check', 'install', 'status'))
    action = parser.parse_args().command
    if action == 'install':
        install()
    elif action == 'check':
        check()
    else:
        path = DATA / 'observation.json'
        print(path.read_text() if path.exists() else 'Not checked yet')
