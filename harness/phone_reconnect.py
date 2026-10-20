"""Read-only diagnostics after a previously running phone's USB returns.

Uses the existing strict SSH aliases. Never resets USB, boots a payload,
changes host-key trust, starts a model, or modifies the phone.
"""
from datetime import datetime, timezone
import json
import os
import subprocess as sp
import uuid


def save(path, value):
    temporary = path.with_suffix('.new')
    with temporary.open('w') as f:
        os.chmod(temporary, 0o600)
        json.dump(value, f, indent=2)
        f.write('\n')
    temporary.replace(path)


def check(observation, directory):
    if not observation.get('last_linux_usb_at'):
        return
    private = directory / 'private'
    private.mkdir(exist_ok=True, mode=0o700)
    path = private / 'reconnect.json'
    state = json.loads(path.read_text()) if path.exists() else {}
    if observation['status'] != 'linux_usb':
        if state.get('state') != 'waiting_usb':
            save(path, {'state': 'waiting_usb', 'outage_since': observation['observed_since']})
        return
    if observation.get('identity', {}).get('HardwareModel') != 'N90AP':
        return
    if not state or state.get('state') == 'recovered':
        return
    # The observer supplies a current, pinned-port observation. SSH still has
    # to prove possession of the saved host key before any command is sent.
    ssh = ['ssh', '-F', str(private / 'ssh_config'), '-o', 'BatchMode=yes',
           '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1',
           '-o', 'StrictHostKeyChecking=yes']
    command = ("test \"$(tr -d '\\000' < /proc/device-tree/model)\" = 'Apple iPhone 4' || exit 42; "
               "cat /proc/sys/kernel/random/boot_id; uname -r; cat /proc/uptime; "
               "cat /proc/meminfo; dmesg | tail -n 200; "
               "test ! -f /run/soy/status.json || cat /run/soy/status.json")
    try:
        result = sp.run(ssh + ['iphone4-usb', command], capture_output=True, timeout=12)
        if result.returncode:
            raise RuntimeError('USB SSH failed; saved identity was not bypassed')
        boot_id = result.stdout.splitlines()[0].decode()
        uuid.UUID(boot_id)
        log = private / 'reconnect-diagnostics.txt'
        with log.open('wb') as f:
            os.chmod(log, 0o600)
            f.write(result.stdout[:262144])
        try:
            tailnet = sp.run(ssh + ['iphone4', 'cat /proc/sys/kernel/random/boot_id'],
                             capture_output=True, timeout=12)
            same_boot = tailnet.returncode == 0 and tailnet.stdout.decode().strip() == boot_id
        except (OSError, sp.SubprocessError, ValueError):
            same_boot = False
    except (OSError, sp.SubprocessError, RuntimeError, ValueError, IndexError) as exc:
        # Only fixed diagnostic categories enter status, never SSH output,
        # endpoint addresses, device identities or key paths.
        state.update(state='waiting_ssh', attempts=state.get('attempts', 0) + 1,
                     reason=type(exc).__name__)
        save(path, state)
        return
    state.update(state='recovered', recovered_at=datetime.now(timezone.utc).isoformat(),
                 usb_ssh=True, tailnet_same_boot=same_boot,
                 evidence='private/reconnect-diagnostics.txt')
    save(path, state)
